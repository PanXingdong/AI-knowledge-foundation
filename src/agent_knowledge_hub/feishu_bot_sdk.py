from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any

from agent_knowledge_hub.feishu_bot import (
    FeishuConfig,
    LocalAPIClient,
    MessageFormatter,
)

logger = logging.getLogger(__name__)


class FeishuBotSDK:
    def __init__(self, config: FeishuConfig | None = None) -> None:
        self.config = config or FeishuConfig.from_env()
        self.local_api = LocalAPIClient(self.config.local_api_base)
        self.formatter = MessageFormatter()
        self._channel = None

    def run(self) -> None:
        try:
            from lark_oapi.channel import Events, FeishuChannel
        except ImportError as exc:
            raise RuntimeError("需要安装飞书官方SDK: pip install lark-oapi") from exc

        self._channel = FeishuChannel(
            app_id=self.config.app_id,
            app_secret=self.config.app_secret,
        )
        self._channel.on(Events.MESSAGE, self._handle_message_event)

        logger.info("启动飞书Bot长连接...")
        logger.info("App ID: %s", self.config.app_id)
        self._channel.start()

    def _handle_message_event(self, event: Any) -> None:
        start_time = time.time()
        try:
            content = event.content if hasattr(event, "content") else {}

            if hasattr(content, "text"):
                text = content.text
            elif isinstance(content, dict):
                text = content.get("text", "")
            elif isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    text = parsed.get("text", "") if isinstance(parsed, dict) else content
                except json.JSONDecodeError:
                    text = content
            else:
                text = str(content)

            text = self._filter_mentions(text)

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
                    self._send_message(chat_id, "未找到相关内容")
                    return

            context_pack_text = self.formatter.format_context_pack(context_pack)
            t3 = time.time()
            logger.info("步骤耗时: 获取Context Pack=%.2fs, 格式化=%.2fs", t2 - t1, t3 - t2)

            gap_report_text = ""
            ref_path = self.config.reference_markdown_path
            if ref_path:
                from pathlib import Path

                if Path(ref_path).exists():
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

            full_reply = self._assemble_reply(context_pack_text, gap_report_text)
            full_reply = self.formatter.truncate_message(full_reply, self.config.max_reply_length)

            t6 = time.time()
            self._send_message(chat_id, full_reply)
            total = time.time() - start_time
            logger.info("总耗时: %.2fs (消息接收→回复发送)", total)

        except Exception:
            logger.exception("处理用户查询失败")
            self._send_message(chat_id, f"处理查询时出错: {query}")

    def _send_message(self, chat_id: str, text: str) -> None:
        url = f"{self.config.api_base}/message/v4/send/"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {self._get_tenant_access_token()}",
        }
        payload = {
            "chat_id": chat_id,
            "msg_type": "text",
            "content": {"text": text},
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                resp_body = response.read().decode("utf-8")
                logger.info("消息已发送到chat_id=%s, 响应: %s", chat_id, resp_body[:200])
        except urllib.error.HTTPError as exc:
            logger.error("发送消息HTTP错误 %d: %s", exc.code, exc.read().decode()[:200])
        except Exception as exc:
            logger.error("发送消息失败: %s", exc)

    def _get_tenant_access_token(self) -> str:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("tenant_access_token", "")

    @staticmethod
    def _filter_mentions(text: str) -> str:
        return re.sub(r"@_?\S+\s?", "", text).strip()

    @staticmethod
    def _assemble_reply(context_pack_text: str, gap_report_text: str) -> str:
        parts = [context_pack_text]
        if gap_report_text:
            parts.append("\n" + "═" * 30 + "\n")
            parts.append(gap_report_text)
        return "\n".join(parts)


def main() -> int:
    import argparse
    import os

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
