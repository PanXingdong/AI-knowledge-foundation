from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from typing import TYPE_CHECKING

try:  # pragma: no cover - exercised indirectly in environment-specific tests
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - depends on interpreter environment
    FastMCP = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as FastMCPType
else:
    FastMCPType = Any

from agent_knowledge_hub.retrieval import (
    build_context_pack_for_processed_dir,
    search_processed_dir,
    trace_evidence_in_processed_dir,
)
from agent_knowledge_hub.quality import build_parse_quality_summary
from agent_knowledge_hub.inventory import build_document_inventory
from agent_knowledge_hub.dependencies import check_runtime_dependencies


class MCPContextPackResult(BaseModel):
    schema_version: str
    task_type: str
    task_profile: dict[str, Any]
    contract: dict[str, Any]
    query: str
    normalized_query: str
    processed_dir: str
    applied_filters: dict[str, list[str]]
    chunk_count: int
    document_count: int
    warnings: list[str]
    sections: list[dict[str, Any]]
    selected_chunks: list[dict[str, Any]]
    markdown: str


class MCPSearchResult(BaseModel):
    query: str
    normalized_query: str
    processed_dir: str
    result_count: int
    document_count: int
    results: list[dict[str, Any]]


class MCPEvidenceTraceResult(BaseModel):
    evidence_id: str
    document_id: str
    document_title: str
    document_version_id: str
    document_version: str
    source_type: str
    source_path: str
    created_at: str
    page: int | None
    section_path: list[str]
    section_titles: list[str]
    block_id: str
    text: str
    bbox: list[float] | None
    chunk_references: list[dict[str, Any]]


class MCPParseQualitySummaryResult(BaseModel):
    processed_dir: str
    processed_document_count: int
    failed_input_count: int
    allowed_document_count: int
    blocked_document_count: int
    status_counts: dict[str, int]
    documents: list[dict[str, Any]]
    failed_inputs: list[dict[str, Any]]
    markdown: str


class MCPDocumentInventoryResult(BaseModel):
    root_dirs: list[str]
    generated_at: str
    document_count: int
    skipped_count: int
    extension_counts: dict[str, int]
    supplier_counts: dict[str, int]
    documents: list[dict[str, Any]]
    skipped: list[dict[str, str]]
    markdown: str


class MCPRuntimeDependencyResult(BaseModel):
    generated_at: str
    dependencies: list[dict[str, Any]]
    capabilities: list[dict[str, Any]]
    markdown: str


