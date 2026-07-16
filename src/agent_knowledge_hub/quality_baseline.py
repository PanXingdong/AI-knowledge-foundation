from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.release_manifest import (
    iter_release_documents,
    load_release_manifest,
)

QUALITY_BASELINE_SCHEMA_VERSION = "knowledge-quality-baseline.v1"


@dataclass(frozen=True)
class QualityBaseline:
    schema_version: str
    release_id: str
    document_count: int
    chunk_count: int
    evidence_count: int
    traceable_chunk_count: int
    traceable_chunk_ratio: float
    quality_status_counts: dict[str, int]
    parser_counts: dict[str, int]
    source_format_counts: dict[str, int]
    warning_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_quality_baseline(manifest_path: Path) -> QualityBaseline:
    manifest = load_release_manifest(manifest_path)
    quality_status_counts: Counter[str] = Counter()
    parser_counts: Counter[str] = Counter()
    source_format_counts: Counter[str] = Counter()
    chunk_count = 0
    evidence_count = 0
    traceable_chunk_count = 0
    warning_count = 0

    for chunks_path, canonical in iter_release_documents(manifest.manifest_path):
        report = canonical.get("parse_report") or {}
        quality_report = report.get("quality_report") or {}
        quality_status_counts[
            str(quality_report.get("status") or "unknown")
        ] += 1
        parser_counts[str(report.get("parser_name") or "unknown")] += 1
        source_format_counts[str(report.get("source_format") or "unknown")] += 1
        warning_count += len(report.get("warnings") or [])

        evidence_ids = {
            str(item.get("evidence_id"))
            for item in canonical.get("evidence_spans") or []
            if item.get("evidence_id")
        }
        evidence_count += len(evidence_ids)
        for chunk in _read_jsonl(chunks_path):
            chunk_count += 1
            references = [
                str(evidence_id)
                for evidence_id in chunk.get("evidence_ids") or []
            ]
            if references and all(
                evidence_id in evidence_ids for evidence_id in references
            ):
                traceable_chunk_count += 1

    ratio = traceable_chunk_count / chunk_count if chunk_count else 0.0
    return QualityBaseline(
        schema_version=QUALITY_BASELINE_SCHEMA_VERSION,
        release_id=manifest.release_id,
        document_count=len(manifest.documents),
        chunk_count=chunk_count,
        evidence_count=evidence_count,
        traceable_chunk_count=traceable_chunk_count,
        traceable_chunk_ratio=round(ratio, 8),
        quality_status_counts=dict(sorted(quality_status_counts.items())),
        parser_counts=dict(sorted(parser_counts.items())),
        source_format_counts=dict(sorted(source_format_counts.items())),
        warning_count=warning_count,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
