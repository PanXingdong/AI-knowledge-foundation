from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
            data = _http_post(url, payload)
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


class MessageFormatter:
    @staticmethod
    def format_context_pack(result: dict[str, Any], score_threshold: float = -30.0) -> str:
        query = result.get("query", "N/A")
        selected_chunks = result.get("selected_chunks", [])
        qualified = [c for c in selected_chunks if c.get("score", float("-inf")) >= score_threshold]

        if not qualified:
            return "未找到相关内容"

        doc_titles = {c.get("document_title", "Unknown") for c in qualified}
        lines = [
            f"【Query】{query}",
            "",
            f"【检索结果】共 {len(qualified)} 个片段，来自 {len(doc_titles)} 个文档",
            "─────────────────────",
        ]

        for i, chunk in enumerate(qualified[:8]):
            doc_title = chunk.get("document_title", "Unknown")
            text = chunk.get("text", "")[:120]
            lines.append(f"\n▶ [{doc_title}]")
            lines.append(f"  {text}")

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


class FeishuMessageHandler:
    def __init__(self, config: FeishuConfig | None = None):
        self.config = config or FeishuConfig.from_env()
        self.local_api = LocalAPIClient(self.config.local_api_base)
        self.feishu_api = FeishuAPI(self.config)
        self.formatter = MessageFormatter()

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
            context_pack = self.local_api.get_context_pack(
                processed_dir=self.config.processed_dir,
                query=query,
                top_k=self.config.default_top_k,
                per_document_limit=self.config.default_per_document_limit,
            )
            context_pack_text = self.formatter.format_context_pack(context_pack)

            gap_report_text = ""
            ref_path = self.config.reference_markdown_path
            if ref_path and Path(ref_path).exists():
                gap_report = self.local_api.get_gap_report(
                    processed_dir=self.config.processed_dir,
                    query=query,
                    reference_markdown_path=ref_path,
                    top_k=self.config.default_top_k,
                    per_document_limit=self.config.default_per_document_limit,
                )
                gap_report_text = self.formatter.format_gap_report(gap_report)

            full_reply = self._assemble_reply(context_pack_text, gap_report_text)
            full_reply = self.formatter.truncate_message(full_reply, self.config.max_reply_length)
            self.feishu_api.send_text_message(chat_id, full_reply)

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
