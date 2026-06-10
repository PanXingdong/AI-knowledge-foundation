from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from agent_knowledge_hub.dependencies import check_runtime_dependencies
from agent_knowledge_hub.incremental import ingest_manifest_incremental
from agent_knowledge_hub.inventory import build_document_inventory
from agent_knowledge_hub.pipeline import ingest_manifest
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    compare_context_pack_against_reference,
    search_processed_dir,
    trace_evidence_in_processed_dir,
)
from agent_knowledge_hub.quality import build_parse_quality_summary


class ContextPackRequest(BaseModel):
    processed_dir: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(8, ge=1, le=100)
    per_document_limit: int = Field(2, ge=1, le=20)


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
    overlap_chars: int = Field(160, ge=0, le=5000)
    fail_fast: bool = False
    incremental: bool = True


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Knowledge Hub API",
        version="0.1.0",
        description="Auto Context Pack Engine v1 service core.",
    )

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
                top_k=request.top_k,
                per_document_limit=request.per_document_limit,
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
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {"data": result.to_dict()}

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
                    overlap_chars=request.overlap_chars,
                    fail_fast=request.fail_fast,
                )
            else:
                result = ingest_manifest(
                    manifest_path=Path(request.manifest_path),
                    out_dir=Path(request.out_dir),
                    project_root=Path(request.project_root) if request.project_root else None,
                    max_chunk_chars=request.max_chunk_chars,
                    overlap_chars=request.overlap_chars,
                    fail_fast=request.fail_fast,
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
                top_k=request.top_k,
                per_document_limit=request.per_document_limit,
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
