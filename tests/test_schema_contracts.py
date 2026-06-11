import json
from pathlib import Path

from agent_knowledge_hub.models import CANONICAL_DOCUMENT_SCHEMA_VERSION


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas" / CANONICAL_DOCUMENT_SCHEMA_VERSION


def _read_schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


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
