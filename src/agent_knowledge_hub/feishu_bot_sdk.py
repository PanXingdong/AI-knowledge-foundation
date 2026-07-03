from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

# Note on gap_report: the gap-report feature (baseline comparison) is still
# available in feishu_bot.py (LocalAPIClient.get_gap_report + assemble_reply).
# This SDK intentionally routes all user queries through the three-stage LLM
# synthesis path instead. Gap reports remain accessible via the /api/gap-report
# HTTP endpoint and the CLI `gap-report` sub-command.
from agent_knowledge_hub.feishu_bot import (
    FeishuAPI,
    FeishuConfig,
    KnowledgeQueryResponder,
    LocalAPIClient,
    MessageFormatter,
    filter_mentions,
)
from agent_knowledge_hub.llm_agent import LLMAgent

logger = logging.getLogger(__name__)


_FOLLOWUP_PATTERNS = (
    "刚才", "上面", "上一个", "前面", "那个问题", "那个",
    "继续", "接着", "然后呢", "还有吗", "补充", "追问",
    "这种方式", "那种方式", "其他方式",
    "命令行", "不用代码", "有没有工具", "具体怎么",
)


class FeishuBotSDK:
    _HEALTH_CHECK_DELAY = 30.0
    _MAX_HISTORY_TURNS = 3
    _MAX_MEMORY_KEYS = 1000
    _MEMORY_TTL_SECONDS = 6 * 60 * 60

    def __init__(self, config: FeishuConfig | None = None) -> None:
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
        self._channel = None
        self._message_count = 0
        self._start_time: float = 0
        self._health_timer: threading.Timer | None = None
        self._history: dict[str, list[dict[str, str]]] = {}
        self._last_query: dict[str, str] = {}
        self._last_seen: dict[str, float] = {}
        self._memory_lock = threading.Lock()

    def run(self) -> None:
        try:
            from lark_oapi.channel import Events, FeishuChannel
            from lark_oapi.core.enum import LogLevel
        except ImportError as exc:
            raise RuntimeError("需要安装飞书官方SDK: pip install lark-oapi") from exc

        # DEBUG级别可通过环境变量 FEISHU_BOT_DEBUG=1 启用
        debug_mode = os.getenv("FEISHU_BOT_DEBUG", "") == "1"
        lark_logger = logging.getLogger("Lark")
        lark_logger.propagate = False  # 避免与root handler重复输出
        if debug_mode:
            lark_logger.setLevel(logging.DEBUG)

        self._channel = FeishuChannel(
            app_id=self.config.app_id,
            app_secret=self.config.app_secret,
            log_level=LogLevel.DEBUG if debug_mode else LogLevel.INFO,
        )
        self._channel.on(Events.MESSAGE, self._handle_message_event)
        self._channel.on(Events.REJECT, self._handle_reject_event)
        for event_name in (
            "CARD_ACTION",
            "CARD_ACTION_TRIGGER",
            "MESSAGE_ACTION",
            "INTERACTIVE_CARD_ACTION",
        ):
            event_value = getattr(Events, event_name, None)
            if event_value is not None:
                self._channel.on(event_value, self._handle_card_action_event)

        logger.info("启动飞书Bot长连接...")
        logger.info("App ID: %s", self.config.app_id)

        # 启动健康检查：30秒内未收到消息事件则输出诊断提示
        self._start_time = time.time()
        self._health_timer = threading.Timer(self._HEALTH_CHECK_DELAY, self._health_check)
        self._health_timer.daemon = True
        self._health_timer.start()

        self._channel.start()

    def _handle_reject_event(self, event: Any) -> None:
        """捕获被SafetyPipeline过滤的消息，用于调试"""
        reason = getattr(event, "reason", "unknown")
        msg = getattr(event, "message", None)
        if msg:
            text = getattr(msg, "content_text", "")
            chat_id = getattr(msg, "chat_id", "")
            logger.warning("消息被过滤: reason=%s, chat_id=%s, text=%s", reason, chat_id, text[:50] if text else "")
        else:
            logger.warning("消息被过滤: reason=%s, event=%s", reason, type(event))

    def _handle_card_action_event(self, event: Any) -> None:
        try:
            value = self._extract_action_value(event)
            if value.get("action") != "show_full_evidence":
                return
            evidence_refs = self._extract_evidence_refs(value)[:6]
            if not evidence_refs:
                return
            chat_id = self._extract_action_chat_id(event)
            if not chat_id:
                logger.warning("卡片回调缺少 chat_id，无法发送证据详情")
                return
            traces = []
            for evidence_ref in evidence_refs:
                evidence_id = evidence_ref["evidence_id"]
                try:
                    trace = self.local_api.get_evidence(
                        processed_dir=self.config.processed_dir,
                        evidence_id=evidence_id,
                    )
                    trace["_evidence_ref"] = evidence_ref
                    traces.append(trace)
                except Exception:
                    logger.warning("获取证据失败: %s", evidence_id, exc_info=True)
            if not traces:
                self.feishu_api.send_text_message(chat_id, "未能获取完整证据，请稍后重试。")
                return
            self.feishu_api.send_text_message(chat_id, self._format_evidence_traces(traces))
        except Exception:
            logger.exception("处理卡片按钮事件失败")

    @staticmethod
    def _extract_action_value(event: Any) -> dict[str, Any]:
        action = getattr(event, "action", None)
        value = getattr(action, "value", None) if action is not None else None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        event_value = getattr(event, "value", None)
        return event_value if isinstance(event_value, dict) else {}

    @staticmethod
    def _extract_evidence_refs(value: dict[str, Any]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        raw_refs = value.get("evidence_refs")
        if isinstance(raw_refs, list):
            for item in raw_refs:
                if not isinstance(item, dict):
                    continue
                evidence_id = str(item.get("evidence_id") or "").strip()
                if not evidence_id:
                    continue
                refs.append(
                    {
                        "evidence_id": evidence_id,
                        "label": str(item.get("label") or "").strip(),
                        "supports": str(item.get("supports") or "").strip(),
                    }
                )
        if refs:
            return refs
        return [
            {"evidence_id": str(evidence_id), "label": "", "supports": ""}
            for evidence_id in (value.get("evidence_ids") or [])
            if str(evidence_id).strip()
        ]

    @staticmethod
    def _extract_action_chat_id(event: Any) -> str:
        for attr in ("chat_id", "open_chat_id"):
            value = getattr(event, attr, "")
            if value:
                return str(value)
        message = getattr(event, "message", None)
        if message is not None:
            value = getattr(message, "chat_id", "") or getattr(message, "open_chat_id", "")
            if value:
                return str(value)
        return ""

    @staticmethod
    def _format_evidence_traces(
        traces: list[dict[str, Any]],
        evidence_refs: list[dict[str, str]] | None = None,
    ) -> str:
        lines = ["完整证据"]
        useful_traces = [
            trace
            for trace in traces
            if not FeishuBotSDK._is_low_value_evidence_text(str(trace.get("text") or ""))
        ]
        if not useful_traces:
            useful_traces = traces
        for index, trace in enumerate(useful_traces, start=1):
            title = str(trace.get("document_title") or "Unknown")
            evidence_ref = trace.get("_evidence_ref")
            if not isinstance(evidence_ref, dict) and evidence_refs:
                evidence_ref = evidence_refs[min(index - 1, len(evidence_refs) - 1)]
            page = trace.get("page")
            sections = " > ".join(str(item) for item in (trace.get("section_titles") or []) if item)
            text = str(trace.get("text") or "").strip()
            if len(text) > 600:
                text = text[:597] + "..."
            location_parts = []
            if sections:
                location_parts.append(sections)
            if page is not None:
                location_parts.append(f"page {page}")
            location = " / ".join(location_parts) or "source"
            lines.extend(["", f"证据 {index}. {title}"])
            if isinstance(evidence_ref, dict):
                label = str(evidence_ref.get("label") or "").strip()
                supports = str(evidence_ref.get("supports") or "").strip()
                if label or supports:
                    relation = label if not supports else f"{label} - {supports}" if label else supports
                    lines.append(f"支撑：{relation}")
            lines.extend([f"位置：{location}", f"原文：{text}"])
        return "\n".join(lines)

    @staticmethod
    def _is_low_value_evidence_text(text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return True
        if len(normalized) <= 30 and re.fullmatch(r"(?i)(chapter|section|part)\s+\d+", normalized):
            return True
        if len(normalized) <= 20 and not any(char in normalized for char in ".。,:：;；"):
            return True
        return False

    def _health_check(self) -> None:
        """启动30秒后执行：若未收到任何消息事件，输出诊断提示。"""
        if self._message_count > 0:
            return
        elapsed = time.time() - self._start_time
        logger.warning(
            "启动 %.0f 秒内未收到任何消息事件 (im.message.receive_v1)。\n"
            "  请检查飞书开放平台配置：\n"
            "  1. 进入 https://open.feishu.cn/app -> 选择本应用\n"
            "  2. 左侧菜单「事件与回调」->「事件订阅」\n"
            "  3. 确认请求方式为「使用长连接接收事件」\n"
            "  4. 确认已添加事件：接收消息 (im.message.receive_v1)\n"
            "  5. 确认已开通权限：im:message 或 im:message.receive_v1:readonly\n"
            "  如需调试详细日志，设置环境变量 FEISHU_BOT_DEBUG=1 后重启",
            elapsed,
        )

    def _handle_message_event(self, event: Any) -> None:
        start_time = time.time()
        self._message_count += 1

        # 首条消息到达，取消健康检查计时器
        if self._message_count == 1 and self._health_timer is not None:
            self._health_timer.cancel()
            self._health_timer = None
            logger.info("首条消息事件已接收，事件订阅配置正常")
        try:
            text = getattr(event, "content_text", "")
            if not text and hasattr(event, "content"):
                content = event.content
                if hasattr(content, "text"):
                    text = content.text
                elif isinstance(content, dict):
                    text = content.get("text", "")
                elif isinstance(content, str):
                    text = content

            text = filter_mentions(text)

            if not text:
                return

            chat_id = event.chat_id if hasattr(event, "chat_id") else ""
            user_id = ""
            sender = getattr(event, "sender", None)
            if sender is not None:
                sender_id = getattr(sender, "sender_id", None) or getattr(sender, "id", None)
                if sender_id is not None:
                    user_id = getattr(sender_id, "open_id", "") or ""
            memory_key = f"{chat_id}:{user_id}" if user_id else chat_id

            logger.info("收到消息: [%s] %s", user_id[:12] or "?", text[:50])
            self._process_query(
                chat_id,
                text,
                start_time,
                memory_key=memory_key,
                allow_followup=bool(user_id),
            )

        except Exception:
            logger.exception("处理消息事件失败")

    @staticmethod
    def _is_followup(query: str) -> bool:
        q = query.strip()
        if len(q) <= 60:
            return any(pattern in q for pattern in _FOLLOWUP_PATTERNS)
        return False

    def _process_query(
        self,
        chat_id: str,
        query: str,
        start_time: float = 0,
        *,
        memory_key: str | None = None,
        allow_followup: bool = True,
    ) -> None:
        if start_time == 0:
            start_time = time.time()
        memory_key = memory_key or chat_id

        try:
            search_query = query
            history, previous_query = self._get_memory_snapshot(memory_key)
            if allow_followup and self._is_followup(query) and previous_query:
                search_query = previous_query
                logger.info("Follow-up detected, reusing previous query: %s", search_query[:50])

            # ── Shared knowledge-answer pipeline ───────────────────────
            t1 = time.time()
            self.responder.local_api = self.local_api
            self.responder.formatter = self.formatter
            self.responder.llm_agent = self.llm_agent
            result = self.responder.process_query(
                query,
                search_query=search_query,
                history=history or None,
            )
            t2 = time.time()
            logger.info("步骤耗时: shared_pipeline=%.2fs", t2 - t1)

            if result.formatted_reply is not None:
                self.feishu_api.send_reply_message(chat_id, result.formatted_reply)
            else:
                self.feishu_api.send_text_message(chat_id, result.text)
            self._update_history(memory_key, query, result.text)
            self._set_last_query(memory_key, result.search_query)
            logger.info("总耗时: %.2fs", time.time() - start_time)

        except Exception:
            logger.exception("处理用户查询失败")
            self.feishu_api.send_text_message(chat_id, f"处理查询时出错，请稍后重试。")

    def _get_memory_snapshot(self, memory_key: str) -> tuple[list[dict[str, str]], str | None]:
        with self._memory_lock:
            self._cleanup_memory_locked(now=time.time())
            self._last_seen[memory_key] = time.time()
            return list(self._history.get(memory_key, [])), self._last_query.get(memory_key)

    def _set_last_query(self, memory_key: str, search_query: str) -> None:
        with self._memory_lock:
            self._cleanup_memory_locked(now=time.time())
            self._last_query[memory_key] = search_query
            self._last_seen[memory_key] = time.time()

    def _update_history(self, memory_key: str, user_msg: str, assistant_msg: str) -> None:
        with self._memory_lock:
            self._cleanup_memory_locked(now=time.time())
            turns = list(self._history.get(memory_key, []))
            turns.append({"role": "user", "content": user_msg})
            turns.append({"role": "assistant", "content": assistant_msg[:500]})
            max_msgs = self._MAX_HISTORY_TURNS * 2
            self._history[memory_key] = turns[-max_msgs:]
            self._last_seen[memory_key] = time.time()

    def _cleanup_memory_locked(self, *, now: float) -> None:
        expired_keys = [
            key
            for key, last_seen in self._last_seen.items()
            if now - last_seen > self._MEMORY_TTL_SECONDS
        ]
        for key in expired_keys:
            self._history.pop(key, None)
            self._last_query.pop(key, None)
            self._last_seen.pop(key, None)

        if len(self._last_seen) <= self._MAX_MEMORY_KEYS:
            return

        overflow = len(self._last_seen) - self._MAX_MEMORY_KEYS
        oldest_keys = sorted(self._last_seen, key=self._last_seen.get)[:overflow]
        for key in oldest_keys:
            self._history.pop(key, None)
            self._last_query.pop(key, None)
            self._last_seen.pop(key, None)


def main() -> int:
    parser = argparse.ArgumentParser(description="飞书Bot（官方SDK长连接方式）")
    parser.add_argument(
        "--app-id",
        default="",
        help="飞书应用ID（也可通过FEISHU_APP_ID环境变量设置）",
    )
    parser.add_argument(
        "--app-secret",
        default="",
        help="飞书应用密钥（也可通过FEISHU_APP_SECRET环境变量设置）",
    )
    parser.add_argument(
        "--processed-dir",
        default="",
        help="processed目录路径（也可通过PROCESSED_DIR环境变量设置）",
    )
    args = parser.parse_args()

    # 配置应用日志级别
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] [%(asctime)s] [%(levelname)s] %(message)s",
    )

    if args.app_id:
        os.environ["FEISHU_APP_ID"] = args.app_id
    if args.app_secret:
        os.environ["FEISHU_APP_SECRET"] = args.app_secret
    if args.processed_dir:
        os.environ["PROCESSED_DIR"] = args.processed_dir

    bot = FeishuBotSDK()
    bot.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
