"""LLM Agent module: intent classification, chitchat handling, and evidence synthesis.

Pipeline:
  query
    ├─ chitchat? ──────────────────────────────► direct_reply (no KB call)
    └─ technical ──► knowledge base retrieval ──► synthesize (evidence → answer)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"

# ---------------------------------------------------------------------------
# System prompt — defines the assistant's identity and rules
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是一个专业的 QNX 嵌入式操作系统知识助手，名叫"QNX助手"。

【身份与职责】
- 你专注于 QNX Neutrino RTOS 相关技术问题的解答。
- 你基于系统提供的官方文档片段来回答问题，不凭空编造。
- 对于问候、闲聊等非技术对话，你友好回应，并提示用户可以向你提问 QNX 技术问题。

【回答规则】
1. 问候/闲聊（你好、hi、谢谢、测试等）：直接友好回应，无需检索文档。
2. 技术问题：基于"参考资料"部分提供的内容回答，引用具体文档名和页码。
3. 若参考资料不足以回答：如实说明"暂无相关文档支撑"，不要编造内容。
4. 回答用中文，简洁清晰，重点突出。
5. 每个技术回答末尾附一行置信度评估：
   - 【置信度：高】参考资料直接包含答案
   - 【置信度：中】参考资料部分相关，存在推断
   - 【置信度：低】参考资料相关性弱，答案存疑

【禁止事项】
- 不捏造 API、函数名、行为描述。
- 不声称某行为"一定"发生，除非文档明确说明。
- 不回答与 QNX/嵌入式操作系统无关的专业技术问题（如前端、机器学习等）。
"""

# ---------------------------------------------------------------------------
# Local heuristic: detect obvious chitchat without an API call
# ---------------------------------------------------------------------------
_CHITCHAT_KEYWORDS = (
    "你好", "hi", "hello", "hey", "早上好", "下午好", "晚上好",
    "谢谢", "感谢", "多谢", "再见", "bye", "👋",
    "你是谁", "你是什么", "介绍一下", "你叫什么",
    "在吗", "在不", "测试", "test",
    "哈哈", "哈", "嗯", "好的", "ok", "好",
)


def _is_chitchat(query: str) -> bool:
    """Cheap local check before spending an API call."""
    q = query.strip().lower()
    # Very short queries that match keywords
    if len(q) <= 15:
        for kw in _CHITCHAT_KEYWORDS:
            if kw.lower() in q:
                return True
    return False


# ---------------------------------------------------------------------------
# DeepSeek API call
# ---------------------------------------------------------------------------
def _call_deepseek(
    messages: list[dict[str, str]],
    api_key: str,
    model: str,
    timeout: int = 60,
    temperature: float = 0.3,
) -> str:
    url = f"{DEEPSEEK_API_BASE}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as e:
        # Log only the status code, not the body, to avoid leaking API keys or
        # sensitive response content into log aggregators.
        logger.debug("DeepSeek API HTTP %d — body omitted from log", e.code)
        raise RuntimeError(f"DeepSeek API error {e.code}") from e


