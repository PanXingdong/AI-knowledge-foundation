import logging
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_knowledge_hub.feishu_bot import FeishuConfig
from agent_knowledge_hub.feishu_bot_sdk import FeishuBotSDK


@pytest.fixture()
def bot():
    """创建一个使用模拟配置的 FeishuBotSDK 实例，不进行真实网络连接。"""
    config = FeishuConfig(
        app_id="test_app_id",
        app_secret="test_secret",
        verification_token="test_token",
        api_base="https://test.feishu.cn",
        local_api_base="http://localhost:9999",
        processed_dir="/tmp/processed",
        reference_markdown_path="",
        default_top_k=5,
        default_per_document_limit=2,
        max_reply_length=3000,
    )
    with patch("agent_knowledge_hub.feishu_bot_sdk.LocalAPIClient"), \
         patch("agent_knowledge_hub.feishu_bot_sdk.FeishuAPI"), \
         patch("agent_knowledge_hub.feishu_bot_sdk.LLMAgent"):
        sdk = FeishuBotSDK(config)
    # Configure default llm_agent mock behaviour used across tests.
    sdk.llm_agent.is_chitchat.return_value = False
    sdk.llm_agent.synthesize.return_value = "合成回答"
    sdk.llm_agent.no_evidence_reply.return_value = "未找到相关内容"
    sdk.llm_agent.direct_reply.return_value = "你好！"
    return sdk


class TestFeishuBotSDKInit:
    def test_default_config_from_env(self):
        env = {
            "FEISHU_APP_ID": "env_app_id",
            "FEISHU_APP_SECRET": "env_secret",
        }
        with patch.dict(os.environ, env, clear=True), \
             patch("agent_knowledge_hub.feishu_bot_sdk.LocalAPIClient"), \
             patch("agent_knowledge_hub.feishu_bot_sdk.FeishuAPI"), \
             patch("agent_knowledge_hub.feishu_bot_sdk.LLMAgent"):
            sdk = FeishuBotSDK()
            assert sdk.config.app_id == "env_app_id"
            assert sdk.config.app_secret == "env_secret"

    def test_explicit_config(self, bot):
        assert bot.config.app_id == "test_app_id"
        assert bot._message_count == 0
        assert bot._health_timer is None


class TestHandleMessageEvent:
    def test_parses_content_text_directly(self, bot):
        """event.content_text 存在时直接使用"""
        event = SimpleNamespace(content_text="你好", chat_id="oc_xxx")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            mock_process.assert_called_once_with("oc_xxx", "你好", pytest.approx(time.time(), abs=5))

    def test_fallback_to_content_object_with_text_attr(self, bot):
        """content_text 为空时，尝试 event.content.text"""
        content = SimpleNamespace(text="来自content.text")
        event = SimpleNamespace(content_text="", content=content, chat_id="oc_yyy")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            mock_process.assert_called_once()
            assert mock_process.call_args[0][1] == "来自content.text"

    def test_fallback_to_content_dict(self, bot):
        """content 为 dict 时通过 .get('text') 取值"""
        event = SimpleNamespace(content_text="", content={"text": "dict文本"}, chat_id="oc_zzz")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            assert mock_process.call_args[0][1] == "dict文本"

    def test_fallback_to_content_string(self, bot):
        """content 为 str 时直接使用"""
        event = SimpleNamespace(content_text="", content="纯字符串", chat_id="oc_www")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            assert mock_process.call_args[0][1] == "纯字符串"

    def test_empty_text_does_not_call_process(self, bot):
        """文本为空时不触发 _process_query"""
        event = SimpleNamespace(content_text="", chat_id="oc_empty")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            mock_process.assert_not_called()

    def test_filter_mentions_applied(self, bot):
        """@bot mention 被正确过滤"""
        event = SimpleNamespace(content_text="@bot 实际问题", chat_id="oc_mention")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            assert mock_process.call_args[0][1] == "实际问题"

    def test_message_count_increments(self, bot):
        """每次调用 _handle_message_event 计数器递增"""
        event = SimpleNamespace(content_text="test", chat_id="oc_cnt")
        with patch.object(bot, "_process_query"):
            bot._handle_message_event(event)
            assert bot._message_count == 1
            bot._handle_message_event(event)
            assert bot._message_count == 2

    def test_first_message_cancels_health_timer(self, bot):
        """首条消息到达时取消健康检查计时器"""
        mock_timer = MagicMock()
        bot._health_timer = mock_timer
        event = SimpleNamespace(content_text="首条消息", chat_id="oc_first")
        with patch.object(bot, "_process_query"):
            bot._handle_message_event(event)
        mock_timer.cancel.assert_called_once()
        assert bot._health_timer is None

    def test_no_chat_id_defaults_to_empty_string(self, bot):
        """event 没有 chat_id 属性时使用空字符串"""
        event = SimpleNamespace(content_text="没有chat_id")
        with patch.object(bot, "_process_query") as mock_process:
            bot._handle_message_event(event)
            assert mock_process.call_args[0][0] == ""

    def test_exception_in_handling_is_caught(self, bot, caplog):
        """处理消息事件时发生异常不会向外抛出"""
        event = SimpleNamespace(content_text="trigger_error", chat_id="oc_err")
        with patch.object(bot, "_process_query", side_effect=RuntimeError("boom")):
            with caplog.at_level(logging.ERROR):
                bot._handle_message_event(event)  # 不应抛出
            assert any("处理消息事件失败" in r.message for r in caplog.records)


