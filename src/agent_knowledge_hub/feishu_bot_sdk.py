from __future__ import annotations

import argparse
import json
import logging
import os
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
    LocalAPIClient,
    MessageFormatter,
    assemble_reply,
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

    def __init__(self, config: FeishuConfig | None = None) -> None:
        self.config = config or FeishuConfig.from_env()
        self.local_api = LocalAPIClient(self.config.local_api_base)
        self.feishu_api = FeishuAPI(self.config)
        self.formatter = MessageFormatter()
        self.llm_agent = LLMAgent.from_env()
        self._channel = None
        self._message_count = 0
        self._start_time: float = 0
        self._health_timer: threading.Timer | None = None
        self._history: dict[str, list[dict[str, str]]] = {}
        self._last_query: dict[str, str] = {}

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
            self._process_query(memory_key, text, start_time)

        except Exception:
            logger.exception("处理消息事件失败")

    @staticmethod
    def _is_followup(query: str) -> bool:
        q = query.strip()
        if len(q) <= 60:
            return any(pattern in q for pattern in _FOLLOWUP_PATTERNS)
        return False

    def _process_query(self, chat_id: str, query: str, start_time: float = 0) -> None:
        if start_time == 0:
            start_time = time.time()

        try:
            search_query = query
            history = self._history.get(chat_id, [])
            if self._is_followup(query) and chat_id in self._last_query:
                search_query = self._last_query[chat_id]
                logger.info("Follow-up detected, reusing previous query: %s", search_query[:50])

            # ── Step 1: chitchat shortcut (no KB call) ──────────────────
            if self.llm_agent.is_chitchat(query):
                logger.info("Intent: chitchat, skipping KB retrieval")
                reply = self.llm_agent.direct_reply(query)
                reply = self.formatter.truncate_message(reply, self.config.max_reply_length)
                self.feishu_api.send_text_message(chat_id, reply)
                self._update_history(chat_id, query, reply)
                logger.info("总耗时: %.2fs", time.time() - start_time)
                return

            # ── Step 2: knowledge base retrieval ───────────────────────
            t1 = time.time()
            context_pack = self.local_api.get_context_pack(
                processed_dir=self.config.processed_dir,
                query=search_query,
                top_k=self.config.default_top_k,
                per_document_limit=self.config.default_per_document_limit,
                fts_index_path=self.config.fts_index_path or None,
                vector_index_path=self.config.vector_index_path or None,
            )
            t2 = time.time()

            score_threshold = self.config.score_threshold  # configurable via SCORE_THRESHOLD env var
            selected_chunks = context_pack.get("selected_chunks", [])
            has_evidence = bool(selected_chunks) and (
                max((c.get("score", float("-inf")) for c in selected_chunks), default=float("-inf"))
                >= score_threshold
            )

            # ── Step 3: LLM synthesis (with conversation history) ───────
            if not has_evidence:
                logger.info("KB: no relevant evidence for query=%s", query[:40])
                reply = self.llm_agent.no_evidence_reply(query)
            else:
                context_pack_text = self.formatter.format_context_pack(context_pack, score_threshold)
                t3 = time.time()
                logger.info("步骤耗时: KB=%.2fs, 格式化=%.2fs", t2 - t1, t3 - t2)
                reply = self.llm_agent.synthesize(query, context_pack_text, history=history or None)

            reply = self.formatter.truncate_message(reply, self.config.max_reply_length)
            self.feishu_api.send_text_message(chat_id, reply)
            self._update_history(chat_id, query, reply)
            self._last_query[chat_id] = search_query
            logger.info("总耗时: %.2fs", time.time() - start_time)

        except Exception:
            logger.exception("处理用户查询失败")
            self.feishu_api.send_text_message(chat_id, f"处理查询时出错，请稍后重试。")

    def _update_history(self, chat_id: str, user_msg: str, assistant_msg: str) -> None:
        turns = self._history.setdefault(chat_id, [])
        turns.append({"role": "user", "content": user_msg})
        turns.append({"role": "assistant", "content": assistant_msg[:500]})
        max_msgs = self._MAX_HISTORY_TURNS * 2
        if len(turns) > max_msgs:
            self._history[chat_id] = turns[-max_msgs:]


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
