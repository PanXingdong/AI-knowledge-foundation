"""Evidence reranker: a deterministic, intent-aware re-ordering pass applied to
already-retrieved chunks. It runs *after* lexical/vector scoring and only adjusts
ordering — it never invents evidence.

Design notes:
- Pure function, no network. An optional cross-encoder / LLM reranker can be added
  later behind the same interface.
- Duck-typed over the chunk object: it only needs ``section_titles`` (list[str]),
  ``text`` (str) and ``score`` (float). This avoids importing ``RetrievedChunk``
  and the resulting circular dependency with ``retrieval``.
"""
from __future__ import annotations

from typing import Sequence, TypeVar

from agent_knowledge_hub.query_planner import (
    INTENT_API_USAGE,
    INTENT_COMPONENT_INVENTORY,
    INTENT_MECHANISM,
    QueryPlan,
)
from agent_knowledge_hub.utils import normalize_space

ChunkT = TypeVar("ChunkT")

_INVENTORY_SIGNALS = (
    "overview", "architecture", "components", "contents", "introduction",
    "modules", "resources", "概述", "架构", "组件", "目录", "简介", "模块",
)
_API_SIGNALS = (
    "(", ")", "return", "parameter", "argument", "signature", "prototype",
    "参数", "返回", "接口", "函数",
)
_MECHANISM_SIGNALS = (
    "mechanism", "because", "in order to", "workflow", "sequence",
    "机制", "原理", "因为", "流程", "工作方式",
)


def _signal_bonus(chunk: object, signals: Sequence[str], *, weight: float) -> float:
    section_text = " ".join(getattr(chunk, "section_titles", []) or []).lower()
    body = normalize_space(getattr(chunk, "text", "") or "").lower()[:400]
    bonus = 0.0
    for signal in signals:
        if signal in section_text:
            bonus += weight  # section-title hit is the strongest signal
        elif signal in body:
            bonus += weight * 0.3
    return bonus


def rerank_chunks(plan: QueryPlan, chunks: Sequence[ChunkT]) -> list[ChunkT]:
    """Return ``chunks`` reordered according to the plan intent.

    Ordering is stable: when rerank bonuses tie, the original retrieval order
    (already sorted by score) is preserved.
    """
    if not chunks:
        return list(chunks)

    if plan.intent == INTENT_COMPONENT_INVENTORY:
        signals, weight = _INVENTORY_SIGNALS, 6.0
    elif plan.intent == INTENT_API_USAGE:
        signals, weight = _API_SIGNALS, 4.0
    elif plan.intent == INTENT_MECHANISM:
        signals, weight = _MECHANISM_SIGNALS, 4.0
    else:
        return list(chunks)

    indexed = list(enumerate(chunks))
    indexed.sort(
        key=lambda item: (_signal_bonus(item[1], signals, weight=weight), -item[0]),
        reverse=True,
    )
    return [chunk for _, chunk in indexed]