class TestHealthCheck:
    def test_health_check_logs_when_no_messages(self, bot, caplog):
        """30秒内无消息时输出诊断提示"""
        bot._start_time = time.time() - 35
        bot._message_count = 0
        with caplog.at_level(logging.WARNING):
            bot._health_check()
        assert any("未收到任何消息事件" in r.message for r in caplog.records)

    def test_health_check_silent_when_messages_received(self, bot, caplog):
        """已收到消息时不输出警告"""
        bot._message_count = 3
        with caplog.at_level(logging.WARNING):
            bot._health_check()
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_records) == 0


class TestProcessQuery:
    def test_detects_followup_queries(self, bot):
        assert bot._is_followup("刚才那个问题具体怎么做")
        assert bot._is_followup("还有吗")
        assert not bot._is_followup("QNX resource manager 怎么配置")

    def test_sends_formatted_reply(self, bot):
        """正常流程：KB检索 → LLM综合 → 发送"""
        bot.formatter = MagicMock()
        context_pack = {
            "query": "QNX priority inheritance技术问题",
            "chunk_count": 1,
            "document_count": 1,
            "selected_chunks": [
                {"document_title": "Doc1", "text": "内容片段", "score": 0.9}
            ],
        }
        bot.local_api.get_context_pack.return_value = context_pack
        bot.formatter.format_context_pack.return_value = "格式化结果"
        bot.formatter.truncate_message.return_value = "合成回答"
        bot.llm_agent.is_chitchat.return_value = False
        bot.llm_agent.synthesize.return_value = "合成回答"

        bot._process_query("oc_test", "QNX priority inheritance技术问题")

        bot.local_api.get_context_pack.assert_called_once()
        bot.llm_agent.synthesize.assert_called_once()
        bot.feishu_api.send_text_message.assert_called_once_with("oc_test", "合成回答")
        assert bot._history["oc_test"]
        assert bot._last_query["oc_test"] == "QNX priority inheritance技术问题"

    def test_followup_reuses_previous_search_query_and_passes_history(self, bot):
        context_pack = {
            "query": "QNX priority inheritance技术问题",
            "chunk_count": 1,
            "document_count": 1,
            "selected_chunks": [
                {"document_title": "Doc1", "text": "内容片段", "score": 0.9}
            ],
        }
        bot.local_api.get_context_pack.return_value = context_pack
        bot.formatter.format_context_pack.return_value = "格式化结果"
        bot.formatter.truncate_message.side_effect = lambda text, max_length: text
        bot.llm_agent.is_chitchat.return_value = False
        bot.llm_agent.synthesize.return_value = "合成回答"

        bot._process_query("oc_thread", "QNX priority inheritance技术问题")
        bot._process_query("oc_thread", "刚才那个具体怎么做")

        calls = bot.local_api.get_context_pack.call_args_list
        assert calls[0].kwargs["query"] == "QNX priority inheritance技术问题"
        assert calls[1].kwargs["query"] == "QNX priority inheritance技术问题"
        second_synthesize_kwargs = bot.llm_agent.synthesize.call_args_list[1].kwargs
        assert second_synthesize_kwargs["history"]

    def test_low_score_sends_not_found(self, bot):
        """所有 chunk 的 score 低于阈值时发送"未找到相关内容" """
        context_pack = {
            "query": "冷门问题",
            "chunk_count": 1,
            "document_count": 1,
            "selected_chunks": [
                {"document_title": "Doc1", "text": "低分内容", "score": -50.0}
            ],
        }
        bot.local_api.get_context_pack.return_value = context_pack

        bot._process_query("oc_low", "冷门问题")

        bot.feishu_api.send_text_message.assert_called_once_with("oc_low", "未找到相关内容")

    def test_empty_chunks_sends_reply(self, bot):
        """selected_chunks 为空时正常走格式化流程（由 formatter 处理空结果）"""
        context_pack = {
            "query": "空查询",
            "chunk_count": 0,
            "document_count": 0,
            "selected_chunks": [],
        }
        bot.local_api.get_context_pack.return_value = context_pack
        bot.formatter.format_context_pack.return_value = "未找到相关内容"
        bot.formatter.truncate_message.return_value = "未找到相关内容"

        bot._process_query("oc_empty", "空查询")

        bot.feishu_api.send_text_message.assert_called_once_with("oc_empty", "未找到相关内容")

    def test_exception_sends_error_message(self, bot):
        """处理查询异常时向用户发送错误提示"""
        bot.local_api.get_context_pack.side_effect = RuntimeError("API挂了")

        bot._process_query("oc_err", "第三方接口调用异常问题")

        bot.feishu_api.send_text_message.assert_called_once()
        sent_text = bot.feishu_api.send_text_message.call_args[0][1]
        assert "处理查询时出错" in sent_text

    def test_gap_report_included_when_reference_exists(self, bot, tmp_path):
        """reference_markdown_path 存在时，仍走 LLM 合成流程并正常回复"""
        ref_file = tmp_path / "ref.md"
        ref_file.write_text("# reference")
        bot.config.reference_markdown_path = str(ref_file)

        context_pack = {
            "query": "QNX内核内存保护机制技术问题",
            "chunk_count": 1,
            "document_count": 1,
            "selected_chunks": [
                {"document_title": "Doc1", "text": "内容", "score": 0.5}
            ],
        }
        bot.local_api.get_context_pack.return_value = context_pack
        bot.formatter.format_context_pack.return_value = "上下文"
        bot.formatter.truncate_message.return_value = "合成回答"
        bot.llm_agent.synthesize.return_value = "合成回答"

        bot._process_query("oc_gap", "QNX内核内存保护机制技术问题")

        bot.local_api.get_context_pack.assert_called_once()
        bot.llm_agent.synthesize.assert_called_once()
        bot.feishu_api.send_text_message.assert_called_once()


