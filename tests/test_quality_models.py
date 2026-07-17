from dataclasses import FrozenInstanceError

import pytest

from agent_knowledge_hub.quality_models import (
    ObservedQualitySignal,
    PublicationPreview,
    QualityDecision,
    QualityPolicy,
    QualityPolicyRule,
    QualityReport,
    QuarantinePreview,
)


def _signal(**overrides):
    values = {
        "reason_code": "chunk.evidence.reference_missing",
        "scope": "chunk",
        "object_id": "chunk_1",
        "detector": "chunk-integrity",
        "detector_version": "1",
        "metric_name": "missing_evidence_count",
        "actual_value": 1,
        "threshold": 0,
        "confidence": 1.0,
        "severity": "error",
        "document_version_id": "docver_1",
        "chunk_id": "chunk_1",
        "evidence_ids": ("span_missing",),
        "message": "first wording",
    }
    values.update(overrides)
    return ObservedQualitySignal.create(**values)


def _decision(**overrides):
    values = {
        "signal_ids": ("signal_1",),
        "policy_id": "phase1-observe-default",
        "policy_version": "1",
        "mode": "observe",
        "recommended_action": "quarantine",
        "effective_action": "allow",
        "scope": "chunk",
        "object_id": "chunk_1",
        "reason_codes": ("chunk.evidence.reference_missing",),
        "artifact_fingerprint": "artifact_1",
    }
    values.update(overrides)
    return QualityDecision.create(**values)


def test_signal_id_is_deterministic_and_excludes_message_copy():
    first = _signal()
    second = _signal(message="translated wording")

    assert first.signal_id == second.signal_id
    assert first.to_dict()["message"] == "first wording"


def test_signal_factory_rejects_caller_supplied_id():
    with pytest.raises(ValueError, match="^signal_id_is_generated$"):
        _signal(signal_id="caller_signal")


def test_signal_factory_sorts_evidence_ids():
    signal = _signal(evidence_ids=("span_2", "span_1"))

    assert signal.evidence_ids == ("span_1", "span_2")


def test_observe_decision_keeps_recommended_and_effective_actions_separate():
    decision = _decision()

    assert decision.recommended_action == "quarantine"
    assert decision.effective_action == "allow"
    assert decision.decision_id.startswith("decision_")


def test_observe_decision_allows_warning_as_effective_action():
    decision = _decision(effective_action="warn")

    assert decision.effective_action == "warn"


@pytest.mark.parametrize(
    "effective_action",
    ["quarantine", "block_document", "block_release"],
)
def test_observe_decision_rejects_enforcing_effective_action(effective_action):
    with pytest.raises(
        ValueError,
        match="^observe_effective_action_must_not_enforce$",
    ):
        _decision(effective_action=effective_action)


def test_decision_factory_rejects_caller_supplied_id():
    with pytest.raises(ValueError, match="^decision_id_is_generated$"):
        _decision(decision_id="caller_decision")


def test_decision_factory_sorts_identity_arrays():
    decision = _decision(
        signal_ids=("signal_2", "signal_1"),
        recommended_action="warn",
        scope="document",
        object_id="docver_1",
        reason_codes=("z.reason", "a.reason"),
    )

    assert decision.signal_ids == ("signal_1", "signal_2")
    assert decision.reason_codes == ("a.reason", "z.reason")


def test_all_model_dictionaries_are_recursively_json_ready():
    signal = _signal(evidence_ids=("span_2", "span_1"))
    decision = _decision(
        signal_ids=("signal_2", "signal_1"),
        reason_codes=("z.reason", "a.reason"),
    )
    policy = QualityPolicy(
        schema_version="knowledge-quality-policy.v1",
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        rules=(
            QualityPolicyRule(
                reason_code="chunk.evidence.reference_missing",
                severity="error",
                recommended_action="quarantine",
            ),
        ),
        policy_hash="a" * 64,
    )
    report = QualityReport(
        schema_version="knowledge-quality-report.v1",
        policy_id="phase1-observe-default",
        policy_version="1",
        policy_hash="a" * 64,
        mode="observe",
        artifact_fingerprint="artifact_1",
        determinism_fingerprint="determinism_1",
        document_version_ids=("docver_1",),
        signals=(signal,),
        decisions=(decision,),
        summary={"error": 1},
    )
    publication = PublicationPreview(
        schema_version="knowledge-publication-preview.v1",
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        all_document_version_ids=("docver_1",),
        all_chunk_ids=("chunk_1",),
        would_exclude_document_version_ids=("docver_1",),
        would_exclude_chunk_ids=("chunk_1",),
        decision_ids=(decision.decision_id,),
    )
    quarantine = QuarantinePreview(
        schema_version="knowledge-quarantine-preview.v1",
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        items=(
            {
                "scope": "chunk",
                "object_id": "chunk_1",
                "decision_id": decision.decision_id,
                "reason_codes": ("chunk.evidence.reference_missing",),
                "recommended_action": "quarantine",
            },
        ),
    )

    assert signal.to_dict()["evidence_ids"] == ["span_1", "span_2"]
    assert policy.to_dict()["rules"] == [
        {
            "reason_code": "chunk.evidence.reference_missing",
            "severity": "error",
            "recommended_action": "quarantine",
        }
    ]
    assert decision.to_dict()["signal_ids"] == ["signal_1", "signal_2"]
    assert decision.to_dict()["reason_codes"] == ["a.reason", "z.reason"]
    assert report.to_dict()["document_version_ids"] == ["docver_1"]
    assert report.to_dict()["signals"] == [signal.to_dict()]
    assert report.to_dict()["decisions"] == [decision.to_dict()]
    assert publication.to_dict()["all_document_version_ids"] == ["docver_1"]
    assert publication.to_dict()["all_chunk_ids"] == ["chunk_1"]
    assert publication.to_dict()["would_exclude_document_version_ids"] == ["docver_1"]
    assert publication.to_dict()["would_exclude_chunk_ids"] == ["chunk_1"]
    assert publication.to_dict()["decision_ids"] == [decision.decision_id]
    assert quarantine.to_dict()["items"] == [
        {
            "scope": "chunk",
            "object_id": "chunk_1",
            "decision_id": decision.decision_id,
            "reason_codes": ["chunk.evidence.reference_missing"],
            "recommended_action": "quarantine",
        }
    ]


def test_quality_models_are_immutable():
    decision = _decision(
        signal_ids=(),
        recommended_action="allow",
        scope="release",
        object_id="release_1",
        reason_codes=(),
    )

    with pytest.raises(FrozenInstanceError):
        decision.mode = "production_enforce"
