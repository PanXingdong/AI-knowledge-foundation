from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CANONICAL_DOCUMENT_SCHEMA_VERSION = "layer1.processed.v1"


@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    source_type: str
    owner: str
    project: str
    supplier: str
    created_at: str


@dataclass(frozen=True)
class DocumentVersion:
    document_version_id: str
    document_id: str
    version: str
    file_path: str
    file_hash: str
    created_at: str


@dataclass(frozen=True)
class Section:
    section_id: str
    document_version_id: str
    section_path: list[str]
    title: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True)
class Block:
    block_id: str
    document_version_id: str
    block_type: str
    text: str
    page_start: int | None
    page_end: int | None
    section_path: list[str]
    order: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceSpan:
    evidence_id: str
    document_version_id: str
    page: int | None
    section_path: list[str]
    block_id: str
    bbox: list[float] | None
    text: str
    text_hash: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_version_id: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    text: str
    evidence_ids: list[str]
    embedding_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseReport:
    parser_name: str
    source_format: str
    page_count: int | None
    section_count: int
    block_count: int
    table_count: int
    has_page_numbers: bool
    warnings: list[str] = field(default_factory=list)
    quality_report: dict[str, Any] | None = None


@dataclass(frozen=True)
class CanonicalDocument:
    schema_version: str
    document: Document
    document_version: DocumentVersion
    sections: list[Section]
    blocks: list[Block]
    evidence_spans: list[EvidenceSpan]
    parse_report: ParseReport

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IngestResult:
    sample_id: str | None
    document_id: str
    document_version_id: str
    status: str
    source_path: Path
    output_dir: Path
    document_json_path: Path
    chunks_jsonl_path: Path
    processing_record_path: Path
    quality_record_path: Path
    chunk_count: int
    warning_count: int

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "status": self.status,
            "source_path": str(self.source_path),
            "output_dir": str(self.output_dir),
            "document_json_path": str(self.document_json_path),
            "chunks_jsonl_path": str(self.chunks_jsonl_path),
            "processing_record_path": str(self.processing_record_path),
            "quality_record_path": str(self.quality_record_path),
            "chunk_count": self.chunk_count,
            "warning_count": self.warning_count,
        }


@dataclass(frozen=True)
class ManifestIngestSummary:
    manifest_path: Path
    output_dir: Path
    processed_count: int
    skipped_count: int
    failed_count: int
    results: list[IngestResult]
    skipped: list[dict[str, str]]
    failed: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "output_dir": str(self.output_dir),
            "processed_count": self.processed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "results": [result.to_summary_dict() for result in self.results],
            "skipped": self.skipped,
            "failed": self.failed,
        }
