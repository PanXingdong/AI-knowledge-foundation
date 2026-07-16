import json
from pathlib import Path

import pytest

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.processing_record import (
    PROCESSING_RECORD_SCHEMA_VERSION,
    load_or_infer_processing_record,
)
from agent_knowledge_hub.utils import file_sha256


def test_ingest_writes_hash_bound_processing_record(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text("# API\n\nMsgSend() sends a message.", encoding="utf-8")

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "processed",
        title="API",
        document_version="v1",
    )

    payload = json.loads(result.processing_record_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PROCESSING_RECORD_SCHEMA_VERSION
    assert payload["document_version_id"] == result.document_version_id
    assert payload["canonical_sha256"] == file_sha256(result.document_json_path)
    assert payload["chunks_sha256"] == file_sha256(result.chunks_jsonl_path)
    assert payload["processing_run_id"].startswith("run_")
    assert payload["parser_name"]
    assert payload["chunker_version"] == "section-aware-block-chunker-v1"
    assert payload["quality_rules_version"] == "parse-quality-gate-v1"


def test_legacy_processing_record_is_inferred_without_mutating_files(tmp_path: Path):
    version_dir = tmp_path / "doc" / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "canonical-document.json").write_text(
        '{"document_version":{"document_version_id":"docver_1","file_hash":"source_hash"},'
        '"parse_report":{"parser_name":"legacy-parser"}}',
        encoding="utf-8",
    )
    (version_dir / "chunks.jsonl").write_text('{"chunk_id":"chunk_1"}\n', encoding="utf-8")

    record = load_or_infer_processing_record(version_dir)

    assert record.document_version_id == "docver_1"
    assert record.record_origin == "legacy_inferred"
    assert not (version_dir / "processing-record.json").exists()


def test_existing_processing_record_rejects_tampered_canonical(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text("# API\n\nMsgSend() sends a message.", encoding="utf-8")
    result = ingest_file(file_path=source, out_dir=tmp_path / "processed")
    result.document_json_path.write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=rf"^canonical_hash_mismatch:{result.document_version_id}$",
    ):
        load_or_infer_processing_record(result.output_dir)


def test_existing_processing_record_rejects_tampered_chunks(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text("# API\n\nMsgSend() sends a message.", encoding="utf-8")
    result = ingest_file(file_path=source, out_dir=tmp_path / "processed")
    result.chunks_jsonl_path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=rf"^chunks_hash_mismatch:{result.document_version_id}$",
    ):
        load_or_infer_processing_record(result.output_dir)
