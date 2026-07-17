import json
from pathlib import Path

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.quality_contracts import QUALITY_RECORD_SCHEMA_VERSION


def test_ingest_writes_explicit_observed_and_unavailable_quality_metrics(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text("# API\n\nMsgSend() sends a message.", encoding="utf-8")

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="API",
        document_version="v1",
    )

    payload = json.loads(result.quality_record_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == QUALITY_RECORD_SCHEMA_VERSION
    assert payload["document_version_id"] == result.document_version_id
    assert payload["profile"]["block_count"] == 2
    assert payload["profile"]["chunk_count"] >= 1
    assert payload["signals"]["traceable_chunk_ratio"]["status"] == "observed"
    assert payload["signals"]["traceable_chunk_ratio"]["value"] == 1.0
    assert payload["signals"]["column_count"]["status"] == "unavailable"
    assert payload["signals"]["ocr_confidence"]["status"] == "unavailable"
    assert payload["signals"]["table_structure_score"]["status"] == "unavailable"
    assert payload["signals"]["bbox_coverage"]["status"] == "unavailable"
