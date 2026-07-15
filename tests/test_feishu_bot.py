import json
import os
from unittest.mock import MagicMock, patch

import pytest

from agent_knowledge_hub.feishu_bot import (
    FeishuConfig,
    FeishuAPI,
    FeishuMessageHandler,
    FormattedReply,
    KnowledgeQueryResponder,
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


class TestKnowledgeQueryResponder:
    def test_process_query_builds_formatted_reply_for_evidence(self):
        config = FeishuConfig(processed_dir="/tmp/processed", fts_index_path="fts.db")
        local_api = MagicMock()
        formatter = MagicMock()
        llm_agent = MagicMock()
        context_pack = {
            "selected_chunks": [
                {"document_title": "Doc1", "text": "evidence", "score": 1.0}
            ]
        }
        formatted = FormattedReply(title="标题", summary="答案", plain_text="答案")
        local_api.get_context_pack.return_value = context_pack
        formatter.format_context_pack.return_value = "context text"
        formatter.truncate_message.side_effect = lambda text, max_length: text
        formatter.build_user_reply.return_value = formatted
        llm_agent.is_chitchat.return_value = False
        llm_agent.synthesize.return_value = "answer json"

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("技术问题", history=[{"role": "user", "content": "上一轮"}])

        assert result.has_evidence is True
        assert result.formatted_reply is formatted
        assert result.text == "answer json"
        local_api.get_context_pack.assert_called_once()
        llm_agent.synthesize.assert_called_once_with(
            "技术问题",
            "context text",
            history=[{"role": "user", "content": "上一轮"}],
        )

    def test_process_query_does_not_truncate_llm_json_before_parsing(self):
        config = FeishuConfig(processed_dir="/tmp/processed", max_reply_length=20)
        local_api = MagicMock()
        formatter = MessageFormatter()
        llm_agent = MagicMock()
        context_pack = {
            "selected_chunks": [
                {"document_title": "Doc1", "text": "evidence", "score": 1.0}
            ]
        }
        long_json = json.dumps(
            {
                "title": "很长的结构化回答",
                "summary": "x" * 200,
                "answer_type": "solution_design",
                "solution": {
                    "recommended": "推荐方案" + ("x" * 200),
                    "steps": ["第一步"],
                },
                "confidence": "中：测试",
            },
            ensure_ascii=False,
        )
        local_api.get_context_pack.return_value = context_pack
        llm_agent.is_chitchat.return_value = False
        llm_agent.synthesize.return_value = long_json

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("给一个方案")

        assert result.formatted_reply is not None
        assert result.formatted_reply.answer_type == "solution_design"
        assert result.formatted_reply.solution["recommended"].startswith("推荐方案")

    def test_process_query_chitchat_skips_retrieval(self):
        config = FeishuConfig(processed_dir="/tmp/processed")
        local_api = MagicMock()
        formatter = MagicMock()
        llm_agent = MagicMock()
        formatter.truncate_message.side_effect = lambda text, max_length: text
        llm_agent.is_chitchat.return_value = True
        llm_agent.direct_reply.return_value = "你好"

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("你好")

        assert result.has_evidence is False
        assert result.formatted_reply is None
        assert result.text == "你好"
        local_api.get_context_pack.assert_not_called()

    def test_process_query_frontend_out_of_scope_skips_retrieval(self):
        config = FeishuConfig(processed_dir="/tmp/processed")
        local_api = MagicMock()
        formatter = MessageFormatter()
        llm_agent = MagicMock()
        llm_agent.is_chitchat.return_value = False

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("帮我用 React 写个页面显示 QNX 日志。")

        assert result.has_evidence is False
        assert result.formatted_reply is None
        assert "前端" in result.text
        local_api.get_context_pack.assert_not_called()

    def test_process_query_weather_out_of_scope_skips_retrieval(self):
        config = FeishuConfig(processed_dir="/tmp/processed")
        local_api = MagicMock()
        formatter = MessageFormatter()
        llm_agent = MagicMock()
        llm_agent.is_chitchat.return_value = False

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("你好，在吗？帮我看看今天天气。")

        assert result.has_evidence is False
        assert "天气" in result.text
        local_api.get_context_pack.assert_not_called()

    def test_process_query_missing_followup_context_skips_retrieval(self):
        config = FeishuConfig(processed_dir="/tmp/processed")
        local_api = MagicMock()
        formatter = MessageFormatter()
        llm_agent = MagicMock()
        llm_agent.is_chitchat.return_value = False

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("那这个方案在 hypervisor 客户机里还成立吗？")

        assert result.has_evidence is False
        assert "上文" in result.text
        local_api.get_context_pack.assert_not_called()

    def test_process_query_qnx_log_export_stays_in_scope(self):
        config = FeishuConfig(processed_dir="/tmp/processed")
        local_api = MagicMock()
        formatter = MagicMock()
        llm_agent = MagicMock()
        context_pack = {
            "selected_chunks": [
                {"document_title": "Doc1", "text": "slog2 evidence", "score": 1.0}
            ]
        }
        formatted = FormattedReply(title="标题", summary="答案", plain_text="答案")
        local_api.get_context_pack.return_value = context_pack
        formatter.format_context_pack.return_value = "context text"
        formatter.build_user_reply.return_value = formatted
        llm_agent.is_chitchat.return_value = False
        llm_agent.synthesize.return_value = "answer json"

        result = KnowledgeQueryResponder(
            config=config,
            local_api=local_api,
            formatter=formatter,
            llm_agent=llm_agent,
        ).process_query("QNX 上怎么把 slog2 日志导出给上层 UI？")

        assert result.has_evidence is True
        local_api.get_context_pack.assert_called_once()

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

    def test_format_context_pack_prefers_api_markdown(self):
        result = {
            "query": "test query",
            "markdown": "# Context Pack\n\nfull evidence text",
            "selected_chunks": [
                {
                    "document_title": "Doc1",
                    "text": "short text",
                    "score": 0.85,
                }
            ],
        }

        text = MessageFormatter.format_context_pack(result)

        assert text == "# Context Pack\n\nfull evidence text"

    def test_format_context_pack_truncates_long_markdown(self):
        result = {
            "query": "test query",
            "markdown": "# Context Pack\n\n" + ("x" * 200),
            "selected_chunks": [
                {
                    "document_title": "Doc1",
                    "text": "short text",
                    "score": 0.85,
                }
            ],
        }

        text = MessageFormatter.format_context_pack(result, max_context_length=40)

        assert len(text) == 40
        assert text.endswith("...")

    def test_build_user_reply_extracts_top_evidence(self):
        result = {
            "selected_chunks": [
                {
                    "document_title": "QNX Memory Guide",
                    "section_titles": ["mmap"],
                    "page_start": 12,
                    "text": "Use PROT_NOCACHE when mapping device memory to avoid stale cache data.",
                    "score": 10.0,
                    "evidence_ids": ["span_1"],
                },
                {
                    "document_title": "QNX Startup Guide",
                    "section_titles": ["cache"],
                    "page_start": 34,
                    "text": "Cache maintenance is required before sharing buffers with DMA devices.",
                    "score": 9.0,
                    "evidence_ids": ["span_2"],
                },
                {
                    "document_title": "Extra",
                    "section_titles": ["ignored"],
                    "page_start": 99,
                    "text": "This third item should be omitted by default.",
                    "score": 8.0,
                    "evidence_ids": ["span_3"],
                },
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="缓存问题怎么处理？",
            answer_text="结论：需要使用非缓存映射，并检查 DMA buffer 的 cache 维护。",
            context_pack=result,
            max_evidence_items=2,
        )

        assert reply.title == "缓存问题怎么处理？"
        assert "结论" in reply.summary
        assert len(reply.evidence_items) == 2
        assert reply.evidence_items[0]["document_title"] == "QNX Memory Guide"
        assert "page 12" in reply.evidence_items[0]["location"]
        assert "span_1" in reply.evidence_items[0]["evidence_ids"]

    def test_format_context_pack_includes_candidate_facts_for_llm(self):
        context_pack = {
            "markdown": "# Context Pack\n\nEvidence text",
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Debugging"],
                    "page_start": 309,
                    "text": "the screeninfo utility and gltracelogger utility are available",
                    "score": 10,
                    "evidence_ids": ["span_tools"],
                }
            ],
        }

        text = MessageFormatter.format_context_pack(context_pack)

        assert "【候选事实】" in text
        assert "name=screeninfo" in text
        assert "name=gltracelogger" in text

    def test_build_user_reply_parses_llm_sections_without_duplicate_evidence(self):
        answer = "\n".join(
            [
                "结论",
                "QNX 提供了图形调试工具和渲染演示程序。",
                "**关键依据**",
                "- Screen Graphics Subsystem Developers Guide 的 Debugging 章节列出 screeninfo 和 gltrace 工具。",
                "- 文档还提到 gles3-gears 可用于验证 3D 渲染管线。",
                "**局限**",
                "- 当前材料未覆盖窗口合成专用 demo。",
                "【置信度：高】参考资料直接提供了图形调试章节。",
            ]
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "Irrelevant IDE Guide",
                    "section_titles": ["Debug tab"],
                    "page_start": 191,
                    "text": "GDB debugger launch configuration.",
                    "score": 9.0,
                    "evidence_ids": ["span_irrelevant"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="qnx是否提供debug渲染显示问题的demo或工具",
            answer_text=answer,
            context_pack=context_pack,
        )
        text = MessageFormatter.format_user_answer_text(reply)

        assert reply.summary == "QNX 提供了图形调试工具和渲染演示程序。"
        assert len(reply.evidence_items) == 2
        assert "Screen Graphics" in reply.evidence_items[0]["summary"]
        assert reply.caveats == ["当前材料未覆盖窗口合成专用 demo。"]
        assert reply.confidence.startswith("中：未绑定到可追溯证据")
        assert "Irrelevant IDE Guide" not in text
        assert text.count("关键依据") == 1
        assert text.count("置信度") == 1

    def test_build_user_reply_prefers_llm_json_schema(self):
        answer = json.dumps(
            {
                "title": "QNX 渲染调试工具",
                "direct_answer": {
                    "tools": "有，当前资料确认 Display Surface Dumps 和 tracelogger。",
                    "demos": "未直接检索到专门 demo。",
                },
                "summary": "QNX 提供 Screen 调试工具和 gles3-gears demo。",
                "answer_type": "tool_lookup",
                "details": [
                    {
                        "name": "screeninfo",
                        "purpose": "查看 Screen 对象和显示状态。",
                        "usage": "在目标机上运行 screeninfo 收集状态。",
                        "when_to_use": "怀疑显示层级或窗口状态异常时使用。",
                    },
                    {
                        "name": "win-vsync",
                        "purpose": "显示窗口层次中的软件光栅化内容。",
                        "usage": "运行示例观察显示刷新行为。",
                    },
                ],
                "key_points": ["先检查 Screen Debugging 章节。"],
                "evidence_items": [
                    {
                        "name": "Display Surface Dumps",
                        "source": "Qualcomm Software Developer Resources / Display / Debug common display issues",
                        "why_relevant": "用于导出显示表面数据，辅助分析显示异常。",
                        "evidence_ids": ["span_screen"],
                    }
                ],
                "caveats": ["没有看到窗口合成专用 demo。"],
                "next_steps": ["先运行 screeninfo。"],
                "confidence": "高：文档直接列出工具。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "text": "Display Surface Dumps can export display surface data for debugging.",
                    "score": 9.0,
                    "evidence_ids": ["span_screen"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="qnx是否提供debug渲染显示问题的demo或工具",
            answer_text=answer,
            context_pack=context_pack,
        )

        assert reply.title == "QNX 渲染调试工具查询结果"
        assert reply.direct_answer["tools"].startswith("有")
        assert reply.direct_answer["demos"].startswith("未直接")
        assert reply.summary == "QNX 提供 Screen 调试工具和 gles3-gears demo。"
        assert reply.answer_type == "tool_lookup"
        assert reply.details[0]["name"] == "screeninfo"
        assert "查看 Screen" in reply.details[0]["purpose"]
        assert reply.details[1]["name"] == "win-vsync"
        assert reply.key_points == ["先检查 Screen Debugging 章节。"]
        assert reply.evidence_items[0]["document_title"] == "QNX Screen Guide"
        assert "Display Surface Dumps" in reply.evidence_items[0]["summary"]
        assert reply.evidence_items[0]["evidence_ids"] == ["span_screen"]
        assert reply.caveats == ["没有看到窗口合成专用 demo。"]
        assert reply.next_steps == ["先运行 screeninfo。"]
        assert reply.confidence == "高：文档直接列出工具。"

    def test_build_user_reply_replaces_hallucinated_evidence_ids_with_retrieved_ids(self):
        answer = json.dumps(
            {
                "title": "screen_create_window 区别",
                "direct_answer": {
                    "primary": "screen_create_window() 创建默认应用窗口。",
                },
                "summary": "需要其他窗口类型时使用 screen_create_window_type()。",
                "answer_type": "api_usage",
                "evidence_items": [
                    {
                        "name": "模型编造证据",
                        "source": "LLM 摘要",
                        "why_relevant": "模型给出了看似相关但不可追溯的证据 ID。",
                        "evidence_ids": ["span_xxx"],
                    }
                ],
                "confidence": "高：文档直接给出。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Windows", "screen_create_window()"],
                    "page_start": 120,
                    "text": "screen_create_window() creates an application window.",
                    "score": 10.0,
                    "evidence_ids": ["span_real_window"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="screen_create_window 和 screen_create_window_type 有什么区别？",
            answer_text=answer,
            context_pack=context_pack,
        )

        evidence_refs = MessageFormatter._collect_evidence_refs(reply)

        assert [ref["evidence_id"] for ref in evidence_refs] == ["span_real_window"]
        assert reply.evidence_items[0]["document_title"] == "QNX Screen Guide"
        assert "span_xxx" not in json.dumps(reply.evidence_items, ensure_ascii=False)

    def test_build_user_reply_uses_retrieved_evidence_when_llm_mixes_real_and_fake_ids(self):
        answer = json.dumps(
            {
                "title": "混合证据测试",
                "summary": "模型给了一个真实 id 和一个幻觉 id。",
                "answer_type": "api_usage",
                "evidence_items": [
                    {
                        "name": "模型证据条目",
                        "source": "LLM source should not be trusted",
                        "why_relevant": "LLM relevance should not become trace source.",
                        "evidence_ids": ["span_real_window", "span_fake_window"],
                    }
                ],
                "confidence": "高：模型声称证据直接支持。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Windows"],
                    "page_start": 120,
                    "text": "screen_create_window() creates an application window.",
                    "score": 10.0,
                    "evidence_ids": ["span_real_window"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="screen_create_window 怎么用？",
            answer_text=answer,
            context_pack=context_pack,
        )

        rendered_evidence = json.dumps(reply.evidence_items, ensure_ascii=False)
        assert reply.evidence_items[0]["document_title"] == "QNX Screen Guide"
        assert reply.evidence_items[0]["evidence_ids"] == ["span_real_window"]
        assert "span_fake_window" not in rendered_evidence
        assert "LLM source should not be trusted" not in rendered_evidence
        assert reply.confidence.startswith("高")

    def test_build_user_reply_prioritizes_core_api_evidence_over_title_fragments(self):
        answer = json.dumps(
            {
                "title": "使用 screen_wait_vsync 实现帧率统计",
                "direct_answer": {
                    "primary": "使用 screen_wait_vsync() 阻塞等待下一次 vsync。",
                },
                "summary": "screen_wait_vsync() 可用于统计帧间隔。",
                "answer_type": "api_usage",
                "details": [
                    {
                        "name": "screen_wait_vsync()",
                        "purpose": "等待下一次 vsync。",
                        "usage": "int screen_wait_vsync(screen_display_t display);",
                    }
                ],
                "confidence": "高：文档直接支持。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Asynchronous Notifications", "Screen notifies you when:Screen API object"],
                    "page_start": 161,
                    "text": "Screen notifies you when:Screen API object",
                    "score": 20.0,
                    "evidence_ids": ["span_title"],
                },
                {
                    "document_title": "QNX Camera Guide",
                    "section_titles": ["Image Buffer Access", "Using stream mode"],
                    "page_start": 28,
                    "text": "Using stream mode Streams give you access to screen_buffer_t objects.",
                    "score": 19.0,
                    "evidence_ids": ["span_camera"],
                },
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Screen library reference", "screen_wait_vsync()"],
                    "page_start": 560,
                    "text": (
                        "screen_wait_vsync() Block the calling thread until the next "
                        "vsync happens on the specified display. Synopsis: int "
                        "screen_wait_vsync(screen_display_t display);"
                    ),
                    "score": 18.0,
                    "evidence_ids": ["span_wait_vsync"],
                },
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="screen 的 vsync 事件怎么订阅？我想做帧率统计。",
            answer_text=answer,
            context_pack=context_pack,
        )

        evidence_ids = MessageFormatter._collect_evidence_ids(reply)
        rendered_evidence = json.dumps(reply.evidence_items, ensure_ascii=False)

        assert evidence_ids[0] == "span_wait_vsync"
        assert "span_title" not in evidence_ids[:2]
        assert "QNX Camera Guide" not in rendered_evidence

    def test_build_user_reply_filters_toc_chunks_when_body_evidence_exists(self):
        answer = json.dumps(
            {
                "title": "OpenWF 多显示输出配置",
                "summary": "在 Wfdcfg 的 mode 数组中添加多个 timing 条目。",
                "answer_type": "how_to",
                "details": [
                    {
                        "name": "mode 数组",
                        "purpose": "保存多个显示模式的时序参数。",
                        "usage": "在 wfdcfg.c 中添加 struct mode 条目。",
                    }
                ],
                "confidence": "中：多输出绑定仍需确认。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "OpenWF Guide",
                    "section_titles": [
                        "About OpenWF Display Configuration + Before you beginWhat you need + Setting timing parametersHow to set timing parameters"
                    ],
                    "page_start": 9,
                    "text": (
                        "About OpenWF Display Configuration\n\n"
                        "This table may help you find what you need in this guide: Go to:To find out about:\n\n"
                        "Before you beginWhat you need\n\nGetting the source codeHow to get the source code"
                    ),
                    "score": 30.0,
                    "evidence_ids": ["span_toc"],
                },
                {
                    "document_title": "OpenWF Guide",
                    "section_titles": ["Setting timing parameters", "60 Hz (CVT)"],
                    "page_start": 18,
                    "text": (
                        "36148488544108019201485001080p @ 60 Hz (1920x1080)\n\n"
                        "You'll need to configure these timing parameters in your Wfdcfg source "
                        "(wfdcfg.c) within a mode structure. It's possible that you may have "
                        "multiple entries in your mode array when more than one physical display "
                        "is connected or when your display supports multiple modes."
                    ),
                    "score": 20.0,
                    "evidence_ids": ["span_heading", "span_timing"],
                },
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="怎么用 OpenWF 配置多个显示输出的分辨率和刷新率？",
            answer_text=answer,
            context_pack=context_pack,
        )
        rendered_evidence = json.dumps(reply.evidence_items, ensure_ascii=False)

        assert MessageFormatter._collect_evidence_ids(reply) == ["span_timing"]
        assert "Before you beginWhat you need" not in rendered_evidence
        assert "36148488544108019201485001080p" not in rendered_evidence
        assert "You'll need to configure these timing parameters" in rendered_evidence

    def test_build_user_reply_falls_back_to_retrieved_evidence_for_unknown_api(self):
        answer = json.dumps(
            {
                "title": "screen_share_buffer_zerocopy() 查询",
                "summary": "未找到 screen_share_buffer_zerocopy() 的官方说明。",
                "answer_type": "api_usage",
                "details": [
                    {
                        "name": "screen_share_buffer_zerocopy()",
                        "purpose": "当前资料未确认该 API 存在。",
                    }
                ],
                "confidence": "低：未找到直接证据。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Resource Sharing", "Cloning"],
                    "page_start": 96,
                    "text": "screen_share_display_buffers() shares display buffers with a window.",
                    "score": 12.0,
                    "evidence_ids": ["span_share_display"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="screen_share_buffer_zerocopy() 这个函数怎么用？",
            answer_text=answer,
            context_pack=context_pack,
        )

        assert MessageFormatter._collect_evidence_ids(reply) == ["span_share_display"]
        assert reply.evidence_items[0]["document_title"] == "QNX Screen Guide"

    def test_build_user_reply_downgrades_high_confidence_when_no_traceable_ids(self):
        answer = json.dumps(
            {
                "title": "无可追溯证据测试",
                "summary": "模型声称有高置信证据。",
                "answer_type": "general",
                "evidence_items": [
                    {
                        "name": "模型证据",
                        "source": "LLM source",
                        "why_relevant": "不可追溯。",
                        "evidence_ids": ["span_xxx"],
                    }
                ],
                "confidence": "高：文档直接支持。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="测试无证据",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )

        assert MessageFormatter._collect_evidence_refs(reply) == []
        assert reply.evidence_items[0]["evidence_ids"] == []
        assert reply.confidence.startswith("中：未绑定到可追溯证据")

    def test_build_user_reply_does_not_leak_malformed_json(self):
        malformed_json = (
            '{ "title": "QNX 音频播放 pop 噪声排查方法", '
            '"summary": "现有文档未提供 pop 噪声排查方法。", '
            '"details": [ { "usage": "在 wave.c 中可调整 -n num_frags、-f fragsize 等参数， "when_to_use": "怀疑缓冲区相关问题时" } ] }'
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Audio Guide",
                    "section_titles": ["wave.c example"],
                    "page_start": 478,
                    "text": "wave.c example configures slog2 and audio playback buffer options.",
                    "score": 10.0,
                    "evidence_ids": ["span_audio"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="audio 播放有 pop 噪声，slog 里没明显错误，怎么排？",
            answer_text=malformed_json,
            context_pack=context_pack,
        )
        rendered = MessageFormatter.format_user_answer_text(reply)

        assert '{"title"' not in rendered
        assert '"details"' not in rendered
        assert "when_to_use" not in rendered
        assert reply.confidence.startswith("低")
        assert MessageFormatter._collect_evidence_ids(reply) == ["span_audio"]

    def test_build_user_reply_parses_solution_design_json(self):
        answer = json.dumps(
            {
                "title": "进程间 Screen Buffer 零拷贝共享方案",
                "answer_type": "solution_design",
                "summary": "文档没有直接给出现成方案，但可以基于 Screen buffer、共享内存和同步机制组合方案。",
                "solution": {
                    "recommended": "优先寻找平台支持的 buffer handle/import 机制；若无，则退化为共享内存近似方案。",
                    "steps": [
                        "生产者负责创建并拥有 Screen buffer。",
                        "通过受支持的 handle/import 机制传递引用。",
                        "用 fence/semaphore 协调 buffer 生命周期。"
                    ],
                    "variants": [
                        "POSIX shared memory 可作为兼容方案，但不是严格零拷贝。"
                    ],
                    "not_recommended": [
                        "不要无同步地跨进程直接传物理地址 mmap。",
                        "memcpy 到共享内存只能作为 fallback，不是真零拷贝。"
                    ],
                    "risks": [
                        "需要确认目标平台是否支持跨进程导入 Screen buffer。",
                        "需要处理 cache coherency 和 ownership。"
                    ],
                    "open_questions": [
                        "是否有平台专用 buffer sharing API。"
                    ],
                },
                "evidence_items": [
                    {
                        "name": "QNX Shared Memory",
                        "source": "System Architecture / Shared memory / page 95",
                        "why_relevant": "说明可用 POSIX 共享内存在进程间映射内存。",
                        "evidence_ids": ["span_shm"],
                    }
                ],
                "confidence": "中：方案由多个证据组合推导，不是官方单篇文档直接给出。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="给一个进程间 screen buffer 零 copy 共享的方案",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )

        assert reply.answer_type == "solution_design"
        assert reply.solution["recommended"].startswith("优先寻找")
        assert "memcpy" in reply.solution["not_recommended"][1]
        assert "cache coherency" in reply.solution["risks"][1]

    def test_solution_steps_strip_model_generated_numbering(self):
        answer = json.dumps(
            {
                "title": "QNX Off-screen 渲染到主窗口最小 Demo",
                "answer_type": "solution_design",
                "summary": "用 pixmap 离屏渲染后 blit 到窗口。",
                "solution": {
                    "recommended": "使用 pixmap + screen_blit()。",
                    "steps": [
                        "1. 创建 screen_context_t 上下文",
                        "2) 创建 screen_pixmap_t 离屏目标",
                        "步骤 6：渲染内容到 pixmap 缓冲区",
                    ],
                },
                "confidence": "中：需确认完整 demo。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="给一个用 screen 做 off-screen render 再 blit 到主 window 的最小 demo。",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        detail_card = MessageFormatter.format_detail_card(reply)
        rendered_card = json.dumps(detail_card, ensure_ascii=False)

        assert reply.solution["steps"] == [
            "创建 screen_context_t 上下文",
            "创建 screen_pixmap_t 离屏目标",
            "渲染内容到 pixmap 缓冲区",
        ]
        assert "1. 1." not in rendered_card
        assert "步骤 6" not in rendered_card

    def test_next_steps_strip_model_generated_numbering(self):
        answer = json.dumps(
            {
                "title": "内存排查",
                "summary": "先定位高内存进程。",
                "answer_type": "troubleshooting",
                "next_steps": [
                    "1. 执行 top 按内存排序。",
                    "2) 使用 pidin info 查看进程。",
                ],
                "confidence": "中：测试。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="内存一路涨到 OOM，还没定位到进程，有没有办法快速看谁在吃内存？",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        rendered = json.dumps(MessageFormatter.format_detail_card(reply), ensure_ascii=False)

        assert reply.next_steps == [
            "执行 top 按内存排序。",
            "使用 pidin info 查看进程。",
        ]
        assert "1. 1." not in rendered
        assert "2. 2)" not in rendered

    def test_solution_steps_do_not_mark_supported_apis_as_unconfirmed(self):
        answer = json.dumps(
            {
                "title": "timer + pulse 方案",
                "answer_type": "solution_design",
                "summary": "使用 timer + pulse 实现高实时定时任务。",
                "solution": {
                    "recommended": "采用 timer + pulse。",
                    "steps": [
                        "调用 ChannelCreate() 创建通道。",
                        "调用 ConnectAttach() 建立连接。",
                        "调用 timer_create() 和 timer_settime() 启动周期定时器。",
                        "调用 MsgReceive() 接收 pulse。",
                    ],
                },
                "confidence": "高：示例直接支持。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Guide",
                    "section_titles": ["Timer and pulse"],
                    "page_start": 161,
                    "text": (
                        "if ((chid = ChannelCreate(0)) == -1) ... "
                        "ConnectAttach(...); timer_create(...); timer_settime(...); "
                        "MsgReceive(chid, &msg, sizeof(msg), NULL);"
                    ),
                    "evidence_ids": ["span_timer"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="定时任务用 timer + pulse 还是单独线程 sleep，实时性要求高？",
            answer_text=answer,
            context_pack=context_pack,
        )

        open_questions = reply.solution.get("open_questions") or []
        assert not any("需确认 API 是否存在" in item for item in open_questions)
        assert len(reply.solution["steps"]) == 4

    def test_unsupported_api_details_are_removed_and_called_out_without_summary_surgery(self):
        answer = json.dumps(
            {
                "title": "Linux DMA 接口迁移到 QNX",
                "summary": "可以使用 rsrcmgr_attach() 和 spi_dma_xfer()。",
                "answer_type": "concept",
                "details": [
                    {
                        "name": "rsrcmgr_attach()",
                        "purpose": "申请 DMA 通道。",
                        "usage": "调用 rsrcmgr_attach()。",
                    },
                    {
                        "name": "rsrcdbmgr_attach()",
                        "purpose": "从资源数据库申请 DMA 通道。",
                        "usage": "调用 rsrcdbmgr_attach()。",
                    },
                    {
                        "name": "spi_dma_xfer()",
                        "purpose": "SPI DMA 传输。",
                        "usage": "调用 spi_dma_xfer()。",
                    },
                ],
                "confidence": "高：文档直接支持。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX C Library Reference",
                    "section_titles": ["rsrcdbmgr_attach()"],
                    "page_start": 2995,
                    "text": "rsrcdbmgr_attach(&req, count) requests one DMA channel.",
                    "evidence_ids": ["span_rsrcdbmgr"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="我要把一段 Linux 的 DMA 代码移到 QNX，接口对应关系是什么？",
            answer_text=answer,
            context_pack=context_pack,
        )

        detail_names = [item["name"] for item in (reply.details or [])]
        assert detail_names == ["rsrcdbmgr_attach()"]
        assert "rsrcmgr_attach()" in reply.summary
        assert "spi_dma_xfer()" in reply.summary
        assert any("未在检索证据中确认的 API" in item for item in (reply.caveats or []))
        assert reply.confidence.startswith("中")

    def test_precise_signal_number_from_compacted_table_lowers_confidence(self):
        answer = json.dumps(
            {
                "title": "命令行触发内存泄漏检查",
                "summary": "发送 SIGRT#142 即可触发 leaks 命令。",
                "answer_type": "how_to",
                "details": [
                    {
                        "name": "SIGRT#142",
                        "purpose": "触发 leaks 命令。",
                        "usage": "kill -s SIGRT#142 <pid>",
                    }
                ],
                "confidence": "高：文档直接说明。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX IDE Guide",
                    "section_titles": ["Controlling librcheck"],
                    "page_start": 86,
                    "text": (
                        "command DescriptionCommandSymbolNumber "
                        "MALLOC_CTRL_CMDExecute a command stored in the file. "
                        "leaksSIGRT#142 stopSIGRT#243 startSIGRT#344"
                    ),
                    "evidence_ids": ["span_signal_table"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="有没有办法命令行触发一次内存泄漏检查而不用改代码？",
            answer_text=answer,
            context_pack=context_pack,
        )

        assert reply.confidence.startswith("中")
        assert any("粘连表格" in item for item in (reply.caveats or []))

    def test_solution_design_card_renders_solution_sections(self):
        reply = FormattedReply(
            title="Screen Buffer 零拷贝共享方案",
            summary="基于证据组合出可落地方案。",
            answer_type="solution_design",
            solution={
                "recommended": "优先使用平台支持的 buffer handle/import 机制。",
                "steps": ["生产者创建 buffer。", "消费者导入 handle。"],
                "variants": ["共享内存近似方案。"],
                "not_recommended": ["memcpy fallback 不是真零拷贝。"],
                "risks": ["需要确认 cache coherency。"],
                "open_questions": ["平台是否支持导出 handle。"],
            },
            confidence="中：方案由证据组合推导。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "推荐方案" in rendered_card
        assert "实施步骤" in rendered_card
        assert "可选方案" in rendered_card
        assert "不推荐做法" in rendered_card
        assert "风险与待确认" in rendered_card
        assert "memcpy fallback 不是真零拷贝" in rendered_card

    def test_solution_query_forces_solution_design_even_if_model_uses_tool_lookup(self):
        answer = json.dumps(
            {
                "title": "进程间 Screen Buffer 零拷贝共享方案",
                "answer_type": "tool_lookup",
                "direct_answer": {
                    "tools": "不确定，文档未提供专门工具。",
                    "demos": "没有。",
                },
                "summary": "可以结合 POSIX 共享内存与 Screen Buffer 获取 API 实现底层共享。",
                "details": [
                    {
                        "name": "共享内存创建与映射",
                        "purpose": "在不同进程间建立同一物理内存区域的映射。",
                        "usage": "使用 shm_open() 和 mmap()。",
                    }
                ],
                "caveats": [
                    "SCREEN_PROPERTY_POINTER 可能仅在本地上下文有效。",
                    "直接映射物理地址是危险做法。",
                ],
                "evidence_items": [],
                "confidence": "中：方案基于推断。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="给一个进程间screen buffer零copy共享的方案",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert reply.answer_type == "solution_design"
        assert "推荐方案" in rendered_card
        assert "不推荐做法" in rendered_card
        assert "memcpy fallback 不是真零拷贝" in rendered_card
        assert "工具：" not in rendered_card

    def test_solution_recommended_echo_is_removed(self):
        answer = json.dumps(
            {
                "title": "重复推荐方案测试",
                "answer_type": "solution_design",
                "summary": "先查看现场日志，再根据证据定位问题。",
                "solution": {
                    "recommended": "先查看现场日志，再根据证据定位问题。",
                    "steps": ["查看 slog2 日志。"],
                },
                "confidence": "中：基于证据组合。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="系统日志被刷爆了根本看不过来，怎么按进程或等级过滤 slog2？",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        rendered = json.dumps(MessageFormatter.format_detail_card(reply), ensure_ascii=False)

        assert "**推荐方案**" not in rendered
        assert "实施步骤" in rendered

    def test_uncertain_variant_moves_to_open_questions(self):
        answer = json.dumps(
            {
                "title": "vsync 统计方案",
                "answer_type": "solution_design",
                "summary": "使用 screen_wait_vsync() 做帧率统计。",
                "solution": {
                    "recommended": "在独立线程中调用 screen_wait_vsync()。",
                    "steps": ["调用 screen_wait_vsync() 记录时间戳。"],
                    "variants": ["使用 screen_notify() 异步通知，但需确认是否严格对应 vsync。"],
                },
                "confidence": "中：测试。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["screen_wait_vsync()"],
                    "page_start": 560,
                    "text": "screen_wait_vsync() blocks until the next vsync happens.",
                    "evidence_ids": ["span_wait"],
                }
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="screen 的 vsync 事件怎么订阅？我想做帧率统计。",
            answer_text=answer,
            context_pack=context_pack,
        )

        assert not reply.solution.get("variants")
        assert any("screen_notify" in item for item in reply.solution.get("open_questions", []))

    def test_visible_text_strips_html_break_tags(self):
        answer = json.dumps(
            {
                "title": "mm-renderer 播放流程",
                "summary": "第一步<br>第二步<br/>第三步",
                "answer_type": "how_to",
                "confidence": "中：测试。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="给个 mm-renderer 播放一个本地视频文件的最小流程。",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        rendered = json.dumps(MessageFormatter.format_detail_card(reply), ensure_ascii=False)

        assert "<br" not in rendered.lower()
        assert "第一步" in rendered
        assert "第二步" in rendered

    def test_visible_text_corrects_smmuman_typo(self):
        answer = json.dumps(
            {
                "title": "smhuman 服务说明",
                "summary": "smhuman 用于管理 SMMU。",
                "answer_type": "concept",
                "confidence": "中：测试。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="SMMUMAN 是干什么的？",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        rendered = json.dumps(MessageFormatter.format_detail_card(reply), ensure_ascii=False)

        assert "smhuman" not in rendered.lower()
        assert "smmuman" in rendered.lower()

    def test_visible_card_removes_model_generated_evidence_numbers(self):
        answer = json.dumps(
            {
                "title": "证据编号测试",
                "summary": "参考 Evidence 5 和 Evidence 6 可以确认该结论。",
                "answer_type": "general",
                "details": [
                    {
                        "name": "说明",
                        "purpose": "Evidence 5 提到某工具。",
                    }
                ],
                "evidence_items": [
                    {
                        "name": "真实证据",
                        "source": "Doc / page 1",
                        "why_relevant": "真实证据说明。",
                        "evidence_ids": ["span_real"],
                    }
                ],
                "confidence": "中：Evidence 6 需要确认。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="测试",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        card = MessageFormatter.format_detail_card(reply)
        visible_card = json.loads(json.dumps(card))
        for element in visible_card.get("elements", []):
            for action in element.get("actions", []):
                action.pop("value", None)
        rendered_card = json.dumps(visible_card, ensure_ascii=False)

        assert "Evidence 5" not in rendered_card
        assert "Evidence 6" not in rendered_card
        assert "真实证据" in rendered_card

    def test_solution_steps_with_unsupported_api_are_moved_to_open_questions(self):
        answer = json.dumps(
            {
                "title": "Screen Buffer 零拷贝共享方案",
                "summary": "基于证据组合方案。",
                "answer_type": "solution_design",
                "solution": {
                    "recommended": "尝试 Screen stream 共享。",
                    "steps": [
                        "调用 screen_clone_stream() 克隆 stream。",
                        "调用 screen_acquire_buffer() 获取 buffer。",
                    ],
                    "open_questions": [],
                },
                "evidence_items": [
                    {
                        "name": "Stream sharing",
                        "source": "Screen Guide / Resource Sharing / page 95",
                        "why_relevant": "说明 stream sharing buffers 概念。",
                        "evidence_ids": ["span_stream"],
                    }
                ],
                "confidence": "中：需要验证 API。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="给一个进程间screen buffer零copy共享的方案",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )

        assert not reply.solution.get("steps")
        assert any("screen_clone_stream" in item for item in reply.solution["open_questions"])
        assert any("screen_acquire_buffer" in item for item in reply.solution["open_questions"])

    def test_truncated_json_does_not_leak_raw_json_into_card(self):
        truncated = (
            '{"title":"进程间 screen buffer 零拷贝共享方案",'
            '"answer_type":"solution_design",'
            '"summary":"使用 screen_share_display_buffers() 让窗口直接引用'
        )

        reply = MessageFormatter.build_user_reply(
            query="给一个进程间screen buffer零copy共享的方案",
            answer_text=truncated,
            context_pack={"selected_chunks": []},
        )
        card = MessageFormatter.format_user_answer_card(reply)
        rendered = json.dumps(card, ensure_ascii=False)

        assert '{"title"' not in rendered
        assert '"answer_type"' not in rendered
        assert reply.answer_type == "solution_design"
        assert "推荐方案" in rendered

    def test_non_tool_answer_uses_generic_direct_answer_labels(self):
        reply = FormattedReply(
            title="WIN_FLAG_PREMULTIPLIED 属性说明",
            summary="该属性表示窗口像素使用预乘 alpha。",
            answer_type="api_usage",
            direct_answer={
                "primary": "它表示窗口 buffer 中颜色已预乘 alpha。",
                "secondary": "可能减少合成阶段混合计算，但文档未量化 GPU 收益。",
            },
            details=[
                {
                    "name": "WIN_FLAG_PREMULTIPLIED",
                    "purpose": "声明像素格式语义。",
                    "usage": "在窗口属性/flags 中设置。",
                }
            ],
            confidence="中：含义有直接证据，优化收益需实测。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "含义" in rendered_card
        assert "优化作用" in rendered_card
        assert "工具：" not in rendered_card
        assert "Demo：" not in rendered_card

    def test_zero_copy_solution_guardrails(self):
        reply = FormattedReply(
            title="Screen Buffer 零拷贝共享方案",
            summary="基于证据组合方案。",
            answer_type="solution_design",
            solution={
                "recommended": "优先确认平台是否支持 buffer handle export/import 或 Screen stream/resource sharing。",
                "steps": ["生产者持有 buffer，消费者导入 handle。"],
                "variants": ["POSIX shared memory 是近似共享方案，不等同于 Screen 原生 buffer 真零拷贝。"],
                "not_recommended": ["memcpy 到共享内存只能作为 fallback，不是真零拷贝。"],
                "risks": ["SCREEN_PROPERTY_POINTER 的虚拟地址不能直接跨进程使用。"],
            },
            confidence="中：方案由证据组合推导。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "真零拷贝" in rendered_card
        assert "近似共享方案" in rendered_card
        assert "fallback" in rendered_card

    def test_induced_screen_zero_copy_claim_is_downgraded_without_direct_evidence(self):
        answer = json.dumps(
            {
                "title": "Screen buffer 真零拷贝支持",
                "direct_answer": {
                    "primary": "QNX 官方明确支持 screen buffer 真零拷贝。",
                    "secondary": "可以直接确认。",
                },
                "summary": "QNX 官方证实了 Screen buffer 真零拷贝。",
                "answer_type": "concept",
                "confidence": "高：文档直接支持。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Camera Guide",
                    "section_titles": ["Zero Buffer Copy"],
                    "page_start": 150,
                    "text": "QCarCam Zero Buffer Copy shares camera buffers among clients.",
                    "evidence_ids": ["span_camera_zbc"],
                },
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Blitting"],
                    "page_start": 54,
                    "text": "screen_blit() copies pixels from one buffer to another.",
                    "evidence_ids": ["span_screen_blit"],
                },
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="screen buffer 零拷贝——QNX 官方明确支持真零拷贝对吧？",
            answer_text=answer,
            context_pack=context_pack,
        )
        rendered = json.dumps(MessageFormatter.format_summary_card(reply), ensure_ascii=False)

        assert "不能确认" in rendered
        assert "官方明确支持 screen buffer 真零拷贝" not in rendered
        assert reply.confidence.startswith("中")

    def test_troubleshooting_render_question_keeps_problem_title_and_avoids_tool_fact_injection(self):
        answer = json.dumps(
            {
                "title": "QNX 渲染调试工具查询结果",
                "summary": "窗口不显示可能与可见性、窗口组或合成有关。",
                "answer_type": "troubleshooting",
                "details": [
                    {
                        "name": "SCREEN_PROPERTY_VISIBLE",
                        "purpose": "控制窗口是否可见。",
                        "usage": "检查该属性是否为非零值。",
                    }
                ],
                "confidence": "中：部分原因需结合现场排查。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Debugging"],
                    "page_start": 319,
                    "text": "the screeninfo utility can inspect Screen objects and display state.",
                    "evidence_ids": ["span_screeninfo"],
                },
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Windows"],
                    "page_start": 689,
                    "text": "SCREEN_CHILD_WINDOW must be added to an application's window group to be visible.",
                    "evidence_ids": ["span_child"],
                },
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="我的 window 内容显示不出来但没报错，可能有哪几类原因？",
            answer_text=answer,
            context_pack=context_pack,
        )
        rendered = json.dumps(MessageFormatter.format_detail_card(reply), ensure_ascii=False)

        assert reply.title != "QNX 渲染调试工具查询结果"
        assert "screeninfo" not in [item.get("name") for item in (reply.details or [])]
        assert "具体命令/参数需参考对应文档章节" not in rendered

    def test_candidate_facts_correct_contradictory_direct_answer(self):
        answer = json.dumps(
            {
                "title": "QNX 渲染调试工具查询结果",
                "direct_answer": {
                    "tools": "不确定，未发现专门工具。",
                    "demos": "不确定，未发现 demo。",
                },
                "summary": "资料不足。",
                "answer_type": "tool_lookup",
                "details": [],
                "evidence_items": [],
                "confidence": "低：未找到证据。",
            },
            ensure_ascii=False,
        )
        context_pack = {
            "selected_chunks": [
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Debugging"],
                    "page_start": 309,
                    "text": (
                        "These tools and resources are at your disposal: "
                        "the screeninfo utility, gltracelogger utility, "
                        "gltraceprinter utility, screencmd utility, "
                        "Screen API SCREEN_PROPERTY_DEBUG."
                    ),
                    "evidence_ids": ["span_tools"],
                },
                {
                    "document_title": "QNX Screen Guide",
                    "section_titles": ["Utilities and binaries"],
                    "page_start": 180,
                    "text": "gles3-gears Demonstrate 3D rendering using OpenGL ES 2.x.",
                    "evidence_ids": ["span_demo"],
                },
            ]
        }

        reply = MessageFormatter.build_user_reply(
            query="qnx是否提供debug渲染显示问题的demo或工具",
            answer_text=answer,
            context_pack=context_pack,
        )

        assert reply.direct_answer["tools"].startswith("有")
        assert "screeninfo" in reply.direct_answer["tools"]
        assert reply.direct_answer["demos"].startswith("有")
        assert "gles3-gears" in reply.direct_answer["demos"]
        assert reply.evidence_items
        assert reply.details

    def test_card_prefers_direct_answer_and_hides_evidence_ids(self):
        reply = FormattedReply(
            title="QNX 渲染显示调试工具查询结果",
            summary="当前资料确认有显示调试工具，但未直接找到专门 demo。",
            answer_type="tool_lookup",
            direct_answer={
                "tools": "有，当前资料确认 Display Surface Dumps 和 tracelogger。",
                "demos": "未直接检索到专门 demo。",
            },
            evidence_items=[
                {
                    "name": "Display Surface Dumps",
                    "source": "Qualcomm Software Developer Resources / Display / Debug common display issues",
                    "why_relevant": "用于导出显示表面数据，辅助分析显示异常。",
                    "evidence_ids": ["span_hidden"],
                },
                {
                    "name": "tracelogger",
                    "source": "Qualcomm Software Developer Resources / Display / Debug common display issues",
                    "why_relevant": "用于记录显示相关追踪信息。",
                    "evidence_ids": ["span_hidden_2"],
                },
                {
                    "name": "extra",
                    "source": "should not render",
                    "why_relevant": "third item",
                },
            ],
            confidence="中：工具信息有直接依据，demo 仍需继续确认。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)
        visible_card = json.loads(json.dumps(card))
        for element in visible_card.get("elements", []):
            for action in element.get("actions", []):
                action.pop("value", None)
        rendered_visible_card = json.dumps(visible_card, ensure_ascii=False)

        assert "结论" in rendered_card
        assert "直接回答" not in rendered_card
        assert "答案" in rendered_card
        assert "有，当前资料确认" in rendered_card
        assert "补充" in rendered_card
        assert "未直接检索到" in rendered_card
        assert "Display Surface Dumps" in rendered_card
        assert "tracelogger" in rendered_card
        assert "should not render" not in rendered_card
        assert "span_hidden" not in rendered_visible_card

    def test_tool_lookup_card_uses_unified_answer_labels(self):
        reply = FormattedReply(
            title="QNX 内存泄漏定位工具查询结果",
            summary="QNX 提供 Memory Analysis 和 Valgrind。",
            answer_type="tool_lookup",
            direct_answer={
                "tools": "有，包括 Memory Analysis、Valgrind Memcheck 和 Valgrind Massif。",
                "demos": "不确定，未找到独立 demo。",
            },
            details=[
                {
                    "name": "Memory Analysis",
                    "purpose": "定位内存泄漏。",
                    "usage": "附加到进程或从 IDE 启动。",
                }
            ],
        )

        rendered = json.dumps(
            [MessageFormatter.format_summary_card(reply), MessageFormatter.format_detail_card(reply)],
            ensure_ascii=False,
        )

        assert "答案：" in rendered
        assert "补充：" in rendered
        assert "工具：" not in rendered
        assert "Demo：" not in rendered
        assert "怎么用这些工具" not in rendered
        assert "关键说明" in rendered

    def test_card_renders_generic_details_for_actionable_answer(self):
        reply = FormattedReply(
            title="QNX 渲染调试工具查询结果",
            summary="当前资料确认有显示调试工具。",
            answer_type="tool_lookup",
            direct_answer={
                "tools": "有，Screen 子系统提供多种调试工具。",
                "demos": "有，win-vsync 可作为显示/渲染相关示例。",
            },
            details=[
                {
                    "name": "screeninfo",
                    "purpose": "查看 Screen 对象和显示状态。",
                    "usage": "在目标机上运行 screeninfo 收集状态。",
                    "when_to_use": "怀疑窗口层级或显示状态异常时使用。",
                },
                {
                    "name": "gltracelogger",
                    "purpose": "记录 OpenGL ES 调用轨迹。",
                    "usage": "配合 gltraceprinter 查看 trace 输出。",
                    "when_to_use": "怀疑 GL 调用或渲染管线异常时使用。",
                },
                {
                    "name": "win-vsync",
                    "purpose": "展示窗口层次中的软件光栅化内容。",
                    "usage": "运行示例观察显示刷新行为。",
                },
            ],
            confidence="高：资料直接列出工具和示例。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "怎么用" in rendered_card
        assert "screeninfo" in rendered_card
        assert "查看 Screen 对象和显示状态。" in rendered_card
        assert "在目标机上运行 screeninfo 收集状态。" in rendered_card
        assert "win-vsync" in rendered_card
        assert "展示窗口层次中的软件光栅化内容" in rendered_card

    def test_card_renders_generic_details_for_concept_answer(self):
        reply = FormattedReply(
            title="mmap cache 问题说明",
            summary="mmap 映射设备内存时需要关注 cache 属性。",
            answer_type="concept",
            details=[
                {
                    "name": "cache 属性",
                    "purpose": "解释为什么 stale data 可能出现。",
                    "usage": "检查映射 flag 是否使用非缓存属性。",
                }
            ],
            confidence="中：资料部分相关。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "关键说明" in rendered_card
        assert "cache 属性" in rendered_card

    def test_card_omits_key_points_when_direct_answer_exists(self):
        reply = FormattedReply(
            title="QNX 渲染调试工具查询结果",
            summary="当前资料确认有显示调试工具。",
            direct_answer={
                "tools": "有，当前资料确认 Display Surface Dumps。",
                "demos": "未直接检索到专门 demo。",
            },
            key_points=["Display Surface Dumps 可用于抓取显示表面状态"],
            confidence="中：工具信息有直接依据。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "要点" not in rendered_card

    def test_card_uses_compact_evidence_and_confidence_format(self):
        reply = FormattedReply(
            title="QNX 渲染调试工具查询结果",
            summary="当前资料确认有显示调试工具。",
            direct_answer={
                "tools": "有，Screen 子系统提供 screeninfo 等工具。",
                "demos": "有，win-vsync 可作为显示/渲染相关示例。",
            },
            evidence_items=[
                {
                    "name": "slog2info、screeninfo、gltracelogger 等调试工具",
                    "source": "QNX SDP 7.1 Screen Graphics Subsystem Developers Guide / Chapter 13 Debugging / 309",
                    "why_relevant": "直接列出调试图形问题可用的工具及其用途，是回答工具问题的核心依据。",
                }
            ],
            confidence="高：参考资料直接给出了专用工具列表和演示程序名称。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "page 309" in rendered_card
        assert "用途：直接列出调试图形问题可用的工具及其用途" in rendered_card
        assert "来源：" not in rendered_card
        assert "说明：" not in rendered_card
        assert "置信度：高｜参考资料直接给出了专用工具列表和演示程序名称。" in rendered_card

    def test_build_user_reply_polishes_repetition_and_debug_noise(self):
        answer = json.dumps(
            {
                "title": "QNX 渲染显示问题调试工具与 Demo 可用性",
                "direct_answer": {
                    "tools": "有，如 Display Surface Dumps 与 tracelogger。",
                    "demos": "不确定，参考资料未提及专用 demo。",
                },
                "summary": (
                    "现有文档显示 QNX 提供了一些用于调试显示/渲染问题的工具。"
                    "通用 IDE 调试工具（GDB、System Profiler 等）可作为辅助手段，但并非渲染专用。"
                ),
                "key_points": [
                    "Display Surface Dumps 可用于抓取显示表面状态",
                    "tracelogger 是分析显示问题的关键日志工具",
                    "Screen 子系统开发者指南第 13 章提供图形调试指引",
                    "未发现专门用于演示渲染调试的 demo 程序",
                ],
                "evidence_items": [
                    {
                        "name": "Display Surface Dumps & tracelogger",
                        "source": "Qualcomm Software Developer Resources / Display / Debug common display issues",
                        "why_relevant": "列出调试显示花屏问题所需的日志和 surface dump 工具。",
                    }
                ],
                "caveats": [],
                "next_steps": [
                    "阅读 Screen Graphics Subsystem Developers Guide 第 13 章。",
                    "查询 Display Surface Dumps 和 tracelogger 的具体用法。",
                    "泛读 IDE Users Guide。",
                ],
                "confidence": "中：工具信息有直接依据，demo 仍需继续确认。",
            },
            ensure_ascii=False,
        )

        reply = MessageFormatter.build_user_reply(
            query="qnx是否提供debug渲染显示问题的demo或工具",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )
        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert reply.title == "QNX 渲染调试工具查询结果"
        assert "GDB" not in reply.summary
        assert "System Profiler" not in rendered_card
        assert len(reply.key_points) <= 2
        assert "泛读 IDE Users Guide" not in reply.next_steps
        assert "Display Surface Dumps" in rendered_card
        assert "tracelogger" in rendered_card

    def test_build_user_reply_falls_back_when_json_is_invalid(self):
        answer = "{not json}\n结论\n仍然可以用自然语言分节。"

        reply = MessageFormatter.build_user_reply(
            query="测试问题",
            answer_text=answer,
            context_pack={"selected_chunks": []},
        )

        assert "仍然可以用自然语言分节" in reply.summary

    def test_format_user_answer_text_is_sectioned(self):
        reply = FormattedReply(
            title="缓存问题怎么处理？",
            summary="需要使用非缓存映射，并检查 DMA buffer。",
            evidence_items=[
                {
                    "document_title": "QNX Memory Guide",
                    "location": "mmap / page 12",
                    "summary": "Use PROT_NOCACHE when mapping device memory.",
                    "evidence_ids": ["span_1"],
                }
            ],
            confidence="高：参考资料直接包含处理建议。",
        )

        text = MessageFormatter.format_user_answer_text(reply)

        assert "结论" in text
        assert "关键依据" in text
        assert "置信度" in text
        assert "QNX Memory Guide" in text

    def test_format_user_answer_post_builds_feishu_post_payload(self):
        reply = FormattedReply(
            title="缓存问题怎么处理？",
            summary="需要使用非缓存映射，并检查 DMA buffer。",
            evidence_items=[
                {
                    "document_title": "QNX Memory Guide",
                    "location": "mmap / page 12",
                    "summary": "Use PROT_NOCACHE when mapping device memory.",
                    "evidence_ids": ["span_1"],
                }
            ],
            caveats=["如果文档没有覆盖硬件平台，需要人工确认。"],
            next_steps=["检查 mmap flags。"],
            confidence="高：证据直接命中。",
        )

        post = MessageFormatter.format_user_answer_post(reply)

        zh_cn = post["post"]["zh_cn"]
        assert zh_cn["title"] == "缓存问题怎么处理？"
        rendered_text = json.dumps(zh_cn["content"], ensure_ascii=False)
        assert "结论" in rendered_text
        assert "关键依据" in rendered_text
        assert "下一步建议" in rendered_text

    def test_format_user_answer_card_builds_interactive_card(self):
        reply = FormattedReply(
            title="缓存问题怎么处理？",
            summary="需要使用非缓存映射，并检查 DMA buffer。",
            evidence_items=[
                {
                    "document_title": "QNX Memory Guide",
                    "location": "mmap / page 12",
                    "summary": "Use PROT_NOCACHE when mapping device memory.",
                    "evidence_ids": ["span_1"],
                }
            ],
            caveats=["如果文档没有覆盖硬件平台，需要人工确认。"],
            next_steps=["检查 mmap flags。"],
            confidence="高：证据直接命中。",
        )

        card = MessageFormatter.format_user_answer_card(reply)

        assert card["config"]["wide_screen_mode"] is True
        assert card["header"]["title"]["content"] == "缓存问题怎么处理？"
        rendered_card = json.dumps(card, ensure_ascii=False)
        assert "结论" in rendered_card
        assert "关键依据" in rendered_card
        assert "需要注意" in rendered_card
        assert "置信度：高｜证据直接命中。" in rendered_card

    def test_summary_card_is_short_and_has_detail_and_evidence_buttons(self):
        reply = FormattedReply(
            title="Screen Buffer 零拷贝共享方案",
            summary="当前资料不能证明通用跨进程 Screen buffer 真零拷贝 API。",
            answer_type="solution_design",
            solution={
                "recommended": "优先确认平台是否支持 buffer handle/import 机制。",
                "steps": ["生产者创建 buffer。", "消费者导入 handle。"],
                "not_recommended": ["memcpy fallback 不是真零拷贝。"],
                "risks": ["需要确认 cache coherency。"],
            },
            evidence_items=[
                {
                    "name": "Screen buffer API",
                    "source": "Screen Guide / Buffers / page 31",
                    "why_relevant": "说明 Screen buffer 获取方式。",
                    "evidence_ids": ["span_1"],
                }
            ],
            confidence="中：需要平台能力确认。",
        )

        card = MessageFormatter.format_summary_card(reply, reply_id="reply_1")
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "Screen Buffer 零拷贝共享方案" in rendered_card
        assert "当前资料不能证明" in rendered_card
        assert "推荐方案" not in rendered_card
        assert "实施步骤" not in rendered_card
        assert "查看详细回答" in rendered_card
        assert "查看完整证据" in rendered_card
        assert "reply_1" in rendered_card
        assert "span_1" in rendered_card

    def test_summary_card_hides_high_confidence_note(self):
        reply = FormattedReply(
            title="高置信回答",
            summary="这是直接证据支持的回答。",
            confidence="高：资料直接支持。",
        )

        card = MessageFormatter.format_summary_card(reply, reply_id="reply_1")
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "置信度" not in rendered_card

    def test_summary_card_shows_medium_confidence_note(self):
        reply = FormattedReply(
            title="中置信回答",
            summary="这是需要推断的回答。",
            confidence="中：资料部分相关，需要推断。",
        )

        card = MessageFormatter.format_summary_card(reply, reply_id="reply_1")
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "置信度：中｜资料部分相关，需要推断。" in rendered_card

    def test_detail_card_keeps_solution_sections(self):
        reply = FormattedReply(
            title="Screen Buffer 零拷贝共享方案",
            summary="当前资料不能证明通用跨进程 Screen buffer 真零拷贝 API。",
            answer_type="solution_design",
            solution={
                "recommended": "优先确认平台是否支持 buffer handle/import 机制。",
                "steps": ["生产者创建 buffer。"],
                "not_recommended": ["memcpy fallback 不是真零拷贝。"],
            },
            confidence="中：需要平台能力确认。",
        )

        card = MessageFormatter.format_detail_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "推荐方案" in rendered_card
        assert "实施步骤" in rendered_card
        assert "memcpy fallback 不是真零拷贝" in rendered_card

    def test_card_includes_show_full_evidence_button_when_evidence_ids_exist(self):
        reply = FormattedReply(
            title="QNX 渲染调试工具查询结果",
            summary="当前资料确认有显示调试工具。",
            evidence_items=[
                {
                    "name": "Display Surface Dumps",
                    "source": "Qualcomm / Display",
                    "why_relevant": "用于导出显示表面数据。",
                    "evidence_ids": ["span_1", "span_2"],
                }
            ],
            confidence="中：工具信息有直接依据。",
        )

        card = MessageFormatter.format_user_answer_card(reply)
        rendered_card = json.dumps(card, ensure_ascii=False)

        assert "查看完整证据" in rendered_card
        assert "show_full_evidence" in rendered_card
        assert "span_1" in rendered_card
        assert "span_2" in rendered_card
        action = next(
            element
            for element in card["elements"]
            if element.get("tag") == "action"
        )["actions"][0]
        assert action["value"]["evidence_refs"][0]["evidence_id"] == "span_1"
        assert action["value"]["evidence_refs"][0]["label"] == "Display Surface Dumps"
        assert "导出显示表面数据" in action["value"]["evidence_refs"][0]["supports"]


class TestFeishuMessageHandler:
    def test_process_query_uses_shared_responder(self):
        config = FeishuConfig(processed_dir="/tmp/processed")
        with patch("agent_knowledge_hub.feishu_bot.LocalAPIClient"), \
             patch("agent_knowledge_hub.feishu_bot.FeishuAPI"), \
             patch("agent_knowledge_hub.feishu_bot.LLMAgent"):
            handler = FeishuMessageHandler(config)
        formatted = FormattedReply(title="标题", summary="答案")
        handler.responder = MagicMock()
        handler.responder.process_query.return_value = MagicMock(
            text="answer",
            formatted_reply=formatted,
        )

        handler._process_query("oc_chat", "技术问题")

        handler.responder.process_query.assert_called_once_with("技术问题")
        handler.feishu_api.send_reply_message.assert_called_once_with("oc_chat", formatted)


class TestFeishuAPIRichText:
    def test_send_card_message_posts_interactive_payload(self):
        config = FeishuConfig(app_id="app", app_secret="secret", api_base="https://test.feishu.cn")
        api = FeishuAPI(config)
        reply = FormattedReply(title="标题", summary="结论内容", confidence="高")

        with patch.object(api.token_manager, "get_token", return_value="token"), \
             patch("agent_knowledge_hub.feishu_bot._http_post", return_value={"code": 0}) as post:
            assert api.send_card_message("oc_chat", reply) is True

        payload = post.call_args.args[1]
        assert payload["chat_id"] == "oc_chat"
        assert payload["msg_type"] == "interactive"
        assert payload["card"]["header"]["title"]["content"] == "标题"

    def test_send_rich_text_message_posts_post_payload(self):
        config = FeishuConfig(app_id="app", app_secret="secret", api_base="https://test.feishu.cn")
        api = FeishuAPI(config)
        reply = FormattedReply(title="标题", summary="结论内容", confidence="高")

        with patch.object(api.token_manager, "get_token", return_value="token"), \
             patch("agent_knowledge_hub.feishu_bot._http_post", return_value={"code": 0}) as post:
            assert api.send_rich_text_message("oc_chat", reply) is True

        payload = post.call_args.args[1]
        assert payload["chat_id"] == "oc_chat"
        assert payload["msg_type"] == "post"
        assert payload["content"]["post"]["zh_cn"]["title"] == "标题"

    def test_send_reply_message_falls_back_to_text_when_post_fails(self):
        config = FeishuConfig(app_id="app", app_secret="secret", api_base="https://test.feishu.cn")
        api = FeishuAPI(config)
        reply = FormattedReply(title="标题", summary="结论内容", plain_text="fallback text")

        with patch.object(api.token_manager, "get_token", return_value="token"), \
             patch(
                 "agent_knowledge_hub.feishu_bot._http_post",
                 side_effect=[
                     {"code": 999, "msg": "bad card"},
                     {"code": 999, "msg": "bad post"},
                     {"code": 0},
                 ],
             ) as post:
            api.send_reply_message("oc_chat", reply)

        assert post.call_count == 3
        assert post.call_args_list[0].args[1]["msg_type"] == "interactive"
        assert post.call_args_list[1].args[1]["msg_type"] == "post"
        assert post.call_args_list[2].args[1]["msg_type"] == "text"
        assert post.call_args_list[2].args[1]["content"]["text"] == "fallback text"

    def test_send_reply_message_uses_card_before_post(self):
        config = FeishuConfig(app_id="app", app_secret="secret", api_base="https://test.feishu.cn")
        api = FeishuAPI(config)
        reply = FormattedReply(title="标题", summary="结论内容", plain_text="fallback text")

        with patch.object(api.token_manager, "get_token", return_value="token"), \
             patch("agent_knowledge_hub.feishu_bot._http_post", return_value={"code": 0}) as post:
            api.send_reply_message("oc_chat", reply)

        assert post.call_count == 1
        assert post.call_args.args[1]["msg_type"] == "interactive"

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
