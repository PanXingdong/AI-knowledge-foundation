from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from agent_knowledge_hub.llm_agent import LLMAgent

logger = logging.getLogger(__name__)


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    api_base: str = "https://open.feishu.cn/open-apis"
    local_api_base: str = "http://127.0.0.1:8789"
    processed_dir: str = ""
    fts_index_path: str = ""
    vector_index_path: str = ""
    reference_markdown_path: str = ""
    default_top_k: int = 8
    default_per_document_limit: int = 2
    max_reply_length: int = 3000
    # Minimum score for a retrieved chunk to be treated as useful evidence.
    # Chunks scoring below this are treated as "no evidence found".
    score_threshold: float = -30.0

    @classmethod
    def from_env(cls) -> FeishuConfig:
        return cls(
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
            api_base=os.getenv("FEISHU_API_BASE", "https://open.feishu.cn/open-apis"),
            local_api_base=os.getenv("LOCAL_API_BASE", "http://127.0.0.1:8789"),
            processed_dir=os.getenv("PROCESSED_DIR", ""),
            fts_index_path=os.getenv("FTS_INDEX_PATH", ""),
            vector_index_path=os.getenv("VECTOR_INDEX_PATH", ""),
            reference_markdown_path=os.getenv("REFERENCE_MARKDOWN_PATH", ""),
            default_top_k=int(os.getenv("DEFAULT_TOP_K", "8")),
            default_per_document_limit=int(os.getenv("DEFAULT_PER_DOCUMENT_LIMIT", "2")),
            max_reply_length=int(os.getenv("MAX_REPLY_LENGTH", "3000")),
            score_threshold=float(os.getenv("SCORE_THRESHOLD", "-30.0")),
        )


@dataclass
class FormattedReply:
    title: str
    summary: str
    answer_type: str = "general"
    direct_answer: dict[str, str] | None = None
    details: list[dict[str, str]] | None = None
    solution: dict[str, Any] | None = None
    key_points: list[str] | None = None
    evidence_items: list[dict[str, Any]] | None = None
    caveats: list[str] | None = None
    next_steps: list[str] | None = None
    confidence: str = ""
    plain_text: str = ""


@dataclass(frozen=True)
class BotReplyResult:
    text: str
    search_query: str
    has_evidence: bool = False
    formatted_reply: FormattedReply | None = None
    context_pack: dict[str, Any] | None = None


