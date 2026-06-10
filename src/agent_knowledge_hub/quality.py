from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.utils import normalize_space, write_json


ALLOWED_QUALITY_STATUSES = {"ok", "recovered_by_fallback"}


@dataclass(frozen=True)
class ParseQualityDocument:
    document_id: str
    document_version_id: str
    title: str
    source_type: str
    owner: str
    project: str
    supplier: str
    document_version: str
    source_path: str
    parser_name: str
    source_format: str
    page_count: int | None
    section_count: int
    block_count: int
    table_count: int
    has_page_numbers: bool
    warning_count: int
    warnings: list[str]
    quality_status: str
    quality_score: float | None
    fallback_used: bool
    fallback_parser: str | None
    reason_codes: list[str]
    metrics: dict[str, Any]
    allowed_for_context_pack: bool
    gate_reasons: list[str]
    canonical_document_path: str
    chunks_jsonl_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParseQualityFailedInput:
    sample_id: str | None
    title: str
    source_path: str
    quality_status: str
    allowed_for_context_pack: bool
    gate_reasons: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParseQualitySummary:
    processed_dir: Path
    processed_document_count: int
    failed_input_count: int
    allowed_document_count: int
    blocked_document_count: int
    status_counts: dict[str, int]
    documents: list[ParseQualityDocument]
    failed_inputs: list[ParseQualityFailedInput]
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed_dir": str(self.processed_dir),
            "processed_document_count": self.processed_document_count,
            "failed_input_count": self.failed_input_count,
            "allowed_document_count": self.allowed_document_count,
            "blocked_document_count": self.blocked_document_count,
            "status_counts": dict(self.status_counts),
            "documents": [document.to_dict() for document in self.documents],
            "failed_inputs": [failed.to_dict() for failed in self.failed_inputs],
        }


def build_parse_quality_summary(processed_dir: Path | str) -> ParseQualitySummary:
    processed_root = Path(processed_dir).resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    documents = [
        _document_from_canonical(canonical_path)
        for canonical_path in sorted(processed_root.rglob("canonical-document.json"))
    ]
    failed_inputs = _load_failed_inputs(processed_root)
    status_counter: Counter[str] = Counter(document.quality_status for document in documents)
    status_counter.update(failed.quality_status for failed in failed_inputs)

    allowed_count = sum(1 for document in documents if document.allowed_for_context_pack)
    blocked_count = len(documents) + len(failed_inputs) - allowed_count
    markdown = _render_parse_quality_summary_markdown(
        processed_dir=processed_root,
        documents=documents,
        failed_inputs=failed_inputs,
        status_counts=status_counter,
        allowed_document_count=allowed_count,
        blocked_document_count=blocked_count,
    )
    return ParseQualitySummary(
        processed_dir=processed_root,
        processed_document_count=len(documents),
        failed_input_count=len(failed_inputs),
        allowed_document_count=allowed_count,
        blocked_document_count=blocked_count,
        status_counts=dict(sorted(status_counter.items())),
        documents=documents,
        failed_inputs=failed_inputs,
        markdown=markdown,
    )


def write_parse_quality_summary_bundle(
    *,
    output_dir: Path | str,
    summary: ParseQualitySummary,
) -> dict[str, Path]:
    bundle_dir = Path(output_dir).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    json_path = bundle_dir / "parse-quality-summary.json"
    markdown_path = bundle_dir / "parse-quality-summary.md"

    write_json(json_path, summary.to_dict())
    markdown_path.write_text(summary.markdown, encoding="utf-8")
    return {"json_path": json_path, "markdown_path": markdown_path}


def _document_from_canonical(canonical_path: Path) -> ParseQualityDocument:
    payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    document = payload.get("document") or {}
    version = payload.get("document_version") or {}
    parse_report = payload.get("parse_report") or {}
    quality_report = parse_report.get("quality_report") or {}
    quality_status = normalize_space(str(quality_report.get("status") or "unknown"))
    quality_score = _optional_float(quality_report.get("score"))
    warnings = [str(warning) for warning in (parse_report.get("warnings") or [])]
    reason_codes = [str(reason) for reason in (quality_report.get("reason_codes") or [])]
    allowed, gate_reasons = _context_pack_gate(
        quality_status=quality_status,
        quality_score=quality_score,
        chunks_jsonl_path=canonical_path.with_name("chunks.jsonl"),
    )

    return ParseQualityDocument(
        document_id=str(document.get("document_id") or ""),
        document_version_id=str(version.get("document_version_id") or ""),
        title=normalize_space(str(document.get("title") or canonical_path.parent.parent.name)),
        source_type=normalize_space(str(document.get("source_type") or "unknown")),
        owner=normalize_space(str(document.get("owner") or "unknown")),
        project=normalize_space(str(document.get("project") or "unknown")),
        supplier=normalize_space(str(document.get("supplier") or "unknown")),
        document_version=normalize_space(str(version.get("version") or "unknown")),
        source_path=normalize_space(str(version.get("file_path") or "")),
        parser_name=normalize_space(str(parse_report.get("parser_name") or "unknown")),
        source_format=normalize_space(str(parse_report.get("source_format") or "unknown")),
        page_count=parse_report.get("page_count"),
        section_count=int(parse_report.get("section_count") or 0),
        block_count=int(parse_report.get("block_count") or 0),
        table_count=int(parse_report.get("table_count") or 0),
        has_page_numbers=bool(parse_report.get("has_page_numbers")),
        warning_count=len(warnings),
        warnings=warnings,
        quality_status=quality_status,
        quality_score=quality_score,
        fallback_used=bool(quality_report.get("fallback_used")),
        fallback_parser=(
            normalize_space(str(quality_report.get("fallback_parser")))
            if quality_report.get("fallback_parser") is not None
            else None
        ),
        reason_codes=reason_codes,
        metrics=dict(quality_report.get("metrics") or {}),
        allowed_for_context_pack=allowed,
        gate_reasons=gate_reasons,
        canonical_document_path=str(canonical_path),
        chunks_jsonl_path=str(canonical_path.with_name("chunks.jsonl"))
        if canonical_path.with_name("chunks.jsonl").exists()
        else None,
    )


