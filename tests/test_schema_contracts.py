import json
from copy import deepcopy
from dataclasses import fields
from pathlib import Path

import pytest

from agent_knowledge_hub.models import CANONICAL_DOCUMENT_SCHEMA_VERSION
from agent_knowledge_hub.processing_record import PROCESSING_RECORD_SCHEMA_VERSION
from agent_knowledge_hub.quality_contracts import QUALITY_RECORD_SCHEMA_VERSION
from agent_knowledge_hub.quality_models import (
    KNOWLEDGE_QUALITY_SCHEMA_VERSION,
    PUBLICATION_PREVIEW_SCHEMA_VERSION,
    QUALITY_POLICY_SCHEMA_VERSION,
    QUALITY_REPORT_SCHEMA_VERSION,
    QUARANTINE_PREVIEW_SCHEMA_VERSION,
    PublicationPreview,
    QualityDecision,
    QualityPolicy,
    QualityPolicyRule,
    QualityReport,
    QuarantinePreview,
    ObservedQualitySignal,
)
from agent_knowledge_hub.release_manifest import RELEASE_MANIFEST_SCHEMA_VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / CANONICAL_DOCUMENT_SCHEMA_VERSION
RELEASE_SCHEMA_DIR = REPO_ROOT / "schemas" / RELEASE_MANIFEST_SCHEMA_VERSION
QUALITY_SCHEMA_DIR = REPO_ROOT / "schemas" / KNOWLEDGE_QUALITY_SCHEMA_VERSION


