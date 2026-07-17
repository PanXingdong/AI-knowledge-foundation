from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.quality_evaluators import (
    artifact_fingerprint,
    evaluate_document_version,
    load_document_artifacts,
)
from agent_knowledge_hub.quality_models import (
    PUBLICATION_PREVIEW_SCHEMA_VERSION,
    QUALITY_REPORT_SCHEMA_VERSION,
    QUARANTINE_PREVIEW_SCHEMA_VERSION,
    ObservedQualitySignal,
    PublicationPreview,
    QualityReport,
    QuarantinePreview,
)
from agent_knowledge_hub.quality_policy import apply_quality_policy, load_quality_policy
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import sha256_text, stable_id, write_json


@dataclass(frozen=True)
class QualityObservationResult:
    processed_dir: Path
    report: QualityReport
    publication_preview: PublicationPreview
    quarantine_preview: QuarantinePreview
    detector_errors: tuple[dict[str, str], ...]
    markdown: str


def _fingerprint_payload(payload: object) -> str:
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(normalized)


def _failed_input_object_id(failed: dict[str, Any], index: int) -> str:
    sample_id = str(failed.get("sample_id") or "").strip()
    if sample_id:
        return sample_id
    file_path = str(failed.get("file_path") or "").strip()
    if file_path:
        return Path(file_path).name or f"failed-input-{index}"
    return f"failed-input-{index}"


def _evaluate_ingest_failures(
    root: Path,
) -> tuple[tuple[ObservedQualitySignal, ...], tuple[dict[str, str], ...]]:
    summary_path = root / "ingest-summary.json"
    if not summary_path.exists():
        return (), ()
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        diagnostic = {
            "error_type": type(exc).__name__,
            "object_id": "ingest-summary",
            "scope": "release",
        }
        return (), (diagnostic,)
    failed_rows = payload.get("failed") if isinstance(payload, dict) else []
    if not isinstance(failed_rows, list):
        failed_rows = []
    signals: list[ObservedQualitySignal] = []
    identity_rows: list[dict[str, str]] = []
    for index, failed in enumerate(failed_rows):
        if not isinstance(failed, dict):
            continue
        reason = str(failed.get("reason") or "")
        reason_code = (
            "document.parse.unsupported"
            if "unsupported document format" in reason.lower()
            else "document.parse.failed"
        )
        object_id = _failed_input_object_id(failed, index)
        definition = REASON_CODE_REGISTRY[reason_code]
        signals.append(
            ObservedQualitySignal.create(
                reason_code=reason_code,
                scope=definition.scope,
                object_id=object_id,
                detector="ingest-failure",
                detector_version="phase1-observe-v1",
                metric_name="ingest_succeeded",
                actual_value=False,
                threshold=True,
                confidence=1.0,
                severity=definition.severity,
                document_version_id="",
                message=reason,
            )
        )
        identity_rows.append(
            {
                "object_id": object_id,
                "reason": reason,
                "reason_code": reason_code,
            }
        )
    return (
        tuple(sorted(signals, key=lambda item: item.signal_id)),
        tuple(
            sorted(
                identity_rows,
                key=lambda item: (
                    item["object_id"],
                    item["reason_code"],
                    item["reason"],
                ),
            )
        ),
    )


def _detector_error(
    *,
    error: Exception,
    object_id: str,
    scope: str = "document",
) -> dict[str, str]:
    return {
        "error_type": type(error).__name__,
        "object_id": object_id,
        "scope": scope,
    }


