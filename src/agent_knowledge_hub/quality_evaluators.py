from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.quality_models import ObservedQualitySignal
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import (
    file_sha256,
    normalize_space,
    sha256_text,
    stable_id,
)

EVALUATOR_VERSION = "phase1-observe-v1"
VALID_BLOCK_TYPES = frozenset({"heading", "paragraph", "table", "code"})
SOFT_MIN_DOCUMENT_CHARS = 40
SOFT_MIN_PAGE_CHARS = 10
SOFT_MAX_BLOCK_CHARS = 20_000
SOFT_MIN_CHUNK_CHARS = 10
SOFT_MAX_CHUNK_CHARS = 8_000
SOFT_WARNING_COUNT = 10


@dataclass(frozen=True)
class DocumentArtifacts:
    version_dir: Path
    canonical_path: Path
    chunks_path: Path
    processing_record_path: Path
    quality_record_path: Path
    canonical: dict[str, Any] | None
    chunks: tuple[dict[str, Any], ...]
    processing_record: dict[str, Any] | None
    quality_record: dict[str, Any] | None
    document_version_id: str
    load_errors: tuple[str, ...]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return tuple(rows)


def load_document_artifacts(version_dir: Path) -> DocumentArtifacts:
    root = version_dir.resolve()
    canonical_path = root / "canonical-document.json"
    chunks_path = root / "chunks.jsonl"
    processing_path = root / "processing-record.json"
    quality_path = root / "quality-record.json"
    canonical = _load_json(canonical_path)
    processing_record = _load_json(processing_path)
    quality_record = _load_json(quality_path)
    errors: list[str] = []
    if canonical_path.exists() and canonical is None:
        errors.append("canonical_invalid_json")
    try:
        chunks = _load_jsonl(chunks_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        chunks = ()
        errors.append("chunks_invalid_json")
    canonical_version = (canonical or {}).get("document_version")
    version_id = str(
        (
            canonical_version.get("document_version_id")
            if isinstance(canonical_version, dict)
            else None
        )
        or root.name
    )
    return DocumentArtifacts(
        version_dir=root,
        canonical_path=canonical_path,
        chunks_path=chunks_path,
        processing_record_path=processing_path,
        quality_record_path=quality_path,
        canonical=canonical,
        chunks=chunks,
        processing_record=processing_record,
        quality_record=quality_record,
        document_version_id=version_id,
        load_errors=tuple(sorted(errors)),
    )


def artifact_fingerprint(artifacts: DocumentArtifacts) -> str:
    parts = [artifacts.document_version_id]
    for path in (
        artifacts.canonical_path,
        artifacts.chunks_path,
        artifacts.processing_record_path,
        artifacts.quality_record_path,
    ):
        parts.append(file_sha256(path) if path.exists() else "missing")
    return stable_id("artifact", *parts)


def _signal(
    reason_code: str,
    *,
    artifacts: DocumentArtifacts,
    object_id: str,
    detector: str,
    metric_name: str,
    actual_value: str | int | float | bool | None,
    threshold: str | int | float | bool | None,
    page: int | None = None,
    block_id: str | None = None,
    chunk_id: str | None = None,
    evidence_ids: tuple[str, ...] = (),
    message: str = "",
) -> ObservedQualitySignal:
    definition = REASON_CODE_REGISTRY[reason_code]
    return ObservedQualitySignal.create(
        reason_code=reason_code,
        scope=definition.scope,
        object_id=object_id,
        detector=detector,
        detector_version=EVALUATOR_VERSION,
        metric_name=metric_name,
        actual_value=actual_value,
        threshold=threshold,
        confidence=1.0 if definition.hard else 0.75,
        severity=definition.severity,
        document_version_id=artifacts.document_version_id,
        page=page,
        block_id=block_id,
        chunk_id=chunk_id,
        evidence_ids=evidence_ids,
        message=message,
    )


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _page_count(canonical: dict[str, Any]) -> int | None:
    parse_report = canonical.get("parse_report")
    if not isinstance(parse_report, dict):
        return None
    value = parse_report.get("page_count")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _evidence_by_block(
    canonical: dict[str, Any],
) -> dict[str, tuple[dict[str, Any], ...]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for evidence in _dict_rows(canonical.get("evidence_spans")):
        block_id = str(evidence.get("block_id") or "")
        if block_id:
            grouped.setdefault(block_id, []).append(evidence)
    return {
        block_id: tuple(
            sorted(items, key=lambda item: str(item.get("evidence_id") or ""))
        )
        for block_id, items in grouped.items()
    }


def _evidence_ids(items: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(item.get("evidence_id"))
            for item in items
            if item.get("evidence_id")
        )
    )


def _evaluate_document(artifacts: DocumentArtifacts) -> list[ObservedQualitySignal]:
    signals: list[ObservedQualitySignal] = []
    version_id = artifacts.document_version_id
    if not artifacts.canonical_path.exists() or artifacts.canonical is None:
        signals.append(
            _signal(
                "document.integrity.canonical_missing",
                artifacts=artifacts,
                object_id=version_id,
                detector="document-integrity",
                metric_name="canonical_available",
                actual_value=False,
                threshold=True,
            )
        )
        return signals
    if not artifacts.chunks_path.exists():
        signals.append(
            _signal(
                "document.integrity.chunks_missing",
                artifacts=artifacts,
                object_id=version_id,
                detector="document-integrity",
                metric_name="chunks_available",
                actual_value=False,
                threshold=True,
            )
        )
    elif not artifacts.chunks:
        signals.append(
            _signal(
                "document.integrity.no_chunks",
                artifacts=artifacts,
                object_id=version_id,
                detector="document-integrity",
                metric_name="chunk_count",
                actual_value=0,
                threshold=1,
            )
        )
    for path, code in (
        (
            artifacts.processing_record_path,
            "document.integrity.processing_record_missing",
        ),
        (artifacts.quality_record_path, "document.integrity.quality_record_missing"),
    ):
        if not path.exists():
            signals.append(
                _signal(
                    code,
                    artifacts=artifacts,
                    object_id=version_id,
                    detector="document-integrity",
                    metric_name="sidecar_available",
                    actual_value=False,
                    threshold=True,
                )
            )
    for record_name, record in (
        ("processing_record", artifacts.processing_record),
        ("quality_record", artifacts.quality_record),
    ):
        if record is not None:
            actual_version = str(record.get("document_version_id") or "")
            if actual_version != version_id:
                signals.append(
                    _signal(
                        "document.integrity.document_version_mismatch",
                        artifacts=artifacts,
                        object_id=version_id,
                        detector="document-integrity",
                        metric_name=f"{record_name}_document_version_id",
                        actual_value=actual_version,
                        threshold=version_id,
                    )
                )
    parse_report = artifacts.canonical.get("parse_report")
    if not isinstance(parse_report, dict):
        parse_report = {}
    warnings = parse_report.get("warnings")
    warning_count = len(warnings) if isinstance(warnings, list) else 0
    if warning_count > SOFT_WARNING_COUNT:
        signals.append(
            _signal(
                "document.parse.warning_count_high",
                artifacts=artifacts,
                object_id=version_id,
                detector="document-parse",
                metric_name="warning_count",
                actual_value=warning_count,
                threshold=SOFT_WARNING_COUNT,
            )
        )
    quality_report = parse_report.get("quality_report")
    fallback_used = (
        quality_report.get("fallback_used")
        if isinstance(quality_report, dict)
        else False
    )
    if fallback_used is True:
        signals.append(
            _signal(
                "document.parse.fallback_used",
                artifacts=artifacts,
                object_id=version_id,
                detector="document-parse",
                metric_name="fallback_used",
                actual_value=True,
                threshold=False,
            )
        )
    blocks = _dict_rows(artifacts.canonical.get("blocks"))
    char_count = sum(len(str(item.get("text") or "")) for item in blocks)
    if char_count < SOFT_MIN_DOCUMENT_CHARS:
        signals.append(
            _signal(
                "document.content.text_too_short",
                artifacts=artifacts,
                object_id=version_id,
                detector="document-content",
                metric_name="text_character_count",
                actual_value=char_count,
                threshold=SOFT_MIN_DOCUMENT_CHARS,
            )
        )
    return signals


def _evaluate_pages(artifacts: DocumentArtifacts) -> list[ObservedQualitySignal]:
    canonical = artifacts.canonical
    if canonical is None:
        return []
    page_count = _page_count(canonical)
    blocks = _dict_rows(canonical.get("blocks"))
    evidence = _dict_rows(canonical.get("evidence_spans"))
    evidence_by_block = _evidence_by_block(canonical)
    evidence_ids_by_page: dict[int, set[str]] = {}
    for item in evidence:
        page = _positive_int(item.get("page"))
        evidence_id = str(item.get("evidence_id") or "")
        if page is not None and evidence_id:
            evidence_ids_by_page.setdefault(page, set()).add(evidence_id)

    signals: list[ObservedQualitySignal] = []
    if page_count is not None:
        out_of_range_pages: set[int] = {
            page
            for page in evidence_ids_by_page
            if page > page_count
        }
        for block in blocks:
            for key in ("page_start", "page_end"):
                page = _positive_int(block.get(key))
                if page is not None and page > page_count:
                    out_of_range_pages.add(page)
        for page in sorted(out_of_range_pages):
            signals.append(
                _signal(
                    "page.integrity.reference_out_of_range",
                    artifacts=artifacts,
                    object_id=f"{artifacts.document_version_id}:page:{page}",
                    detector="page-integrity",
                    metric_name="page_reference",
                    actual_value=page,
                    threshold=page_count,
                    page=page,
                    evidence_ids=tuple(sorted(evidence_ids_by_page.get(page, set()))),
                )
            )

        for block in blocks:
            text = str(block.get("text") or "")
            if not text.strip():
                continue
            start = _positive_int(block.get("page_start"))
            end = _positive_int(block.get("page_end"))
            has_valid_range = (
                start is not None
                and end is not None
                and start <= end
                and end <= page_count
            )
            block_id = str(block.get("block_id") or "")
            block_evidence = evidence_by_block.get(block_id, ())
            has_resolvable_evidence = any(
                (page := _positive_int(item.get("page"))) is not None
                and page <= page_count
                for item in block_evidence
            )
            if not has_valid_range and not has_resolvable_evidence:
                signals.append(
                    _signal(
                        "page.integrity.source_location_missing",
                        artifacts=artifacts,
                        object_id=block_id or artifacts.document_version_id,
                        detector="page-integrity",
                        metric_name="source_location_available",
                        actual_value=False,
                        threshold=True,
                        block_id=block_id or None,
                        evidence_ids=_evidence_ids(block_evidence),
                    )
                )

        text_by_page = {page: [] for page in range(1, page_count + 1)}
        for block in blocks:
            start = _positive_int(block.get("page_start"))
            end = _positive_int(block.get("page_end"))
            if (
                start is not None
                and end is not None
                and start <= end <= page_count
            ):
                for page in range(start, end + 1):
                    text_by_page[page].append(str(block.get("text") or ""))
        for page, texts in sorted(text_by_page.items()):
            char_count = sum(len(text) for text in texts)
            if char_count < SOFT_MIN_PAGE_CHARS:
                signals.append(
                    _signal(
                        "page.content.text_too_short",
                        artifacts=artifacts,
                        object_id=f"{artifacts.document_version_id}:page:{page}",
                        detector="page-content",
                        metric_name="text_character_count",
                        actual_value=char_count,
                        threshold=SOFT_MIN_PAGE_CHARS,
                        page=page,
                        evidence_ids=tuple(
                            sorted(evidence_ids_by_page.get(page, set()))
                        ),
                    )
                )

    for item in evidence:
        actual_version = str(item.get("document_version_id") or "")
        if actual_version == artifacts.document_version_id:
            continue
        evidence_id = str(item.get("evidence_id") or "")
        page = _positive_int(item.get("page"))
        signals.append(
            _signal(
                "page.integrity.document_version_mismatch",
                artifacts=artifacts,
                object_id=(
                    f"{artifacts.document_version_id}:page:{page}"
                    if page is not None
                    else evidence_id or artifacts.document_version_id
                ),
                detector="page-integrity",
                metric_name="evidence_document_version_id",
                actual_value=actual_version,
                threshold=artifacts.document_version_id,
                page=page,
                block_id=str(item.get("block_id") or "") or None,
                evidence_ids=(evidence_id,) if evidence_id else (),
            )
        )
    return signals


def _evaluate_blocks(artifacts: DocumentArtifacts) -> list[ObservedQualitySignal]:
    canonical = artifacts.canonical
    if canonical is None:
        return []
    blocks = sorted(
        _dict_rows(canonical.get("blocks")),
        key=lambda item: str(item.get("block_id") or ""),
    )
    evidence_by_block = _evidence_by_block(canonical)
    signals: list[ObservedQualitySignal] = []
    hashes: dict[str, list[str]] = {}
    block_by_id: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks):
        block_id = str(block.get("block_id") or f"block_{index}")
        block_by_id[block_id] = block
        block_evidence = evidence_by_block.get(block_id, ())
        evidence_ids = _evidence_ids(block_evidence)
        text = str(block.get("text") or "")
        common = {
            "artifacts": artifacts,
            "object_id": block_id,
            "detector": "block-integrity",
            "block_id": block_id,
            "evidence_ids": evidence_ids,
        }
        if not text.strip():
            signals.append(
                _signal(
                    "block.integrity.empty",
                    metric_name="text_character_count",
                    actual_value=0,
                    threshold=1,
                    **common,
                )
            )
        block_type = str(block.get("block_type") or "")
        if block_type not in VALID_BLOCK_TYPES:
            signals.append(
                _signal(
                    "block.integrity.type_invalid",
                    metric_name="block_type",
                    actual_value=block_type,
                    threshold="valid_block_type",
                    **common,
                )
            )
        raw_start = block.get("page_start")
        raw_end = block.get("page_end")
        start = _positive_int(raw_start)
        end = _positive_int(raw_end)
        range_invalid = (raw_start is None) != (raw_end is None) or (
            raw_start is not None
            and raw_end is not None
            and (start is None or end is None or start > end)
        )
        if range_invalid:
            signals.append(
                _signal(
                    "block.integrity.page_range_invalid",
                    metric_name="page_range",
                    actual_value=f"{raw_start}:{raw_end}",
                    threshold="positive_ordered_range_or_null",
                    **common,
                )
            )
        actual_version = str(block.get("document_version_id") or "")
        if actual_version != artifacts.document_version_id:
            signals.append(
                _signal(
                    "block.integrity.document_version_mismatch",
                    metric_name="document_version_id",
                    actual_value=actual_version,
                    threshold=artifacts.document_version_id,
                    **common,
                )
            )
        if not block_evidence:
            signals.append(
                _signal(
                    "block.evidence.missing",
                    metric_name="evidence_count",
                    actual_value=0,
                    threshold=1,
                    **common,
                )
            )
        for evidence in block_evidence:
            evidence_id = str(evidence.get("evidence_id") or "")
            evidence_text = str(evidence.get("text") or "")
            actual_hash = str(evidence.get("text_hash") or "")
            expected_hash = sha256_text(evidence_text)
            if actual_hash != expected_hash:
                signals.append(
                    _signal(
                        "block.evidence.hash_mismatch",
                        artifacts=artifacts,
                        object_id=block_id,
                        detector="block-evidence",
                        metric_name="text_hash",
                        actual_value=actual_hash,
                        threshold=expected_hash,
                        block_id=block_id,
                        evidence_ids=(evidence_id,) if evidence_id else (),
                    )
                )
        if len(text) > SOFT_MAX_BLOCK_CHARS:
            signals.append(
                _signal(
                    "block.content.too_long",
                    artifacts=artifacts,
                    object_id=block_id,
                    detector="block-content",
                    metric_name="text_character_count",
                    actual_value=len(text),
                    threshold=SOFT_MAX_BLOCK_CHARS,
                    block_id=block_id,
                    evidence_ids=evidence_ids,
                )
            )
        normalized = normalize_space(text)
        if normalized:
            hashes.setdefault(sha256_text(normalized), []).append(block_id)
    for text_hash, object_ids in sorted(hashes.items()):
        for duplicate_id in sorted(object_ids)[1:]:
            signals.append(
                _signal(
                    "block.content.duplicate",
                    artifacts=artifacts,
                    object_id=duplicate_id,
                    detector="block-content",
                    metric_name="normalized_text_hash",
                    actual_value=text_hash,
                    threshold="unique",
                    block_id=duplicate_id,
                    evidence_ids=_evidence_ids(
                        evidence_by_block.get(duplicate_id, ())
                    ),
                )
            )
    return signals


