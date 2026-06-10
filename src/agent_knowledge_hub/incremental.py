from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.pipeline import _infer_supplier, _optional, _resolve_manifest_path, ingest_file
from agent_knowledge_hub.parsers import DocumentParseError
from agent_knowledge_hub.utils import file_sha256, is_placeholder, utc_now_iso, write_json


@dataclass(frozen=True)
class IncrementalIngestDocument:
    sample_id: str
    status: str
    source_path: str
    content_hash: str | None
    previous_hash: str | None
    output_dir: str | None
    document_json_path: str | None
    chunks_jsonl_path: str | None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IncrementalIngestSummary:
    manifest_path: Path
    output_dir: Path
    generated_at: str
    processed_count: int
    unchanged_count: int
    changed_count: int
    skipped_count: int
    failed_count: int
    documents: list[IncrementalIngestDocument]
    skipped: list[dict[str, str]]
    failed: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "output_dir": str(self.output_dir),
            "generated_at": self.generated_at,
            "processed_count": self.processed_count,
            "unchanged_count": self.unchanged_count,
            "changed_count": self.changed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "documents": [document.to_dict() for document in self.documents],
            "skipped": list(self.skipped),
            "failed": list(self.failed),
        }


def ingest_manifest_incremental(
    *,
    manifest_path: Path | str,
    out_dir: Path | str,
    project_root: Path | str | None = None,
    max_chunk_chars: int = 1600,
    overlap_chars: int = 160,
    fail_fast: bool = False,
) -> IncrementalIngestSummary:
    manifest = Path(manifest_path).resolve()
    output_root = Path(out_dir).resolve()
    root = Path(project_root).resolve() if project_root else manifest.parent
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest}")

    state_path = output_root / "ingest-state.json"
    state = _load_state(state_path)
    next_state = dict(state)
    documents: list[IncrementalIngestDocument] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    processed_count = 0
    unchanged_count = 0
    changed_count = 0

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
                content_hash = file_sha256(source_path)
            except OSError as exc:
                failure = _build_failure(row, sample_id, row_number, source_path, str(exc))
                failed.append(failure)
                if fail_fast:
                    raise
                continue

            state_key = str(source_path.resolve())
            previous = state.get(state_key) or {}
            previous_hash = previous.get("content_hash")
            if previous_hash == content_hash:
                unchanged_count += 1
                documents.append(
                    IncrementalIngestDocument(
                        sample_id=sample_id,
                        status="unchanged",
                        source_path=str(source_path),
                        content_hash=content_hash,
                        previous_hash=previous_hash,
                        output_dir=previous.get("output_dir"),
                        document_json_path=previous.get("document_json_path"),
                        chunks_jsonl_path=previous.get("chunks_jsonl_path"),
                    )
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
                    overlap_chars=overlap_chars,
                )
                processed_count += 1
                if previous_hash is not None:
                    changed_count += 1
                document = IncrementalIngestDocument(
                    sample_id=sample_id,
                    status="processed",
                    source_path=str(source_path),
                    content_hash=content_hash,
                    previous_hash=previous_hash,
                    output_dir=str(result.output_dir),
                    document_json_path=str(result.document_json_path),
                    chunks_jsonl_path=str(result.chunks_jsonl_path),
                )
                documents.append(document)
                next_state[state_key] = {
                    **document.to_dict(),
                    "updated_at": utc_now_iso(),
                }
            except (DocumentParseError, OSError, ValueError) as exc:
                failure = _build_failure(row, sample_id, row_number, source_path, str(exc))
                failed.append(failure)
                documents.append(
                    IncrementalIngestDocument(
                        sample_id=sample_id,
                        status="failed",
                        source_path=str(source_path),
                        content_hash=content_hash,
                        previous_hash=previous_hash,
                        output_dir=None,
                        document_json_path=None,
                        chunks_jsonl_path=None,
                        reason=str(exc),
                    )
                )
                if fail_fast:
                    raise

    summary = IncrementalIngestSummary(
        manifest_path=manifest,
        output_dir=output_root,
        generated_at=utc_now_iso(),
        processed_count=processed_count,
        unchanged_count=unchanged_count,
        changed_count=changed_count,
        skipped_count=len(skipped),
        failed_count=len(failed),
        documents=documents,
        skipped=skipped,
        failed=failed,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root / "ingest-run-summary.json", summary.to_dict())
    write_json(output_root / "ingest-state.json", {"documents": next_state})
    _write_legacy_ingest_summary(output_root / "ingest-summary.json", summary)
    return summary


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents") or {}
    return {
        str(key): dict(value)
        for key, value in documents.items()
        if isinstance(value, dict)
    }


def _write_legacy_ingest_summary(path: Path, summary: IncrementalIngestSummary) -> None:
    processed = [
        {
            "sample_id": document.sample_id,
            "status": document.status,
            "source_path": document.source_path,
            "output_dir": document.output_dir,
            "document_json_path": document.document_json_path,
            "chunks_jsonl_path": document.chunks_jsonl_path,
        }
        for document in summary.documents
        if document.status == "processed"
    ]
    write_json(
        path,
        {
            "manifest_path": str(summary.manifest_path),
            "output_dir": str(summary.output_dir),
            "processed_count": summary.processed_count,
            "skipped_count": summary.skipped_count,
            "failed_count": summary.failed_count,
            "results": processed,
            "skipped": summary.skipped,
            "failed": summary.failed,
        },
    )


def _get(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _build_failure(
    row: dict[str, str],
    sample_id: str,
    row_number: int,
    source_path: Path,
    reason: str,
) -> dict[str, str]:
    return {
        "sample_id": sample_id,
        "row_number": str(row_number),
        "file_path": str(source_path),
        "document_title": _optional(row, "document_title") or source_path.stem,
        "source_type": _optional(row, "slot_type") or "unknown",
        "owner": _optional(row, "owner") or "unknown",
        "project": _optional(row, "project") or "unknown",
        "supplier": _infer_supplier(row),
        "document_version": _optional(row, "document_version") or "unknown",
        "reason": reason,
    }
