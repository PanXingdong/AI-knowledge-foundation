from pathlib import Path

from agent_knowledge_hub.fts_index import build_fts_index, query_fts_index
from agent_knowledge_hub.pipeline import ingest_file


def test_build_fts_index_writes_sqlite_db_and_supports_prefix_symbol_query(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "fts" / "chunks.db"

    api = tmp_path / "api.md"
    api.write_text(
        "# API\n\nruntime_requires_approval 事件用于审批。\n",
        encoding="utf-8",
    )
    notes = tmp_path / "notes.md"
    notes.write_text(
        "# Notes\n\n这是一份普通说明文档。\n",
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="API",
        source_type="internal api",
        owner="checker",
        project="cockpit",
        supplier="internal",
        document_version="v1",
    )
    ingest_file(
        file_path=notes,
        out_dir=processed_root,
        title="Notes",
        source_type="internal guide",
        owner="checker",
        project="cockpit",
        supplier="internal",
        document_version="v1",
    )

    summary = build_fts_index(
        processed_dir=processed_root,
        index_path=index_path,
    )

    assert index_path.exists()
    assert summary.indexed_chunk_count >= 2
    assert summary.indexed_document_count == 2

    hits = query_fts_index(
        index_path=index_path,
        query="runtime_requir",
        limit=5,
    )

    assert hits
    assert hits[0].document_title == "API"
    assert hits[0].chunk_id
    assert hits[0].bm25_score <= 0.0


def test_query_fts_index_handles_dotted_versions_and_punctuation(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "fts" / "chunks.db"

    source = tmp_path / "qnx.md"
    source.write_text(
        "# QNX Neutrino RTOS\n\n"
        "QNX SDP 7.1 provides high-performance networking capabilities through "
        "resource managers and the io-pkt networking stack. The QNX SDP 7.1 release "
        "includes enhanced support for multi-core ARM and x86 platforms, along with "
        "improved adaptive partitioning and real-time scheduling guarantees. "
        "Developers targeting QNX SDP 7.1 should review the migration guide for "
        "changes to the process manager and resource manager interfaces.\n",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="QNX Guide",
        source_type="supplier guide",
        owner="checker",
        project="qnx-validation",
        supplier="QNX",
        document_version="SDP 7.1",
    )
    build_fts_index(processed_dir=processed_root, index_path=index_path)

    hits = query_fts_index(
        index_path=index_path,
        query="QNX SDP 7.1 high-performance resource manager",
        limit=5,
    )

    assert hits
    assert hits[0].document_title == "QNX Guide"