# ---------------------------------------------------------------------------
# LLMAgent
# ---------------------------------------------------------------------------
class LLMAgent:
    """Wraps DeepSeek API for intent routing, chitchat reply, and synthesis."""

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        timeout: int = 90,
        synthesis_temperature: float | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.synthesis_temperature = (
            synthesis_temperature
            if synthesis_temperature is not None
            else float(os.getenv("DEEPSEEK_SYNTHESIS_TEMPERATURE", "0"))
        )

    @classmethod
    def from_env(cls) -> LLMAgent:
        return cls(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_chitchat(self, query: str) -> bool:
        return _is_chitchat(query)

    def direct_reply(self, query: str) -> str:
        """Generate a friendly response for chitchat without retrieving docs."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        try:
            return _call_deepseek(
                messages,
                self.api_key,
                self.model,
                self.timeout,
                temperature=0.3,
            )
        except Exception:
            logger.exception("LLM direct_reply failed, using fallback")
            return "你好！我是QNX助手，有什么 QNX 相关的技术问题都可以问我～"

    def synthesize(
        self,
        query: str,
        context_pack_text: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Synthesize a final answer from retrieved evidence + original query."""
        user_content = (
            f"【用户问题】\n{query}\n\n"
            f"【参考资料】\n{context_pack_text}\n\n"
            "请根据参考资料生成适合飞书聊天窗口阅读的中文回答。\n"
            "只输出一个 JSON 对象，不要输出 Markdown，不要输出代码块，不要解释 JSON 之外的内容。\n"
            "JSON schema:\n"
            "{\n"
            '  "title": "问题简短标题",\n'
            '  "direct_answer": {\n'
            '    "primary": "通用问题主答案；非工具/demo问题优先填写",\n'
            '    "secondary": "通用问题补充答案；例如优化作用/限制",\n'
            '    "tools": "仅工具查询时填写：有/没有/不确定 + 一句话说明",\n'
            '    "demos": "仅 demo 查询时填写：有/没有/不确定 + 一句话说明"\n'
            "  },\n"
            '  "summary": "2-4行直接结论",\n'
            '  "answer_type": "tool_lookup | demo_lookup | how_to | concept | troubleshooting | api_usage | solution_design | general",\n'
            '  "details": [\n'
            "    {\n"
            '      "name": "工具/API/概念/步骤名",\n'
            '      "purpose": "它解决什么问题或说明什么",\n'
            '      "usage": "怎么用；如果资料不足就写不确定",\n'
            '      "when_to_use": "什么场景下使用；不适用可省略"\n'
            "    }\n"
            "  ],\n"
            '  "solution": {\n'
            '    "recommended": "推荐方案摘要；仅 answer_type=solution_design 时填写",\n'
            '    "steps": ["实施步骤"],\n'
            '    "variants": ["可选方案"],\n'
            '    "not_recommended": ["不推荐做法"],\n'
            '    "risks": ["风险"],\n'
            '    "open_questions": ["待确认点"]\n'
            "  },\n"
            '  "key_points": ["可选：关键要点"],\n'
            '  "evidence_items": [\n'
            "    {\n"
            '      "name": "工具/概念名，例如 Display Surface Dumps",\n'
            '      "source": "文档名 / 章节 / 页码",\n'
            '      "why_relevant": "为什么这条证据能回答用户问题",\n'
            '      "evidence_ids": []\n'
            "    }\n"
            "  ],\n"
            '  "caveats": ["可选：限制或缺口"],\n'
            '  "next_steps": ["可选：下一步建议"],\n'
            '  "confidence": "高/中/低：简短理由"\n'
            "}\n"
            "要求：\n"
            "1. 先拆解用户问题。工具/demo 查询才填写 direct_answer.tools/demos；属性、API、概念、方案类问题使用 primary/secondary，不要硬套工具/Demo。\n"
            "2. title 用中性短标题，渲染显示调试类问题优先用“QNX 渲染调试工具查询结果”。\n"
            "3. summary 只写总览，不重复 direct_answer，不提 IDE/GDB/System Profiler 这类通用调试噪声。\n"
            "4. 根据问题选择 answer_type。工具/demo 查询用 tool_lookup/demo_lookup；概念解释用 concept；排障用 troubleshooting；API 用法用 api_usage。\n"
            "5. 当用户问方案、架构、最佳实践、怎么实现、给 demo、有没有办法时，优先选择 solution_design。\n"
            "6. solution_design 要填写 solution 字段；不要只回答“没有现成方案”。如果文档没有现成方案，也要基于 API、机制、限制和证据组合推荐方案，并说明哪些是直接证据、哪些是推导。\n"
            "7. zero-copy/dma-buf/screen buffer 方案必须区分：真零拷贝、共享内存/PMEM 近似方案、memcpy fallback；不要把 fallback 说成真零拷贝。\n"
            "8. details 是通用细节列表：工具问题写工具作用/用法/适用场景；概念问题写概念拆解；API 问题写 API/参数/注意事项。不要只列名字。\n"
            "9. key_points 最多 2 条；不要重复 evidence_items 或 details 中已经展示的内容。\n"
            "10. evidence_items 最多 2 条，只放强相关证据；不要把 IDE/GDB 通用调试配置作为渲染显示问题的主依据。\n"
            "11. 不要填写、猜测或复述 evidence_id；evidence_ids 必须始终写空数组 []，系统会从检索结果自动绑定真实可追溯 id。\n"
            "12. next_steps 必须和用户问题直接相关，不要推荐无关文档。\n"
            "13. 如果资料不足，如实说明缺口。\n"
            "14. confidence 必须填写。"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_content})
        try:
            return _call_deepseek(
                messages,
                self.api_key,
                self.model,
                self.timeout,
                temperature=self.synthesis_temperature,
            )
        except Exception:
            logger.exception("LLM synthesis failed, using safe fallback")
            return (
                "抱歉，本次模型生成失败。系统已检索到相关资料，"
                "但未能安全生成结构化回答。请稍后重试，或查看完整证据。"
            )

    def plan_query(self, query: str, intent: str = "") -> dict:
        """Optional LLM-backed query planning hook.

        Returns a dict with optional keys ``intent``, ``expanded_queries`` and
        ``preferred_sections``. On any failure (no API key, network error, bad
        JSON) it returns ``{}`` so the deterministic planner is used unchanged.
        """
        if not self.api_key:
            return {}
        system = (
            "你是检索查询规划助手。读取用户问题，输出 JSON："
            '{"intent": "...", "expanded_queries": ["..."], "preferred_sections": ["..."]}。'
            "expanded_queries 给 2-5 个用于全文检索的英文/中文关键词短语；"
            "preferred_sections 给可能命中答案的章节名（如 overview/architecture/概述）。"
            "只输出 JSON，不要解释。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ]
        try:
            raw = _call_deepseek(
                messages,
                self.api_key,
                self.model,
                self.timeout,
                temperature=0.1,
            )
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return {}
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            logger.exception("LLM plan_query failed, falling back to local planner")
            return {}

    def no_evidence_reply(self, query: str) -> str:
        """Reply when knowledge base returned no useful results."""
        user_content = (
            f"用户问了一个问题：{query}\n"
            "知识库中未找到与此问题相关的文档片段。"
            "请礼貌告知用户，并建议换个问法，或确认问题是否属于 QNX 领域。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            return _call_deepseek(
                messages,
                self.api_key,
                self.model,
                self.timeout,
                temperature=0.2,
            )
        except Exception:
            logger.exception("LLM no_evidence_reply failed, using fallback")
            return (
                "抱歉，知识库中未找到与您问题相关的文档，"
                "请尝试换个问法，或确认问题是否属于 QNX 领域。"
            )
