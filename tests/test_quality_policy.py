import hashlib
import json
from pathlib import Path

import pytest

from agent_knowledge_hub.quality_models import (
    QUALITY_POLICY_SCHEMA_VERSION,
    ObservedQualitySignal,
)
from agent_knowledge_hub.quality_policy import (
    apply_quality_policy,
    build_default_observe_policy,
    load_quality_policy,
)
from agent_knowledge_hub.quality_registry import REASON_CODE_REGISTRY


def _signal(
    reason_code: str,
    *,
    scope: str | None = None,
    severity: str | None = None,
) -> ObservedQualitySignal:
    definition = REASON_CODE_REGISTRY[reason_code]
    return ObservedQualitySignal.create(
        reason_code=reason_code,
        scope=scope or definition.scope,
        object_id="chunk_1",
        detector="test",
        detector_version="1",
        metric_name="count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity=severity or definition.severity,
        document_version_id="docver_1",
        chunk_id="chunk_1" if definition.scope == "chunk" else None,
        message="fixture",
    )


def _policy_hash(payload: dict[str, object]) -> str:
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _custom_payload(
    *,
    rules: list[dict[str, str]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "schema_version": QUALITY_POLICY_SCHEMA_VERSION,
        "policy_id": "custom-observe",
        "policy_version": "7",
        "mode": "observe",
    }
    selected_rules = rules or [
        {
            "reason_code": "chunk.content.too_short",
            "severity": "warning",
            "recommended_action": "warn",
        }
    ]
    hash_payload = {**identity, "rules": selected_rules}
    payload = {
        **hash_payload,
        "policy_hash": _policy_hash(hash_payload),
    }
    payload.update(overrides)
    return payload


def _write_policy(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_default_policy_covers_every_registered_reason_code():
    policy = build_default_observe_policy()

    assert tuple(rule.reason_code for rule in policy.rules) == tuple(
        sorted(REASON_CODE_REGISTRY)
    )


def test_integrity_review_reason_codes_have_exact_registry_contract():
    expected = {
        "document.evaluator.detector_error": (
            "document",
            "error",
            "block_document",
            True,
        ),
        "document.integrity.canonical_invalid": (
            "document",
            "fatal",
            "block_document",
            True,
        ),
        "document.integrity.chunks_invalid": (
            "document",
            "fatal",
            "block_document",
            True,
        ),
        "document.integrity.processing_record_invalid": (
            "document",
            "error",
            "block_document",
            True,
        ),
        "document.integrity.quality_record_invalid": (
            "document",
            "error",
            "block_document",
            True,
        ),
        "block.evidence.block_reference_missing": (
            "block",
            "error",
            "quarantine",
            True,
        ),
    }

    assert {
        reason_code: (
            definition.scope,
            definition.severity,
            definition.recommended_action,
            definition.hard,
        )
        for reason_code, definition in REASON_CODE_REGISTRY.items()
        if reason_code in expected
    } == expected


def test_default_policy_recommends_quarantine_but_observe_effectively_allows():
    policy = build_default_observe_policy()
    decisions = apply_quality_policy(
        (_signal("chunk.evidence.reference_missing"),),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert decisions[0].recommended_action == "quarantine"
    assert decisions[0].effective_action == "allow"


def test_default_policy_recommends_block_but_observe_effectively_allows():
    policy = build_default_observe_policy()
    decisions = apply_quality_policy(
        (_signal("release.integrity.no_documents"),),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert decisions[0].recommended_action == "block_release"
    assert decisions[0].effective_action == "allow"


def test_detector_error_recommends_document_block_but_observe_allows():
    policy = build_default_observe_policy()

    decisions = apply_quality_policy(
        (_signal("document.evaluator.detector_error"),),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert decisions[0].scope == "document"
    assert decisions[0].recommended_action == "block_document"
    assert decisions[0].effective_action == "allow"


def test_soft_signal_remains_warning_in_observe():
    policy = build_default_observe_policy()
    decisions = apply_quality_policy(
        (_signal("chunk.content.too_short", severity="warning"),),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert decisions[0].recommended_action == "warn"
    assert decisions[0].effective_action == "warn"


def test_unknown_reason_code_is_rejected():
    policy = build_default_observe_policy()
    unknown = ObservedQualitySignal.create(
        reason_code="chunk.unknown.rule",
        scope="chunk",
        object_id="chunk_1",
        detector="test",
        detector_version="1",
        metric_name="count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        chunk_id="chunk_1",
    )

    with pytest.raises(ValueError, match="^unknown_reason_code:chunk.unknown.rule$"):
        apply_quality_policy((unknown,), policy, artifact_fingerprint="artifact_1")


def test_registered_signal_with_wrong_scope_is_rejected():
    policy = build_default_observe_policy()
    signal = _signal("chunk.content.too_short", scope="document")

    with pytest.raises(
        ValueError,
        match="^signal_scope_mismatch:chunk.content.too_short$",
    ):
        apply_quality_policy((signal,), policy, artifact_fingerprint="artifact_1")


def test_registered_signal_with_wrong_severity_is_rejected():
    policy = build_default_observe_policy()
    signal = _signal("chunk.content.too_short", severity="error")

    with pytest.raises(
        ValueError,
        match="^signal_severity_mismatch:chunk.content.too_short$",
    ):
        apply_quality_policy((signal,), policy, artifact_fingerprint="artifact_1")


def test_decisions_are_deterministically_sorted_and_ignore_display_message():
    policy = build_default_observe_policy()
    first = _signal("chunk.content.too_short")
    second = _signal("chunk.evidence.reference_missing")
    translated_values = first.to_dict()
    translated_values.pop("signal_id")
    translated_first = ObservedQualitySignal.create(
        **{**translated_values, "message": "translated"}
    )

    forward = apply_quality_policy(
        (first, second),
        policy,
        artifact_fingerprint="artifact_1",
    )
    reverse = apply_quality_policy(
        (second, translated_first),
        policy,
        artifact_fingerprint="artifact_1",
    )

    assert tuple(item.decision_id for item in forward) == tuple(
        sorted(item.decision_id for item in forward)
    )
    assert forward == reverse


def test_custom_policy_hash_ignores_path_time_and_display_fields(tmp_path):
    payload = _custom_payload(
        source_path="C:/one/policy.json",
        generated_at="2026-07-17T00:00:00Z",
        display_name="First wording",
    )
    first = load_quality_policy(_write_policy(tmp_path / "first.json", payload))
    payload.update(
        source_path="D:/other/policy.json",
        generated_at="2030-01-01T00:00:00Z",
        display_name="Translated wording",
    )
    second = load_quality_policy(_write_policy(tmp_path / "second.json", payload))

    assert first.policy_hash == second.policy_hash
    assert first == second


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (
            _custom_payload(schema_version="knowledge-quality-policy.v0"),
            "unsupported_quality_policy_schema",
        ),
        (
            _custom_payload(mode="production_enforce"),
            "phase1_pr1_requires_observe_mode",
        ),
        (
            _custom_payload(
                rules=[
                    {
                        "reason_code": "chunk.unknown.rule",
                        "severity": "warning",
                        "recommended_action": "warn",
                    }
                ]
            ),
            "unknown_reason_code:chunk.unknown.rule",
        ),
        (
            _custom_payload(
                rules=[
                    {
                        "reason_code": "chunk.content.too_short",
                        "severity": "warning",
                        "recommended_action": "warn",
                    },
                    {
                        "reason_code": "chunk.content.too_short",
                        "severity": "warning",
                        "recommended_action": "warn",
                    },
                ]
            ),
            "duplicate_policy_rule:chunk.content.too_short",
        ),
        (
            _custom_payload(
                rules=[
                    {
                        "reason_code": "chunk.content.too_short",
                        "severity": "error",
                        "recommended_action": "warn",
                    }
                ]
            ),
            "policy_severity_mismatch:chunk.content.too_short",
        ),
        (
            _custom_payload(
                rules=[
                    {
                        "reason_code": "chunk.content.too_short",
                        "severity": "warning",
                        "recommended_action": "notify",
                    }
                ]
            ),
            "unsupported_quality_action:notify",
        ),
        (
            _custom_payload(policy_hash="0" * 64),
            "quality_policy_hash_mismatch",
        ),
    ],
)
def test_custom_policy_rejects_invalid_contract(tmp_path, payload, error):
    path = _write_policy(tmp_path / "policy.json", payload)

    with pytest.raises(ValueError, match=f"^{error}$"):
        load_quality_policy(path)


def test_apply_rejects_missing_policy_rule():
    policy = load_quality_policy(None)
    incomplete = type(policy)(
        schema_version=policy.schema_version,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        mode=policy.mode,
        rules=(),
        policy_hash=policy.policy_hash,
    )

    with pytest.raises(
        ValueError,
        match="^missing_policy_rule:chunk.content.too_short$",
    ):
        apply_quality_policy(
            (_signal("chunk.content.too_short"),),
            incomplete,
            artifact_fingerprint="artifact_1",
        )
