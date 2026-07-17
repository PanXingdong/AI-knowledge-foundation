from pathlib import Path
import sys
from types import SimpleNamespace

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.vector_index import (
    build_vector_index,
    query_vector_index,
    _select_bge_m3_device,
)


def test_build_vector_index_writes_json_and_supports_local_similarity_query(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "vector" / "chunks.vector.json"

    safety = tmp_path / "safety.md"
    safety.write_text(
        "# 出境限制\n\n车辆重要数据出境传输需要进行安全评估，并记录证据。\n",
        encoding="utf-8",
    )
    diagnostics = tmp_path / "diagnostics.md"
    diagnostics.write_text(
        "# 诊断\n\nDTC 状态同步需要覆盖上电、下电和异常恢复场景。\n",
        encoding="utf-8",
    )

    ingest_file(
        file_path=safety,
        out_dir=processed_root,
        title="Z 出境限制",
        source_type="internal spec",
        owner="checker",
        project="cockpit",
        supplier="internal",
        document_version="v1",
    )
    ingest_file(
        file_path=diagnostics,
        out_dir=processed_root,
        title="A 诊断",
        source_type="internal spec",
        owner="checker",
        project="cockpit",
        supplier="internal",
        document_version="v1",
    )

    summary = build_vector_index(
        processed_dir=processed_root,
        index_path=index_path,
    )

    assert index_path.exists()
    assert summary.indexed_chunk_count >= 2
    assert summary.indexed_document_count == 2
    assert summary.embedding_strategy == "local-hashed-token-v1"

    hits = query_vector_index(
        index_path=index_path,
        query="海外批准要求",
        limit=5,
    )

    assert hits
    assert hits[0].document_title == "Z 出境限制"
    assert hits[0].similarity_score > 0.0


def test_select_bge_m3_device_uses_cuda_when_available(monkeypatch):
    monkeypatch.delenv("AKF_BGE_M3_DEVICE", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )

    assert _select_bge_m3_device() == "cuda"


def test_select_bge_m3_device_can_be_overridden(monkeypatch):
    monkeypatch.setenv("AKF_BGE_M3_DEVICE", "cpu")
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )

    assert _select_bge_m3_device() == "cpu"
