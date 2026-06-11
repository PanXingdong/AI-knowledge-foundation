from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.models import CANONICAL_DOCUMENT_SCHEMA_VERSION
from agent_knowledge_hub.utils import normalize_space, write_json


@dataclass(frozen=True)
class ProcessedContractSummary:
    processed_dir: Path
    is_valid: bool
    document_count: int
    chunk_count: int
    document_version_ids: list[str]
    error_count: int
    warning_count: int
    errors: list[dict[str, object]]
    warnings: list[dict[str, object]]
    markdown: str

    def to_dict(self) -> dict[str, object]:
        return {
            "processed_dir": str(self.processed_dir),
            "is_valid": self.is_valid,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "document_version_ids": list(self.document_version_ids),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def validate_processed_dir(processed_dir: Path | str) -> ProcessedContractSummary:
    processed_root = Path(processed_dir).resolve()
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    errors: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    document_count = 0
    chunk_count = 0
    document_version_ids: list[str] = []

    canonical_paths = sorted(processed_root.rglob("canonical-document.json"))
    if not canonical_paths:
        errors.append(
            _issue(
                severity="error",
                code="missing_canonical_documents",
                path=processed_root,
                message="No canonical-document.json files found under processed_dir.",
            )
        )

    for canonical_path in canonical_paths:
        document_count += 1
        try:
            canonical = _read_json(canonical_path)
        except json.JSONDecodeError as exc:
            errors.append(
                _issue(
                    severity="error",
                    code="invalid_canonical_json",
                    path=canonical_path,
                    message=str(exc),
                )
            )
            continue

        version_dir = canonical_path.parent
        chunks_path = version_dir / "chunks.jsonl"
        _validate_schema_version(
            canonical=canonical,
            path=canonical_path,
            errors=errors,
        )
        document = _dict_at(canonical, "document")
        document_version = _dict_at(canonical, "document_version")
        parse_report = _dict_at(canonical, "parse_report")
        document_version_id = normalize_space(
            str(document_version.get("document_version_id") or "")
        )
        if document_version_id:
            document_version_ids.append(document_version_id)
        document_id = normalize_space(str(document.get("document_id") or ""))

        _require_object_fields(
            errors=errors,
            obj=document,
            path=canonical_path,
            object_name="document",
            required_fields=(
                "document_id",
                "title",
                "source_type",
                "owner",
                "project",
                "supplier",
                "created_at",
            ),
        )
        _require_object_fields(
            errors=errors,
            obj=document_version,
            path=canonical_path,
            object_name="document_version",
            required_fields=(
                "document_version_id",
                "document_id",
                "version",
                "file_path",
                "file_hash",
                "created_at",
            ),
        )
        _require_object_fields(
            errors=errors,
            obj=parse_report,
            path=canonical_path,
            object_name="parse_report",
            required_fields=(
                "parser_name",
                "source_format",
                "page_count",
                "section_count",
                "block_count",
                "table_count",
                "has_page_numbers",
                "warnings",
                "quality_report",
            ),
        )

        if document_id and document_version.get("document_id") != document_id:
            errors.append(
                _issue(
                    severity="error",
                    code="document_id_mismatch",
                    path=canonical_path,
                    message="document_version.document_id must match document.document_id.",
                    document_version_id=document_version_id,
                )
            )

        if _is_unknown_like(document_version.get("version")):
            warnings.append(
                _issue(
                    severity="warning",
                    code="unknown_document_version",
                    path=canonical_path,
                    message="document_version.version is empty or unknown.",
                    document_version_id=document_version_id,
                )
            )

        section_paths = _collect_section_paths(canonical.get("sections"), canonical_path, errors)
        block_ids = _collect_block_ids(
            canonical.get("blocks"),
            canonical_path,
            errors,
            document_version_id=document_version_id,
            section_paths=section_paths,
        )
        evidence_ids = _collect_evidence_ids(
            canonical.get("evidence_spans"),
            canonical_path,
            errors,
            document_version_id=document_version_id,
            block_ids=block_ids,
            section_paths=section_paths,
        )
        _validate_quality_report(
            parse_report=parse_report,
            path=canonical_path,
            errors=errors,
            warnings=warnings,
            document_version_id=document_version_id,
        )

        if not chunks_path.exists():
            errors.append(
                _issue(
                    severity="error",
                    code="missing_chunks_jsonl",
                    path=chunks_path,
                    message="chunks.jsonl is required next to canonical-document.json.",
                    document_version_id=document_version_id,
                )
            )
            continue

        chunk_count += _validate_chunks_jsonl(
            chunks_path=chunks_path,
            errors=errors,
            document_version_id=document_version_id,
            evidence_ids=evidence_ids,
            section_paths=section_paths,
        )

    markdown = _render_markdown(
        processed_dir=processed_root,
        document_count=document_count,
        chunk_count=chunk_count,
        document_version_ids=document_version_ids,
        errors=errors,
        warnings=warnings,
    )
    return ProcessedContractSummary(
        processed_dir=processed_root,
        is_valid=not errors,
        document_count=document_count,
        chunk_count=chunk_count,
        document_version_ids=document_version_ids,
        error_count=len(errors),
        warning_count=len(warnings),
        errors=errors,
        warnings=warnings,
        markdown=markdown,
    )


def write_processed_contract_summary_bundle(
    *,
    output_dir: Path | str,
    summary: ProcessedContractSummary,
) -> dict[str, Path]:
    bundle_dir = Path(output_dir).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    json_path = bundle_dir / "processed-contract-validation.json"
    markdown_path = bundle_dir / "processed-contract-validation.md"
    write_json(json_path, summary.to_dict())
    markdown_path.write_text(summary.markdown, encoding="utf-8")
    return {
        "json_path": json_path,
        "markdown_path": markdown_path,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _dict_at(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _validate_schema_version(
    *,
    canonical: dict[str, Any],
    path: Path,
    errors: list[dict[str, object]],
) -> None:
    raw_schema_version = canonical.get("schema_version")
    schema_version = normalize_space(str(raw_schema_version or ""))
    if not schema_version:
        errors.append(
            _issue(
                severity="error",
                code="missing_schema_version",
                path=path,
                message="schema_version is required.",
            )
        )
        return
    if schema_version != CANONICAL_DOCUMENT_SCHEMA_VERSION:
        errors.append(
            _issue(
                severity="error",
                code="unsupported_schema_version",
                path=path,
                message=(
                    "schema_version must be "
                    f"{CANONICAL_DOCUMENT_SCHEMA_VERSION}."
                ),
                schema_version=schema_version,
                expected_schema_version=CANONICAL_DOCUMENT_SCHEMA_VERSION,
            )
        )


def _require_object_fields(
    *,
    errors: list[dict[str, object]],
    obj: dict[str, Any],
    path: Path,
    object_name: str,
    required_fields: tuple[str, ...],
) -> None:
    for field in required_fields:
        if field not in obj:
            errors.append(
                _issue(
                    severity="error",
                    code="missing_required_field",
                    path=path,
                    message=f"{object_name}.{field} is required.",
                    field=f"{object_name}.{field}",
                )
            )


def _collect_section_paths(
    sections: object,
    path: Path,
    errors: list[dict[str, object]],
) -> set[tuple[str, ...]]:
    if not isinstance(sections, list):
        errors.append(
            _issue(
                severity="error",
                code="invalid_sections",
                path=path,
                message="sections must be a list.",
            )
        )
        return set()

    section_paths: set[tuple[str, ...]] = set()
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(
                _issue(
                    severity="error",
                    code="invalid_section",
                    path=path,
                    message="section item must be an object.",
                    index=index,
                )
            )
            continue
        section_path = _section_path_tuple(section.get("section_path"))
        if not section_path:
            errors.append(
                _issue(
                    severity="error",
                    code="missing_section_path",
                    path=path,
                    message="section.section_path is required.",
                    index=index,
                )
            )
            continue
        section_paths.add(section_path)
    return section_paths


def _collect_block_ids(
    blocks: object,
    path: Path,
    errors: list[dict[str, object]],
    *,
    document_version_id: str,
    section_paths: set[tuple[str, ...]],
) -> set[str]:
    if not isinstance(blocks, list):
        errors.append(
            _issue(
                severity="error",
                code="invalid_blocks",
                path=path,
                message="blocks must be a list.",
                document_version_id=document_version_id,
            )
        )
        return set()

    block_ids: set[str] = set()
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(
                _issue(
                    severity="error",
                    code="invalid_block",
                    path=path,
                    message="block item must be an object.",
                    document_version_id=document_version_id,
                    index=index,
                )
            )
            continue
        block_id = normalize_space(str(block.get("block_id") or ""))
        if not block_id:
            errors.append(
                _issue(
                    severity="error",
                    code="missing_block_id",
                    path=path,
                    message="block.block_id is required.",
                    document_version_id=document_version_id,
                    index=index,
                )
            )
        else:
            block_ids.add(block_id)
        _validate_version_reference(
            errors=errors,
            actual=str(block.get("document_version_id") or ""),
            expected=document_version_id,
            path=path,
            code="block_document_version_mismatch",
            message="block.document_version_id must match document_version.document_version_id.",
            document_version_id=document_version_id,
            index=index,
        )
        _validate_section_reference(
            errors=errors,
            section_path=_section_path_tuple(block.get("section_path")),
            section_paths=section_paths,
            path=path,
            code="unknown_block_section_path",
            message="block.section_path must point to a known section.",
            document_version_id=document_version_id,
            index=index,
            block_id=block_id,
        )
    return block_ids


def _collect_evidence_ids(
    evidence_spans: object,
    path: Path,
    errors: list[dict[str, object]],
    *,
    document_version_id: str,
    block_ids: set[str],
    section_paths: set[tuple[str, ...]],
) -> set[str]:
    if not isinstance(evidence_spans, list):
        errors.append(
            _issue(
                severity="error",
                code="invalid_evidence_spans",
                path=path,
                message="evidence_spans must be a list.",
                document_version_id=document_version_id,
            )
        )
        return set()

    evidence_ids: set[str] = set()
    for index, evidence in enumerate(evidence_spans):
        if not isinstance(evidence, dict):
            errors.append(
                _issue(
                    severity="error",
                    code="invalid_evidence_span",
                    path=path,
                    message="evidence span item must be an object.",
                    document_version_id=document_version_id,
                    index=index,
                )
            )
            continue
        evidence_id = normalize_space(str(evidence.get("evidence_id") or ""))
        block_id = normalize_space(str(evidence.get("block_id") or ""))
        if not evidence_id:
            errors.append(
                _issue(
                    severity="error",
                    code="missing_evidence_id",
                    path=path,
                    message="evidence.evidence_id is required.",
                    document_version_id=document_version_id,
                    index=index,
                )
            )
        else:
            evidence_ids.add(evidence_id)
        _validate_version_reference(
            errors=errors,
            actual=str(evidence.get("document_version_id") or ""),
            expected=document_version_id,
            path=path,
            code="evidence_document_version_mismatch",
            message="evidence.document_version_id must match document_version.document_version_id.",
            document_version_id=document_version_id,
            index=index,
            evidence_id=evidence_id,
        )
        if block_id not in block_ids:
            errors.append(
                _issue(
                    severity="error",
                    code="unknown_evidence_block_id",
                    path=path,
                    message="evidence.block_id must point to a known block.",
                    document_version_id=document_version_id,
                    index=index,
                    evidence_id=evidence_id,
                    block_id=block_id,
                )
            )
        _validate_section_reference(
            errors=errors,
            section_path=_section_path_tuple(evidence.get("section_path")),
            section_paths=section_paths,
            path=path,
            code="unknown_evidence_section_path",
            message="evidence.section_path must point to a known section.",
            document_version_id=document_version_id,
            index=index,
            evidence_id=evidence_id,
        )
    return evidence_ids


def _validate_quality_report(
    *,
    parse_report: dict[str, Any],
    path: Path,
    errors: list[dict[str, object]],
    warnings: list[dict[str, object]],
    document_version_id: str,
) -> None:
    quality_report = parse_report.get("quality_report")
    if not isinstance(quality_report, dict):
        errors.append(
            _issue(
                severity="error",
                code="missing_quality_report",
                path=path,
                message="parse_report.quality_report must be an object.",
                document_version_id=document_version_id,
            )
        )
        return
    status = normalize_space(str(quality_report.get("status") or ""))
    if not status:
        errors.append(
            _issue(
                severity="error",
                code="missing_quality_status",
                path=path,
                message="parse_report.quality_report.status is required.",
                document_version_id=document_version_id,
            )
        )
    if _optional_float(quality_report.get("score")) is None:
        warnings.append(
            _issue(
                severity="warning",
                code="missing_quality_score",
                path=path,
                message="parse_report.quality_report.score is missing or not numeric.",
                document_version_id=document_version_id,
            )
        )


def _validate_chunks_jsonl(
    *,
    chunks_path: Path,
    errors: list[dict[str, object]],
    document_version_id: str,
    evidence_ids: set[str],
    section_paths: set[tuple[str, ...]],
) -> int:
    chunk_count = 0
    for line_number, line in enumerate(chunks_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        chunk_count += 1
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                _issue(
                    severity="error",
                    code="invalid_chunk_json",
                    path=chunks_path,
                    message=str(exc),
                    document_version_id=document_version_id,
                    line_number=line_number,
                )
            )
            continue
        if not isinstance(chunk, dict):
            errors.append(
                _issue(
                    severity="error",
                    code="invalid_chunk",
                    path=chunks_path,
                    message="chunk line must be a JSON object.",
                    document_version_id=document_version_id,
                    line_number=line_number,
                )
            )
            continue
        chunk_id = normalize_space(str(chunk.get("chunk_id") or ""))
        _require_chunk_fields(
            errors=errors,
            chunk=chunk,
            path=chunks_path,
            document_version_id=document_version_id,
            line_number=line_number,
            chunk_id=chunk_id,
        )
        _validate_version_reference(
            errors=errors,
            actual=str(chunk.get("document_version_id") or ""),
            expected=document_version_id,
            path=chunks_path,
            code="chunk_document_version_mismatch",
            message="chunk.document_version_id must match document_version.document_version_id.",
            document_version_id=document_version_id,
            line_number=line_number,
            chunk_id=chunk_id,
        )
        _validate_section_reference(
            errors=errors,
            section_path=_section_path_tuple(chunk.get("section_path")),
            section_paths=section_paths,
            path=chunks_path,
            code="unknown_chunk_section_path",
            message="chunk.section_path must point to a known section.",
            document_version_id=document_version_id,
            line_number=line_number,
            chunk_id=chunk_id,
        )
        for evidence_id in [str(item) for item in (chunk.get("evidence_ids") or [])]:
            if evidence_id not in evidence_ids:
                errors.append(
                    _issue(
                        severity="error",
                        code="unknown_evidence_id",
                        path=chunks_path,
                        message="chunk.evidence_ids must point to known evidence_spans.",
                        document_version_id=document_version_id,
                        line_number=line_number,
                        chunk_id=chunk_id,
                        evidence_id=evidence_id,
                    )
                )
    if chunk_count == 0:
        errors.append(
            _issue(
                severity="error",
                code="empty_chunks_jsonl",
                path=chunks_path,
                message="chunks.jsonl must contain at least one chunk.",
                document_version_id=document_version_id,
            )
        )
    return chunk_count


def _require_chunk_fields(
    *,
    errors: list[dict[str, object]],
    chunk: dict[str, Any],
    path: Path,
    document_version_id: str,
    line_number: int,
    chunk_id: str,
) -> None:
    for field in (
        "chunk_id",
        "document_version_id",
        "section_path",
        "page_start",
        "page_end",
        "text",
        "evidence_ids",
        "embedding_id",
        "metadata",
    ):
        if field not in chunk:
            errors.append(
                _issue(
                    severity="error",
                    code="missing_required_field",
                    path=path,
                    message=f"chunk.{field} is required.",
                    field=f"chunk.{field}",
                    document_version_id=document_version_id,
                    line_number=line_number,
                    chunk_id=chunk_id,
                )
            )


def _validate_version_reference(
    *,
    errors: list[dict[str, object]],
    actual: str,
    expected: str,
    path: Path,
    code: str,
    message: str,
    **extra: object,
) -> None:
    if normalize_space(actual) != normalize_space(expected):
        errors.append(
            _issue(
                severity="error",
                code=code,
                path=path,
                message=message,
                **extra,
            )
        )


def _validate_section_reference(
    *,
    errors: list[dict[str, object]],
    section_path: tuple[str, ...],
    section_paths: set[tuple[str, ...]],
    path: Path,
    code: str,
    message: str,
    **extra: object,
) -> None:
    if section_path not in section_paths:
        errors.append(
            _issue(
                severity="error",
                code=code,
                path=path,
                message=message,
                **extra,
            )
        )


def _section_path_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return tuple()
    return tuple(str(item) for item in value if str(item))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_unknown_like(value: object) -> bool:
    normalized = normalize_space(str(value or "")).lower()
    return normalized in {"", "unknown", "待确认", "待提供", "待填写"}


def _issue(
    *,
    severity: str,
    code: str,
    path: Path,
    message: str,
    **extra: object,
) -> dict[str, object]:
    return {
        "severity": severity,
        "code": code,
        "path": str(path),
        "message": message,
        **{key: value for key, value in extra.items() if value not in (None, "")},
    }


def _render_markdown(
    *,
    processed_dir: Path,
    document_count: int,
    chunk_count: int,
    document_version_ids: list[str],
    errors: list[dict[str, object]],
    warnings: list[dict[str, object]],
) -> str:
    lines = [
        "# Processed Contract Validation",
        "",
        f"Processed Dir: `{processed_dir}`",
        f"Valid: `{not errors}`",
        f"Documents: `{document_count}`",
        f"Chunks: `{chunk_count}`",
        f"Document Versions: `{', '.join(document_version_ids) if document_version_ids else 'none'}`",
        f"Errors: `{len(errors)}`",
        f"Warnings: `{len(warnings)}`",
        "",
        "## Errors",
        "",
    ]
    if errors:
        lines.extend(_render_issue_lines(errors))
    else:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        lines.extend(_render_issue_lines(warnings))
    else:
        lines.append("- None")
    return "\n".join(lines).strip() + "\n"


def _render_issue_lines(issues: list[dict[str, object]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        context_parts = []
        for key in ("document_version_id", "chunk_id", "evidence_id", "line_number", "field"):
            if key in issue:
                context_parts.append(f"{key}={issue[key]}")
        context = f" ({', '.join(context_parts)})" if context_parts else ""
        lines.append(
            f"- `{issue['code']}`{context}: {issue['message']} [{issue['path']}]"
        )
    return lines
