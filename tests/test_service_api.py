import json
import csv
from pathlib import Path

from fastapi.testclient import TestClient

from agent_knowledge_hub.pipeline import ingest_file
from agent_knowledge_hub.service import create_app


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
            "top_k": 2,
            "per_document_limit": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["markdown"].startswith("# Context Pack")
    assert payload["chunk_count"] == 1
    assert payload["sections"][0]["title"] == "Architecture Decision"
    assert payload["sections"][0]["items"][0]["document_title"] == "架构"


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
