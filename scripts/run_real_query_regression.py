from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from agent_knowledge_hub.feishu_bot import MessageFormatter
from agent_knowledge_hub.llm_agent import LLMAgent
from agent_knowledge_hub.retrieval import build_context_pack_for_processed_dir


@dataclass(frozen=True)
class QueryCase:
    case_id: str
    query: str
    must_have_facts: tuple[str, ...] = ()
    must_have_documents: tuple[str, ...] = ()


CASES: tuple[QueryCase, ...] = (
    QueryCase(
        case_id="qnx-render-debug-tools",
        query="qnx是否提供了一些debug渲染显示问题的demo或工具",
        must_have_facts=("screeninfo", "gltracelogger"),
        must_have_documents=("Screen Graphics Subsystem Developers Guide",),
    ),
    QueryCase(
        case_id="sa8397-zero-copy-cache",
        query="高通8397上 缓存零拷贝的技术方案架构是什么",
        must_have_facts=("cache",),
        must_have_documents=("Qualcomm",),
    ),
    QueryCase(
        case_id="mm-dma-vs-dma-ecc-above-4g",
        query="mm_dma和dma_ecc_above_4g 的区别是什么",
        must_have_facts=("mm_dma", "dma_ecc_above_4g"),
    ),
    QueryCase(
        case_id="process-vram-allocation",
        query="实际进程的显存是如何分配的",
        must_have_facts=("memory",),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real query regression checks.")
    parser.add_argument("--processed-dir", required=True)
    parser.add_argument("--vector-index-path", default="")
    parser.add_argument("--output-dir", default=".agent-artifacts/real-query-regression")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--per-document-limit", type=int, default=4)
    parser.add_argument("--use-llm", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    agent = LLMAgent.from_env() if args.use_llm else None

    for case in CASES:
        context_pack = build_context_pack_for_processed_dir(
            processed_dir=args.processed_dir,
            query=case.query,
            top_k=args.top_k,
            per_document_limit=args.per_document_limit,
            vector_index_path=args.vector_index_path or None,
        )
        payload = context_pack.to_json_dict()
        candidate_facts = MessageFormatter.extract_candidate_facts(payload)
        llm_reply = None
        parsed_reply = None
        if agent is not None:
            context_text = MessageFormatter.format_context_pack(payload)
            llm_reply = agent.synthesize(case.query, context_text)
            parsed = MessageFormatter.build_user_reply(
                query=case.query,
                answer_text=llm_reply,
                context_pack=payload,
            )
            parsed_reply = {
                "title": parsed.title,
                "answer_type": parsed.answer_type,
                "direct_answer": parsed.direct_answer,
                "details": parsed.details,
                "evidence_items": parsed.evidence_items,
                "confidence": parsed.confidence,
            }

        document_titles = [
            chunk["document_title"]
            for chunk in payload.get("selected_chunks", [])
        ]
        fact_names = [str(fact.get("name") or "") for fact in candidate_facts]
        checks = {
            "must_have_facts": {
                item: any(item.lower() in name.lower() for name in fact_names)
                for item in case.must_have_facts
            },
            "must_have_documents": {
                item: any(item.lower() in title.lower() for title in document_titles)
                for item in case.must_have_documents
            },
        }
        passed = all(checks["must_have_facts"].values()) and all(
            checks["must_have_documents"].values()
        )
        results.append(
            {
                "case": asdict(case),
                "passed": passed,
                "checks": checks,
                "candidate_facts": candidate_facts,
                "selected_documents": document_titles,
                "selected_chunks": [
                    {
                        "document_title": chunk["document_title"],
                        "section_titles": chunk.get("section_titles", []),
                        "score": chunk.get("score"),
                        "evidence_ids": chunk.get("evidence_ids", []),
                    }
                    for chunk in payload.get("selected_chunks", [])
                ],
                "llm_reply": llm_reply,
                "parsed_reply": parsed_reply,
            }
        )

    report = {
        "passed": all(item["passed"] for item in results),
        "case_count": len(results),
        "results": results,
    }
    (output_dir / "real-query-regression.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "real-query-regression.md").write_text(
        _render_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps({"passed": report["passed"], "output_dir": str(output_dir)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Real Query Regression",
        "",
        f"Passed: `{report['passed']}`",
        f"Cases: `{report['case_count']}`",
        "",
    ]
    for item in report["results"]:
        case = item["case"]
        lines.extend(
            [
                f"## {case['case_id']}",
                "",
                f"Query: {case['query']}",
                f"Passed: `{item['passed']}`",
                "",
                "Candidate facts:",
            ]
        )
        for fact in item["candidate_facts"][:12]:
            lines.append(f"- `{fact.get('kind')}` {fact.get('name')} — {fact.get('purpose')}")
        lines.extend(["", "Selected documents:"])
        for title in item["selected_documents"][:8]:
            lines.append(f"- {title}")
        if item.get("parsed_reply"):
            lines.extend(["", "Parsed reply:", "```json"])
            lines.append(json.dumps(item["parsed_reply"], ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
