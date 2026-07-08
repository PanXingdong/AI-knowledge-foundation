from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from agent_knowledge_hub.dependencies import check_runtime_dependencies
from agent_knowledge_hub.feishu_bot import MessageFormatter
from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.incremental import ingest_manifest_incremental
from agent_knowledge_hub.inventory import build_document_inventory
from agent_knowledge_hub.pipeline import ingest_manifest
from agent_knowledge_hub.vector_index import build_vector_index
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    configure_llm_planner,
    compare_context_pack_against_reference,
    prewarm,
    search_processed_dir,
    trace_evidence_in_processed_dir,
)
from agent_knowledge_hub.quality import build_parse_quality_summary

logger = logging.getLogger(__name__)


class ContextPackRequest(BaseModel):
    processed_dir: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    task_type: str = "general_query"
    top_k: int = Field(8, ge=1, le=100)
    per_document_limit: int = Field(2, ge=1, le=20)
    metadata_filters: dict[str, list[str]] = Field(default_factory=dict)
    fts_index_path: str | None = None
    vector_index_path: str | None = None


class RemoteContextPackRequest(BaseModel):
    query: str = Field(..., min_length=1)
    task_type: str | None = None
    top_k: int | None = Field(None, ge=1, le=100)
    per_document_limit: int | None = Field(None, ge=1, le=20)
    metadata_filters: dict[str, list[str]] = Field(default_factory=dict)


class GapReportRequest(ContextPackRequest):
    reference_markdown_path: str = Field(..., min_length=1)


class DocumentInventoryRequest(BaseModel):
    root_dirs: list[str] = Field(..., min_length=1)
    max_files: int = Field(200, ge=1, le=10000)
    max_file_mb: float = Field(100.0, gt=0)
    owner: str = "checker"
    project: str = "unknown"
    document_version: str = "unknown"
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    dedupe_content_hash: bool = True


class IngestManifestRequest(BaseModel):
    manifest_path: str = Field(..., min_length=1)
    out_dir: str = Field(..., min_length=1)
    project_root: str | None = None
    max_chunk_chars: int = Field(1600, ge=100, le=20000)
    max_tokens: int = Field(512, ge=0, le=8192)
    overlap_chars: int = Field(160, ge=0, le=5000)
    fail_fast: bool = False
    incremental: bool = True


class BuildFtsIndexRequest(BaseModel):
    processed_dir: str = Field(..., min_length=1)
    index_path: str = Field(..., min_length=1)


class BuildVectorIndexRequest(BaseModel):
    processed_dir: str = Field(..., min_length=1)
    index_path: str = Field(..., min_length=1)


@dataclass(frozen=True)
class KnowledgeBaseConfig:
    knowledge_base_id: str
    processed_dir: str
    fts_index_path: str | None = None
    vector_index_path: str | None = None
    default_task_type: str = "general_query"
    default_top_k: int = 8
    default_per_document_limit: int = 2
    metadata_filters: dict[str, list[str]] | None = None


def _load_knowledge_base_registry() -> dict[str, KnowledgeBaseConfig]:
    raw = os.environ.get("KNOWLEDGE_BASES_JSON", "").strip()
    config_path = os.environ.get("KNOWLEDGE_BASES_CONFIG", "").strip()
    if raw and config_path:
        raise ValueError("Set only one of KNOWLEDGE_BASES_JSON or KNOWLEDGE_BASES_CONFIG")
    if config_path:
        raw = Path(config_path).read_text(encoding="utf-8")
    if not raw:
        return _load_default_knowledge_base_from_feishu_env()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Knowledge base registry must be valid JSON") from exc

    entries: Any
    if isinstance(payload, dict) and "knowledge_bases" in payload:
        entries = payload["knowledge_bases"]
    else:
        entries = payload

    registry: dict[str, KnowledgeBaseConfig] = {}
    if isinstance(entries, dict):
        iterable = []
        for key, value in entries.items():
            if not isinstance(value, dict):
                raise ValueError("Each knowledge base entry must be an object")
            iterable.append({**value, "knowledge_base_id": key})
    elif isinstance(entries, list):
        iterable = entries
    else:
        raise ValueError("Knowledge base registry must be an object or a list")

    for entry in iterable:
        if not isinstance(entry, dict):
            raise ValueError("Each knowledge base entry must be an object")
        knowledge_base_id = str(entry.get("knowledge_base_id", "")).strip()
        processed_dir = str(entry.get("processed_dir", "")).strip()
        if not knowledge_base_id or not processed_dir:
            raise ValueError("Each knowledge base entry requires knowledge_base_id and processed_dir")
        metadata_filters = entry.get("metadata_filters") or None
        if metadata_filters is not None and not isinstance(metadata_filters, dict):
            raise ValueError("metadata_filters must be an object when provided")
        registry[knowledge_base_id] = KnowledgeBaseConfig(
            knowledge_base_id=knowledge_base_id,
            processed_dir=processed_dir,
            fts_index_path=entry.get("fts_index_path") or None,
            vector_index_path=entry.get("vector_index_path") or None,
            default_task_type=str(entry.get("default_task_type") or "general_query"),
            default_top_k=int(entry.get("default_top_k") or 8),
            default_per_document_limit=int(entry.get("default_per_document_limit") or 2),
            metadata_filters=metadata_filters,
        )
    return registry


