import json
from pathlib import Path

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.layer2_run import run_layer2_acceptance
from agent_knowledge_hub.pipeline import ingest_file


def test_run_layer2_acceptance_writes_complete_bundle(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "qnx-api.md"
    source.write_text(
        "\n".join(
            [
                "# resmgr_attach",
                "",
                "resmgr_attach registers a pathname with the resource manager.",
                "The caller must check returned errors and preserve evidence ids.",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="QNX API Reference",
        source_type="api_reference",
        owner="checker",
        project="qnx-demo",
        supplier="QNX",
        document_version="SDP 7.1",
    )

    output_dir = tmp_path / "layer2-run"

    summary = run_layer2_acceptance(
        processed_dir=processed_root,
        output_dir=output_dir,
        query="How does resmgr_attach register a pathname?",
        top_k=4,
        per_document_limit=2,
    )

    assert summary.is_ready
    assert summary.contract_valid
    assert summary.document_count == 1
    assert summary.chunk_count >= 1
    assert summary.selected_chunk_count >= 1
    assert summary.selected_document_count == 1
    assert summary.trace_found
    assert summary.traced_evidence_id
    assert not summary.blockers

    assert (output_dir / "layer2-run-summary.json").exists()
    assert (output_dir / "layer2-run-summary.md").exists()
    assert (output_dir / "contract" / "processed-contract-validation.json").exists()
    assert (output_dir / "indexes" / "chunks.fts.sqlite").exists()
    assert (output_dir / "indexes" / "chunks.vector.json").exists()
    assert (output_dir / "context-pack" / "context_pack.json").exists()
    assert (output_dir / "context-pack" / "context_pack.md").exists()
    assert (output_dir / "evidence-trace.json").exists()

    summary_payload = json.loads(
        (output_dir / "layer2-run-summary.json").read_text(encoding="utf-8")
    )
    assert summary_payload["is_ready"] is True
    assert summary_payload["context_pack_json_path"].endswith("context_pack.json")
    assert summary_payload["evidence_trace_json_path"].endswith("evidence-trace.json")

    trace_payload = json.loads((output_dir / "evidence-trace.json").read_text(encoding="utf-8"))
    assert trace_payload["evidence_id"] == summary.traced_evidence_id
    assert "resmgr_attach" in trace_payload["text"]


def test_layer2_run_cli_returns_nonzero_when_require_ready_and_invalid(tmp_path: Path):
    missing_processed = tmp_path / "missing"
    output_dir = tmp_path / "layer2-run"

    exit_code = main(
        [
            "layer2-run",
            "--processed-dir",
            str(missing_processed),
            "--output-dir",
            str(output_dir),
            "--query",
            "anything",
            "--require-ready",
        ]
    )

    assert exit_code == 1
    summary_path = output_dir / "layer2-run-summary.json"
    assert summary_path.exists()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["is_ready"] is False
    assert payload["contract_valid"] is False
    assert any("contract_validation_failed" in blocker for blocker in payload["blockers"])


def test_layer2_run_cli_writes_acceptance_bundle(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "safety.md"
    source.write_text(
        "# Safety\n\nSafety constraints require checking timeout and permission errors.\n",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="Safety API",
        source_type="api_reference",
        owner="checker",
        project="demo",
        supplier="internal",
        document_version="v1",
    )

    output_dir = tmp_path / "cli-layer2-run"
    exit_code = main(
        [
            "layer2-run",
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
            "--query",
            "What safety constraints apply to timeout errors?",
            "--require-ready",
        ]
    )

    assert exit_code == 0
    payload = json.loads((output_dir / "layer2-run-summary.json").read_text(encoding="utf-8"))
    assert payload["is_ready"] is True
    assert payload["selected_chunk_count"] >= 1
