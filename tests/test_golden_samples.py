from pathlib import Path

from agent_knowledge_hub.contract import validate_processed_dir
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    trace_evidence_in_processed_dir,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SAMPLES_DIR = REPO_ROOT / "samples" / "golden"


def test_golden_samples_validate_against_processed_contract():
    summary = validate_processed_dir(GOLDEN_SAMPLES_DIR)

    assert summary.is_valid
    assert summary.document_count >= 1
    assert summary.chunk_count >= 1


def test_golden_samples_feed_context_pack_and_evidence_trace():
    context_pack = build_context_pack_for_processed_dir(
        processed_dir=GOLDEN_SAMPLES_DIR,
        query="outbound transfer safety assessment",
        top_k=1,
        per_document_limit=1,
    )

    assert context_pack.selected_chunks
    chunk = context_pack.selected_chunks[0]
    assert chunk.document_title == "Demo SPEC"
    assert chunk.evidence_ids == ["span_demo_1"]

    trace = trace_evidence_in_processed_dir(
        processed_dir=GOLDEN_SAMPLES_DIR,
        evidence_id="span_demo_1",
    )

    assert trace.document_title == "Demo SPEC"
    assert trace.document_version == "v1"
    assert trace.chunk_references[0].chunk_id == "chunk_demo_1"