def _load_default_knowledge_base_from_feishu_env() -> dict[str, KnowledgeBaseConfig]:
    processed_dir = os.environ.get("PROCESSED_DIR", "").strip()
    if not processed_dir:
        return {}
    knowledge_base_id = os.environ.get("KNOWLEDGE_BASE_ID", "qnx-main").strip() or "qnx-main"
    return {
        knowledge_base_id: KnowledgeBaseConfig(
            knowledge_base_id=knowledge_base_id,
            processed_dir=processed_dir,
            fts_index_path=os.environ.get("FTS_INDEX_PATH", "").strip() or None,
            vector_index_path=os.environ.get("VECTOR_INDEX_PATH", "").strip() or None,
            default_task_type=os.environ.get("DEFAULT_TASK_TYPE", "general_query").strip() or "general_query",
            default_top_k=int(os.environ.get("DEFAULT_TOP_K", "8")),
            default_per_document_limit=int(os.environ.get("DEFAULT_PER_DOCUMENT_LIMIT", "2")),
        )
    }


def _resolve_knowledge_base(knowledge_base_id: str) -> KnowledgeBaseConfig:
    try:
        registry = _load_knowledge_base_registry()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    config = registry.get(knowledge_base_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}")
    return config


def _merge_metadata_filters(
    base_filters: dict[str, list[str]] | None,
    request_filters: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {key: list(value) for key, value in (base_filters or {}).items()}
    for key, value in request_filters.items():
        merged[key] = list(value)
    return merged


def _require_remote_api_token(authorization: str | None) -> None:
    expected = os.environ.get("KNOWLEDGE_HUB_API_TOKEN", "").strip()
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing Knowledge Hub token")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Knowledge Hub API",
        version="0.1.0",
        description="Auto Context Pack Engine v1 service core.",
    )

    @app.on_event("startup")
    def _startup_prewarm() -> None:
        """Pre-warm retrieval caches at boot so the first user query is fast."""
        configure_llm_planner(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            timeout=int(os.environ.get("LLM_PLANNER_TIMEOUT", "30")),
        )

        if os.environ.get("KNOWLEDGE_HUB_SKIP_PREWARM", "") == "1":
            logger.info("KNOWLEDGE_HUB_SKIP_PREWARM=1, skipping cache prewarm")
            return

        processed_dir = os.environ.get("PROCESSED_DIR", "")
        if not processed_dir:
            logger.info("PROCESSED_DIR not set, skipping cache prewarm")
            return
        vector_index_path = os.environ.get("VECTOR_INDEX_PATH") or None
        t0 = time.time()
        logger.info("=== Cache prewarm starting ===")
        prewarm(processed_dir, vector_index_path=vector_index_path)
        logger.info("=== Cache prewarm done in %.1fs ===", time.time() - t0)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok"}

    @app.get("/api/runtime-dependencies")
    def runtime_dependencies() -> dict[str, object]:
        result = check_runtime_dependencies()
        return {
            "data": {
                **result.to_dict(),
                "markdown": result.markdown,
            }
        }

    @app.post("/api/context-pack")
    def context_pack(request: ContextPackRequest) -> dict[str, object]:
        try:
            result = build_context_pack_for_processed_dir(
                processed_dir=request.processed_dir,
                query=request.query,
                task_type=request.task_type,
                top_k=request.top_k,
                per_document_limit=request.per_document_limit,
                metadata_filters=request.metadata_filters,
                fts_index_path=request.fts_index_path,
                vector_index_path=request.vector_index_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "data": {
                **result.to_json_dict(),
                "markdown": result.markdown,
            }
        }

    @app.post("/api/search")
    def search(request: ContextPackRequest) -> dict[str, object]:
        try:
            result = search_processed_dir(
                processed_dir=request.processed_dir,
                query=request.query,
                top_k=request.top_k,
                per_document_limit=request.per_document_limit,
                metadata_filters=request.metadata_filters,
                fts_index_path=request.fts_index_path,
                vector_index_path=request.vector_index_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"data": result.to_dict()}

    @app.post("/api/knowledge-bases/{knowledge_base_id}/context-pack")
    def remote_context_pack(
        knowledge_base_id: str,
        request: RemoteContextPackRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_remote_api_token(authorization)
        kb = _resolve_knowledge_base(knowledge_base_id)
        try:
            result = build_context_pack_for_processed_dir(
                processed_dir=kb.processed_dir,
                query=request.query,
                task_type=request.task_type or kb.default_task_type,
                top_k=request.top_k or kb.default_top_k,
                per_document_limit=request.per_document_limit or kb.default_per_document_limit,
                metadata_filters=_merge_metadata_filters(kb.metadata_filters, request.metadata_filters),
                fts_index_path=kb.fts_index_path,
                vector_index_path=kb.vector_index_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload = result.to_json_dict()
        payload["knowledge_base_id"] = knowledge_base_id
        payload["processed_dir"] = f"knowledge-base:{knowledge_base_id}"
        payload["markdown"] = result.markdown
        payload["formatted_context"] = MessageFormatter.format_context_pack(payload)
        return {"data": payload}

    @app.get("/api/knowledge-bases/{knowledge_base_id}/evidence/{evidence_id}")
    def remote_trace_evidence(
        knowledge_base_id: str,
        evidence_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_remote_api_token(authorization)
        kb = _resolve_knowledge_base(knowledge_base_id)
        try:
            result = trace_evidence_in_processed_dir(
                processed_dir=kb.processed_dir,
                evidence_id=evidence_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            if "Evidence not found" in str(exc):
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload = result.to_dict()
        payload["knowledge_base_id"] = knowledge_base_id
        return {"data": payload}

    @app.post("/api/document-inventory")
    def document_inventory(request: DocumentInventoryRequest) -> dict[str, object]:
        try:
            result = build_document_inventory(
                root_dirs=[Path(root_dir) for root_dir in request.root_dirs],
                max_files=request.max_files,
                max_file_mb=request.max_file_mb,
                owner=request.owner,
                project=request.project,
                document_version=request.document_version,
                include_keywords=request.include_keywords,
                exclude_keywords=request.exclude_keywords,
                dedupe_content_hash=request.dedupe_content_hash,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "data": {
                **result.to_dict(),
                "markdown": result.markdown,
            }
        }

    @app.post("/api/ingest-manifest")
    def ingest_manifest_endpoint(request: IngestManifestRequest) -> dict[str, object]:
        try:
            if request.incremental:
                result = ingest_manifest_incremental(
                    manifest_path=Path(request.manifest_path),
                    out_dir=Path(request.out_dir),
                    project_root=Path(request.project_root) if request.project_root else None,
                    max_chunk_chars=request.max_chunk_chars,
                    max_tokens=request.max_tokens,
                    overlap_chars=request.overlap_chars,
                    fail_fast=request.fail_fast,
                )
            else:
                result = ingest_manifest(
                    manifest_path=Path(request.manifest_path),
                    out_dir=Path(request.out_dir),
                    project_root=Path(request.project_root) if request.project_root else None,
                    max_chunk_chars=request.max_chunk_chars,
                    max_tokens=request.max_tokens,
                    overlap_chars=request.overlap_chars,
                    fail_fast=request.fail_fast,
                )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"data": result.to_dict()}

    @app.post("/api/build-fts-index")
    def build_fts_index_endpoint(request: BuildFtsIndexRequest) -> dict[str, object]:
        try:
            result = build_fts_index(
                processed_dir=request.processed_dir,
                index_path=request.index_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"data": result.to_dict()}

    @app.post("/api/build-vector-index")
    def build_vector_index_endpoint(request: BuildVectorIndexRequest) -> dict[str, object]:
        try:
            result = build_vector_index(
                processed_dir=request.processed_dir,
                index_path=request.index_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"data": result.to_dict()}

    @app.post("/api/gap-report")
    def gap_report(request: GapReportRequest) -> dict[str, object]:
        try:
            context_pack = build_context_pack_for_processed_dir(
                processed_dir=request.processed_dir,
                query=request.query,
                task_type=request.task_type,
                top_k=request.top_k,
                per_document_limit=request.per_document_limit,
                metadata_filters=request.metadata_filters,
                fts_index_path=request.fts_index_path,
                vector_index_path=request.vector_index_path,
            )
            report = compare_context_pack_against_reference(
                auto_result=context_pack,
                reference_markdown_path=Path(request.reference_markdown_path),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "data": {
                **report.to_dict(),
                "markdown": report.markdown,
            }
        }

    @app.get("/api/evidence/{evidence_id}")
    def trace_evidence(
        evidence_id: str,
        processed_dir: str = Query(..., min_length=1),
    ) -> dict[str, object]:
        try:
            result = trace_evidence_in_processed_dir(
                processed_dir=processed_dir,
                evidence_id=evidence_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            if "Evidence not found" in str(exc):
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"data": result.to_dict()}

    @app.get("/api/parse-quality-summary")
    def parse_quality_summary(
        processed_dir: str = Query(..., min_length=1),
    ) -> dict[str, object]:
        try:
            result = build_parse_quality_summary(processed_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "data": {
                **result.to_dict(),
                "markdown": result.markdown,
            }
        }

    return app
