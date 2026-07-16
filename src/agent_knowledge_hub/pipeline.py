from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from agent_knowledge_hub.builder import build_canonical_document
from agent_knowledge_hub.chunker import build_chunks, chunks_to_dicts
from agent_knowledge_hub.models import IngestResult, ManifestIngestSummary
from agent_knowledge_hub.parsers import DocumentParseError, parse_document
from agent_knowledge_hub.processing_record import build_processing_record, write_processing_record
from agent_knowledge_hub.quality_contracts import build_quality_record, write_quality_record
from agent_knowledge_hub.utils import is_placeholder, slugify, write_json, write_jsonl


def ingest_file(
    *,
    file_path: Path | str,
    out_dir: Path | str,
    title: str | None = None,
    source_type: str = "unknown",
    owner: str = "unknown",
    project: str = "unknown",
    supplier: str = "unknown",
    document_version: str = "unknown",
    sample_id: str | None = None,
    max_chunk_chars: int = 1600,
    max_tokens: int = 512,
    overlap_chars: int = 160,
    min_chunk_chars: int = 10,
) -> IngestResult:
    source_path = Path(file_path).resolve()
    output_root = Path(out_dir).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Document does not exist: {source_path}")
    if not source_path.is_file():
        raise ValueError(f"Document path is not a file: {source_path}")

    parsed = parse_document(source_path)
    canonical = build_canonical_document(
        parsed=parsed,
        file_path=source_path,
        title=title,
        source_type=source_type,
        owner=owner,
        project=project,
        supplier=supplier,
        document_version=document_version,
        sample_id=sample_id,
    )
    chunks = build_chunks(
        canonical,
        max_chunk_chars=max_chunk_chars,
        max_tokens=max_tokens,
        overlap_chars=overlap_chars,
        min_chunk_chars=min_chunk_chars,
    )

    safe_title = slugify(canonical.document.title, fallback="document")
    document_dir = output_root / safe_title / canonical.document_version.document_version_id
    document_json_path = document_dir / "canonical-document.json"
    chunks_jsonl_path = document_dir / "chunks.jsonl"
    processing_record_path = document_dir / "processing-record.json"
    quality_record_path = document_dir / "quality-record.json"

    write_json(document_json_path, canonical.to_dict())
    write_jsonl(chunks_jsonl_path, chunks_to_dicts(chunks))
    processing_record = build_processing_record(
        document_version_id=canonical.document_version.document_version_id,
        source_file_hash=canonical.document_version.file_hash,
        parser_name=canonical.parse_report.parser_name,
        canonical_path=document_json_path,
        chunks_path=chunks_jsonl_path,
    )
    write_processing_record(processing_record_path, processing_record)
    quality_record = build_quality_record(
        canonical.to_dict(),
        chunks_to_dicts(chunks),
    )
    write_quality_record(quality_record_path, quality_record)

    return IngestResult(
        sample_id=sample_id,
        document_id=canonical.document.document_id,
        document_version_id=canonical.document_version.document_version_id,
        status="processed",
        source_path=source_path,
        output_dir=document_dir,
        document_json_path=document_json_path,
        chunks_jsonl_path=chunks_jsonl_path,
        processing_record_path=processing_record_path,
        quality_record_path=quality_record_path,
        chunk_count=len(chunks),
        warning_count=len(canonical.parse_report.warnings),
    )


def ingest_manifest(
    *,
    manifest_path: Path | str,
    out_dir: Path | str,
    project_root: Path | str | None = None,
    max_chunk_chars: int = 1600,
    max_tokens: int = 512,
    overlap_chars: int = 160,
    min_chunk_chars: int = 10,
    fail_fast: bool = False,
) -> ManifestIngestSummary:
    manifest = Path(manifest_path).resolve()
    output_root = Path(out_dir).resolve()
    root = Path(project_root).resolve() if project_root else manifest.parent
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest}")

    results: list[IngestResult] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            sample_id = _get(row, "sample_id") or f"row-{row_number}"
            raw_path = _get(row, "file_path")
            if is_placeholder(raw_path):
                skipped.append(
                    {
                        "sample_id": sample_id,
                        "row_number": str(row_number),
                        "reason": "missing_or_placeholder_path",
                    }
                )
                continue

            source_path = _resolve_manifest_path(raw_path, root, manifest.parent)
            if not source_path.exists():
                skipped.append(
                    {
                        "sample_id": sample_id,
                        "row_number": str(row_number),
                        "reason": "missing_or_placeholder_path",
                        "file_path": str(source_path),
                    }
                )
                continue

            try:
                result = ingest_file(
                    file_path=source_path,
                    out_dir=output_root,
                    title=_optional(row, "document_title") or source_path.stem,
                    source_type=_optional(row, "slot_type") or "unknown",
                    owner=_optional(row, "owner") or "unknown",
                    project=_optional(row, "project") or "unknown",
                    supplier=_infer_supplier(row),
                    document_version=_optional(row, "document_version") or "unknown",
                    sample_id=sample_id,
                    max_chunk_chars=max_chunk_chars,
                    max_tokens=max_tokens,
                    overlap_chars=overlap_chars,
                    min_chunk_chars=min_chunk_chars,
                )
                results.append(result)
            except (DocumentParseError, OSError, ValueError) as exc:
                failure = {
                    "sample_id": sample_id,
                    "row_number": str(row_number),
                    "file_path": str(source_path),
                    "document_title": _optional(row, "document_title") or source_path.stem,
                    "source_type": _optional(row, "slot_type") or "unknown",
                    "owner": _optional(row, "owner") or "unknown",
                    "project": _optional(row, "project") or "unknown",
                    "supplier": _infer_supplier(row),
                    "document_version": _optional(row, "document_version") or "unknown",
                    "reason": str(exc),
                }
                failed.append(failure)
                if fail_fast:
                    raise

    summary = ManifestIngestSummary(
        manifest_path=manifest,
        output_dir=output_root,
        processed_count=len(results),
        skipped_count=len(skipped),
        failed_count=len(failed),
        results=results,
        skipped=skipped,
        failed=failed,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "ingest-summary.json", summary.to_dict())
    return summary


def _get(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _optional(row: dict[str, str], key: str) -> str | None:
    value = _get(row, key)
    return None if is_placeholder(value) else value


def _resolve_manifest_path(raw_path: str, project_root: Path, manifest_dir: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()

    project_candidate = (project_root / candidate).resolve()
    if project_candidate.exists():
        return project_candidate
    return (manifest_dir / candidate).resolve()


def _infer_supplier(row: dict[str, str]) -> str:
    explicit = _optional(row, "supplier")
    if explicit:
        return explicit
    source_type = _optional(row, "slot_type") or ""
    title = _optional(row, "document_title") or ""
    text = f"{source_type} {title}".lower()
    if "高通" in text or "qualcomm" in text:
        return "Qualcomm"
    if "博世" in text or "bosch" in text:
        return "Bosch"
    return "unknown"
