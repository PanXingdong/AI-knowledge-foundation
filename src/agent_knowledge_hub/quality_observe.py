from __future__ import annotations

import json
import tempfile
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
from agent_knowledge_hub.utils import file_sha256, sha256_text, stable_id, write_json


_ARTIFACT_FILENAMES = (
    "canonical-document.json",
    "chunks.jsonl",
    "processing-record.json",
    "quality-record.json",
)


@dataclass(frozen=True)
class QualityObservationResult:
    processed_dir: Path
    report: QualityReport
    publication_preview: PublicationPreview
    quarantine_preview: QuarantinePreview
    markdown: str


def _fingerprint_payload(payload: object) -> str:
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(normalized)


def _determinism_fingerprint(
    payload: object,
    *,
    quality_report_schema_version: str = QUALITY_REPORT_SCHEMA_VERSION,
    publication_preview_schema_version: str = PUBLICATION_PREVIEW_SCHEMA_VERSION,
    quarantine_preview_schema_version: str = QUARANTINE_PREVIEW_SCHEMA_VERSION,
) -> str:
    return _fingerprint_payload(
        {
            "payload": payload,
            "schema_versions": {
                "publication_preview": publication_preview_schema_version,
                "quality_report": quality_report_schema_version,
                "quarantine_preview": quarantine_preview_schema_version,
            },
        }
    )


def _unresolved_document_identity(version_dir: Path) -> str:
    hashes: list[str] = []
    for filename in _ARTIFACT_FILENAMES:
        path = version_dir / filename
        if not path.exists():
            hashes.append("missing")
            continue
        try:
            hashes.append(file_sha256(path))
        except OSError as exc:
            hashes.append(f"unreadable:{type(exc).__name__}")
    return stable_id("unresolved-docver", *hashes)


