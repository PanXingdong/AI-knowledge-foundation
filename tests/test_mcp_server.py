import json
import importlib.util
from pathlib import Path

import anyio
import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="MCP SDK not installed in this interpreter",
)

from agent_knowledge_hub.mcp_server import create_mcp_server
from agent_knowledge_hub.pipeline import ingest_file


def test_mcp_server_lists_phase1_tools():
    server = create_mcp_server()

    async def _list_tool_names() -> list[str]:
        tools = await server.list_tools()
        return [tool.name for tool in tools]

    tool_names = anyio.run(_list_tool_names)

    assert "get_context_pack" in tool_names
    assert "search_knowledge" in tool_names
    assert "trace_evidence" in tool_names
    assert "get_parse_quality_summary" in tool_names
    assert "get_document_inventory" in tool_names
    assert "get_runtime_dependencies" in tool_names


def test_mcp_get_context_pack_and_search_knowledge_return_structured_payloads(tmp_path: Path):
    processed_root = tmp_path / "processed"
    architecture = tmp_path / "architecture.md"
    architecture.write_text(
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

    server = create_mcp_server()

    async def _call_tools() -> tuple[dict, dict]:
        _, context_pack_payload = await server.call_tool(
            "get_context_pack",
            {
                "processed_dir": str(processed_root),
                "query": "为什么选第三种 runtime，默认治理规则是什么？",
                "task_type": "code_review",
                "top_k": 3,
                "per_document_limit": 2,
            },
        )
        _, search_payload = await server.call_tool(
            "search_knowledge",
            {
                "processed_dir": str(processed_root),
                "query": "默认治理规则是什么？",
                "top_k": 2,
                "per_document_limit": 1,
            },
        )
        return context_pack_payload, search_payload

    context_pack_payload, search_payload = anyio.run(_call_tools)

    assert context_pack_payload["markdown"].startswith("# Context Pack")
    assert context_pack_payload["schema_version"] == "context-pack.v1"
    assert context_pack_payload["task_type"] == "code_review"
    assert context_pack_payload["contract"]["stability"] == "stable_for_layer3"
    assert context_pack_payload["document_count"] == 2
    assert context_pack_payload["sections"]
    assert context_pack_payload["sections"][0]["items"][0]["task_item_type"].startswith("review_")
    assert search_payload["result_count"] >= 1
    assert any("默认不开放无限网络" in item["text"] for item in search_payload["results"])


def test_mcp_trace_evidence_returns_structured_payload(tmp_path: Path):
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

    server = create_mcp_server()

    async def _trace() -> dict:
        _, trace_payload = await server.call_tool(
            "trace_evidence",
            {
                "processed_dir": str(processed_root),
                "evidence_id": evidence_id,
            },
        )
        return trace_payload

    trace_payload = anyio.run(_trace)

    assert trace_payload["evidence_id"] == evidence_id
    assert trace_payload["document_title"] == "API"
    assert "/runtime-runs/{run_id}/events" in trace_payload["text"]
    assert trace_payload["chunk_references"]


def test_mcp_get_parse_quality_summary_returns_structured_payload(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "doc.md"
    source.write_text(
        "# 设计\n\n这是一个足够长的设计文档，包含正文约束、接口说明和测试要求，允许进入 Context Pack。",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="设计",
        source_type="内部设计文档",
        owner="checker",
        project="mcp-test",
        supplier="internal",
        document_version="v1",
    )

    server = create_mcp_server()

    async def _quality_summary() -> dict:
        _, quality_payload = await server.call_tool(
            "get_parse_quality_summary",
            {"processed_dir": str(processed_root)},
        )
        return quality_payload

    quality_payload = anyio.run(_quality_summary)

    assert quality_payload["processed_document_count"] == 1
    assert quality_payload["status_counts"]["ok"] == 1
    assert quality_payload["documents"][0]["allowed_for_context_pack"] is True


def test_mcp_get_document_inventory_returns_structured_payload(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "bosch-diagnostic.txt").write_text(
        "Bosch diagnostic constraints require DTC synchronization.",
        encoding="utf-8",
    )

    server = create_mcp_server()

    async def _inventory() -> dict:
        _, inventory_payload = await server.call_tool(
            "get_document_inventory",
            {
                "root_dirs": [str(docs)],
                "max_files": 10,
                "max_file_mb": 1,
                "owner": "checker",
                "project": "mcp-test",
            },
        )
        return inventory_payload

    inventory_payload = anyio.run(_inventory)

    assert inventory_payload["document_count"] == 1
    assert inventory_payload["documents"][0]["supplier"] == "Bosch"
    assert inventory_payload["markdown"].startswith("# Document Inventory")


def test_mcp_get_runtime_dependencies_returns_structured_payload():
    server = create_mcp_server()

    async def _dependencies() -> dict:
        _, dependency_payload = await server.call_tool("get_runtime_dependencies", {})
        return dependency_payload

    dependency_payload = anyio.run(_dependencies)

    assert any(
        capability["capability"] == "plain_text"
        for capability in dependency_payload["capabilities"]
    )
    assert dependency_payload["markdown"].startswith("# Runtime Dependency Report")