def _http_post(url: str, data: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    req_headers = headers or {}
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8", **req_headers},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class FeishuTokenManager:
    def __init__(self, config: FeishuConfig):
        self.config = config
        self._token = ""
        self._expires_at = 0.0

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at:
            return self._token

        url = f"{self.config.api_base}/auth/v3/tenant_access_token/internal"
        data = _http_post(url, {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        })

        if data.get("code") != 0:
            raise RuntimeError(f"获取Token失败: {data}")

        self._token = data["tenant_access_token"]
        self._expires_at = time.time() + data["expire"]
        logger.info("刷新tenant_access_token，有效期%s秒", data["expire"])
        return self._token


class LocalAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def get_context_pack(
        self,
        processed_dir: str,
        query: str,
        top_k: int = 8,
        per_document_limit: int = 2,
        task_type: str | None = None,
        fts_index_path: str | None = None,
        vector_index_path: str | None = None,
        timeout: int = 180,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/context-pack"
        try:
            payload: dict[str, Any] = {
                "processed_dir": processed_dir,
                "query": query,
                "top_k": top_k,
                "per_document_limit": per_document_limit,
            }
            if task_type is not None:
                payload["task_type"] = task_type
            if fts_index_path is not None:
                payload["fts_index_path"] = fts_index_path
            if vector_index_path is not None:
                payload["vector_index_path"] = vector_index_path
            data = _http_post(url, payload, timeout=timeout)
            return data.get("data", {})
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            logger.error("获取Context Pack失败: %s", error_body)
            raise RuntimeError(f"获取Context Pack失败: {error_body}") from e

    def get_gap_report(
        self,
        processed_dir: str,
        query: str,
        reference_markdown_path: str,
        top_k: int = 8,
        per_document_limit: int = 2,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/gap-report"
        try:
            data = _http_post(url, {
                "processed_dir": processed_dir,
                "query": query,
                "reference_markdown_path": reference_markdown_path,
                "top_k": top_k,
                "per_document_limit": per_document_limit,
            })
            return data.get("data", {})
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            logger.error("获取Gap Report失败: %s", error_body)
            raise RuntimeError(f"获取Gap Report失败: {error_body}") from e

    def get_evidence(
        self,
        *,
        processed_dir: str,
        evidence_id: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}/api/evidence/{urllib.parse.quote(evidence_id)}"
            f"?processed_dir={urllib.parse.quote(processed_dir)}"
        )
        try:
            data = _http_get(url, timeout=timeout)
            return data.get("data", {})
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            logger.error("获取Evidence失败: %s", error_body)
            raise RuntimeError(f"获取Evidence失败: {error_body}") from e


class MessageFormatter:
    @staticmethod
    def build_user_reply(
        *,
        query: str,
        answer_text: str,
        context_pack: dict[str, Any],
        max_evidence_items: int = 3,
    ) -> FormattedReply:
        candidate_facts = MessageFormatter.extract_candidate_facts(context_pack)
        parsed_json = MessageFormatter._parse_answer_json(answer_text)
        if parsed_json is not None:
            MessageFormatter._apply_candidate_fact_consistency(parsed_json, candidate_facts)
            if not parsed_json.evidence_items:
                parsed_json.evidence_items = MessageFormatter.extract_evidence_summary(
                    context_pack,
                    max_items=max_evidence_items,
                )
            parsed_json.plain_text = MessageFormatter.format_user_answer_text(parsed_json)
            return parsed_json

        title = MessageFormatter._compact_title(query)
        parsed = MessageFormatter._parse_answer_sections(answer_text)
        summary = parsed["summary"]
        evidence_items = parsed["evidence_items"] or MessageFormatter.extract_evidence_summary(
            context_pack,
            max_items=max_evidence_items,
        )
        confidence = parsed["confidence"]
        reply = FormattedReply(
            title=title,
            summary=summary,
            evidence_items=evidence_items,
            caveats=parsed["caveats"],
            next_steps=parsed["next_steps"],
            confidence=confidence,
        )
        MessageFormatter._apply_candidate_fact_consistency(reply, candidate_facts)
        reply.plain_text = MessageFormatter.format_user_answer_text(reply)
        return reply

    @staticmethod
    def extract_candidate_facts(context_pack: dict[str, Any]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        patterns = [
            ("tool", "screeninfo", r"\bscreeninfo\b", "查看 Screen 对象和显示状态"),
            ("tool", "slog2info", r"\bslog2info\b", "查看 slog2 日志"),
            ("tool", "gltracelogger", r"\bgltracelogger\b", "记录 OpenGL ES 调用轨迹"),
            ("tool", "gltraceprinter", r"\bgltraceprinter\b", "打印 gltrace 日志"),
            ("tool", "screencmd", r"\bscreencmd\b", "执行 Screen 命令和状态检查"),
            ("api_feature", "SCREEN_PROPERTY_DEBUG", r"\bSCREEN_PROPERTY_DEBUG\b", "通过 Screen API 启用调试属性"),
            ("api_feature", "SCREEN_DEBUG_GRAPH", r"\bSCREEN_DEBUG_GRAPH_[A-Z_]+\b", "显示 Screen 调试图表"),
            ("demo", "gles3-gears", r"\bgles3-gears\b", "演示 OpenGL ES 3D 渲染能力"),
            ("demo", "vk-gears", r"\bvk-gears\b", "演示 Vulkan 3D 渲染能力"),
            ("demo", "vk-fsray", r"\bvk-fsray\b", "演示 Vulkan shader 渲染内容"),
            ("demo", "win-vsync", r"\bwin-vsync\b", "演示多窗口软件光栅化内容"),
        ]
        for chunk in context_pack.get("selected_chunks") or []:
            text = str(chunk.get("text") or "")
            source = MessageFormatter._candidate_source(chunk)
            evidence_ids = [str(item) for item in (chunk.get("evidence_ids") or [])]
            for kind, name, pattern, purpose in patterns:
                if not re.search(pattern, text, flags=re.IGNORECASE):
                    continue
                if any(fact["kind"] == kind and fact["name"] == name for fact in facts):
                    continue
                facts.append(
                    {
                        "kind": kind,
                        "name": name,
                        "purpose": purpose,
                        "source": source,
                        "evidence_ids": evidence_ids,
                    }
                )
        return facts

    @staticmethod
    def _candidate_source(chunk: dict[str, Any]) -> str:
        title = str(chunk.get("document_title") or "Unknown")
        sections = " > ".join(str(item) for item in (chunk.get("section_titles") or []) if item)
        page = chunk.get("page_start")
        parts = [title]
        if sections:
            parts.append(sections)
        if page is not None:
            parts.append(f"page {page}")
        return " / ".join(parts)

    @staticmethod
    def _apply_candidate_fact_consistency(
        reply: FormattedReply,
        candidate_facts: list[dict[str, Any]],
    ) -> None:
        if not candidate_facts:
            return
        direct_answer = dict(reply.direct_answer or {})
        tool_facts = [fact for fact in candidate_facts if fact["kind"] in {"tool", "api_feature"}]
        demo_facts = [fact for fact in candidate_facts if fact["kind"] == "demo"]
        if tool_facts and MessageFormatter._answer_says_unknown(direct_answer.get("tools", "")):
            names = ", ".join(fact["name"] for fact in tool_facts[:6])
            direct_answer["tools"] = f"有，检索证据明确提到 {names} 等调试工具/能力。"
        if demo_facts and MessageFormatter._answer_says_unknown(direct_answer.get("demos", "")):
            names = ", ".join(fact["name"] for fact in demo_facts[:4])
            direct_answer["demos"] = f"有，检索证据明确提到 {names} 等渲染/显示示例。"
        if direct_answer:
            reply.direct_answer = direct_answer

        existing_detail_names = {str(item.get("name") or "") for item in (reply.details or [])}
        details = list(reply.details or [])
        for fact in candidate_facts:
            if fact["name"] in existing_detail_names:
                continue
            details.append(
                {
                    "name": fact["name"],
                    "purpose": fact["purpose"],
                    "usage": "具体命令/参数需参考对应文档章节。",
                    "when_to_use": "当问题与该工具/能力描述匹配时使用。",
                }
            )
            existing_detail_names.add(fact["name"])
            if len(details) >= 4:
                break
        reply.details = details

        if not reply.evidence_items:
            reply.evidence_items = [
                {
                    "name": fact["name"],
                    "source": fact["source"],
                    "why_relevant": fact["purpose"],
                    "evidence_ids": fact["evidence_ids"],
                }
                for fact in candidate_facts[:2]
            ]

    @staticmethod
    def _answer_says_unknown(value: str) -> bool:
        normalized = value.strip().lower()
        if not normalized:
            return True
        return any(token in normalized for token in ("不确定", "未发现", "没有找到", "unknown"))

    @staticmethod
    def extract_evidence_summary(
        context_pack: dict[str, Any],
        *,
        max_items: int = 3,
        max_summary_chars: int = 160,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        selected_chunks = context_pack.get("selected_chunks", [])
        for chunk in selected_chunks:
            if len(items) >= max_items:
                break
            text = MessageFormatter._clean_inline_text(str(chunk.get("text") or ""))
            if not text:
                continue
            section = " > ".join(str(item) for item in (chunk.get("section_titles") or []) if item)
            page = chunk.get("page_start")
            location_parts = []
            if section:
                location_parts.append(section)
            if page is not None:
                location_parts.append(f"page {page}")
            items.append(
                {
                    "document_title": str(chunk.get("document_title") or "Unknown"),
                    "location": " / ".join(location_parts) or "source chunk",
                    "summary": MessageFormatter.truncate_message(text, max_summary_chars),
                    "evidence_ids": [str(item) for item in (chunk.get("evidence_ids") or [])],
                }
            )
        return items

    @staticmethod
    def format_user_answer_text(reply: FormattedReply, *, max_length: int = 3000) -> str:
        lines = [reply.title.strip() or "知识库回答"]
        direct_answer = reply.direct_answer or {}
        if direct_answer:
            lines.extend(["", "结论"])
            tools = direct_answer.get("tools")
            demos = direct_answer.get("demos")
            if tools:
                lines.append(f"工具：{tools}")
            if demos:
                lines.append(f"Demo：{demos}")
        else:
            lines.extend(["", "结论", reply.summary.strip()])
        key_points = [] if direct_answer else (reply.key_points or [])
        if key_points:
            lines.extend(["", "要点"])
            lines.extend(f"{index}. {item}" for index, item in enumerate(key_points, start=1))

        if reply.answer_type == "solution_design" and reply.solution:
            solution = reply.solution
            recommended = solution.get("recommended")
            if recommended:
                lines.extend(["", "推荐方案", str(recommended)])
            for title, key in (
                ("实施步骤", "steps"),
                ("可选方案", "variants"),
                ("不推荐做法", "not_recommended"),
                ("风险", "risks"),
                ("待确认", "open_questions"),
            ):
                items = solution.get(key) or []
                if items:
                    lines.extend(["", title])
                    lines.extend(f"{index}. {item}" for index, item in enumerate(items, start=1))

        evidence_items = (reply.evidence_items or [])[:2]
        if evidence_items:
            lines.extend(["", "关键依据"])
            for index, item in enumerate(evidence_items, start=1):
                title = item.get("name") or item.get("document_title") or "参考资料"
                source = item.get("source") or item.get("location") or "source chunk"
                summary = item.get("why_relevant") or item.get("summary") or ""
                lines.append(
                    f"{index}. {title}\n"
                    f"   来源：{source}\n"
                    f"   说明：{summary}"
                )

        caveats = reply.caveats or []
        if caveats:
            lines.extend(["", "需要注意"])
            lines.extend(f"- {item}" for item in caveats)

        next_steps = reply.next_steps or []
        if next_steps:
            lines.extend(["", "下一步建议"])
            lines.extend(f"{index}. {item}" for index, item in enumerate(next_steps, start=1))

        if reply.confidence:
            lines.extend(["", "置信度", reply.confidence])

        return MessageFormatter.truncate_message("\n".join(lines), max_length)

    @staticmethod
    def format_user_answer_post(reply: FormattedReply) -> dict[str, Any]:
        content: list[list[dict[str, Any]]] = []

        def add_line(text: str, *, bold: bool = False) -> None:
            if not text:
                return
            item: dict[str, Any] = {"tag": "text", "text": text}
            content.append([item])

        add_line("结论", bold=True)
        for line in reply.summary.strip().splitlines():
            add_line(line)

        if reply.key_points:
            add_line("")
            add_line("要点", bold=True)
            for index, item in enumerate(reply.key_points, start=1):
                add_line(f"{index}. {item}")

        if reply.evidence_items:
            add_line("")
            add_line("关键依据", bold=True)
            for index, item in enumerate(reply.evidence_items, start=1):
                evidence_ids = ", ".join(item.get("evidence_ids") or [])
                suffix = f" [{evidence_ids}]" if evidence_ids else ""
                add_line(
                    f"{index}. {item.get('document_title', 'Unknown')} "
                    f"({item.get('location', 'source chunk')}): "
                    f"{item.get('summary', '')}{suffix}"
                )

        if reply.caveats:
            add_line("")
            add_line("需要注意", bold=True)
            for item in reply.caveats:
                add_line(f"- {item}")

        if reply.next_steps:
            add_line("")
            add_line("下一步建议", bold=True)
            for index, item in enumerate(reply.next_steps, start=1):
                add_line(f"{index}. {item}")

        if reply.confidence:
            add_line("")
            add_line("置信度", bold=True)
            add_line(reply.confidence)

        return {
            "post": {
                "zh_cn": {
                    "title": MessageFormatter.truncate_message(reply.title or "知识库回答", 80),
                    "content": content,
                }
            }
        }

    @staticmethod
    def format_user_answer_card(reply: FormattedReply) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []

        def add_markdown(content: str) -> None:
            content = content.strip()
            if not content:
                return
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content,
                    },
                }
            )

        def add_hr() -> None:
            if elements:
                elements.append({"tag": "hr"})

        direct_answer = reply.direct_answer or {}
        if direct_answer:
            answer_lines = []
            tools = direct_answer.get("tools")
            demos = direct_answer.get("demos")
            if tools:
                answer_lines.append(f"**工具：**{MessageFormatter._escape_card_markdown(tools)}")
            if demos:
                answer_lines.append(f"**Demo：**{MessageFormatter._escape_card_markdown(demos)}")
            if answer_lines:
                add_markdown("**结论**\n" + "\n".join(answer_lines))
        else:
            add_markdown(f"**结论**\n{MessageFormatter._escape_card_markdown(reply.summary)}")

        if reply.answer_type == "solution_design" and reply.solution:
            MessageFormatter._append_solution_card_sections(
                add_hr=add_hr,
                add_markdown=add_markdown,
                solution=reply.solution,
            )
        elif reply.details:
            add_hr()
            detail_lines = []
            for item in reply.details[:4]:
                name = item.get("name", "说明")
                purpose = item.get("purpose", "")
                usage = item.get("usage", "")
                when = item.get("when_to_use", "")
                line_parts = [f"**{MessageFormatter._escape_card_markdown(name)}**"]
                if purpose:
                    line_parts.append(MessageFormatter._escape_card_markdown(purpose))
                if usage:
                    line_parts.append(f"怎么用：{MessageFormatter._escape_card_markdown(usage)}")
                if when:
                    line_parts.append(f"适用：{MessageFormatter._escape_card_markdown(when)}")
                detail_lines.append("：".join(line_parts[:2]) + ("\n   " + "\n   ".join(line_parts[2:]) if len(line_parts) > 2 else ""))
            add_markdown(f"**{MessageFormatter._details_section_title(reply.answer_type)}**\n" + "\n".join(detail_lines))

        if reply.key_points and not direct_answer:
            add_hr()
            key_points = "\n".join(
                f"{index}. {MessageFormatter._escape_card_markdown(item)}"
                for index, item in enumerate(reply.key_points, start=1)
            )
            add_markdown(f"**要点**\n{key_points}")

        evidence_items = (reply.evidence_items or [])[:2]
        if evidence_items:
            add_hr()
            evidence_lines = []
            for index, item in enumerate(evidence_items, start=1):
                title = item.get("name") or item.get("document_title") or "参考资料"
                source = item.get("source") or item.get("location") or "source chunk"
                summary = item.get("why_relevant") or item.get("summary") or ""
                evidence_lines.append(
                    f"{index}. **{MessageFormatter._escape_card_markdown(str(title))}**\n"
                    f"   {MessageFormatter._escape_card_markdown(MessageFormatter._format_source_text(str(source)))}\n"
                    f"   用途：{MessageFormatter._escape_card_markdown(str(summary))}"
                )
            add_markdown("**关键依据**\n" + "\n".join(evidence_lines))

        if reply.caveats:
            add_hr()
            caveat_lines = "\n".join(
                f"- {MessageFormatter._escape_card_markdown(item)}"
                for item in reply.caveats
            )
            add_markdown(f"**需要注意**\n{caveat_lines}")

        if reply.next_steps:
            add_hr()
            step_lines = "\n".join(
                f"{index}. {MessageFormatter._escape_card_markdown(item)}"
                for index, item in enumerate(reply.next_steps, start=1)
            )
            add_markdown(f"**下一步建议**\n{step_lines}")

        if reply.confidence:
            elements.append(
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": MessageFormatter._format_confidence_text(reply.confidence),
                        }
                    ],
                }
            )

        evidence_refs = MessageFormatter._collect_evidence_refs(reply)
        evidence_ids = [item["evidence_id"] for item in evidence_refs]
        if evidence_ids:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "查看完整证据",
                            },
                            "type": "default",
                            "value": {
                                "action": "show_full_evidence",
                                "evidence_ids": evidence_ids[:6],
                                "evidence_refs": evidence_refs[:6],
                            },
                        }
                    ],
                }
            )

        return {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True,
            },
            "header": {
                "template": MessageFormatter._confidence_card_template(reply.confidence),
                "title": {
                    "tag": "plain_text",
                    "content": MessageFormatter.truncate_message(reply.title or "知识库回答", 80),
                },
            },
            "elements": elements,
        }

    @staticmethod
    def format_context_pack(
        result: dict[str, Any],
        score_threshold: float = -30.0,
        max_context_length: int = 12000,
    ) -> str:
        selected_chunks = result.get("selected_chunks", [])
        qualified = [c for c in selected_chunks if c.get("score", float("-inf")) >= score_threshold]

        if not qualified:
            return "未找到相关内容"

        # Prefer the pre-rendered markdown from the API so the LLM receives
        # full chunk text, section paths, scores, and evidence context.
        markdown = result.get("markdown", "")
        if markdown:
            facts = MessageFormatter.format_candidate_facts_for_llm(
                MessageFormatter.extract_candidate_facts(result)
            )
            content = f"{facts}\n\n{markdown}" if facts else markdown
            return MessageFormatter.truncate_message(content, max_context_length)

        query = result.get("query", "N/A")
        doc_titles = {c.get("document_title", "Unknown") for c in qualified}
        lines = [
            f"【Query】{query}",
            "",
            f"【检索结果】共 {len(qualified)} 个片段，来自 {len(doc_titles)} 个文档",
            "─────────────────────",
        ]

        for i, chunk in enumerate(qualified[:8]):
            doc_title = chunk.get("document_title", "Unknown")
            section = " > ".join(chunk.get("section_titles", []) or [])
            text = chunk.get("text", "")[:800]
            lines.append(f"\n▶ [{doc_title}]")
            if section:
                lines.append(f"  章节: {section}")
            lines.append(f"  {text}")

        return MessageFormatter.truncate_message("\n".join(lines), max_context_length)

    @staticmethod
    def format_candidate_facts_for_llm(candidate_facts: list[dict[str, Any]]) -> str:
        if not candidate_facts:
            return ""
        lines = ["【候选事实】", "这些事实由程序从检索证据中抽取，用于约束回答判断："]
        for index, fact in enumerate(candidate_facts[:12], start=1):
            lines.append(
                f"{index}. kind={fact.get('kind')} name={fact.get('name')} "
                f"purpose={fact.get('purpose')} source={fact.get('source')}"
            )
        return "\n".join(lines)

    @staticmethod
    def format_gap_report(result: dict[str, Any]) -> str:
        covered_count = result.get("covered_reference_item_count", 0)
        missing_count = result.get("missing_reference_item_count", 0)
        total = covered_count + missing_count
        coverage = f"{covered_count / total * 100:.1f}%" if total > 0 else "N/A"

        lines = [
            "【基线对比报告】",
            "",
            f"覆盖率: {coverage} ({covered_count}/{total})",
        ]

        covered = result.get("covered_items", [])
        if covered:
            lines.append("\n✅ 已覆盖:")
            for item in covered[:5]:
                lines.append(f"  ✓ {item}")

        missing = result.get("missing_items", [])
        if missing:
            lines.append("\n❌ 缺失:")
            for item in missing[:5]:
                lines.append(f"  ✗ {item}")

        return "\n".join(lines)

    @staticmethod
    def truncate_message(text: str, max_length: int = 3000) -> str:
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."

    @staticmethod
    def _compact_title(query: str, *, max_length: int = 60) -> str:
        normalized = MessageFormatter._clean_inline_text(query)
        return MessageFormatter.truncate_message(normalized or "知识库回答", max_length)

    @staticmethod
    def _clean_answer_text(text: str) -> str:
        lines = [line.strip() for line in text.strip().splitlines()]
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _clean_inline_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _escape_card_markdown(text: str) -> str:
        return str(text).replace("\\", "\\\\")

    @staticmethod
    def _format_source_text(source: str) -> str:
        source = MessageFormatter._clean_inline_text(source)
        source = re.sub(r"/\s*(\d{1,5})$", r"/ page \1", source)
        return source

    @staticmethod
    def _format_confidence_text(confidence: str) -> str:
        confidence = MessageFormatter._clean_inline_text(confidence)
        if "：" in confidence:
            level, reason = confidence.split("：", 1)
            return f"置信度：{level}｜{reason}"
        if ":" in confidence:
            level, reason = confidence.split(":", 1)
            return f"置信度：{level.strip()}｜{reason.strip()}"
        return f"置信度：{confidence}"

    @staticmethod
    def _details_section_title(answer_type: str) -> str:
        if answer_type == "solution_design":
            return "推荐方案"
        if answer_type in {"tool_lookup", "demo_lookup"}:
            return "怎么用这些工具"
        if answer_type == "api_usage":
            return "用法说明"
        if answer_type in {"concept", "troubleshooting", "how_to"}:
            return "关键说明"
        return "补充说明"

    @staticmethod
    def _append_solution_card_sections(
        *,
        add_hr: Any,
        add_markdown: Any,
        solution: dict[str, Any],
    ) -> None:
        recommended = str(solution.get("recommended") or "").strip()
        if recommended:
            add_hr()
            add_markdown(f"**推荐方案**\n{MessageFormatter._escape_card_markdown(recommended)}")

        def add_list_section(title: str, key: str) -> None:
            items = solution.get(key) or []
            if not items:
                return
            add_hr()
            lines = "\n".join(
                f"{index}. {MessageFormatter._escape_card_markdown(str(item))}"
                for index, item in enumerate(items, start=1)
            )
            add_markdown(f"**{title}**\n{lines}")

        add_list_section("实施步骤", "steps")
        add_list_section("可选方案", "variants")
        add_list_section("不推荐做法", "not_recommended")

        risks = list(solution.get("risks") or [])
        open_questions = list(solution.get("open_questions") or [])
        if risks or open_questions:
            add_hr()
            lines = []
            for item in risks:
                lines.append(f"- 风险：{MessageFormatter._escape_card_markdown(str(item))}")
            for item in open_questions:
                lines.append(f"- 待确认：{MessageFormatter._escape_card_markdown(str(item))}")
            add_markdown("**风险与待确认**\n" + "\n".join(lines))

    @staticmethod
    def _confidence_card_template(confidence: str) -> str:
        if confidence.startswith("高"):
            return "green"
        if confidence.startswith("中"):
            return "yellow"
        if confidence.startswith("低"):
            return "red"
        return "blue"

    @staticmethod
    def _collect_evidence_ids(reply: FormattedReply) -> list[str]:
        return [item["evidence_id"] for item in MessageFormatter._collect_evidence_refs(reply)]

    @staticmethod
    def _collect_evidence_refs(reply: FormattedReply) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for item in reply.evidence_items or []:
            label = str(item.get("name") or item.get("document_title") or "证据")
            supports = str(item.get("why_relevant") or item.get("summary") or "")
            for evidence_id in item.get("evidence_ids") or []:
                text = str(evidence_id)
                if text and all(ref["evidence_id"] != text for ref in refs):
                    refs.append(
                        {
                            "evidence_id": text,
                            "label": label,
                            "supports": supports,
                        }
                    )
        return refs

    @staticmethod
    def _extract_confidence(text: str) -> str:
        bracketed = re.search(r"【\s*置信度[:：]\s*([^】\n]+)】\s*(.*)$", text)
        if bracketed:
            level = bracketed.group(1).strip()
            reason = bracketed.group(2).strip()
            return f"{level}：{reason}" if reason else level
        match = re.search(r"【?置信度[:：]\s*([^】\n]+)】?", text)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _parse_answer_sections(answer_text: str) -> dict[str, Any]:
        section_aliases = {
            "结论": "summary",
            "直接结论": "summary",
            "关键依据": "evidence",
            "依据": "evidence",
            "证据": "evidence",
            "需要注意": "caveats",
            "注意事项": "caveats",
            "局限": "caveats",
            "限制": "caveats",
            "下一步建议": "next_steps",
            "下一步": "next_steps",
            "建议": "next_steps",
            "置信度": "confidence",
        }
        sections: dict[str, list[str]] = {
            "summary": [],
            "evidence": [],
            "caveats": [],
            "next_steps": [],
            "confidence": [],
        }
        current = "summary"

        for raw_line in answer_text.splitlines():
            line = MessageFormatter._strip_markdown(raw_line)
            if not line:
                continue
            inline_confidence = MessageFormatter._extract_confidence(line)
            if inline_confidence:
                sections["confidence"].append(inline_confidence)
                continue
            heading = MessageFormatter._normalize_section_heading(line)
            if heading in section_aliases:
                current = section_aliases[heading]
                continue
            sections[current].append(line)

        summary = MessageFormatter._clean_answer_text("\n".join(sections["summary"]))
        if not summary:
            summary = MessageFormatter._clean_answer_text(answer_text)

        evidence_items = [
            {
                "document_title": "参考资料",
                "location": "LLM 摘要",
                "summary": MessageFormatter._strip_list_marker(line),
                "evidence_ids": [],
            }
            for line in sections["evidence"]
            if MessageFormatter._strip_list_marker(line)
        ]
        caveats = [
            MessageFormatter._strip_list_marker(line)
            for line in sections["caveats"]
            if MessageFormatter._strip_list_marker(line)
        ]
        next_steps = [
            MessageFormatter._strip_list_marker(line)
            for line in sections["next_steps"]
            if MessageFormatter._strip_list_marker(line)
        ]
        confidence = sections["confidence"][-1] if sections["confidence"] else ""

        return {
            "summary": summary,
            "evidence_items": evidence_items,
            "caveats": caveats,
            "next_steps": next_steps,
            "confidence": confidence,
        }

    @staticmethod
    def _parse_answer_json(answer_text: str) -> FormattedReply | None:
        json_text = MessageFormatter._extract_json_object(answer_text)
        if json_text is None:
            return None
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None

        summary = MessageFormatter._clean_answer_text(str(payload.get("summary") or ""))
        if not summary:
            return None
        title = MessageFormatter._compact_title(str(payload.get("title") or "知识库回答"))
        title = MessageFormatter._polish_title(title)
        evidence_items = MessageFormatter._normalize_json_evidence_items(
            payload.get("evidence_items")
        )
        direct_answer = MessageFormatter._normalize_direct_answer(payload.get("direct_answer"))
        reply = FormattedReply(
            title=title,
            summary=MessageFormatter._polish_summary(summary),
            answer_type=MessageFormatter._normalize_answer_type(payload.get("answer_type")),
            direct_answer=direct_answer,
            details=MessageFormatter._normalize_detail_items(payload.get("details")),
            solution=MessageFormatter._normalize_solution(payload.get("solution")),
            key_points=MessageFormatter._polish_key_points(
                MessageFormatter._normalize_string_list(payload.get("key_points")),
                direct_answer=direct_answer,
                evidence_items=evidence_items,
            ),
            evidence_items=evidence_items,
            caveats=MessageFormatter._normalize_string_list(payload.get("caveats")),
            next_steps=MessageFormatter._polish_next_steps(
                MessageFormatter._normalize_string_list(payload.get("next_steps"))
            ),
            confidence=MessageFormatter._clean_inline_text(str(payload.get("confidence") or "")),
        )
        reply.plain_text = MessageFormatter.format_user_answer_text(reply)
        return reply

    @staticmethod
    def _extract_json_object(text: str) -> str | None:
        stripped = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
        if fenced:
            return fenced.group(1)
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return stripped[start : end + 1]

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for item in value:
            text = MessageFormatter._clean_inline_text(str(item))
            if text:
                items.append(text)
        return items

    @staticmethod
    def _normalize_answer_type(value: Any) -> str:
        text = MessageFormatter._clean_inline_text(str(value or "general"))
        allowed = {
            "tool_lookup",
            "demo_lookup",
            "how_to",
            "concept",
            "troubleshooting",
            "api_usage",
            "solution_design",
            "general",
        }
        return text if text in allowed else "general"

    @staticmethod
    def _normalize_detail_items(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        details: list[dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized: dict[str, str] = {}
            for key in ("name", "purpose", "usage", "when_to_use"):
                text = MessageFormatter._clean_inline_text(str(item.get(key) or ""))
                if text:
                    normalized[key] = text
            if normalized.get("name"):
                details.append(normalized)
        return details[:4]

    @staticmethod
    def _normalize_solution(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        normalized: dict[str, Any] = {}
        recommended = MessageFormatter._clean_inline_text(str(value.get("recommended") or ""))
        if recommended:
            normalized["recommended"] = recommended
        for key in ("steps", "variants", "not_recommended", "risks", "open_questions"):
            items = MessageFormatter._normalize_string_list(value.get(key))
            if items:
                normalized[key] = items
        return normalized or None

    @staticmethod
    def _normalize_direct_answer(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for key in ("tools", "demos"):
            text = MessageFormatter._clean_inline_text(str(value.get(key) or ""))
            if text:
                result[key] = text
        return result

    @staticmethod
    def _normalize_json_evidence_items(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            summary = MessageFormatter._clean_inline_text(
                str(item.get("why_relevant") or item.get("summary") or "")
            )
            if not summary:
                continue
            evidence_ids = item.get("evidence_ids")
            if not isinstance(evidence_ids, list):
                evidence_ids = []
            name = str(item.get("name") or item.get("document_title") or "参考资料")
            source = str(item.get("source") or item.get("location") or "LLM 摘要")
            items.append(
                {
                    "name": name,
                    "source": source,
                    "document_title": name,
                    "location": source,
                    "why_relevant": summary,
                    "summary": summary,
                    "evidence_ids": [str(evidence_id) for evidence_id in evidence_ids],
                }
            )
        return items

    @staticmethod
    def _normalize_section_heading(line: str) -> str:
        heading = line.strip().strip("：:")
        heading = re.sub(r"^[#>\-\s]+", "", heading).strip().strip("：:")
        return heading

    @staticmethod
    def _strip_markdown(line: str) -> str:
        text = line.strip()
        text = re.sub(r"^\*\*(.+)\*\*$", r"\1", text)
        text = re.sub(r"^__(.+)__$", r"\1", text)
        return text.strip()

    @staticmethod
    def _strip_list_marker(line: str) -> str:
        return re.sub(r"^(?:[-*•]\s*|\d+[.)、]\s*)", "", line.strip()).strip()

    @staticmethod
    def _polish_title(title: str) -> str:
        lowered = title.lower()
        if (
            "渲染" in title
            and "调试" in title
            and ("demo" in lowered or "工具" in title)
        ):
            return "QNX 渲染调试工具查询结果"
        return title

    @staticmethod
    def _polish_summary(summary: str) -> str:
        sentences = re.split(r"(?<=[。！？])", summary)
        kept = []
        for sentence in sentences:
            text = sentence.strip()
            if not text:
                continue
            lowered = text.lower()
            if any(token in lowered for token in ("gdb", "system profiler", "ide")):
                continue
            kept.append(text)
        return "".join(kept).strip() or summary

    @staticmethod
    def _polish_key_points(
        key_points: list[str],
        *,
        direct_answer: dict[str, str],
        evidence_items: list[dict[str, Any]],
    ) -> list[str]:
        evidence_terms = " ".join(
            str(item.get("name") or item.get("summary") or item.get("why_relevant") or "")
            for item in evidence_items
        ).lower()
        polished: list[str] = []
        for point in key_points:
            lowered = point.lower()
            if any(token in lowered for token in ("gdb", "system profiler", "ide users guide")):
                continue
            # Avoid repeating evidence names as generic key points.
            if evidence_terms and any(
                term in evidence_terms
                for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", lowered)
            ):
                if "demo" not in lowered and "指南" not in point and "章节" not in point:
                    continue
            polished.append(point)
            if len(polished) >= 2:
                break
        if not polished and direct_answer:
            for key in ("tools", "demos"):
                value = direct_answer.get(key)
                if value:
                    polished.append(value)
                if len(polished) >= 2:
                    break
        return polished

    @staticmethod
    def _polish_next_steps(next_steps: list[str]) -> list[str]:
        polished: list[str] = []
        for step in next_steps:
            lowered = step.lower()
            if "ide users guide" in lowered or "gdb" in lowered:
                continue
            polished.append(step)
            if len(polished) >= 3:
                break
        return polished


class KnowledgeQueryResponder:
    """Shared knowledge-answer pipeline used by Feishu entrypoints."""

    def __init__(
        self,
        *,
        config: FeishuConfig,
        local_api: LocalAPIClient,
        formatter: MessageFormatter,
        llm_agent: LLMAgent,
    ) -> None:
        self.config = config
        self.local_api = local_api
        self.formatter = formatter
        self.llm_agent = llm_agent

    def process_query(
        self,
        query: str,
        *,
        search_query: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> BotReplyResult:
        effective_search_query = search_query or query
        if self.llm_agent.is_chitchat(query):
            reply = self.llm_agent.direct_reply(query)
            reply = self.formatter.truncate_message(reply, self.config.max_reply_length)
            return BotReplyResult(text=reply, search_query=effective_search_query)

        context_pack = self.local_api.get_context_pack(
            processed_dir=self.config.processed_dir,
            query=effective_search_query,
            top_k=self.config.default_top_k,
            per_document_limit=self.config.default_per_document_limit,
            fts_index_path=self.config.fts_index_path or None,
            vector_index_path=self.config.vector_index_path or None,
        )
        score_threshold = self.config.score_threshold
        selected_chunks = context_pack.get("selected_chunks", [])
        has_evidence = bool(selected_chunks) and (
            max((chunk.get("score", float("-inf")) for chunk in selected_chunks), default=float("-inf"))
            >= score_threshold
        )
        if not has_evidence:
            reply = self.llm_agent.no_evidence_reply(query)
            reply = self.formatter.truncate_message(reply, self.config.max_reply_length)
            return BotReplyResult(
                text=reply,
                search_query=effective_search_query,
                has_evidence=False,
                context_pack=context_pack,
            )

        context_pack_text = self.formatter.format_context_pack(context_pack, score_threshold)
        reply = self.llm_agent.synthesize(query, context_pack_text, history=history or None)
        reply = self.formatter.truncate_message(reply, self.config.max_reply_length)
        formatted_reply = self.formatter.build_user_reply(
            query=query,
            answer_text=reply,
            context_pack=context_pack,
        )
        return BotReplyResult(
            text=reply,
            search_query=effective_search_query,
            has_evidence=True,
            formatted_reply=formatted_reply,
            context_pack=context_pack,
        )



class FeishuAPI:
    def __init__(self, config: FeishuConfig):
        self.config = config
        self.token_manager = FeishuTokenManager(config)

    def send_text_message(self, chat_id: str, text: str) -> None:
        token = self.token_manager.get_token()
        url = f"{self.config.api_base}/message/v4/send/"

        resp = _http_post(
            url,
            {
                "chat_id": chat_id,
                "msg_type": "text",
                "content": {"text": text},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        code = resp.get("code", -1)
        if code != 0:
            logger.error(
                "发送消息失败: chat_id=%s, code=%s, msg=%s, resp=%s",
                chat_id, code, resp.get("msg", ""), json.dumps(resp, ensure_ascii=False)[:300],
            )
        else:
            logger.info("消息已发送到chat_id=%s", chat_id)

    def send_card_message(self, chat_id: str, reply: FormattedReply) -> bool:
        token = self.token_manager.get_token()
        url = f"{self.config.api_base}/message/v4/send/"
        resp = _http_post(
            url,
            {
                "chat_id": chat_id,
                "msg_type": "interactive",
                "card": MessageFormatter.format_user_answer_card(reply),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        code = resp.get("code", -1)
        if code != 0:
            logger.warning(
                "发送卡片消息失败: chat_id=%s, code=%s, msg=%s",
                chat_id,
                code,
                resp.get("msg", ""),
            )
            return False
        logger.info("卡片消息已发送到chat_id=%s", chat_id)
        return True

    def send_rich_text_message(self, chat_id: str, reply: FormattedReply) -> bool:
        token = self.token_manager.get_token()
        url = f"{self.config.api_base}/message/v4/send/"
        resp = _http_post(
            url,
            {
                "chat_id": chat_id,
                "msg_type": "post",
                "content": MessageFormatter.format_user_answer_post(reply),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        code = resp.get("code", -1)
        if code != 0:
            logger.warning(
                "发送富文本消息失败: chat_id=%s, code=%s, msg=%s",
                chat_id,
                code,
                resp.get("msg", ""),
            )
            return False
        logger.info("富文本消息已发送到chat_id=%s", chat_id)
        return True

    def send_reply_message(self, chat_id: str, reply: FormattedReply) -> None:
        try:
            if self.send_card_message(chat_id, reply):
                return
        except Exception:
            logger.warning("发送卡片消息异常，降级为富文本消息", exc_info=True)
        try:
            if self.send_rich_text_message(chat_id, reply):
                return
        except Exception:
            logger.warning("发送富文本消息异常，降级为文本消息", exc_info=True)
        fallback = reply.plain_text or MessageFormatter.format_user_answer_text(reply)
        self.send_text_message(chat_id, fallback)


class FeishuMessageHandler:
    def __init__(self, config: FeishuConfig | None = None):
        self.config = config or FeishuConfig.from_env()
        self.local_api = LocalAPIClient(self.config.local_api_base)
        self.feishu_api = FeishuAPI(self.config)
        self.formatter = MessageFormatter()
        self.llm_agent = LLMAgent.from_env()
        self.responder = KnowledgeQueryResponder(
            config=self.config,
            local_api=self.local_api,
            formatter=self.formatter,
            llm_agent=self.llm_agent,
        )

    def handle_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        if event_data.get("type") == "url_verification":
            return {"challenge": event_data.get("challenge", "")}

        header = event_data.get("header", {})
        event_type = header.get("event_type", "")

        if event_type == "im.message.receive_v1":
            event = event_data.get("event", {})
            self._handle_message(event)
            return {"code": 0, "msg": "ok"}

        return {"code": 0, "msg": "ignored"}

    def _handle_message(self, event: dict[str, Any]) -> None:
        try:
            message = event.get("message", {})
            content_str = message.get("content", "{}")
            content = json.loads(content_str)
            text = content.get("text", "")

            text = self._filter_mentions(text)
            if not text:
                return

            chat_id = event.get("sender", {}).get("chat_id", "")
            self._process_query(chat_id, text)

        except Exception:
            logger.exception("处理消息事件失败")

    def _process_query(self, chat_id: str, query: str) -> None:
        try:
            result = self.responder.process_query(query)
            if result.formatted_reply is not None:
                self.feishu_api.send_reply_message(chat_id, result.formatted_reply)
            else:
                self.feishu_api.send_text_message(chat_id, result.text)

        except Exception:
            logger.exception("处理用户查询失败")
            self.feishu_api.send_text_message(chat_id, "处理查询时出错")

    @staticmethod
    def _assemble_reply(context_pack_text: str, gap_report_text: str) -> str:
        return assemble_reply(context_pack_text, gap_report_text)

    @staticmethod
    def _filter_mentions(text: str) -> str:
        return filter_mentions(text)


def assemble_reply(context_pack_text: str, gap_report_text: str) -> str:
    parts = [context_pack_text]
    if gap_report_text:
        parts.append("\n" + "═" * 30 + "\n")
        parts.append(gap_report_text)
    return "\n".join(parts)


def filter_mentions(text: str) -> str:
    return re.sub(r"@_?\S+\s?", "", text).strip()