class TestHandleRejectEvent:
    def test_logs_with_message_details(self, bot, caplog):
        """被过滤消息包含内容时记录详细信息"""
        msg = SimpleNamespace(content_text="敏感内容", chat_id="oc_reject")
        event = SimpleNamespace(reason="safety_filter", message=msg)
        with caplog.at_level(logging.WARNING):
            bot._handle_reject_event(event)
        assert any("消息被过滤" in r.message and "safety_filter" in r.message for r in caplog.records)

    def test_logs_without_message(self, bot, caplog):
        """event.message 为 None 时记录事件类型"""
        event = SimpleNamespace(reason="unknown_reason", message=None)
        with caplog.at_level(logging.WARNING):
            bot._handle_reject_event(event)
        assert any("消息被过滤" in r.message and "unknown_reason" in r.message for r in caplog.records)

    def test_truncates_long_text(self, bot, caplog):
        """被过滤消息文本过长时截断为50字符"""
        long_text = "x" * 200
        msg = SimpleNamespace(content_text=long_text, chat_id="oc_long")
        event = SimpleNamespace(reason="test", message=msg)
        with caplog.at_level(logging.WARNING):
            bot._handle_reject_event(event)
        log_text = caplog.records[-1].message
        # 日志中的 text 部分应被截断到50字符
        assert "x" * 50 in log_text
        assert "x" * 51 not in log_text
        # 日志中的 text 部分应被截断到50字符
        assert "x" * 50 in log_text
        assert "x" * 51 not in log_text