def _load_failed_inputs(processed_dir: Path) -> list[ParseQualityFailedInput]:
    summary_path = processed_dir / "ingest-summary.json"
    if not summary_path.exists():
        return []

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    failed_inputs: list[ParseQualityFailedInput] = []
    for failed in payload.get("failed") or []:
        reason = normalize_space(str(failed.get("reason") or "unknown failure"))
        quality_status = _failed_quality_status(reason)
        failed_inputs.append(
            ParseQualityFailedInput(
                sample_id=normalize_space(str(failed.get("sample_id") or "")) or None,
                title=normalize_space(str(failed.get("document_title") or failed.get("sample_id") or "failed input")),
                source_path=normalize_space(str(failed.get("file_path") or "")),
                quality_status=quality_status,
                allowed_for_context_pack=False,
                gate_reasons=[f"quality_status_{quality_status}"],
                reason=reason,
            )
        )
    return failed_inputs


def _failed_quality_status(reason: str) -> str:
    lowered = reason.lower()
    if "unsupported document format" in lowered:
        return "unsupported"
    if "ocr" in lowered and "unavailable" in lowered:
        return "ocr_unavailable"
    return "failed"


def _context_pack_gate(
    *,
    quality_status: str,
    quality_score: float | None,
    chunks_jsonl_path: Path,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if quality_status not in ALLOWED_QUALITY_STATUSES:
        reasons.append(f"quality_status_{quality_status or 'unknown'}")
    if quality_score is not None and quality_score < 40.0:
        reasons.append("quality_score_below_40")
    if not chunks_jsonl_path.exists():
        reasons.append("missing_chunks_jsonl")
    return not reasons, reasons


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_parse_quality_summary_markdown(
    *,
    processed_dir: Path,
    documents: list[ParseQualityDocument],
    failed_inputs: list[ParseQualityFailedInput],
    status_counts: Counter[str],
    allowed_document_count: int,
    blocked_document_count: int,
) -> str:
    lines = [
        "# Parse Quality Summary",
        "",
        f"Processed Dir: `{processed_dir}`",
        "",
        "## Totals",
        "",
        f"- Processed documents: {len(documents)}",
        f"- Failed inputs: {len(failed_inputs)}",
        f"- Allowed for Context Pack: {allowed_document_count}",
        f"- Blocked from Context Pack: {blocked_document_count}",
        "",
        "## Status Counts",
        "",
    ]
    if status_counts:
        lines.extend(f"- `{status}`: {count}" for status, count in sorted(status_counts.items()))
    else:
        lines.append("- None")

    lines.extend(["", "## Documents", ""])
    if documents:
        lines.extend(
            [
                "| Title | Status | Score | Gate | Parser | Owner | Project | Supplier |",
                "| --- | --- | ---: | --- | --- | --- | --- | --- |",
            ]
        )
        for document in documents:
            gate = "allow" if document.allowed_for_context_pack else ", ".join(document.gate_reasons)
            score = "" if document.quality_score is None else f"{document.quality_score:.2f}"
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_table_cell(document.title),
                        f"`{document.quality_status}`",
                        score,
                        _escape_table_cell(gate),
                        _escape_table_cell(document.parser_name),
                        _escape_table_cell(document.owner),
                        _escape_table_cell(document.project),
                        _escape_table_cell(document.supplier),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Failed Inputs", ""])
    if failed_inputs:
        lines.extend(
            [
                "| Title | Status | Gate | Source Path | Reason |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for failed in failed_inputs:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_table_cell(failed.title),
                        f"`{failed.quality_status}`",
                        ", ".join(failed.gate_reasons),
                        _escape_table_cell(failed.source_path),
                        _escape_table_cell(failed.reason),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- None")

    return "\n".join(lines).strip() + "\n"


def _escape_table_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
