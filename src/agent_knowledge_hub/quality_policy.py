from __future__ import annotations

import json
from pathlib import Path

from agent_knowledge_hub.quality_models import (
    QUALITY_ACTIONS,
    QUALITY_MODES,
    QUALITY_POLICY_SCHEMA_VERSION,
    ObservedQualitySignal,
    QualityDecision,
    QualityPolicy,
    QualityPolicyRule,
)
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY
from agent_knowledge_hub.utils import sha256_text


def _policy_hash(payload: dict[str, object]) -> str:
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_text(normalized)


def build_default_observe_policy() -> QualityPolicy:
    rules = tuple(
        QualityPolicyRule(
            reason_code=reason_code,
            severity=definition.severity,
            recommended_action=definition.recommended_action,
        )
        for reason_code, definition in sorted(REASON_CODE_REGISTRY.items())
    )
    identity = {
        "schema_version": QUALITY_POLICY_SCHEMA_VERSION,
        "policy_id": "phase1-observe-default",
        "policy_version": "1",
        "mode": "observe",
    }
    hash_payload = {
        **identity,
        "rules": [
            {
                "reason_code": item.reason_code,
                "severity": item.severity,
                "recommended_action": item.recommended_action,
            }
            for item in rules
        ],
    }
    return QualityPolicy(
        **identity,
        rules=rules,
        policy_hash=_policy_hash(hash_payload),
    )


def load_quality_policy(path: Path | None) -> QualityPolicy:
    if path is None:
        return build_default_observe_policy()
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if payload.get("schema_version") != QUALITY_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported_quality_policy_schema")
    if payload.get("mode") != "observe":
        raise ValueError("phase1_pr1_requires_observe_mode")
    rules = tuple(QualityPolicyRule(**item) for item in payload.get("rules") or [])
    seen: set[str] = set()
    for rule in rules:
        if rule.reason_code not in REASON_CODE_REGISTRY:
            raise ValueError(f"unknown_reason_code:{rule.reason_code}")
        if rule.reason_code in seen:
            raise ValueError(f"duplicate_policy_rule:{rule.reason_code}")
        if rule.severity != REASON_CODE_REGISTRY[rule.reason_code].severity:
            raise ValueError(f"policy_severity_mismatch:{rule.reason_code}")
        if rule.recommended_action not in QUALITY_ACTIONS:
            raise ValueError(
                f"unsupported_quality_action:{rule.recommended_action}"
            )
        seen.add(rule.reason_code)
    base = {
        key: payload[key]
        for key in ("schema_version", "policy_id", "policy_version", "mode")
    }
    normalized = {**base, "rules": [item.__dict__ for item in rules]}
    expected_hash = _policy_hash(normalized)
    if payload.get("policy_hash") != expected_hash:
        raise ValueError("quality_policy_hash_mismatch")
    return QualityPolicy(**base, rules=rules, policy_hash=expected_hash)


def apply_quality_policy(
    signals: tuple[ObservedQualitySignal, ...],
    policy: QualityPolicy,
    *,
    artifact_fingerprint: str,
) -> tuple[QualityDecision, ...]:
    if policy.mode not in QUALITY_MODES:
        raise ValueError(f"unsupported_quality_mode:{policy.mode}")
    rules = {item.reason_code: item for item in policy.rules}
    decisions: list[QualityDecision] = []
    for signal in sorted(signals, key=lambda item: item.signal_id):
        if signal.reason_code not in REASON_CODE_REGISTRY:
            raise ValueError(f"unknown_reason_code:{signal.reason_code}")
        definition = REASON_CODE_REGISTRY[signal.reason_code]
        if signal.scope != definition.scope:
            raise ValueError(f"signal_scope_mismatch:{signal.reason_code}")
        rule = rules.get(signal.reason_code)
        if rule is None:
            raise ValueError(f"missing_policy_rule:{signal.reason_code}")
        if signal.severity != rule.severity:
            raise ValueError(f"signal_severity_mismatch:{signal.reason_code}")
        if rule.recommended_action not in QUALITY_ACTIONS:
            raise ValueError(
                f"unsupported_quality_action:{rule.recommended_action}"
            )
        effective = "warn" if rule.recommended_action == "warn" else "allow"
        decisions.append(
            QualityDecision.create(
                signal_ids=(signal.signal_id,),
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                mode=policy.mode,
                recommended_action=rule.recommended_action,
                effective_action=effective,
                scope=signal.scope,
                object_id=signal.object_id,
                reason_codes=(signal.reason_code,),
                artifact_fingerprint=artifact_fingerprint,
            )
        )
    return tuple(sorted(decisions, key=lambda item: item.decision_id))
