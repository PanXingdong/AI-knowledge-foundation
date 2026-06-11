import json
from pathlib import Path

from agent_knowledge_hub.models import CANONICAL_DOCUMENT_SCHEMA_VERSION
from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    trace_evidence_in_processed_dir,
)


def test_layer1_manual_processed_contract_can_feed_retrieval_and_trace(tmp_path: Path):
    processed_root = tmp_path / "processed"
    version_dir = processed_root / "demo-spec" / "docver_demo_v1"
    version_dir.mkdir(parents=True)

    canonical = {
        "schema_version": CANONICAL_DOCUMENT_SCHEMA_VERSION,
        "document": {
            "document_id": "doc_demo",
            "title": "Demo SPEC",
            "source_type": "internal_spec",
            "owner": "checker",
            "project": "demo",
            "supplier": "internal",
            "created_at": "2026-06-10T00:00:00Z",
        },
        "document_version": {
            "document_version_id": "docver_demo_v1",
            "document_id": "doc_demo",
            "version": "v1",
            "file_path": "samples/golden/demo-spec.md",
            "file_hash": "sha256_demo",
            "created_at": "2026-06-10T00:00:00Z",
        },
        "sections": [
            {
                "section_id": "sec_demo_1",
                "document_version_id": "docver_demo_v1",
                "section_path": ["1"],
                "title": "Safety Constraint",
                "page_start": 1,
                "page_end": 1,
            }
        ],
        "blocks": [
            {
                "block_id": "blk_demo_1",
                "document_version_id": "docver_demo_v1",
                "block_type": "paragraph",
                "text": "Important data outbound transfer requires safety assessment.",
                "page_start": 1,
                "page_end": 1,
                "section_path": ["1"],
                "order": 1,
                "metadata": {},
            }
        ],
        "evidence_spans": [
            {
                "evidence_id": "span_demo_1",
                "document_version_id": "docver_demo_v1",
                "page": 1,
                "section_path": ["1"],
                "block_id": "blk_demo_1",
                "bbox": None,
                "text": "Important data outbound transfer requires safety assessment.",
                "text_hash": "sha256_text_demo",
            }
        ],
        "parse_report": {
            "parser_name": "manual-golden-sample",
            "source_format": "manual",
            "page_count": 1,
            "section_count": 1,
            "block_count": 1,
            "table_count": 0,
            "has_page_numbers": True,
            "warnings": [],
            "quality_report": {
                "status": "ok",
                "score": 100.0,
                "fallback_used": False,
                "fallback_parser": None,
                "reason_codes": [],
            },
        },
    }
    chunk = {
        "chunk_id": "chunk_demo_1",
        "document_version_id": "docver_demo_v1",
        "section_path": ["1"],
        "page_start": 1,
        "page_end": 1,
        "text": "Important data outbound transfer requires safety assessment.",
        "evidence_ids": ["span_demo_1"],
        "embedding_id": None,
        "metadata": {
            "document_id": "doc_demo",
            "document_title": "Demo SPEC",
            "source_type": "internal_spec",
        },
    }

    (version_dir / "canonical-document.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (version_dir / "chunks.jsonl").write_text(
        json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    context_pack = build_context_pack_for_processed_dir(
        processed_dir=processed_root,
        query="outbound transfer safety assessment",
        top_k=1,
        per_document_limit=1,
    )

    assert context_pack.selected_chunks
    assert context_pack.selected_chunks[0].document_title == "Demo SPEC"
    assert context_pack.selected_chunks[0].document_version == "v1"
    assert context_pack.selected_chunks[0].project == "demo"
    assert context_pack.selected_chunks[0].supplier == "internal"
    assert context_pack.selected_chunks[0].evidence_ids == ["span_demo_1"]

    trace = trace_evidence_in_processed_dir(
        processed_dir=processed_root,
        evidence_id="span_demo_1",
    )

    assert trace.document_title == "Demo SPEC"
    assert trace.document_version == "v1"
    assert trace.section_titles == ["Safety Constraint"]
    assert trace.chunk_references[0].chunk_id == "chunk_demo_1"