def _read_schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _read_release_schema(name: str) -> dict[str, object]:
    return json.loads((RELEASE_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_layer1_processed_schema_files_exist():
    assert (SCHEMA_DIR / "README.md").exists()
    assert (SCHEMA_DIR / "canonical-document.schema.json").exists()
    assert (SCHEMA_DIR / "chunk.schema.json").exists()


def test_canonical_document_schema_matches_supported_version():
    schema = _read_schema("canonical-document.schema.json")

    assert schema["$id"].endswith(
        f"/schemas/{CANONICAL_DOCUMENT_SCHEMA_VERSION}/canonical-document.schema.json"
    )
    assert schema["properties"]["schema_version"]["const"] == CANONICAL_DOCUMENT_SCHEMA_VERSION
    assert schema["required"] == [
        "schema_version",
        "document",
        "document_version",
        "sections",
        "blocks",
        "evidence_spans",
        "parse_report",
    ]


def test_canonical_document_schema_keeps_layer2_required_metadata():
    schema = _read_schema("canonical-document.schema.json")
    defs = schema["$defs"]

    assert defs["document"]["required"] == [
        "document_id",
        "title",
        "source_type",
        "owner",
        "project",
        "supplier",
        "created_at",
    ]
    assert defs["document_version"]["required"] == [
        "document_version_id",
        "document_id",
        "version",
        "file_path",
        "file_hash",
        "created_at",
    ]
    assert defs["evidence_span"]["required"] == [
        "evidence_id",
        "document_version_id",
        "page",
        "section_path",
        "block_id",
        "bbox",
        "text",
        "text_hash",
    ]


def test_chunk_schema_keeps_layer2_required_fields():
    schema = _read_schema("chunk.schema.json")

    assert schema["$id"].endswith(
        f"/schemas/{CANONICAL_DOCUMENT_SCHEMA_VERSION}/chunk.schema.json"
    )
    assert schema["required"] == [
        "chunk_id",
        "document_version_id",
        "section_path",
        "page_start",
        "page_end",
        "text",
        "evidence_ids",
        "embedding_id",
        "metadata",
    ]
    assert schema["properties"]["metadata"]["required"] == [
        "document_id",
        "document_title",
        "source_type",
    ]


def test_knowledge_release_schema_files_exist():
    assert (RELEASE_SCHEMA_DIR / "README.md").exists()
    assert (RELEASE_SCHEMA_DIR / "processing-record.schema.json").exists()
    assert (RELEASE_SCHEMA_DIR / "quality-record.schema.json").exists()
    assert (RELEASE_SCHEMA_DIR / "release-manifest.schema.json").exists()


def test_knowledge_release_schemas_match_supported_versions():
    processing = _read_release_schema("processing-record.schema.json")
    quality = _read_release_schema("quality-record.schema.json")
    manifest = _read_release_schema("release-manifest.schema.json")

    assert processing["properties"]["schema_version"]["const"] == (
        PROCESSING_RECORD_SCHEMA_VERSION
    )
    assert quality["properties"]["schema_version"]["const"] == (
        QUALITY_RECORD_SCHEMA_VERSION
    )
    assert manifest["properties"]["schema_version"]["const"] == (
        RELEASE_MANIFEST_SCHEMA_VERSION
    )
    document_schema = manifest["$defs"]["document"]
    assert "processing_record_sha256" in document_schema["required"]
    assert document_schema["properties"]["processing_record_path"]["type"] == "string"
    vector_schema = manifest["$defs"]["vector_index"]["properties"]
    assert {"metadata_path", "metadata_sha256"} <= set(vector_schema)


def _quality_schema(name: str) -> dict[str, object]:
    return json.loads((QUALITY_SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _field_names(model: type[object]) -> set[str]:
    return {field.name for field in fields(model)}


def test_knowledge_quality_schema_files_and_versions():
    expected = {
        "quality-policy.schema.json": QUALITY_POLICY_SCHEMA_VERSION,
        "quality-report.schema.json": QUALITY_REPORT_SCHEMA_VERSION,
        "publication-preview.schema.json": PUBLICATION_PREVIEW_SCHEMA_VERSION,
        "quarantine-preview.schema.json": QUARANTINE_PREVIEW_SCHEMA_VERSION,
    }
    assert (QUALITY_SCHEMA_DIR / "README.md").is_file()
    for name, version in expected.items():
        payload = _quality_schema(name)
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["additionalProperties"] is False
        assert payload["properties"]["schema_version"]["const"] == version
        assert payload["properties"]["mode"]["const"] == "observe"


def test_quality_schema_top_level_fields_match_dataclasses_exactly():
    expected = {
        "quality-policy.schema.json": QualityPolicy,
        "quality-report.schema.json": QualityReport,
        "publication-preview.schema.json": PublicationPreview,
        "quarantine-preview.schema.json": QuarantinePreview,
    }

    for name, model in expected.items():
        payload = _quality_schema(name)
        model_fields = _field_names(model)
        assert set(payload["properties"]) == model_fields
        assert set(payload["required"]) == model_fields


def test_quality_report_nested_definitions_match_dataclasses_exactly():
    report = _quality_schema("quality-report.schema.json")

    for definition_name, model in {
        "signal": ObservedQualitySignal,
        "decision": QualityDecision,
    }.items():
        definition = report["$defs"][definition_name]
        model_fields = _field_names(model)
        assert definition["additionalProperties"] is False
        assert set(definition["properties"]) == model_fields
        assert set(definition["required"]) == model_fields


def test_quality_report_schema_accepts_non_enforcing_observe_decisions_only():
    jsonschema = pytest.importorskip("jsonschema")
    schema = _quality_schema("quality-report.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    report = {
        "schema_version": QUALITY_REPORT_SCHEMA_VERSION,
        "policy_id": "phase1-observe-default",
        "policy_version": "1",
        "policy_hash": "a" * 64,
        "mode": "observe",
        "artifact_fingerprint": "artifact_1",
        "determinism_fingerprint": "determinism_1",
        "document_version_ids": ["docver_1"],
        "signals": [],
        "decisions": [
            {
                "decision_id": "decision_1",
                "signal_ids": ["signal_1"],
                "policy_id": "phase1-observe-default",
                "policy_version": "1",
                "mode": "observe",
                "recommended_action": "quarantine",
                "effective_action": "warn",
                "scope": "chunk",
                "object_id": "chunk_1",
                "reason_codes": ["chunk.evidence.reference_missing"],
                "artifact_fingerprint": "artifact_1",
            }
        ],
        "summary": {"warning": 1},
    }

    validator.validate(report)
    for enforcing_action in ("quarantine", "block_document", "block_release"):
        invalid_report = deepcopy(report)
        invalid_report["decisions"][0]["effective_action"] = enforcing_action
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(invalid_report)


def test_quality_policy_rule_definition_matches_dataclass_exactly():
    policy = _quality_schema("quality-policy.schema.json")
    rule = policy["properties"]["rules"]["items"]

    assert rule["additionalProperties"] is False
    assert set(rule["properties"]) == _field_names(QualityPolicyRule)
    assert set(rule["required"]) == _field_names(QualityPolicyRule)


def test_quarantine_preview_items_are_strict_and_complete():
    quarantine = _quality_schema("quarantine-preview.schema.json")
    item = quarantine["properties"]["items"]["items"]
    expected = {
        "scope",
        "object_id",
        "decision_id",
        "reason_codes",
        "recommended_action",
    }

    assert item["additionalProperties"] is False
    assert set(item["properties"]) == expected
    assert set(item["required"]) == expected
