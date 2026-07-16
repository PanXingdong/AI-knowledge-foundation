from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.utils import write_json

QUALITY_RECORD_SCHEMA_VERSION = "knowledge-quality-record.v1"
QUALITY_EVALUATOR_VERSION = "phase0-baseline-v1"


@dataclass(frozen=True)
class QualitySignal:
    status: str
    value: float | int | str | bool | None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentProfile:
    source_format: str
    page_count: int | None
    block_count: int
    chunk_count: int
    table_count: int
    text_character_count: int


@dataclass(frozen=True)
class QualityRecord:
    schema_version: str
    document_version_id: str
    evaluator_version: str
    profile: DocumentProfile
    signals: dict[str, QualitySignal]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_quality_record(
    canonical: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> QualityRecord:
    version = canonical["document_version"]
    report = canonical.get("parse_report") or {}
    blocks = canonical.get("blocks") or []
    evidence_ids = {
        str(item.get("evidence_id"))
        for item in canonical.get("evidence_spans") or []
        if item.get("evidence_id")
    }
    traceable = sum(
        1
        for chunk in chunks
        if chunk.get("evidence_ids")
        and all(str(item) in evidence_ids for item in chunk["evidence_ids"])
    )
    ratio = traceable / len(chunks) if chunks else 0.0
    unavailable = QualitySignal(
        status="unavailable",
        value=None,
        reason_codes=("not_measured_in_phase0",),
    )
    return QualityRecord(
        schema_version=QUALITY_RECORD_SCHEMA_VERSION,
        document_version_id=str(version["document_version_id"]),
        evaluator_version=QUALITY_EVALUATOR_VERSION,
        profile=DocumentProfile(
            source_format=str(report.get("source_format") or "unknown"),
            page_count=report.get("page_count"),
            block_count=len(blocks),
            chunk_count=len(chunks),
            table_count=int(report.get("table_count") or 0),
            text_character_count=sum(len(str(block.get("text") or "")) for block in blocks),
        ),
        signals={
            "traceable_chunk_ratio": QualitySignal("observed", ratio),
            "parse_quality_status": QualitySignal(
                "observed",
                str((report.get("quality_report") or {}).get("status") or "unknown"),
            ),
            "parse_quality_score": QualitySignal(
                "observed",
                (report.get("quality_report") or {}).get("score"),
            ),
            "column_count": unavailable,
            "ocr_confidence": unavailable,
            "table_structure_score": unavailable,
            "bbox_coverage": unavailable,
        },
    )


def write_quality_record(path: Path, record: QualityRecord) -> None:
    write_json(path, record.to_dict())
