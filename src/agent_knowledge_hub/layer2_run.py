from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_knowledge_hub.contract import (
    ProcessedContractSummary,
    validate_processed_dir,
    write_processed_contract_summary_bundle,
)
from agent_knowledge_hub.fts_index import FtsIndexBuildSummary, build_fts_index
from agent_knowledge_hub.retrieval import (
    ContextPackResult,
    EvidenceTraceResult,
    build_context_pack_for_processed_dir,
    trace_evidence_in_processed_dir,
    write_context_pack_bundle,
)
from agent_knowledge_hub.utils import write_json
from agent_knowledge_hub.vector_index import VectorIndexBuildSummary, build_vector_index


@dataclass(frozen=True)
class Layer2RunSummary:
    processed_dir: Path
    output_dir: Path
    query: str
    contract_valid: bool
    document_count: int
    chunk_count: int
    fts_index_path: Path | None
    vector_index_path: Path | None
    context_pack_json_path: Path | None
    context_pack_markdown_path: Path | None
    selected_chunk_count: int
    selected_document_count: int
    traced_evidence_id: str | None
    trace_found: bool
    evidence_trace_json_path: Path | None
    is_ready: bool
    blockers: list[str]
    warning_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "processed_dir": str(self.processed_dir),
            "output_dir": str(self.output_dir),
            "query": self.query,
            "contract_valid": self.contract_valid,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "fts_index_path": _path_to_string(self.fts_index_path),
            "vector_index_path": _path_to_string(self.vector_index_path),
            "context_pack_json_path": _path_to_string(self.context_pack_json_path),
            "context_pack_markdown_path": _path_to_string(self.context_pack_markdown_path),
            "selected_chunk_count": self.selected_chunk_count,
            "selected_document_count": self.selected_document_count,
            "traced_evidence_id": self.traced_evidence_id,
            "trace_found": self.trace_found,
            "evidence_trace_json_path": _path_to_string(self.evidence_trace_json_path),
            "is_ready": self.is_ready,
            "blockers": list(self.blockers),
            "warning_count": self.warning_count,
        }


def run_layer2_acceptance(
    *,
    processed_dir: Path | str,
    output_dir: Path | str,
    query: str,
    top_k: int = 8,
    per_document_limit: int = 2,
) -> Layer2RunSummary:
    processed_root = Path(processed_dir).resolve()
    run_root = Path(output_dir).resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    blockers: list[str] = []
    contract_summary: ProcessedContractSummary | None = None
    fts_summary: FtsIndexBuildSummary | None = None
    vector_summary: VectorIndexBuildSummary | None = None
    context_pack: ContextPackResult | None = None
    trace_result: EvidenceTraceResult | None = None
    context_pack_paths: dict[str, Path] = {}
    evidence_trace_json_path: Path | None = None

    try:
        contract_summary = validate_processed_dir(processed_root)
        write_processed_contract_summary_bundle(
            output_dir=run_root / "contract",
            summary=contract_summary,
        )
    except Exception as exc:
        blockers.append(f"contract_validation_failed: {exc}")

    if contract_summary is not None and not contract_summary.is_valid:
        blockers.append(
            f"processed_contract_invalid: {contract_summary.error_count} error(s)"
        )

    if contract_summary is not None and contract_summary.is_valid:
        fts_index_path = run_root / "indexes" / "chunks.fts.sqlite"
        vector_index_path = run_root / "indexes" / "chunks.vector.json"
        try:
            fts_summary = build_fts_index(
                processed_dir=processed_root,
                index_path=fts_index_path,
            )
        except Exception as exc:
            blockers.append(f"fts_index_failed: {exc}")
        try:
            vector_summary = build_vector_index(
                processed_dir=processed_root,
                index_path=vector_index_path,
            )
        except Exception as exc:
            blockers.append(f"vector_index_failed: {exc}")

        try:
            context_pack = build_context_pack_for_processed_dir(
                processed_dir=processed_root,
                query=query,
                top_k=top_k,
                per_document_limit=per_document_limit,
                fts_index_path=fts_summary.index_path if fts_summary else None,
                vector_index_path=vector_summary.index_path if vector_summary else None,
            )
            context_pack_paths = write_context_pack_bundle(
                output_dir=run_root / "context-pack",
                result=context_pack,
            )
            if not context_pack.selected_chunks:
                blockers.append("context_pack_empty")
        except Exception as exc:
            blockers.append(f"context_pack_failed: {exc}")

        traced_evidence_id = _first_evidence_id(context_pack) if context_pack else None
        if traced_evidence_id:
            try:
                trace_result = trace_evidence_in_processed_dir(
                    processed_dir=processed_root,
                    evidence_id=traced_evidence_id,
                )
                evidence_trace_json_path = run_root / "evidence-trace.json"
                write_json(evidence_trace_json_path, trace_result.to_dict())
            except Exception as exc:
                blockers.append(f"evidence_trace_failed: {exc}")
        elif context_pack is not None:
            blockers.append("no_evidence_id_selected")

    summary = _build_summary(
        processed_dir=processed_root,
        output_dir=run_root,
        query=query,
        contract_summary=contract_summary,
        fts_summary=fts_summary,
        vector_summary=vector_summary,
        context_pack=context_pack,
        context_pack_paths=context_pack_paths,
        trace_result=trace_result,
        evidence_trace_json_path=evidence_trace_json_path,
        blockers=blockers,
    )
    write_layer2_run_summary_bundle(summary=summary)
    return summary