def _render_observe_markdown(
    report: QualityReport,
    publication: PublicationPreview,
    quarantine: QuarantinePreview,
    detector_errors: tuple[dict[str, str], ...],
) -> str:
    lines = [
        "# Quality Observe Report",
        "",
        f"- Policy: `{report.policy_id}`",
        f"- Policy version: `{report.policy_version}`",
        f"- Mode: `{report.mode}`",
        f"- Documents: {len(report.document_version_ids)}",
        f"- Signals: {len(report.signals)}",
        f"- Decisions: {len(report.decisions)}",
        f"- Would exclude documents: "
        f"{len(publication.would_exclude_document_version_ids)}",
        f"- Would exclude chunks: {len(publication.would_exclude_chunk_ids)}",
        f"- Quarantine preview items: {len(quarantine.items)}",
        "",
        "## Recommended Actions",
        "",
    ]
    action_counts = Counter(
        decision.recommended_action for decision in report.decisions
    )
    if action_counts:
        lines.extend(
            f"- `{action}`: {count}"
            for action, count in sorted(action_counts.items())
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Decisions", ""])
    if report.decisions:
        lines.extend(
            (
                f"- `{decision.decision_id}` scope=`{decision.scope}` "
                f"object=`{decision.object_id}` "
                f"reasons=`{','.join(decision.reason_codes)}` "
                f"recommended=`{decision.recommended_action}` "
                f"effective=`{decision.effective_action}`"
            )
            for decision in sorted(
                report.decisions,
                key=lambda item: item.decision_id,
            )
        )
    else:
        lines.append("- None")
    lines.extend(["", "## Detector Errors", ""])
    if detector_errors:
        lines.extend(
            (
                f"- scope=`{item['scope']}` object=`{item['object_id']}` "
                f"error=`{item['error_type']}`"
            )
            for item in detector_errors
        )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def evaluate_processed_dir_observe(
    processed_dir: Path | str,
    policy_path: Path | None = None,
) -> QualityObservationResult:
    root = Path(processed_dir).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {root}")
    policy = load_quality_policy(policy_path)
    version_dirs = sorted(
        {
            path.parent
            for pattern in ("canonical-document.json", "chunks.jsonl")
            for path in root.rglob(pattern)
        },
        key=lambda path: path.as_posix(),
    )
    signals: list[ObservedQualitySignal] = []
    document_ids: list[str] = []
    all_chunk_ids: list[str] = []
    artifact_parts: list[str] = []
    loaded_artifacts = []
    detector_errors: list[dict[str, str]] = []

    ingest_signals, ingest_identity = _evaluate_ingest_failures(root)
    signals.extend(ingest_signals)
    if ingest_identity:
        artifact_parts.append(_fingerprint_payload(ingest_identity))

    for version_dir in version_dirs:
        try:
            artifacts = load_document_artifacts(version_dir)
        except Exception as exc:
            object_id = stable_id(
                "unresolved-docver",
                *(path.name for path in sorted(version_dir.iterdir())),
            )
            detector_errors.append(
                _detector_error(error=exc, object_id=object_id)
            )
            continue
        loaded_artifacts.append(artifacts)
        document_ids.append(artifacts.document_version_id)
        artifact_parts.append(artifact_fingerprint(artifacts))
        all_chunk_ids.extend(
            str(item.get("chunk_id"))
            for item in artifacts.chunks
            if item.get("chunk_id")
        )
        try:
            signals.extend(evaluate_document_version(version_dir))
        except Exception as exc:
            detector_errors.append(
                _detector_error(
                    error=exc,
                    object_id=artifacts.document_version_id,
                )
            )

    if not version_dirs:
        definition = REASON_CODE_REGISTRY["release.integrity.no_documents"]
        signals.append(
            ObservedQualitySignal.create(
                reason_code="release.integrity.no_documents",
                scope=definition.scope,
                object_id="processed-tree",
                detector="release-integrity",
                detector_version="phase1-observe-v1",
                metric_name="document_count",
                actual_value=0,
                threshold=1,
                confidence=1.0,
                severity=definition.severity,
                document_version_id="",
                message="Processed tree contains no document versions.",
            )
        )

    ordered_errors = tuple(
        sorted(
            detector_errors,
            key=lambda item: (
                item["scope"],
                item["object_id"],
                item["error_type"],
            ),
        )
    )
    artifact_fp = _fingerprint_payload(sorted(artifact_parts))
    ordered_signals = tuple(sorted(signals, key=lambda item: item.signal_id))
    decisions = apply_quality_policy(
        ordered_signals,
        policy,
        artifact_fingerprint=artifact_fp,
    )

    would_exclude_docs = {
        decision.object_id
        for decision in decisions
        if decision.recommended_action == "block_document"
    }
    direct_exclude_chunks = {
        decision.object_id
        for decision in decisions
        if decision.scope == "chunk"
        and decision.recommended_action
        in {"quarantine", "block_document", "block_release"}
    }
    signal_by_id = {item.signal_id: item for item in ordered_signals}
    source_decisions_by_evidence: dict[str, set[str]] = {}
    for decision in decisions:
        if decision.recommended_action not in {
            "quarantine",
            "block_document",
            "block_release",
        }:
            continue
        for signal_id in decision.signal_ids:
            for evidence_id in signal_by_id[signal_id].evidence_ids:
                source_decisions_by_evidence.setdefault(evidence_id, set()).add(
                    decision.decision_id
                )

    document_decisions: dict[str, set[str]] = {}
    for decision in decisions:
        if (
            decision.scope == "document"
            and decision.recommended_action == "block_document"
        ):
            document_decisions.setdefault(decision.object_id, set()).add(
                decision.decision_id
            )

    propagated_chunk_decisions: dict[str, set[str]] = {}
    would_exclude_chunks = set(direct_exclude_chunks)
    for artifacts in loaded_artifacts:
        for chunk in artifacts.chunks:
            chunk_id = str(chunk.get("chunk_id") or "")
            if not chunk_id:
                continue
            source_ids = set(
                document_decisions.get(artifacts.document_version_id, set())
            )
            evidence_ids = {
                str(item) for item in chunk.get("evidence_ids") or []
            }
            for evidence_id in evidence_ids:
                source_ids.update(
                    source_decisions_by_evidence.get(evidence_id, set())
                )
            if source_ids:
                would_exclude_chunks.add(chunk_id)
                propagated_chunk_decisions.setdefault(chunk_id, set()).update(
                    source_ids
                )

    direct_quarantine_items = [
        {
            "decision_id": decision.decision_id,
            "object_id": decision.object_id,
            "propagated": False,
            "reason_codes": list(decision.reason_codes),
            "recommended_action": decision.recommended_action,
            "scope": decision.scope,
            "source_decision_id": decision.decision_id,
        }
        for decision in decisions
        if decision.recommended_action
        in {"quarantine", "block_document", "block_release"}
    ]
    decision_by_id = {item.decision_id: item for item in decisions}
    propagated_quarantine_items = [
        {
            "decision_id": decision_id,
            "object_id": chunk_id,
            "propagated": True,
            "reason_codes": list(decision_by_id[decision_id].reason_codes),
            "recommended_action": "quarantine",
            "scope": "chunk",
            "source_decision_id": decision_id,
        }
        for chunk_id, decision_ids in sorted(propagated_chunk_decisions.items())
        for decision_id in sorted(decision_ids)
    ]
    quarantine_items = tuple(
        sorted(
            [*direct_quarantine_items, *propagated_quarantine_items],
            key=lambda item: (
                item["scope"],
                item["object_id"],
                item["source_decision_id"],
                item["decision_id"],
            ),
        )
    )

    summary_counter = Counter(
        decision.recommended_action for decision in decisions
    )
    summary_counter["signal_count"] = len(ordered_signals)
    summary_counter["decision_count"] = len(decisions)
    if ordered_errors:
        summary_counter["detector_error"] = len(ordered_errors)
    pre_report = {
        "artifact_fingerprint": artifact_fp,
        "decisions": [item.to_dict() for item in decisions],
        "detector_errors": list(ordered_errors),
        "document_version_ids": sorted(document_ids),
        "mode": policy.mode,
        "policy_hash": policy.policy_hash,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "signals": [item.to_dict() for item in ordered_signals],
        "summary": dict(sorted(summary_counter.items())),
    }
    report = QualityReport(
        schema_version=QUALITY_REPORT_SCHEMA_VERSION,
        determinism_fingerprint=_fingerprint_payload(pre_report),
        document_version_ids=tuple(sorted(document_ids)),
        signals=ordered_signals,
        decisions=decisions,
        summary=dict(sorted(summary_counter.items())),
        **{
            key: pre_report[key]
            for key in (
                "policy_id",
                "policy_version",
                "policy_hash",
                "mode",
                "artifact_fingerprint",
            )
        },
    )
    publication = PublicationPreview(
        schema_version=PUBLICATION_PREVIEW_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode="observe",
        all_document_version_ids=tuple(sorted(document_ids)),
        all_chunk_ids=tuple(sorted(all_chunk_ids)),
        would_exclude_document_version_ids=tuple(sorted(would_exclude_docs)),
        would_exclude_chunk_ids=tuple(sorted(would_exclude_chunks)),
        decision_ids=tuple(sorted(item.decision_id for item in decisions)),
    )
    quarantine = QuarantinePreview(
        schema_version=QUARANTINE_PREVIEW_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode="observe",
        items=quarantine_items,
    )
    markdown = _render_observe_markdown(
        report,
        publication,
        quarantine,
        ordered_errors,
    )
    return QualityObservationResult(
        processed_dir=root,
        report=report,
        publication_preview=publication,
        quarantine_preview=quarantine,
        detector_errors=ordered_errors,
        markdown=markdown,
    )


def write_quality_observation_bundle(
    output_dir: Path | str,
    result: QualityObservationResult,
) -> dict[str, Path]:
    root = Path(output_dir).resolve()
    paths = {
        "report_json": root / "quality-report.json",
        "report_markdown": root / "quality-report.md",
        "publication_preview": root / "publication-preview.json",
        "quarantine_preview": root / "quarantine-preview.json",
    }
    report_payload = {
        **result.report.to_dict(),
        "detector_errors": list(result.detector_errors),
    }
    write_json(paths["report_json"], report_payload)
    write_json(
        paths["publication_preview"],
        result.publication_preview.to_dict(),
    )
    write_json(
        paths["quarantine_preview"],
        result.quarantine_preview.to_dict(),
    )
    paths["report_markdown"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_markdown"].write_text(result.markdown, encoding="utf-8")
    return paths
