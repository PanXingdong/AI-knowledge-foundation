from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from agent_knowledge_hub.feishu_bot import (
    FeishuAPI,
    FeishuConfig,
    LocalAPIClient,
    MessageFormatter,
    assemble_reply,
    filter_mentions,
)

logger = logging.getLogger(__name__)


class FeishuBotSDK:
    _HEALTH_CHECK_DELAY = 30.0

    def __init__(self, config: FeishuConfig | None = None) -> None:
        self.config = config or FeishuConfig.from_env()
        self.local_api = LocalAPIClient(self.config.local_api_base)
        self.feishu_api = FeishuAPI(self.config)
        self.formatter = MessageFormatter()
        self._channel = None
        self._message_count = 0
        self._start_time: float = 0
        self._health_timer: threading.Timer | None = None

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

            logger.info("收到消息: %s", text[:50])
            self._process_query(chat_id, text, start_time)

        except Exception:
            logger.exception("处理消息事件失败")

    def _process_query(self, chat_id: str, query: str, start_time: float = 0) -> None:
        if start_time == 0:
            start_time = time.time()

        try:
            t1 = time.time()
            context_pack = self.local_api.get_context_pack(
                processed_dir=self.config.processed_dir,
                query=query,
                top_k=self.config.default_top_k,
                per_document_limit=self.config.default_per_document_limit,
            )
            t2 = time.time()

            score_threshold = -30.0
            selected_chunks = context_pack.get("selected_chunks", [])
            if selected_chunks:
                max_score = max(chunk.get("score", float("-inf")) for chunk in selected_chunks)
                if max_score < score_threshold:
                    logger.info("查询无匹配内容: query=%s, max_score=%.2f", query, max_score)
                    self.feishu_api.send_text_message(chat_id, "未找到相关内容")
                    return

            context_pack_text = self.formatter.format_context_pack(context_pack, score_threshold)
            t3 = time.time()
            logger.info("步骤耗时: 获取Context Pack=%.2fs, 格式化=%.2fs", t2 - t1, t3 - t2)

            gap_report_text = ""
            ref_path = self.config.reference_markdown_path
            if ref_path and Path(ref_path).exists():
                t4 = time.time()
                gap_report = self.local_api.get_gap_report(
                    processed_dir=self.config.processed_dir,
                    query=query,
                    reference_markdown_path=ref_path,
                    top_k=self.config.default_top_k,
                    per_document_limit=self.config.default_per_document_limit,
                )
                gap_report_text = self.formatter.format_gap_report(gap_report)
                t5 = time.time()
                logger.info("步骤耗时: 基线对比=%.2fs", t5 - t4)

            full_reply = assemble_reply(context_pack_text, gap_report_text)
            full_reply = self.formatter.truncate_message(full_reply, self.config.max_reply_length)

            self.feishu_api.send_text_message(chat_id, full_reply)
            total = time.time() - start_time
            logger.info("总耗时: %.2fs (消息接收→回复发送)", total)

        except Exception:
            logger.exception("处理用户查询失败")
            self.feishu_api.send_text_message(chat_id, f"处理查询时出错: {query}")


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
