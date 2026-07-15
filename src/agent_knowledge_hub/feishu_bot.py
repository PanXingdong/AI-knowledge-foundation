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
    def build_vsync_screenshot_demo_reply() -> FormattedReply:
        reply = FormattedReply(
            title="Screen vsync 订阅与帧率统计",
            summary=(
                "Screen 文档没有提供明确的 vsync 异步订阅接口。更稳妥的做法是使用 "
                "screen_wait_vsync() 同步等待下一次 vsync，并把它放在独立线程中循环调用，"
                "通过时间戳或计数统计帧率。"
            ),
            answer_type="solution_design",
            solution={
                "recommended": (
                    "使用独立统计线程调用 screen_wait_vsync(display)。每次函数返回后记录时间戳，"
                    "计算相邻两次返回之间的时间差，或者按固定时间窗口统计返回次数，从而得到实际刷新频率。"
                ),
                "steps": [
                    "获取目标显示器的 screen_display_t。",
                    "创建独立统计线程，避免阻塞 UI 或主渲染线程。",
                    "在线程中循环调用 screen_wait_vsync(display)。",
                    "每次返回后记录单调时钟时间戳。",
                    "根据相邻时间戳计算帧间隔，或按秒统计返回次数得到 FPS。",
                    "将统计结果通过日志、共享状态或调试接口输出。",
                ],
                "risks": [
                    "screen_wait_vsync() 是阻塞调用，不应放在 UI 线程或主渲染线程。",
                    "当前资料未发现明确的 vsync 事件订阅接口。",
                    "Screen 的异步通知可用于 post/composition 相关事件，但不能直接等同于每个 vsync。",
                    "实际唤醒频率建议在目标硬件上验证，确认是否与显示刷新率一致。",
                ],
            },
            evidence_items=[
                {
                    "name": "screen_wait_vsync()",
                    "source": "QNX SDP 7.1 Screen Graphics Subsystem Developers Guide / Screen library reference > Displays (screen.h) / p.560",
                    "why_relevant": "文档明确说明该函数会阻塞调用线程，直到指定 display 的下一次 vsync 发生，是做帧率统计的核心依据。",
                    "evidence_ids": [],
                },
                {
                    "name": "Asynchronous Notifications",
                    "source": "QNX SDP 7.1 Screen Graphics Subsystem Developers Guide / Asynchronous Notifications / p.161-162",
                    "why_relevant": "文档说明 Screen 有异步通知机制，但没有给出明确的 vsync 专用事件，因此不能把它当成直接订阅 vsync 的证据。",
                    "evidence_ids": [],
                },
            ],
            caveats=[
                "screen_wait_vsync() 是同步等待，不是事件订阅。",
                "如果需要非阻塞统计，应通过独立线程封装。",
                "不建议用 Camera API 或硬件寄存器替代 Screen 层的 vsync 统计。",
            ],
            confidence="高：screen_wait_vsync() 的 API 定义有直接文档证据；独立线程统计 FPS 是基于该同步等待机制的工程实现建议。",
        )
        reply.plain_text = MessageFormatter.format_user_answer_text(reply)
        return reply

    @staticmethod
    def classify_query_intent(
        query: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        normalized = query.strip().lower()
        if MessageFormatter._is_missing_context_followup(normalized, history):
            return "missing_context"
        if MessageFormatter._is_out_of_scope_request(normalized):
            return "out_of_scope"
        return "in_scope"

    @staticmethod
    def _is_missing_context_followup(
        normalized_query: str,
        history: list[dict[str, str]] | None,
    ) -> bool:
        markers = ("接上", "刚才", "上一个", "上面", "这个方案", "那这个", "那刚")
        if not any(marker in normalized_query for marker in markers):
            return False
        return not history

    @staticmethod
    def _is_out_of_scope_request(normalized_query: str) -> bool:
        if "天气" in normalized_query:
            return True
        frontend_terms = ("react", "vue", "前端", "页面", "websocket", "node.js")
        build_terms = ("帮我写", "写个", "写一个", "实现", "代码")
        qnx_log_terms = ("qnx", "日志", "slog")
        asks_frontend_build = any(term in normalized_query for term in frontend_terms) and any(
            term in normalized_query for term in build_terms
        )
        if asks_frontend_build and any(term in normalized_query for term in qnx_log_terms):
            return True
        return False

    @staticmethod
    def boundary_reply(intent: str) -> str:
        if intent == "missing_context":
            return "这条问题依赖上文，但当前没有足够的上文方案可引用。请把上一轮方案或要延续的具体内容贴出来，我再基于它继续分析。"
        if intent == "out_of_scope":
            return (
                "这个请求超出 QNX 知识库的回答范围。我可以继续帮你分析 QNX 侧的日志采集、"
                "slog2、PPS/资源管理器或系统服务接口，但不会编写前端页面、天气查询或其他非 QNX 实现。"
            )
        return ""

    @staticmethod
    def build_user_reply(
        *,
        query: str,
        answer_text: str,
        context_pack: dict[str, Any],
        max_evidence_items: int = 3,
    ) -> FormattedReply:
        candidate_facts = MessageFormatter.extract_candidate_facts(context_pack)
        retrieved_evidence_items = MessageFormatter.extract_evidence_summary(
            context_pack,
            max_items=max_evidence_items,
            query=query,
            answer_text=answer_text,
        )
        parsed_json = MessageFormatter._parse_answer_json(answer_text)
        if parsed_json is not None:
            MessageFormatter._force_solution_design_if_needed(parsed_json, query)
            MessageFormatter._apply_candidate_fact_consistency(parsed_json, candidate_facts)
            MessageFormatter._polish_title_for_query(parsed_json, query)
            retrieved_evidence_items = MessageFormatter.extract_evidence_summary(
                context_pack,
                max_items=max_evidence_items,
                query=query,
                answer_text=MessageFormatter._reply_evidence_ranking_text(parsed_json),
            )
            if not parsed_json.evidence_items:
                parsed_json.evidence_items = retrieved_evidence_items
            MessageFormatter._bind_evidence_to_retrieved_context(
                parsed_json,
                retrieved_evidence_items,
            )
            MessageFormatter._apply_support_guardrails(parsed_json, context_pack)
            MessageFormatter._dedupe_solution_echo(parsed_json)
            parsed_json.plain_text = MessageFormatter.format_user_answer_text(parsed_json)
            return parsed_json
        if MessageFormatter._looks_like_malformed_json(answer_text):
            reply = MessageFormatter._build_malformed_json_fallback(query)
            MessageFormatter._apply_candidate_fact_consistency(reply, candidate_facts)
            MessageFormatter._force_solution_design_if_needed(reply, query)
            MessageFormatter._polish_title_for_query(reply, query)
            if not reply.evidence_items:
                reply.evidence_items = retrieved_evidence_items
            MessageFormatter._bind_evidence_to_retrieved_context(
                reply,
                retrieved_evidence_items,
            )
            MessageFormatter._apply_support_guardrails(reply, context_pack)
            MessageFormatter._dedupe_solution_echo(reply)
            reply.plain_text = MessageFormatter.format_user_answer_text(reply)
            return reply

        title = MessageFormatter._compact_title(query)
        parsed = MessageFormatter._parse_answer_sections(answer_text)
        summary = parsed["summary"]
        evidence_items = parsed["evidence_items"] or retrieved_evidence_items
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
        MessageFormatter._force_solution_design_if_needed(reply, query)
        MessageFormatter._polish_title_for_query(reply, query)
        MessageFormatter._sanitize_visible_reply_text(reply)
        MessageFormatter._bind_evidence_to_retrieved_context(
            reply,
            retrieved_evidence_items,
        )
        MessageFormatter._apply_support_guardrails(reply, context_pack)
        MessageFormatter._dedupe_solution_echo(reply)
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
        if reply.answer_type in {"tool_lookup", "demo_lookup"}:
            if tool_facts and MessageFormatter._answer_says_unknown(direct_answer.get("tools", "")):
                names = ", ".join(fact["name"] for fact in tool_facts[:6])
                direct_answer["tools"] = f"有，检索证据明确提到 {names} 等调试工具/能力。"
            if demo_facts and MessageFormatter._answer_says_unknown(direct_answer.get("demos", "")):
                names = ", ".join(fact["name"] for fact in demo_facts[:4])
                direct_answer["demos"] = f"有，检索证据明确提到 {names} 等渲染/显示示例。"
        if direct_answer:
            reply.direct_answer = direct_answer

        existing_detail_names = {str(item.get("name") or "") for item in (reply.details or [])}
        if reply.answer_type in {"tool_lookup", "demo_lookup"}:
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
    def _polish_title_for_query(reply: FormattedReply, query: str) -> None:
        if reply.title != "QNX 渲染调试工具查询结果":
            return
        if reply.answer_type in {"tool_lookup", "demo_lookup"}:
            return
        direct_answer = reply.direct_answer or {}
        if direct_answer.get("tools") or direct_answer.get("demos"):
            return
        if "工具" in query or "demo" in query.lower():
            return
        reply.title = MessageFormatter._compact_title(query)

    @staticmethod
    def _answer_says_unknown(value: str) -> bool:
        normalized = value.strip().lower()
        if not normalized:
            return True
        return any(token in normalized for token in ("不确定", "未发现", "没有找到", "unknown"))

    @staticmethod
    def _force_solution_design_if_needed(reply: FormattedReply, query: str) -> None:
        if not MessageFormatter._looks_like_solution_query(query):
            return
        if reply.answer_type == "solution_design" and reply.solution:
            return
        reply.answer_type = "solution_design"
        caveats = list(reply.caveats or [])
        details = list(reply.details or [])
        recommended = reply.summary
        if reply.direct_answer:
            parts = []
            for key, label in (("tools", "工具"), ("demos", "Demo")):
                value = reply.direct_answer.get(key)
                if value and not MessageFormatter._answer_says_unknown(value):
                    parts.append(f"{label}：{value}")
            if parts:
                recommended = "；".join(parts)
        steps = [
            f"{item.get('name')}: {item.get('usage') or item.get('purpose')}"
            for item in details[:3]
            if item.get("name")
        ]
        not_recommended = []
        risks = []
        if MessageFormatter._looks_like_zero_copy_query(query):
            not_recommended.append("memcpy fallback 不是真零拷贝。")
            risks.append("需要确认目标平台是否支持 buffer handle export/import 或等价共享机制。")
            risks.append("不能把 SCREEN_PROPERTY_POINTER 返回的进程内虚拟地址直接跨进程使用。")
        for caveat in caveats:
            if "危险" in caveat or "不能" in caveat or "不应" in caveat:
                not_recommended.append(caveat)
            else:
                risks.append(caveat)
        reply.solution = {
            "recommended": recommended,
            "steps": steps or ["先确认文档和平台是否提供可跨进程共享的 buffer handle/import 机制。"],
            "variants": [
                "若无原生 buffer 共享机制，可退化为 POSIX shared memory 近似共享方案，但需明确这不等同于 Screen 原生 buffer 真零拷贝。"
            ] if MessageFormatter._looks_like_zero_copy_query(query) else [],
            "not_recommended": list(dict.fromkeys(not_recommended)),
            "risks": list(dict.fromkeys(risks)),
            "open_questions": ["目标 BSP/驱动是否支持对应 buffer 共享能力。"] if MessageFormatter._looks_like_zero_copy_query(query) else [],
        }
        reply.direct_answer = None
        reply.key_points = []

    @staticmethod
    def _looks_like_solution_query(query: str) -> bool:
        normalized = query.lower()
        if any(
            token in normalized
            for token in (
                "方案",
                "架构",
                "最佳实践",
                "怎么实现",
                "如何实现",
                "给一个",
                "给我一个",
                "有没有办法",
                "zero-copy",
                "零copy",
                "零拷贝",
            )
        ):
            return True
        if "demo" in normalized:
            return any(token in normalized for token in ("给demo", "给 demo", "调用demo", "调用 demo", "demo代码", "demo 代码"))
        return False

    @staticmethod
    def _looks_like_zero_copy_query(query: str) -> bool:
        normalized = query.lower()
        return any(token in normalized for token in ("zero-copy", "零copy", "零拷贝", "dma-buf", "screen buffer"))

    @staticmethod
    def extract_evidence_summary(
        context_pack: dict[str, Any],
        *,
        max_items: int = 3,
        max_summary_chars: int = 160,
        query: str = "",
        answer_text: str = "",
    ) -> list[dict[str, Any]]:
        def build_candidates(*, require_core_or_query_hit: bool) -> list[tuple[float, int, bool, dict[str, Any]]]:
            candidates: list[tuple[float, int, bool, dict[str, Any]]] = []
            for index, chunk in enumerate(selected_chunks):
                raw_text = str(chunk.get("text") or "")
                text = MessageFormatter._clean_inline_text(raw_text)
                if not text:
                    continue
                section = " > ".join(str(item) for item in (chunk.get("section_titles") or []) if item)
                if MessageFormatter._is_generic_debug_noise_evidence(
                    query=query,
                    document_title=str(chunk.get("document_title") or ""),
                    section=section,
                    text=text,
                ):
                    continue
                haystack = f"{chunk.get('document_title') or ''} {section} {text}".lower()
                core_hit = any(term.lower() in haystack for term in core_terms)
                strong_query_hit = any(term in haystack for term in strong_query_terms)
                is_title_fragment = MessageFormatter._looks_like_title_fragment(text)
                is_toc_fragment = MessageFormatter._looks_like_toc_evidence(section, text)
                if require_core_or_query_hit and core_terms and not core_hit and not strong_query_hit:
                    continue
                page = chunk.get("page_start")
                location_parts = []
                if section:
                    location_parts.append(section)
                if page is not None:
                    location_parts.append(f"page {page}")
                evidence_ids = MessageFormatter._rank_evidence_ids_for_display(
                    text,
                    [str(item) for item in (chunk.get("evidence_ids") or [])],
                )
                item = {
                    "document_title": str(chunk.get("document_title") or "Unknown"),
                    "location": " / ".join(location_parts) or "source chunk",
                    "summary": MessageFormatter.truncate_message(
                        MessageFormatter._best_evidence_summary_text(raw_text),
                        max_summary_chars,
                    ),
                    "evidence_ids": evidence_ids,
                }
                score = MessageFormatter._evidence_display_score(
                    text=text,
                    section=section,
                    core_hit=core_hit,
                    strong_query_hit=strong_query_hit,
                    is_title_fragment=is_title_fragment,
                    is_toc_fragment=is_toc_fragment,
                    original_score=float(chunk.get("score") or 0.0),
                )
                candidates.append((score, index, is_toc_fragment, item))
            return candidates

        candidates: list[tuple[float, int, bool, dict[str, Any]]] = []
        selected_chunks = context_pack.get("selected_chunks", [])
        core_terms = MessageFormatter._extract_core_evidence_terms(f"{query} {answer_text}")
        strong_query_terms = MessageFormatter._extract_strong_query_terms(query)
        candidates = build_candidates(require_core_or_query_hit=True)
        if not candidates:
            candidates = build_candidates(require_core_or_query_hit=False)
        if any(not is_toc for _, _, is_toc, _ in candidates):
            candidates = [entry for entry in candidates if not entry[2]]
        candidates.sort(key=lambda entry: (-entry[0], entry[1]))
        return [item for _, _, _, item in candidates[:max_items]]

    @staticmethod
    def _reply_evidence_ranking_text(reply: FormattedReply) -> str:
        parts = [reply.title, reply.summary]
        if reply.direct_answer:
            parts.extend(reply.direct_answer.values())
        for item in reply.details or []:
            parts.extend(str(item.get(key) or "") for key in ("name", "purpose", "usage"))
        if reply.solution:
            parts.append(str(reply.solution.get("recommended") or ""))
            for key in ("steps", "variants", "not_recommended", "risks", "open_questions"):
                parts.extend(str(item) for item in (reply.solution.get(key) or []))
        return " ".join(parts)

    @staticmethod
    def _extract_core_evidence_terms(text: str) -> list[str]:
        terms = []
        for term in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\s*(?=\()", text):
            terms.append(term.strip())
        for term in re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", text):
            terms.append(term.strip())
        ignored = {"int", "void", "return", "sizeof"}
        return [
            term
            for term in dict.fromkeys(terms)
            if term.lower() not in ignored
        ][:12]

    @staticmethod
    def _extract_strong_query_terms(query: str) -> list[str]:
        terms = []
        for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", query.lower()):
            if term not in {"screen", "qnx", "demo", "buffer"}:
                terms.append(term)
        return list(dict.fromkeys(terms))

    @staticmethod
    def _looks_like_title_fragment(text: str) -> bool:
        normalized = MessageFormatter._clean_inline_text(text)
        if not normalized:
            return True
        if len(normalized) <= 64 and not re.search(r"[。.!?;；:：]", normalized):
            return True
        if len(normalized.split()) <= 5 and not re.search(r"[。.!?;；]", normalized):
            return True
        return False

    @staticmethod
    def _looks_like_toc_evidence(section: str, text: str) -> bool:
        normalized = MessageFormatter._clean_inline_text(f"{section} {text}")
        if not normalized:
            return False
        toc_markers = (
            "This table may help you find what you need",
            "Go to:To find out about",
            "Before you beginWhat you need",
            "Getting the source codeHow to get the source code",
            "How to set timing parameters",
            "How to update your target",
        )
        marker_hits = sum(1 for marker in toc_markers if marker in normalized)
        return marker_hits >= 2

    @staticmethod
    def _best_evidence_summary_text(text: str) -> str:
        paragraphs = [
            MessageFormatter._clean_inline_text(paragraph)
            for paragraph in re.split(r"\n\s*\n", text)
            if MessageFormatter._clean_inline_text(paragraph)
        ]
        for paragraph in paragraphs:
            if MessageFormatter._looks_like_title_fragment(paragraph):
                continue
            if MessageFormatter._looks_like_numeric_table_fragment(paragraph):
                continue
            if len(paragraph) >= 40:
                return paragraph
        return paragraphs[0] if paragraphs else ""

    @staticmethod
    def _looks_like_numeric_table_fragment(text: str) -> bool:
        normalized = MessageFormatter._clean_inline_text(text)
        if not normalized:
            return False
        digit_count = sum(char.isdigit() for char in normalized)
        alpha_count = sum(char.isalpha() for char in normalized)
        long_digit_run = re.search(r"\d{12,}", normalized) is not None
        return long_digit_run and digit_count >= 20

    @staticmethod
    def _rank_evidence_ids_for_display(text: str, evidence_ids: list[str]) -> list[str]:
        unique_ids = [item for item in dict.fromkeys(evidence_ids) if item]
        if len(unique_ids) <= 1:
            return unique_ids
        if MessageFormatter._looks_like_title_fragment(text):
            return unique_ids[:1]
        if len(text) > 120:
            return [unique_ids[-1]]
        first_line = text.splitlines()[0] if text.splitlines() else text
        if MessageFormatter._looks_like_title_fragment(first_line) and len(text) > len(first_line) + 40:
            return [unique_ids[-1]]
        return unique_ids[:1]

    @staticmethod
    def _evidence_display_score(
        *,
        text: str,
        section: str,
        core_hit: bool,
        strong_query_hit: bool,
        is_title_fragment: bool,
        is_toc_fragment: bool,
        original_score: float,
    ) -> float:
        score = original_score
        if core_hit:
            score += 100.0
        if strong_query_hit:
            score += 25.0
        if is_title_fragment:
            score -= 80.0
        if is_toc_fragment:
            score -= 160.0
        if len(text) >= 80:
            score += 8.0
        if section and MessageFormatter._looks_like_title_fragment(section):
            score -= 5.0
        return score

    @staticmethod
    def _is_generic_debug_noise_evidence(
        *,
        query: str,
        document_title: str,
        section: str,
        text: str,
    ) -> bool:
        normalized_query = query.lower()
        if not any(
            token in normalized_query
            for token in ("渲染", "显示", "render", "display", "screen", "graphics")
        ):
            return False
        haystack = f"{document_title} {section} {text}".lower()
        generic_debug_terms = ("gdb", "ide", "debug tab", "launch configuration", "system profiler")
        render_terms = (
            "screen",
            "render",
            "display",
            "graphics",
            "gltrace",
            "screeninfo",
            "screencmd",
            "gles",
            "surface",
        )
        return any(term in haystack for term in generic_debug_terms) and not any(
            term in haystack for term in render_terms
        )

    @staticmethod
    def _bind_evidence_to_retrieved_context(
        reply: FormattedReply,
        retrieved_evidence_items: list[dict[str, Any]],
    ) -> None:
        # Evidence traceability is a retrieval invariant: ids must come from the
        # selected Context Pack chunks, never from model-generated JSON.
        if retrieved_evidence_items:
            reply.evidence_items = MessageFormatter._trusted_retrieved_evidence_items(
                retrieved_evidence_items
            )
        else:
            for item in reply.evidence_items or []:
                item["evidence_ids"] = []
        MessageFormatter._downgrade_high_confidence_without_evidence_refs(reply)

    @staticmethod
    def _downgrade_high_confidence_without_evidence_refs(reply: FormattedReply) -> None:
        if MessageFormatter._collect_evidence_refs(reply):
            return
        confidence = MessageFormatter._clean_inline_text(reply.confidence)
        if confidence.startswith("高"):
            reply.confidence = "中：未绑定到可追溯证据，需查看检索结果确认。"

    @staticmethod
    def _trusted_retrieved_evidence_items(
        retrieved_evidence_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        trusted_items: list[dict[str, Any]] = []
        for item in retrieved_evidence_items:
            trusted_item = dict(item)
            trusted_item["evidence_ids"] = [
                str(evidence_id)
                for evidence_id in dict.fromkeys(item.get("evidence_ids") or [])
                if str(evidence_id)
            ]
            trusted_items.append(trusted_item)
        return trusted_items

    @staticmethod
    def format_user_answer_text(reply: FormattedReply, *, max_length: int = 3000) -> str:
        lines = [reply.title.strip() or "知识库回答"]
        direct_answer = reply.direct_answer or {}
        if direct_answer:
            lines.extend(["", "结论"])
            for label, value in MessageFormatter._direct_answer_items(reply):
                lines.append(f"{label}：{value}")
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
        return MessageFormatter.format_detail_card(reply)

    @staticmethod
    def format_detail_card(reply: FormattedReply) -> dict[str, Any]:
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
            for label, value in MessageFormatter._direct_answer_items(reply):
                answer_lines.append(f"**{label}：**{MessageFormatter._escape_card_markdown(value)}")
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
    def format_summary_card(reply: FormattedReply, *, reply_id: str | None = None) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []

        def add_markdown(content: str) -> None:
            content = content.strip()
            if content:
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})

        summary_lines = []
        for label, value in MessageFormatter._direct_answer_items(reply):
            summary_lines.append(f"**{label}：**{MessageFormatter._escape_card_markdown(value)}")
        if not summary_lines:
            summary_lines.append(MessageFormatter._escape_card_markdown(reply.summary))
        add_markdown("**结论**\n" + "\n".join(summary_lines[:3]))

        evidence_items = (reply.evidence_items or [])[:2]
        if evidence_items:
            evidence_lines = []
            for index, item in enumerate(evidence_items, start=1):
                title = item.get("name") or item.get("document_title") or "参考资料"
                source = item.get("source") or item.get("location") or "source chunk"
                evidence_lines.append(
                    f"{index}. **{MessageFormatter._escape_card_markdown(str(title))}** — "
                    f"{MessageFormatter._escape_card_markdown(MessageFormatter._format_source_text(str(source)))}"
                )
            elements.append({"tag": "hr"})
            add_markdown("**依据摘要**\n" + "\n".join(evidence_lines))

        if MessageFormatter._should_show_confidence_note(reply.confidence):
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

        actions = []
        if reply_id:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看详细回答"},
                    "type": "default",
                    "value": {"action": "show_detail_answer", "reply_id": reply_id},
                }
            )
        evidence_refs = MessageFormatter._collect_evidence_refs(reply)
        if evidence_refs:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "查看完整证据"},
                    "type": "default",
                    "value": {
                        "action": "show_full_evidence",
                        "evidence_ids": [item["evidence_id"] for item in evidence_refs[:6]],
                        "evidence_refs": evidence_refs[:6],
                    },
                }
            )
        if actions:
            elements.append({"tag": "action", "actions": actions})

        return {
            "config": {"wide_screen_mode": True, "enable_forward": True},
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
    def _should_show_confidence_note(confidence: str) -> bool:
        confidence = MessageFormatter._clean_inline_text(confidence)
        if not confidence:
            return False
        return not confidence.startswith("高")

    @staticmethod
    def _details_section_title(answer_type: str) -> str:
        if answer_type == "solution_design":
            return "推荐方案"
        if answer_type in {"tool_lookup", "demo_lookup"}:
            return "关键说明"
        if answer_type == "api_usage":
            return "用法说明"
        if answer_type in {"concept", "troubleshooting", "how_to"}:
            return "关键说明"
        return "补充说明"

    @staticmethod
    def _direct_answer_items(reply: FormattedReply) -> list[tuple[str, str]]:
        direct_answer = reply.direct_answer or {}
        if reply.answer_type == "solution_design":
            return []
        if reply.answer_type == "api_usage":
            mapping = (("primary", "含义"), ("secondary", "优化作用"))
        elif reply.answer_type in {"tool_lookup", "demo_lookup"}:
            mapping = (
                ("primary", "答案"),
                ("tools", "答案"),
                ("secondary", "补充"),
                ("demos", "补充"),
            )
        else:
            mapping = (("primary", "答案"), ("secondary", "补充"))
        items: list[tuple[str, str]] = []
        used_labels: set[str] = set()
        for key, label in mapping:
            value = direct_answer.get(key)
            if value and label not in used_labels:
                items.append((label, value))
                used_labels.add(label)
        if not items and reply.answer_type not in {"tool_lookup", "demo_lookup"}:
            for key, value in direct_answer.items():
                if value:
                    items.append((key, value))
        return items

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
        MessageFormatter._sanitize_visible_reply_text(reply)
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
    def _looks_like_truncated_json(text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith("{") and stripped.count("{") > stripped.count("}")

    @staticmethod
    def _looks_like_malformed_json(text: str) -> bool:
        stripped = text.strip()
        if MessageFormatter._looks_like_truncated_json(stripped):
            return True
        if not stripped.startswith("{"):
            return False
        return any(token in stripped for token in ('"title"', '"summary"', '"answer_type"'))

    @staticmethod
    def _build_malformed_json_fallback(query: str) -> FormattedReply:
        reply = FormattedReply(
            title=MessageFormatter._compact_title(query),
            summary="模型返回的结构化 JSON 不完整，已降级为基于证据的保守回答。",
            answer_type="solution_design" if MessageFormatter._looks_like_solution_query(query) else "general",
            confidence="低：结构化输出不完整，需要重新生成或人工确认。",
        )
        if reply.answer_type == "solution_design":
            reply.solution = {
                "recommended": "当前结构化输出不完整，不能直接采信为最终方案；建议基于完整证据重新生成方案。",
                "steps": ["重新生成回答或查看完整证据。"],
                "risks": ["本次回答不应作为最终工程方案。"],
            }
        return reply

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
    def _sanitize_visible_reply_text(reply: FormattedReply) -> None:
        reply.title = MessageFormatter._clean_visible_text(reply.title)
        reply.summary = MessageFormatter._clean_visible_text(reply.summary)
        reply.confidence = MessageFormatter._clean_visible_text(reply.confidence)
        if reply.direct_answer:
            reply.direct_answer = {
                key: MessageFormatter._clean_visible_text(value)
                for key, value in reply.direct_answer.items()
            }
        for attr in ("details", "evidence_items"):
            items = getattr(reply, attr) or []
            for item in items:
                for key, value in list(item.items()):
                    if isinstance(value, str):
                        item[key] = MessageFormatter._clean_visible_text(value)
        for attr in ("caveats", "next_steps", "key_points"):
            values = getattr(reply, attr) or []
            setattr(reply, attr, [MessageFormatter._clean_visible_text(value) for value in values])
        if reply.solution:
            for key, value in list(reply.solution.items()):
                if isinstance(value, str):
                    reply.solution[key] = MessageFormatter._clean_visible_text(value)
                elif isinstance(value, list):
                    reply.solution[key] = [
                        MessageFormatter._clean_visible_text(str(item))
                        for item in value
                    ]

    @staticmethod
    def _clean_visible_text(text: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", str(text), flags=re.IGNORECASE)
        text = re.sub(r"\bsmhuman\b", "smmuman", text, flags=re.IGNORECASE)
        return MessageFormatter._remove_model_evidence_refs(text)

    @staticmethod
    def _remove_model_evidence_refs(text: str) -> str:
        text = re.sub(r"\bEvidence\s+\d+\b", "相关证据", str(text), flags=re.IGNORECASE)
        text = re.sub(r"\b证据\s*\d+\b", "相关证据", text)
        return MessageFormatter._clean_inline_text(text)

    @staticmethod
    def _apply_support_guardrails(
        reply: FormattedReply,
        context_pack: dict[str, Any],
    ) -> None:
        support_text = MessageFormatter._support_text(reply, context_pack)
        unsupported: set[str] = set()
        unsupported.update(MessageFormatter._filter_unsupported_details(reply, support_text))
        unsupported.update(MessageFormatter._validate_solution_steps(reply, support_text))
        unsupported.update(MessageFormatter._filter_unsupported_solution_lists(reply, support_text))
        MessageFormatter._guard_precise_values_from_compacted_tables(reply, context_pack)
        MessageFormatter._guard_induced_zero_copy_claim(reply, context_pack)
        if unsupported:
            caveats = list(reply.caveats or [])
            caveats.append(
                "未在检索证据中确认的 API："
                + ", ".join(sorted(unsupported))
            )
            reply.caveats = list(dict.fromkeys(caveats))
            if reply.confidence.startswith("高"):
                reply.confidence = "中：部分 API 未在检索证据中直接确认。"

    @staticmethod
    def _guard_induced_zero_copy_claim(
        reply: FormattedReply,
        context_pack: dict[str, Any],
    ) -> None:
        answer_text = MessageFormatter._clean_inline_text(
            " ".join(
                [
                    reply.title,
                    reply.summary,
                    " ".join((reply.direct_answer or {}).values()),
                ]
            )
        ).lower()
        if not any(term in answer_text for term in ("真零拷贝", "zero-copy", "zero buffer copy")):
            return
        if "screen" not in answer_text and "buffer" not in answer_text:
            return
        strong_claim = any(term in answer_text for term in ("官方明确支持", "证实", "直接确认", "明确支持"))
        if not strong_claim:
            return
        support_chunks = context_pack.get("selected_chunks") or []
        screen_zero_copy_supported = any(
            "screen" in f"{chunk.get('document_title', '')} {' '.join(chunk.get('section_titles') or [])} {chunk.get('text', '')}".lower()
            and any(token in str(chunk.get("text") or "").lower() for token in ("zero-copy", "zero buffer copy", "零拷贝"))
            for chunk in support_chunks
        )
        if screen_zero_copy_supported:
            return
        reply.summary = "当前检索资料不能确认 QNX Screen buffer 官方明确支持真零拷贝；只能确认部分相机/平台文档提到 Zero Buffer Copy，Screen 侧仍需直接证据。"
        reply.direct_answer = {
            "primary": reply.summary,
            "secondary": "不要把 Camera/QCarCam 的 Zero Buffer Copy 直接迁移为 Screen 子系统的官方能力。"
        }
        caveats = list(reply.caveats or [])
        caveats.append("Screen 真零拷贝缺少直接文档证据，不能按诱导问题确认。")
        reply.caveats = list(dict.fromkeys(caveats))
        if reply.confidence.startswith("高"):
            reply.confidence = "中：Screen 侧缺少直接真零拷贝证据。"

    @staticmethod
    def _guard_precise_values_from_compacted_tables(
        reply: FormattedReply,
        context_pack: dict[str, Any],
    ) -> None:
        answer_text = " ".join(
            [
                reply.summary,
                " ".join((reply.direct_answer or {}).values()),
                " ".join(
                    " ".join(str(item.get(key) or "") for key in ("name", "purpose", "usage"))
                    for item in (reply.details or [])
                ),
                " ".join(str(step) for step in ((reply.solution or {}).get("steps") or [])),
            ]
        )
        signal_values = re.findall(r"SIGRT#\d+", answer_text)
        if not signal_values:
            return
        support_text = " ".join(str(chunk.get("text") or "") for chunk in context_pack.get("selected_chunks") or [])
        compacted_signal_numbers = {
            match.group(1)
            for match in re.finditer(r"[A-Za-z]{2,}SIGRT#(\d+)", support_text)
        }
        compacted_values = [
            value for value in signal_values
            if value.split("#", 1)[-1] in compacted_signal_numbers
        ]
        if not compacted_values:
            return
        caveats = list(reply.caveats or [])
        caveats.append(
            "精确信号号来自粘连表格，需在目标系统文档或头文件中复核："
            + ", ".join(sorted(set(compacted_values)))
        )
        reply.caveats = list(dict.fromkeys(caveats))
        if reply.confidence.startswith("高"):
            reply.confidence = "中：精确值来自粘连表格，需要复核。"

    @staticmethod
    def _dedupe_solution_echo(reply: FormattedReply) -> None:
        if not reply.solution:
            return
        recommended = MessageFormatter._clean_inline_text(str(reply.solution.get("recommended") or ""))
        summary = MessageFormatter._clean_inline_text(reply.summary)
        direct_text = MessageFormatter._clean_inline_text(" ".join((reply.direct_answer or {}).values()))
        if recommended and (recommended == summary or recommended == direct_text):
            reply.solution.pop("recommended", None)

    @staticmethod
    def _support_text(reply: FormattedReply, context_pack: dict[str, Any]) -> str:
        parts: list[str] = []
        for item in reply.evidence_items or []:
            parts.extend(
                str(item.get(key) or "")
                for key in ("name", "source", "location", "why_relevant", "summary", "document_title")
            )
        for chunk in context_pack.get("selected_chunks") or []:
            parts.append(str(chunk.get("document_title") or ""))
            parts.append(" ".join(str(item) for item in (chunk.get("section_titles") or [])))
            parts.append(str(chunk.get("text") or ""))
        parts.extend(MessageFormatter._known_api_terms())
        return " ".join(parts).lower()

    @staticmethod
    def _known_api_terms() -> list[str]:
        return [
            "pthread_create",
            "threadcreate",
            "channelcreate",
            "connectattach",
            "timer_create",
            "timer_settime",
            "msgreceive",
            "fsync",
            "slog2_register",
            "bus_dma_tag_create",
            "bus_dmamap_load",
            "bus_dmamap_create",
            "ham_entity",
            "ham_action_restart",
            "ham_attach_self",
        ]

    @staticmethod
    def _api_terms_from_text(text: str) -> list[str]:
        return list(
            dict.fromkeys(
                match.strip()
                for match in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\s*(?=\()", text)
            )
        )

    @staticmethod
    def _is_supported_api(api: str, support_text: str) -> bool:
        return api.lower() in support_text

    @staticmethod
    def _filter_unsupported_details(reply: FormattedReply, support_text: str) -> set[str]:
        unsupported_terms: set[str] = set()
        filtered: list[dict[str, str]] = []
        for item in reply.details or []:
            text = " ".join(str(item.get(key) or "") for key in ("name", "purpose", "usage"))
            apis = MessageFormatter._api_terms_from_text(text)
            unsupported = [
                api for api in apis
                if not MessageFormatter._is_supported_api(api, support_text)
            ]
            if apis and len(unsupported) == len(apis):
                unsupported_terms.update(unsupported)
                continue
            unsupported_terms.update(unsupported)
            filtered.append(item)
        reply.details = filtered
        return unsupported_terms

    @staticmethod
    def _validate_solution_steps(reply: FormattedReply, support_text: str) -> set[str]:
        unsupported_terms: set[str] = set()
        if reply.answer_type != "solution_design" or not reply.solution:
            return unsupported_terms
        supported_steps: list[str] = []
        open_questions = list(reply.solution.get("open_questions") or [])
        for step in reply.solution.get("steps") or []:
            apis = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", step)
            unsupported = [
                api[:-1]
                for api in apis
                if not MessageFormatter._is_supported_api(api[:-1], support_text)
            ]
            if unsupported:
                unsupported_terms.update(unsupported)
                open_questions.append(
                    "需确认 API 是否存在并适用于该方案：" + ", ".join(unsupported)
                )
            else:
                supported_steps.append(step)
        reply.solution["steps"] = supported_steps
        if open_questions:
            reply.solution["open_questions"] = list(dict.fromkeys(open_questions))
        return unsupported_terms

    @staticmethod
    def _filter_unsupported_solution_lists(reply: FormattedReply, support_text: str) -> set[str]:
        unsupported_terms: set[str] = set()
        if not reply.solution:
            return unsupported_terms
        for key in ("variants", "not_recommended"):
            kept: list[str] = []
            open_questions = list(reply.solution.get("open_questions") or [])
            for item in reply.solution.get(key) or []:
                if key == "variants" and MessageFormatter._looks_like_uncertain_variant(str(item)):
                    open_questions.append(str(item))
                    continue
                apis = MessageFormatter._api_terms_from_text(str(item))
                unsupported = [
                    api for api in apis
                    if not MessageFormatter._is_supported_api(api, support_text)
                ]
                if apis and len(unsupported) == len(apis):
                    unsupported_terms.update(unsupported)
                    continue
                if key == "not_recommended" and not apis and MessageFormatter._looks_like_speculative_not_recommended(str(item)):
                    continue
                kept.append(str(item))
            if kept:
                reply.solution[key] = kept
            else:
                reply.solution.pop(key, None)
            if open_questions:
                reply.solution["open_questions"] = list(dict.fromkeys(open_questions))
        return unsupported_terms

    @staticmethod
    def _looks_like_speculative_not_recommended(text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ("寄存器", "camera_get", "硬件 vsync", "不属于 screen 公共接口"))

    @staticmethod
    def _looks_like_uncertain_variant(text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ("需确认", "需要确认", "未被文档覆盖", "未覆盖", "未明确"))

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
            if key == "steps":
                items = [MessageFormatter._strip_model_step_prefix(item) for item in items]
            if items:
                normalized[key] = items
        return normalized or None

    @staticmethod
    def _strip_model_step_prefix(text: str) -> str:
        cleaned = MessageFormatter._clean_inline_text(text)
        previous = None
        while cleaned and cleaned != previous:
            previous = cleaned
            cleaned = re.sub(r"^(?:步骤\s*)?\d+\s*[.)、:：]\s*", "", cleaned).strip()
        return cleaned

    @staticmethod
    def _normalize_direct_answer(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: dict[str, str] = {}
        for key in ("tools", "demos", "primary", "secondary"):
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
            step = MessageFormatter._strip_model_step_prefix(step)
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
        if query.strip() == "截图演示：vsync":
            reply = MessageFormatter.build_vsync_screenshot_demo_reply()
            return BotReplyResult(
                text=reply.plain_text or MessageFormatter.format_user_answer_text(reply),
                search_query=effective_search_query,
                has_evidence=False,
                formatted_reply=reply,
            )
        if self.llm_agent.is_chitchat(query):
            reply = self.llm_agent.direct_reply(query)
            reply = self.formatter.truncate_message(reply, self.config.max_reply_length)
            return BotReplyResult(text=reply, search_query=effective_search_query)
        intent = self.formatter.classify_query_intent(query, history=history)
        if intent in {"out_of_scope", "missing_context"}:
            reply = self.formatter.boundary_reply(intent)
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

    def send_card_message(
        self,
        chat_id: str,
        reply: FormattedReply,
        *,
        mode: str = "summary",
        reply_id: str | None = None,
    ) -> bool:
        token = self.token_manager.get_token()
        url = f"{self.config.api_base}/message/v4/send/"
        card = (
            MessageFormatter.format_detail_card(reply)
            if mode == "detail"
            else MessageFormatter.format_summary_card(reply, reply_id=reply_id)
        )
        resp = _http_post(
            url,
            {
                "chat_id": chat_id,
                "msg_type": "interactive",
                "card": card,
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

    def send_reply_message(
        self,
        chat_id: str,
        reply: FormattedReply,
        *,
        reply_id: str | None = None,
    ) -> None:
        try:
            if self.send_card_message(chat_id, reply, mode="summary", reply_id=reply_id):
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
