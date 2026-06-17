import os
from unittest.mock import patch

import pytest

from agent_knowledge_hub.feishu_bot import (
    FeishuConfig,
    MessageFormatter,
    assemble_reply,
    filter_mentions,
)


class TestFeishuConfig:
    def test_from_env_reads_all_variables(self):
        env = {
            "FEISHU_APP_ID": "test_app_id",
            "FEISHU_APP_SECRET": "test_secret",
            "FEISHU_VERIFICATION_TOKEN": "test_token",
            "FEISHU_API_BASE": "https://test.feishu.cn",
            "LOCAL_API_BASE": "http://localhost:9999",
            "PROCESSED_DIR": "/tmp/processed",
            "REFERENCE_MARKDOWN_PATH": "/tmp/ref.md",
            "DEFAULT_TOP_K": "10",
            "DEFAULT_PER_DOCUMENT_LIMIT": "3",
            "MAX_REPLY_LENGTH": "1500",
        }
        with patch.dict(os.environ, env, clear=True):
            config = FeishuConfig.from_env()
            assert config.app_id == "test_app_id"
            assert config.app_secret == "test_secret"
            assert config.verification_token == "test_token"
            assert config.api_base == "https://test.feishu.cn"
            assert config.local_api_base == "http://localhost:9999"
            assert config.processed_dir == "/tmp/processed"
            assert config.reference_markdown_path == "/tmp/ref.md"
            assert config.default_top_k == 10
            assert config.default_per_document_limit == 3
            assert config.max_reply_length == 1500

    def test_from_env_uses_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            config = FeishuConfig.from_env()
            assert config.app_id == ""
            assert config.app_secret == ""
            assert config.api_base == "https://open.feishu.cn/open-apis"
            assert config.local_api_base == "http://127.0.0.1:8789"
            assert config.default_top_k == 8
            assert config.default_per_document_limit == 2
            assert config.max_reply_length == 3000


class TestFilterMentions:
    def test_removes_at_mention_prefix(self):
        assert filter_mentions("@bot hello") == "hello"

    def test_removes_multiple_mentions(self):
        assert filter_mentions("@bot @user hello world") == "hello world"

    def test_removes_mention_with_trailing_space(self):
        assert filter_mentions("@bot  hello") == "hello"

    def test_removes_mention_without_space(self):
        assert filter_mentions("@bothello") == ""

    def test_no_mention_unchanged(self):
        assert filter_mentions("hello world") == "hello world"

    def test_empty_string(self):
        assert filter_mentions("") == ""


class TestMessageFormatter:
    def test_format_context_pack_basic(self):
        result = {
            "query": "test query",
            "chunk_count": 2,
            "document_count": 1,
            "selected_chunks": [
                {
                    "document_title": "Doc1",
                    "text": "some text content",
                    "score": 0.85,
                }
            ],
        }
        text = MessageFormatter.format_context_pack(result)
        assert "test query" in text
        assert "Doc1" in text
        assert "some text content" in text
        assert "共 1 个片段" in text

    def test_format_context_pack_empty(self):
        result = {
            "query": "empty",
            "chunk_count": 0,
            "document_count": 0,
            "selected_chunks": [],
        }
        text = MessageFormatter.format_context_pack(result)
        assert "未找到相关内容" in text

    def test_format_gap_report(self):
        result = {
            "covered_reference_item_count": 3,
            "missing_reference_item_count": 2,
            "covered_items": ["item1", "item2"],
            "missing_items": ["item3"],
        }
        text = MessageFormatter.format_gap_report(result)
        assert "覆盖率:" in text
        assert "60.0%" in text
        assert "item1" in text
        assert "item3" in text

    def test_format_gap_report_empty(self):
        result = {
            "covered_reference_item_count": 0,
            "missing_reference_item_count": 0,
            "covered_items": [],
            "missing_items": [],
        }
        text = MessageFormatter.format_gap_report(result)
        assert "N/A" in text

    def test_truncate_message_no_truncation(self):
        text = "short text"
        assert MessageFormatter.truncate_message(text, max_length=100) == text

    def test_truncate_message_truncates(self):
        text = "a" * 100
        result = MessageFormatter.truncate_message(text, max_length=10)
        assert len(result) == 10
        assert result.endswith("...")


class TestAssembleReply:
    def test_context_pack_only(self):
        result = assemble_reply("context", "")
        assert result == "context"

    def test_with_gap_report(self):
        result = assemble_reply("context", "gap")
        assert "context" in result
        assert "gap" in result
