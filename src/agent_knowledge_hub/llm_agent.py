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
) -> str:
    url = f"{DEEPSEEK_API_BASE}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1200,
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
        body = e.read().decode("utf-8") if e.fp else str(e)
        raise RuntimeError(f"DeepSeek API error {e.code}: {body}") from e


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
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model or os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

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
            return _call_deepseek(messages, self.api_key, self.model, self.timeout)
        except Exception:
            logger.exception("LLM direct_reply failed, using fallback")
            return "你好！我是QNX助手，有什么 QNX 相关的技术问题都可以问我～"

    def synthesize(self, query: str, context_pack_text: str) -> str:
        """Synthesize a final answer from retrieved evidence + original query."""
        user_content = (
            f"【用户问题】\n{query}\n\n"
            f"【参考资料】\n{context_pack_text}\n\n"
            "请根据参考资料回答用户问题。"
            "在回答末尾注明置信度（高/中/低）及简短理由。"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            return _call_deepseek(messages, self.api_key, self.model, self.timeout)
        except Exception:
            logger.exception("LLM synthesis failed, falling back to raw evidence")
            return context_pack_text  # show raw evidence if LLM fails

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
            raw = _call_deepseek(messages, self.api_key, self.model, self.timeout)
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
            return _call_deepseek(messages, self.api_key, self.model, self.timeout)
        except Exception:
            logger.exception("LLM no_evidence_reply failed, using fallback")
            return (
                "抱歉，知识库中未找到与您问题相关的文档，"
                "请尝试换个问法，或确认问题是否属于 QNX 领域。"
            )
