from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from agent_knowledge_hub.utils import stable_id


KNOWLEDGE_QUALITY_SCHEMA_VERSION = "knowledge-quality.v1"
QUALITY_REPORT_SCHEMA_VERSION = "knowledge-quality-report.v1"
QUALITY_POLICY_SCHEMA_VERSION = "knowledge-quality-policy.v1"
PUBLICATION_PREVIEW_SCHEMA_VERSION = "knowledge-publication-preview.v1"
QUARANTINE_PREVIEW_SCHEMA_VERSION = "knowledge-quarantine-preview.v1"

QUALITY_SCOPES = frozenset({"document", "page", "block", "chunk", "release"})
QUALITY_SEVERITIES = frozenset({"info", "warning", "error", "fatal"})
QUALITY_ACTIONS = frozenset(
    {"allow", "warn", "quarantine", "block_document", "block_release"}
)
QUALITY_MODES = frozenset({"observe", "candidate_enforce", "production_enforce"})

JsonScalar = str | int | float | bool | None


@dataclass(frozen=True)
class ObservedQualitySignal:
    signal_id: str
    reason_code: str
    scope: str
    object_id: str
    detector: str
    detector_version: str
    metric_name: str
    actual_value: JsonScalar
    threshold: JsonScalar
    confidence: float
    severity: str
    document_version_id: str
    page: int | None = None
    block_id: str | None = None
    chunk_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    message: str = ""

    @classmethod
    def create(cls, **values: Any) -> ObservedQualitySignal:
        payload = dict(values)
        evidence_ids = tuple(
            sorted(str(item) for item in payload.pop("evidence_ids", ()))
        )
        signal_id = stable_id(
            "signal",
            payload["reason_code"],
            payload["scope"],
            payload["object_id"],
            payload["detector"],
            payload["detector_version"],
            payload["metric_name"],
            payload.get("actual_value"),
            payload.get("threshold"),
            payload["document_version_id"],
            payload.get("page"),
            payload.get("block_id"),
            payload.get("chunk_id"),
            *evidence_ids,
        )
        return cls(signal_id=signal_id, evidence_ids=evidence_ids, **payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityPolicyRule:
    reason_code: str
    severity: str
    recommended_action: str


@dataclass(frozen=True)
class QualityPolicy:
    schema_version: str
    policy_id: str
    policy_version: str
    mode: str
    rules: tuple[QualityPolicyRule, ...]
    policy_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityDecision:
    decision_id: str
    signal_ids: tuple[str, ...]
    policy_id: str
    policy_version: str
    mode: str
    recommended_action: str
    effective_action: str
    scope: str
    object_id: str
    reason_codes: tuple[str, ...]
    artifact_fingerprint: str

    @classmethod
    def create(cls, **values: Any) -> QualityDecision:
        payload = dict(values)
        signal_ids = tuple(sorted(payload.pop("signal_ids")))
        reason_codes = tuple(sorted(payload.pop("reason_codes")))
        decision_id = stable_id(
            "decision",
            payload["policy_id"],
            payload["policy_version"],
            payload["mode"],
            payload["scope"],
            payload["object_id"],
            payload["recommended_action"],
            payload["effective_action"],
            payload["artifact_fingerprint"],
            *signal_ids,
            *reason_codes,
        )
        return cls(
            decision_id=decision_id,
            signal_ids=signal_ids,
            reason_codes=reason_codes,
            **payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QualityReport:
    schema_version: str
    policy_id: str
    policy_version: str
    policy_hash: str
    mode: str
    artifact_fingerprint: str
    determinism_fingerprint: str
    document_version_ids: tuple[str, ...]
    signals: tuple[ObservedQualitySignal, ...]
    decisions: tuple[QualityDecision, ...]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "signals": [item.to_dict() for item in self.signals],
            "decisions": [item.to_dict() for item in self.decisions],
        }


@dataclass(frozen=True)
class PublicationPreview:
    schema_version: str
    policy_id: str
    policy_version: str
    mode: str
    all_document_version_ids: tuple[str, ...]
    all_chunk_ids: tuple[str, ...]
    would_exclude_document_version_ids: tuple[str, ...]
    would_exclude_chunk_ids: tuple[str, ...]
    decision_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuarantinePreview:
    schema_version: str
    policy_id: str
    policy_version: str
    mode: str
    items: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