def _evaluate_chunks(artifacts: DocumentArtifacts) -> list[ObservedQualitySignal]:
    if artifacts.canonical is None:
        return []
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in _dict_rows(artifacts.canonical.get("evidence_spans"))
        if item.get("evidence_id")
    }
    chunks = sorted(
        artifacts.chunks,
        key=lambda item: str(item.get("chunk_id") or ""),
    )
    signals: list[ObservedQualitySignal] = []
    hashes: dict[str, list[str]] = {}
    chunk_by_id: dict[str, dict[str, Any]] = {}
    for index, chunk in enumerate(chunks):
        chunk_id = str(chunk.get("chunk_id") or f"chunk_{index}")
        chunk_by_id[chunk_id] = chunk
        text = str(chunk.get("text") or "")
        raw_evidence_ids = chunk.get("evidence_ids")
        evidence_ids = tuple(
            sorted(
                str(item)
                for item in (
                    raw_evidence_ids if isinstance(raw_evidence_ids, list) else []
                )
            )
        )
        common = {
            "artifacts": artifacts,
            "object_id": chunk_id,
            "detector": "chunk-integrity",
            "chunk_id": chunk_id,
            "evidence_ids": evidence_ids,
        }
        if not text.strip():
            signals.append(
                _signal(
                    "chunk.integrity.empty",
                    metric_name="text_character_count",
                    actual_value=0,
                    threshold=1,
                    **common,
                )
            )
        actual_version = str(chunk.get("document_version_id") or "")
        if actual_version != artifacts.document_version_id:
            signals.append(
                _signal(
                    "chunk.integrity.document_version_mismatch",
                    metric_name="document_version_id",
                    actual_value=actual_version,
                    threshold=artifacts.document_version_id,
                    **common,
                )
            )
        if not evidence_ids:
            signals.append(
                _signal(
                    "chunk.evidence.missing",
                    metric_name="evidence_count",
                    actual_value=0,
                    threshold=1,
                    **common,
                )
            )
        missing_ids = tuple(
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id not in evidence_by_id
        )
        if missing_ids:
            signals.append(
                _signal(
                    "chunk.evidence.reference_missing",
                    metric_name="missing_evidence_count",
                    actual_value=len(missing_ids),
                    threshold=0,
                    **{**common, "evidence_ids": missing_ids},
                )
            )
        text_length = len(text)
        if text_length < SOFT_MIN_CHUNK_CHARS:
            signals.append(
                _signal(
                    "chunk.content.too_short",
                    metric_name="text_character_count",
                    actual_value=text_length,
                    threshold=SOFT_MIN_CHUNK_CHARS,
                    **common,
                )
            )
        if text_length > SOFT_MAX_CHUNK_CHARS:
            signals.append(
                _signal(
                    "chunk.content.too_long",
                    metric_name="text_character_count",
                    actual_value=text_length,
                    threshold=SOFT_MAX_CHUNK_CHARS,
                    **common,
                )
            )
        normalized = normalize_space(text)
        if normalized:
            hashes.setdefault(sha256_text(normalized), []).append(chunk_id)
    for object_ids in hashes.values():
        for duplicate_id in sorted(object_ids)[1:]:
            duplicate = chunk_by_id[duplicate_id]
            raw_evidence_ids = duplicate.get("evidence_ids")
            evidence_ids = tuple(
                sorted(
                    str(item)
                    for item in (
                        raw_evidence_ids
                        if isinstance(raw_evidence_ids, list)
                        else []
                    )
                )
            )
            signals.append(
                _signal(
                    "chunk.content.duplicate",
                    artifacts=artifacts,
                    object_id=duplicate_id,
                    detector="chunk-content",
                    metric_name="normalized_text_hash",
                    actual_value=sha256_text(
                        normalize_space(str(duplicate.get("text") or ""))
                    ),
                    threshold="unique",
                    chunk_id=duplicate_id,
                    evidence_ids=evidence_ids,
                )
            )
    return signals


def evaluate_document_version(
    version_dir: Path,
) -> tuple[ObservedQualitySignal, ...]:
    artifacts = load_document_artifacts(version_dir)
    signals = [
        *_evaluate_document(artifacts),
        *_evaluate_pages(artifacts),
        *_evaluate_blocks(artifacts),
        *_evaluate_chunks(artifacts),
    ]
    return tuple(sorted(signals, key=lambda item: item.signal_id))