def write_layer2_run_summary_bundle(*, summary: Layer2RunSummary) -> dict[str, Path]:
    summary_json_path = summary.output_dir / "layer2-run-summary.json"
    summary_markdown_path = summary.output_dir / "layer2-run-summary.md"
    write_json(summary_json_path, summary.to_dict())
    summary_markdown_path.write_text(_render_summary_markdown(summary), encoding="utf-8")
    return {
        "json_path": summary_json_path,
        "markdown_path": summary_markdown_path,
    }


def _build_summary(
    *,
    processed_dir: Path,
    output_dir: Path,
    query: str,
    contract_summary: ProcessedContractSummary | None,
    fts_summary: FtsIndexBuildSummary | None,
    vector_summary: VectorIndexBuildSummary | None,
    context_pack: ContextPackResult | None,
    context_pack_paths: dict[str, Path],
    trace_result: EvidenceTraceResult | None,
    evidence_trace_json_path: Path | None,
    blockers: list[str],
) -> Layer2RunSummary:
    selected_chunk_count = context_pack.chunk_count if context_pack else 0
    selected_document_count = context_pack.document_count if context_pack else 0
    traced_evidence_id = trace_result.evidence_id if trace_result else _first_evidence_id(context_pack)
    trace_found = trace_result is not None
    ready_blockers = list(dict.fromkeys(blockers))
    if selected_chunk_count <= 0 and "context_pack_empty" not in ready_blockers:
        ready_blockers.append("context_pack_empty")
    if not trace_found and "evidence_trace_missing" not in ready_blockers:
        ready_blockers.append("evidence_trace_missing")

    return Layer2RunSummary(
        processed_dir=processed_dir,
        output_dir=output_dir,
        query=query,
        contract_valid=bool(contract_summary and contract_summary.is_valid),
        document_count=contract_summary.document_count if contract_summary else 0,
        chunk_count=contract_summary.chunk_count if contract_summary else 0,
        fts_index_path=fts_summary.index_path if fts_summary else None,
        vector_index_path=vector_summary.index_path if vector_summary else None,
        context_pack_json_path=context_pack_paths.get("json_path"),
        context_pack_markdown_path=context_pack_paths.get("markdown_path"),
        selected_chunk_count=selected_chunk_count,
        selected_document_count=selected_document_count,
        traced_evidence_id=traced_evidence_id,
        trace_found=trace_found,
        evidence_trace_json_path=evidence_trace_json_path,
        is_ready=not ready_blockers,
        blockers=ready_blockers,
        warning_count=contract_summary.warning_count if contract_summary else 0,
    )


def _first_evidence_id(context_pack: ContextPackResult | None) -> str | None:
    if context_pack is None:
        return None
    for chunk in context_pack.selected_chunks:
        for evidence_id in chunk.evidence_ids:
            if evidence_id:
                return evidence_id
    return None


def _render_summary_markdown(summary: Layer2RunSummary) -> str:
    lines = [
        "# Layer2 Run Summary",
        "",
        f"Ready: `{summary.is_ready}`",
        f"Processed Dir: `{summary.processed_dir}`",
        f"Output Dir: `{summary.output_dir}`",
        f"Query: `{summary.query}`",
        "",
        "## Checks",
        "",
        f"- Contract valid: `{summary.contract_valid}`",
        f"- Documents: `{summary.document_count}`",
        f"- Chunks: `{summary.chunk_count}`",
        f"- Selected chunks: `{summary.selected_chunk_count}`",
        f"- Selected documents: `{summary.selected_document_count}`",
        f"- Trace found: `{summary.trace_found}`",
        f"- Traced evidence id: `{summary.traced_evidence_id or 'none'}`",
        "",
        "## Outputs",
        "",
        f"- FTS index: `{_path_to_string(summary.fts_index_path) or 'none'}`",
        f"- Vector index: `{_path_to_string(summary.vector_index_path) or 'none'}`",
        f"- Context Pack JSON: `{_path_to_string(summary.context_pack_json_path) or 'none'}`",
        f"- Context Pack Markdown: `{_path_to_string(summary.context_pack_markdown_path) or 'none'}`",
        f"- Evidence trace JSON: `{_path_to_string(summary.evidence_trace_json_path) or 'none'}`",
        "",
        "## Blockers",
        "",
    ]
    if summary.blockers:
        lines.extend(f"- `{blocker}`" for blocker in summary.blockers)
    else:
        lines.append("- None")
    return "\n".join(lines).strip() + "\n"


def _path_to_string(path: Path | None) -> str | None:
    return str(path) if path is not None else None