def _ordered_unique(items: list[Any], id_attribute: str) -> tuple[Any, ...]:
    ordered = sorted(
        items,
        key=lambda item: (
            str(getattr(item, id_attribute)),
            json.dumps(
                item.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    unique: dict[str, Any] = {}
    for item in ordered:
        unique.setdefault(str(getattr(item, id_attribute)), item)
    return tuple(unique[item_id] for item_id in sorted(unique))


def _failed_input_object_id(failed: dict[str, Any], index: int) -> str:
    sample_id = str(failed.get("sample_id") or "").strip()
    if sample_id:
        return f"failed-input:{sample_id}"
    file_path = str(failed.get("file_path") or "").strip()
    if file_path:
        file_identity = Path(file_path).name
        return f"failed-input:{sha256_text(file_identity)[:16]}"
    reason = str(failed.get("reason") or "")
    return f"failed-input:{sha256_text(f'{index}:{reason}')[:16]}"


def _evaluate_ingest_failures(
    root: Path,
) -> tuple[tuple[ObservedQualitySignal, ...], tuple[dict[str, str], ...]]:
    summary_path = root / "ingest-summary.json"
    if not summary_path.exists():
        return (), ()
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        reason_code = "document.evaluator.detector_error"
        definition = REASON_CODE_REGISTRY[reason_code]
        object_id = "failed-input:ingest-summary"
        signal = ObservedQualitySignal.create(
            reason_code=reason_code,
            scope=definition.scope,
            object_id=object_id,
            detector="ingest-summary-loader",
            detector_version="phase1-observe-v1",
            metric_name="summary_loaded",
            actual_value=type(exc).__name__,
            threshold="no_exception",
            confidence=1.0,
            severity=definition.severity,
            document_version_id=object_id,
            message=type(exc).__name__,
        )
        return (signal,), (
            {
                "object_id": object_id,
                "reason": type(exc).__name__,
                "reason_code": reason_code,
            },
        )
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
                document_version_id=object_id,
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
    unique_identity_rows = {
        (
            item["object_id"],
            item["reason_code"],
            item["reason"],
        ): item
        for item in identity_rows
    }
    return (
        _ordered_unique(signals, "signal_id"),
        tuple(unique_identity_rows[key] for key in sorted(unique_identity_rows)),
    )


def _detector_error_signal(
    *,
    document_version_id: str,
    error: Exception,
) -> ObservedQualitySignal:
    reason_code = "document.evaluator.detector_error"
    definition = REASON_CODE_REGISTRY[reason_code]
    error_type = type(error).__name__
    return ObservedQualitySignal.create(
        reason_code=reason_code,
        scope=definition.scope,
        object_id=document_version_id,
        detector="document-quality-evaluator",
        detector_version="phase1-observe-v1",
        metric_name="evaluation_succeeded",
        actual_value=error_type,
        threshold="no_exception",
        confidence=1.0,
        severity=definition.severity,
        document_version_id=document_version_id,
        message=error_type,
    )


def _render_observe_markdown(
    report: QualityReport,
    publication: PublicationPreview,
    quarantine: QuarantinePreview,
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
    detector_errors = tuple(
        signal
        for signal in report.signals
        if signal.reason_code == "document.evaluator.detector_error"
    )
    lines.extend(["", "## Detector Errors", ""])
    if detector_errors:
        lines.extend(
            (
                f"- scope=`{signal.scope}` object=`{signal.object_id}` "
                f"error=`{signal.actual_value}`"
            )
            for signal in detector_errors
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
            for pattern in (
                "canonical-document.json",
                "chunks.jsonl",
                "processing-record.json",
                "quality-record.json",
            )
            for path in root.rglob(pattern)
        },
        key=lambda path: path.as_posix(),
    )
    signals: list[ObservedQualitySignal] = []
    document_ids: set[str] = set()
    all_chunk_ids: set[str] = set()
    artifact_parts: set[str] = set()
    loaded_artifacts: dict[tuple[str, str], Any] = {}

    ingest_signals, ingest_identity = _evaluate_ingest_failures(root)
    signals.extend(ingest_signals)
    if ingest_identity:
        artifact_parts.add(_fingerprint_payload(ingest_identity))

    for version_dir in version_dirs:
        try:
            artifacts = load_document_artifacts(version_dir)
        except Exception as exc:
            object_id = _unresolved_document_identity(version_dir)
            document_ids.add(object_id)
            signals.append(
                _detector_error_signal(
                    document_version_id=object_id,
                    error=exc,
                )
            )
            artifact_parts.add(
                _fingerprint_payload(
                    {
                        "document_version_id": object_id,
                        "error_type": type(exc).__name__,
                    }
                )
            )
            continue
        artifact_fp = artifact_fingerprint(artifacts)
        loaded_artifacts.setdefault(
            (artifacts.document_version_id, artifact_fp),
            artifacts,
        )
        document_ids.add(artifacts.document_version_id)
        artifact_parts.add(artifact_fp)
        all_chunk_ids.update(
            str(item.get("chunk_id"))
            for item in artifacts.chunks
            if item.get("chunk_id")
        )
        try:
            signals.extend(evaluate_document_version(version_dir))
        except Exception as exc:
            signals.append(
                _detector_error_signal(
                    document_version_id=artifacts.document_version_id,
                    error=exc,
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
                document_version_id="processed-tree",
                message="Processed tree contains no document versions.",
            )
        )

    artifact_fp = _fingerprint_payload(sorted(artifact_parts))
    ordered_signals = _ordered_unique(signals, "signal_id")
    decisions = _ordered_unique(
        list(
            apply_quality_policy(
                ordered_signals,
                policy,
                artifact_fingerprint=artifact_fp,
            )
        ),
        "decision_id",
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
    for artifacts_key in sorted(loaded_artifacts):
        artifacts = loaded_artifacts[artifacts_key]
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
            "reason_codes": list(decision.reason_codes),
            "recommended_action": decision.recommended_action,
            "scope": decision.scope,
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
            "reason_codes": list(decision_by_id[decision_id].reason_codes),
            "recommended_action": "quarantine",
            "scope": "chunk",
        }
        for chunk_id, decision_ids in sorted(propagated_chunk_decisions.items())
        for decision_id in sorted(decision_ids)
    ]
    quarantine_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in [*direct_quarantine_items, *propagated_quarantine_items]:
        key = (item["scope"], item["object_id"], item["decision_id"])
        if key not in quarantine_by_key:
            quarantine_by_key[key] = item
    quarantine_items = tuple(
        quarantine_by_key[key] for key in sorted(quarantine_by_key)
    )

    summary_counter = Counter(
        decision.recommended_action for decision in decisions
    )
    summary_counter["signal_count"] = len(ordered_signals)
    summary_counter["decision_count"] = len(decisions)
    publication = PublicationPreview(
        schema_version=PUBLICATION_PREVIEW_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode="observe",
        all_document_version_ids=tuple(sorted(document_ids)),
        all_chunk_ids=tuple(sorted(all_chunk_ids)),
        would_exclude_document_version_ids=tuple(sorted(would_exclude_docs)),
        would_exclude_chunk_ids=tuple(sorted(would_exclude_chunks)),
        decision_ids=tuple(sorted({item.decision_id for item in decisions})),
    )
    quarantine = QuarantinePreview(
        schema_version=QUARANTINE_PREVIEW_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode="observe",
        items=quarantine_items,
    )
    pre_report = {
        "artifact_fingerprint": artifact_fp,
        "decisions": [item.to_dict() for item in decisions],
        "document_version_ids": sorted(document_ids),
        "mode": policy.mode,
        "policy_hash": policy.policy_hash,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "publication_preview": publication.to_dict(),
        "quarantine_preview": quarantine.to_dict(),
        "signals": [item.to_dict() for item in ordered_signals],
        "summary": dict(sorted(summary_counter.items())),
    }
    report = QualityReport(
        schema_version=QUALITY_REPORT_SCHEMA_VERSION,
        determinism_fingerprint=_determinism_fingerprint(pre_report),
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
    markdown = _render_observe_markdown(
        report,
        publication,
        quarantine,
    )
    return QualityObservationResult(
        processed_dir=root,
        report=report,
        publication_preview=publication,
        quarantine_preview=quarantine,
        markdown=markdown,
    )


def _temporary_sibling(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        return Path(handle.name)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = _temporary_sibling(path)
    try:
        write_json(temp_path, payload)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, content: str) -> None:
    temp_path = _temporary_sibling(path)
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


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
    _atomic_write_json(paths["report_json"], result.report.to_dict())
    _atomic_write_json(
        paths["publication_preview"],
        result.publication_preview.to_dict(),
    )
    _atomic_write_json(
        paths["quarantine_preview"],
        result.quarantine_preview.to_dict(),
    )
    _atomic_write_text(paths["report_markdown"], result.markdown)
    return paths
