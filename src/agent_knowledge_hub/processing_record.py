from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.utils import file_sha256, stable_id, write_json

PROCESSING_RECORD_SCHEMA_VERSION = "knowledge-processing-record.v1"
CHUNKER_VERSION = "section-aware-block-chunker-v1"
QUALITY_RULES_VERSION = "parse-quality-gate-v1"


@dataclass(frozen=True)
class ProcessingRecord:
    schema_version: str
    processing_run_id: str
    document_version_id: str
    source_file_hash: str
    parser_name: str
    chunker_version: str
    quality_rules_version: str
    canonical_sha256: str
    chunks_sha256: str
    record_origin: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_processing_record(
    *,
    document_version_id: str,
    source_file_hash: str,
    parser_name: str,
    canonical_path: Path,
    chunks_path: Path,
) -> ProcessingRecord:
    canonical_sha256 = file_sha256(canonical_path)
    chunks_sha256 = file_sha256(chunks_path)
    run_id = stable_id(
        "run",
        document_version_id,
        source_file_hash,
        parser_name,
        CHUNKER_VERSION,
        QUALITY_RULES_VERSION,
        canonical_sha256,
        chunks_sha256,
    )
    return ProcessingRecord(
        schema_version=PROCESSING_RECORD_SCHEMA_VERSION,
        processing_run_id=run_id,
        document_version_id=document_version_id,
        source_file_hash=source_file_hash,
        parser_name=parser_name,
        chunker_version=CHUNKER_VERSION,
        quality_rules_version=QUALITY_RULES_VERSION,
        canonical_sha256=canonical_sha256,
        chunks_sha256=chunks_sha256,
        record_origin="ingestion",
    )


def load_or_infer_processing_record(version_dir: Path) -> ProcessingRecord:
    record_path = version_dir / "processing-record.json"
    canonical_path = version_dir / "canonical-document.json"
    chunks_path = version_dir / "chunks.jsonl"
    if record_path.exists():
        record = ProcessingRecord(**json.loads(record_path.read_text(encoding="utf-8")))
        if file_sha256(canonical_path) != record.canonical_sha256:
            raise ValueError(f"canonical_hash_mismatch:{record.document_version_id}")
        if file_sha256(chunks_path) != record.chunks_sha256:
            raise ValueError(f"chunks_hash_mismatch:{record.document_version_id}")
        return record
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    version = payload.get("document_version") or {}
    report = payload.get("parse_report") or {}
    inferred = build_processing_record(
        document_version_id=str(version.get("document_version_id") or ""),
        source_file_hash=str(version.get("file_hash") or ""),
        parser_name=str(report.get("parser_name") or "legacy"),
        canonical_path=canonical_path,
        chunks_path=chunks_path,
    )
    return ProcessingRecord(**{**inferred.to_dict(), "record_origin": "legacy_inferred"})


def write_processing_record(path: Path, record: ProcessingRecord) -> None:
    write_json(path, record.to_dict())