def create_mcp_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8788,
    streamable_http_path: str = "/mcp",
) -> FastMCPType:
    if FastMCP is None:
        raise RuntimeError(
            "The Python 'mcp' package is not available in this interpreter. "
            "Use a Python environment with the MCP SDK installed, such as Python 3.12 on this machine."
        )
    server = FastMCP(
        name="agent-knowledge-hub",
        instructions=(
            "Use these tools to retrieve Context Pack data from processed engineering documents. "
            "Prefer get_context_pack before coding, review, or analysis tasks; use search_knowledge "
            "for follow-up retrieval and trace_evidence when exact provenance is needed."
        ),
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    @server.tool(
        name="get_context_pack",
        description=(
            "Build a structured Context Pack from processed document chunks. "
            "Use before coding, review, defect analysis, or test design."
        ),
        structured_output=True,
    )
    def get_context_pack(
        processed_dir: str,
        query: str,
        task_type: str = "general_query",
        top_k: int = Field(default=8, ge=1, le=100),
        per_document_limit: int = Field(default=2, ge=1, le=20),
    ) -> MCPContextPackResult:
        result = build_context_pack_for_processed_dir(
            processed_dir=processed_dir,
            query=query,
            task_type=task_type,
            top_k=top_k,
            per_document_limit=per_document_limit,
        )
        return MCPContextPackResult(
            **result.to_json_dict(),
            markdown=result.markdown,
        )

    @server.tool(
        name="search_knowledge",
        description=(
            "Search processed engineering knowledge and return ranked chunk results. "
            "Use for follow-up retrieval after a Context Pack or for direct evidence lookup."
        ),
        structured_output=True,
    )
    def search_knowledge(
        processed_dir: str,
        query: str,
        top_k: int = Field(default=8, ge=1, le=100),
        per_document_limit: int = Field(default=2, ge=1, le=20),
    ) -> MCPSearchResult:
        result = search_processed_dir(
            processed_dir=processed_dir,
            query=query,
            top_k=top_k,
            per_document_limit=per_document_limit,
        )
        return MCPSearchResult(**result.to_dict())

    @server.tool(
        name="trace_evidence",
        description=(
            "Trace one evidence span back to its document, version, section, page, and related chunks."
        ),
        structured_output=True,
    )
    def trace_evidence(
        processed_dir: str,
        evidence_id: str,
    ) -> MCPEvidenceTraceResult:
        result = trace_evidence_in_processed_dir(
            processed_dir=processed_dir,
            evidence_id=evidence_id,
        )
        return MCPEvidenceTraceResult(**result.to_dict())

    @server.tool(
        name="get_parse_quality_summary",
        description=(
            "Summarize parse quality reports for processed documents, including quality gates. "
            "Use before building Context Packs to inspect low-quality, unsupported, or OCR-recovered inputs."
        ),
        structured_output=True,
    )
    def get_parse_quality_summary(processed_dir: str) -> MCPParseQualitySummaryResult:
        result = build_parse_quality_summary(processed_dir)
        return MCPParseQualitySummaryResult(
            **result.to_dict(),
            markdown=result.markdown,
        )

    @server.tool(
        name="get_document_inventory",
        description=(
            "Discover supported local engineering documents under explicit root directories. "
            "Use this before ingesting a sample set or when deciding which documents can feed Agent Context Packs. "
            "This tool returns metadata and hashes only; it does not move or modify source files."
        ),
        structured_output=True,
    )
    def get_document_inventory(
        root_dirs: list[str],
        max_files: int = Field(default=200, ge=1, le=10000),
        max_file_mb: float = Field(default=100.0, gt=0),
        owner: str = "checker",
        project: str = "unknown",
        document_version: str = "unknown",
        include_keywords: list[str] = Field(default_factory=list),
        exclude_keywords: list[str] = Field(default_factory=list),
        dedupe_content_hash: bool = True,
    ) -> MCPDocumentInventoryResult:
        result = build_document_inventory(
            root_dirs=[Path(root_dir) for root_dir in root_dirs],
            max_files=max_files,
            max_file_mb=max_file_mb,
            owner=owner,
            project=project,
            document_version=document_version,
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
            dedupe_content_hash=dedupe_content_hash,
        )
        return MCPDocumentInventoryResult(
            **result.to_dict(),
            markdown=result.markdown,
        )

    @server.tool(
        name="get_runtime_dependencies",
        description=(
            "Check whether this runtime can parse PDF text, DOCX, and low-quality PDF OCR fallback. "
            "Use before ingesting mixed document sets or diagnosing blocked parse-quality results."
        ),
        structured_output=True,
    )
    def get_runtime_dependencies() -> MCPRuntimeDependencyResult:
        result = check_runtime_dependencies()
        return MCPRuntimeDependencyResult(
            **result.to_dict(),
            markdown=result.markdown,
        )

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-knowledge-hub-mcp",
        description="Run the Agent Knowledge Hub MCP server.",
    )
    parser.add_argument(
        "--transport",
        default="streamable-http",
        choices=("stdio", "sse", "streamable-http"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--streamable-http-path", default="/mcp")
    args = parser.parse_args(argv)

    server = create_mcp_server(
        host=args.host,
        port=args.port,
        streamable_http_path=args.streamable_http_path,
    )
    server.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
