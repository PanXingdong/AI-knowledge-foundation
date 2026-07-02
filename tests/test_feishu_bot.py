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
        assert reply.confidence == "高：参考资料直接提供了图形调试章节。"
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
                    "document_title": "Irrelevant IDE Guide",
                    "text": "This should not be appended when JSON evidence exists.",
                    "score": 9.0,
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
        assert reply.evidence_items[0]["name"] == "Display Surface Dumps"
        assert "Qualcomm Software" in reply.evidence_items[0]["source"]
        assert "导出显示表面数据" in reply.evidence_items[0]["why_relevant"]
        assert reply.caveats == ["没有看到窗口合成专用 demo。"]
        assert reply.next_steps == ["先运行 screeninfo。"]
        assert reply.confidence == "高：文档直接列出工具。"

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
        assert "工具" in rendered_card
        assert "有，当前资料确认" in rendered_card
        assert "Demo" in rendered_card
        assert "未直接检索到" in rendered_card
        assert "Display Surface Dumps" in rendered_card
        assert "tracelogger" in rendered_card
        assert "should not render" not in rendered_card
        assert "span_hidden" not in rendered_visible_card

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
