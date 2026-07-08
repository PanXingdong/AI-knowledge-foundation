import json
import csv
from pathlib import Path

from fastapi.testclient import TestClient

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.service import create_app
from agent_knowledge_hub.vector_index import build_vector_index


def test_context_pack_api_returns_markdown_and_sections(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "architecture.md"
    source.write_text(
        "\n".join(
            [
                "# 架构",
                "",
                "采用第三种 runtime 模式。",
                "默认不写主仓库。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/context-pack",
        json={
            "processed_dir": str(processed_root),
            "query": "为什么选第三种 runtime，默认规则是什么？",
            "task_type": "code_review",
            "top_k": 2,
            "per_document_limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["markdown"].startswith("# Context Pack")
    assert payload["schema_version"] == "context-pack.v1"
    assert payload["task_type"] == "code_review"
    assert payload["contract"]["stability"] == "stable_for_layer3"
    assert payload["chunk_count"] == 1
    assert payload["sections"][0]["title"].startswith("Review ")
    assert payload["sections"][0]["items"][0]["task_item_type"].startswith("review_")
    assert payload["sections"][0]["items"][0]["document_title"] == "架构"


def test_remote_context_pack_api_returns_feishu_formatted_context(tmp_path: Path, monkeypatch):
    processed_root = tmp_path / "processed"
    source = tmp_path / "screen.md"
    source.write_text(
        "# Screen\n\nSCREEN_PROPERTY_FLAGS is used to read or set Screen object flags for QNX Screen.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="Screen Guide",
        source_type="guide",
        owner="checker",
        document_version="v1",
    )
    monkeypatch.setenv(
        "KNOWLEDGE_BASES_JSON",
        json.dumps({"knowledge_bases": {"qnx-main": {"processed_dir": str(processed_root)}}}),
    )
    monkeypatch.setenv("KNOWLEDGE_HUB_API_TOKEN", "local-dev-token")

    client = TestClient(create_app())
    response = client.post(
        "/api/knowledge-bases/qnx-main/context-pack",
        json={"query": "SCREEN_PROPERTY_FLAGS 是什么？"},
        headers={"Authorization": "Bearer local-dev-token"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["knowledge_base_id"] == "qnx-main"
    assert payload["processed_dir"] == "knowledge-base:qnx-main"
    assert payload["formatted_context"]
    assert payload["markdown"].startswith("# Context Pack")


def test_search_api_returns_ranked_results(tmp_path: Path):
    processed_root = tmp_path / "processed"
    architecture = tmp_path / "architecture.md"
    architecture.write_text(
        "\n".join(
            [
                "# 架构",
                "",
                "采用第三种 runtime 模式。",
            ]
        ),
        encoding="utf-8",
    )
    governance = tmp_path / "governance.md"
    governance.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不开放无限网络。",
                "默认高风险动作必须审批。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=architecture,
        out_dir=processed_root,
        title="架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=governance,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/search",
        json={
            "processed_dir": str(processed_root),
            "query": "默认治理规则是什么？",
            "top_k": 2,
            "per_document_limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["result_count"] >= 1
    assert any("默认不开放无限网络" in item["text"] for item in payload["results"])


def test_context_pack_api_applies_metadata_filters(tmp_path: Path):
    processed_root = tmp_path / "processed"
    bosch = tmp_path / "bosch.md"
    bosch.write_text(
        "# 诊断\n\n诊断模块修改时必须检查 DTC 状态同步。",
        encoding="utf-8",
    )
    qualcomm = tmp_path / "qualcomm.md"
    qualcomm.write_text(
        "# 诊断\n\n诊断模块修改时必须检查 BSP 电源状态同步。",
        encoding="utf-8",
    )

    ingest_file(
        file_path=bosch,
        out_dir=processed_root,
        title="Bosch Diagnostic Constraint",
        source_type="supplier spec",
        owner="checker",
        project="cockpit",
        supplier="Bosch",
        document_version="v7.0",
    )
    ingest_file(
        file_path=qualcomm,
        out_dir=processed_root,
        title="Qualcomm Diagnostic Constraint",
        source_type="supplier spec",
        owner="checker",
        project="cockpit",
        supplier="Qualcomm",
        document_version="v8.0",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/context-pack",
        json={
            "processed_dir": str(processed_root),
            "query": "诊断模块修改需要注意什么？",
            "top_k": 4,
            "per_document_limit": 2,
            "metadata_filters": {
                "supplier": ["Bosch"],
                "document_version": ["v7.0"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["schema_version"] == "context-pack.v1"
    assert payload["applied_filters"] == {
        "supplier": ["Bosch"],
        "document_version": ["v7.0"],
    }
    assert {item["document_title"] for item in payload["selected_chunks"]} == {
        "Bosch Diagnostic Constraint"
    }


def test_context_pack_api_uses_fts_index_for_prefix_symbol_query(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "fts" / "chunks.db"

    api = tmp_path / "api.md"
    api.write_text(
        "# API\n\nruntime_requires_approval 事件用于审批。\n",
        encoding="utf-8",
    )
    generic = tmp_path / "generic.md"
    generic.write_text(
        "# A Generic Requirement\n\nruntime requirement guidance for workflows.\n",
        encoding="utf-8",
    )

    ingest_file(
        file_path=api,
        out_dir=processed_root,
        title="Z API",
        source_type="internal api",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=generic,
        out_dir=processed_root,
        title="A Generic Requirement",
        source_type="internal guide",
        owner="checker",
        document_version="v1",
    )

    build_fts_index(processed_dir=processed_root, index_path=index_path)

    client = TestClient(create_app())
    response = client.post(
        "/api/context-pack",
        json={
            "processed_dir": str(processed_root),
            "query": "runtime_requir",
            "top_k": 1,
            "per_document_limit": 1,
            "fts_index_path": str(index_path),
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["selected_chunks"][0]["document_title"] == "Z API"


def test_build_fts_index_api_returns_index_summary(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "fts" / "chunks.db"
    source = tmp_path / "api.md"
    source.write_text(
        "# API\n\nruntime_requires_approval 事件用于审批。\n",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="API",
        source_type="internal api",
        owner="checker",
        document_version="v1",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/build-fts-index",
        json={
            "processed_dir": str(processed_root),
            "index_path": str(index_path),
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["indexed_chunk_count"] >= 1
    assert payload["indexed_document_count"] == 1
    assert index_path.exists()


def test_context_pack_api_uses_vector_index_for_local_similarity_query(tmp_path: Path):
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
        document_version="v1",
    )
    ingest_file(
        file_path=diagnostics,
        out_dir=processed_root,
        title="A 诊断",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    build_vector_index(processed_dir=processed_root, index_path=index_path)

    client = TestClient(create_app())
    response = client.post(
        "/api/context-pack",
        json={
            "processed_dir": str(processed_root),
            "query": "海外批准要求",
            "top_k": 1,
            "per_document_limit": 1,
            "vector_index_path": str(index_path),
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["selected_chunks"][0]["document_title"] == "Z 出境限制"


def test_build_vector_index_api_returns_index_summary(tmp_path: Path):
    processed_root = tmp_path / "processed"
    index_path = tmp_path / "vector" / "chunks.vector.json"

    source = tmp_path / "safety.md"
    source.write_text(
        "# 出境限制\n\n车辆重要数据跨境传输需要进行出境安全评估。\n",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="Z 出境限制",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/build-vector-index",
        json={
            "processed_dir": str(processed_root),
            "index_path": str(index_path),
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["indexed_chunk_count"] >= 1
    assert payload["indexed_document_count"] == 1
    assert payload["embedding_strategy"] == "local-hashed-token-v1"
    assert index_path.exists()


def test_gap_report_api_returns_missing_items(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "safety.md"
    source.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不写主仓库。",
                "默认不开放无限网络。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- 默认不写主仓库",
                "- 默认不开放无限网络",
                "- 默认不绕过审批",
            ]
        ),
        encoding="utf-8",
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/gap-report",
        json={
            "processed_dir": str(processed_root),
            "query": "默认安全规则是什么？",
            "reference_markdown_path": str(reference),
            "top_k": 2,
            "per_document_limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["missing_reference_item_count"] >= 1
    assert "默认不绕过审批" in payload["markdown"]


def test_evidence_api_returns_trace_payload(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "api.md"
    source.write_text(
        "\n".join(
            [
                "# API",
                "",
                "GET /runtime-runs/{run_id}/events 提供事件流查询。",
                "",
                "runtime_requires_approval 事件用于审批。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_result = ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="API",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )
    payload = json.loads(ingest_result.document_json_path.read_text(encoding="utf-8"))
    evidence_id = next(
        evidence["evidence_id"]
        for evidence in payload["evidence_spans"]
        if "/runtime-runs/{run_id}/events" in evidence["text"]
    )

    client = TestClient(create_app())
    response = client.get(
        f"/api/evidence/{evidence_id}",
        params={"processed_dir": str(processed_root)},
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["evidence_id"] == evidence_id
    assert data["document_title"] == "API"
    assert "/runtime-runs/{run_id}/events" in data["text"]
    assert data["chunk_references"]


def test_parse_quality_summary_api_returns_gate_results(tmp_path: Path):
    processed_root = tmp_path / "processed"
    good = tmp_path / "good.md"
    good.write_text(
        "# 设计\n\n这是一个足够长的设计文档，包含正文约束、接口说明和测试要求，允许进入 Context Pack。",
        encoding="utf-8",
    )
    short = tmp_path / "short.txt"
    short.write_text("短文本", encoding="utf-8")
    ingest_file(
        file_path=good,
        out_dir=processed_root,
        title="设计",
        source_type="内部设计文档",
        owner="checker",
        project="api-test",
        supplier="internal",
        document_version="v1",
    )
    ingest_file(
        file_path=short,
        out_dir=processed_root,
        title="短文本",
        source_type="内部说明",
        owner="checker",
        project="api-test",
        supplier="internal",
        document_version="v1",
    )

    client = TestClient(create_app())
    response = client.get(
        "/api/parse-quality-summary",
        params={"processed_dir": str(processed_root)},
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["processed_document_count"] == 2
    assert data["status_counts"]["ok"] == 1
    assert data["status_counts"]["low_quality"] == 1
    assert data["documents"][0]["quality_status"] in {"ok", "low_quality"}
    assert any(item["allowed_for_context_pack"] for item in data["documents"])
    assert any(not item["allowed_for_context_pack"] for item in data["documents"])


def test_document_inventory_api_returns_supported_local_documents(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "qualcomm-bsp.md").write_text(
        "# Qualcomm BSP\n\nInterface constraints must be traced.",
        encoding="utf-8",
    )
    (docs / "ignored.bin").write_bytes(b"ignored")

    client = TestClient(create_app())
    response = client.post(
        "/api/document-inventory",
        json={
            "root_dirs": [str(docs)],
            "max_files": 10,
            "max_file_mb": 1,
            "owner": "checker",
            "project": "api-test",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["document_count"] == 1
    assert data["documents"][0]["supplier"] == "Qualcomm"
    assert data["documents"][0]["content_hash"]
    assert data["markdown"].startswith("# Document Inventory")


def test_ingest_manifest_api_runs_incremental_ingest(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control.",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    rows = [
        {
            "sample_id": "sample-001",
            "file_path": str(source),
            "document_title": "Vehicle Data SPEC",
            "slot_type": "internal spec",
            "owner": "checker",
            "project": "api-test",
            "supplier": "internal",
            "document_version": "v1",
        }
    ]
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    processed = tmp_path / "processed"
    client = TestClient(create_app())
    response = client.post(
        "/api/ingest-manifest",
        json={
            "manifest_path": str(manifest),
            "out_dir": str(processed),
            "project_root": str(tmp_path),
            "incremental": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]

    assert data["processed_count"] == 1
    assert data["unchanged_count"] == 0
    assert (processed / "ingest-run-summary.json").exists()


def test_runtime_dependencies_api_returns_capabilities():
    client = TestClient(create_app())

    response = client.get("/api/runtime-dependencies")

    assert response.status_code == 200
    data = response.json()["data"]
    assert any(item["capability"] == "plain_text" for item in data["capabilities"])
    assert any(item["capability"] == "pdf_text" for item in data["capabilities"])
    assert data["markdown"].startswith("# Runtime Dependency Report")
