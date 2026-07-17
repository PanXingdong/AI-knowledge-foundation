from dataclasses import FrozenInstanceError

import pytest

from agent_knowledge_hub.quality_models import (
    ObservedQualitySignal,
    QualityDecision,
)


def test_signal_id_is_deterministic_and_excludes_message_copy():
    first = ObservedQualitySignal.create(
        reason_code="chunk.evidence.reference_missing",
        scope="chunk",
        object_id="chunk_1",
        detector="chunk-integrity",
        detector_version="1",
        metric_name="missing_evidence_count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        chunk_id="chunk_1",
        evidence_ids=("span_missing",),
        message="first wording",
    )
    second = ObservedQualitySignal.create(
        reason_code="chunk.evidence.reference_missing",
        scope="chunk",
        object_id="chunk_1",
        detector="chunk-integrity",
        detector_version="1",
        metric_name="missing_evidence_count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        chunk_id="chunk_1",
        evidence_ids=("span_missing",),
        message="translated wording",
    )

    assert first.signal_id == second.signal_id
    assert first.to_dict()["message"] == "first wording"


def test_signal_factory_sorts_evidence_ids():
    signal = ObservedQualitySignal.create(
        reason_code="chunk.evidence.reference_missing",
        scope="chunk",
        object_id="chunk_1",
        detector="chunk-integrity",
        detector_version="1",
        metric_name="missing_evidence_count",
        actual_value=1,
        threshold=0,
        confidence=1.0,
        severity="error",
        document_version_id="docver_1",
        evidence_ids=("span_2", "span_1"),
    )

    assert signal.evidence_ids == ("span_1", "span_2")
    assert signal.to_dict()["evidence_ids"] == ("span_1", "span_2")


def test_observe_decision_keeps_recommended_and_effective_actions_separate():
    decision = QualityDecision.create(
        signal_ids=("signal_1",),
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        recommended_action="quarantine",
        effective_action="allow",
        scope="chunk",
        object_id="chunk_1",
        reason_codes=("chunk.evidence.reference_missing",),
        artifact_fingerprint="artifact_1",
    )

    assert decision.recommended_action == "quarantine"
    assert decision.effective_action == "allow"
    assert decision.decision_id.startswith("decision_")


def test_decision_factory_sorts_identity_arrays():
    decision = QualityDecision.create(
        signal_ids=("signal_2", "signal_1"),
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        recommended_action="warn",
        effective_action="allow",
        scope="document",
        object_id="docver_1",
        reason_codes=("z.reason", "a.reason"),
        artifact_fingerprint="artifact_1",
    )

    assert decision.signal_ids == ("signal_1", "signal_2")
    assert decision.reason_codes == ("a.reason", "z.reason")


def test_quality_models_are_immutable():
    decision = QualityDecision.create(
        signal_ids=(),
        policy_id="phase1-observe-default",
        policy_version="1",
        mode="observe",
        recommended_action="allow",
        effective_action="allow",
        scope="release",
        object_id="release_1",
        reason_codes=(),
        artifact_fingerprint="artifact_1",
    )

    with pytest.raises(FrozenInstanceError):
        decision.mode = "production_enforce"
