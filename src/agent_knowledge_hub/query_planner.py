"""Query planner: turns a raw user query into a structured retrieval plan.

The planner is the anti-overfitting layer. Instead of growing more hard-coded
``_looks_like_<platform feature>`` rules, it:

1. Detects a *generic* intent (component inventory / api usage / mechanism /
   troubleshooting / general) using domain-neutral cues that apply to any vendor
   document (QNX, Qualcomm, ...).
2. Consults the data-driven :mod:`retrieval_memory` store for query-specific
   expansions and source preferences.
3. Optionally accepts an LLM-backed planner callable for richer expansion. The
   deterministic path always works with no network / no API key, so retrieval
   stays reproducible and testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agent_knowledge_hub.retrieval_memory import (
    RetrievalMemoryStore,
    get_default_memory_store,
)
from agent_knowledge_hub.utils import normalize_space

INTENT_COMPONENT_INVENTORY = "component_inventory"
INTENT_API_USAGE = "api_usage"
INTENT_MECHANISM = "mechanism_lookup"
INTENT_TROUBLESHOOTING = "troubleshooting"
INTENT_GENERAL = "general"

# Domain-neutral cues. These intentionally describe *document structure* and
# *question shape*, not any specific platform feature, so they generalise.
_COMPONENT_INVENTORY_CUES = (
    "包含哪些", "有哪些", "包括哪些", "组成", "构成", "组件", "模块有哪些",
    "清单", "列表", "目录", "总体架构", "整体架构", "系统架构", "提供哪些",
    "有什么功能", "支持哪些", "包含什么", "概览", "概述",
    "overview", "contents", "table of contents", "architecture", "components",
    "modules", "inventory", "list of", "what does it include", "what are the",
)
_API_USAGE_CUES = (
    "函数", "接口", "参数", "返回值", "调用", "用法", "原型", "签名",
    "api", "function", "interface", "parameter", "return value", "signature",
    "prototype", "how to call", "how to use",
)
_MECHANISM_CUES = (
    "机制", "原理", "为什么", "怎么实现", "如何工作", "流程", "工作方式",
    "mechanism", "how does", "why does", "principle", "workflow", "internals",
)
_TROUBLESHOOTING_CUES = (
    "报错", "失败", "卡死", "崩溃", "不工作", "异常", "无法", "旧数据", "脏数据",
    "error", "crash", "fail", "stuck", "hang", "not working", "stale", "issue",
)

# Generic structural expansion terms for component-inventory style questions.
# These are document-skeleton words present in almost any technical manual.
_INVENTORY_EXPANSION_TERMS = (
    "overview", "contents", "architecture", "components", "modules", "resources",
    "目录", "概述", "架构", "组件", "模块",
)

# Generic section names worth boosting for inventory/overview questions.
_INVENTORY_PREFERRED_SECTIONS = (
    "overview", "architecture", "contents", "introduction",
    "概述", "架构", "目录", "简介",
)


@dataclass
class QueryPlan:
    """Structured retrieval plan derived from a raw query."""

    query: str
    normalized_query: str
    intent: str = INTENT_GENERAL
    # (expanded_query_text, weight) — fed into FTS variant generation.
    expanded_queries: list[tuple[str, float]] = field(default_factory=list)
    preferred_sources: list[str] = field(default_factory=list)
    preferred_sections: list[str] = field(default_factory=list)
    negative_sources: list[str] = field(default_factory=list)
    matched_memory_ids: list[str] = field(default_factory=list)
    source: str = "local"  # "local" or "llm"

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "intent": self.intent,
            "expanded_queries": [list(item) for item in self.expanded_queries],
            "preferred_sources": list(self.preferred_sources),
            "preferred_sections": list(self.preferred_sections),
            "negative_sources": list(self.negative_sources),
            "matched_memory_ids": list(self.matched_memory_ids),
            "source": self.source,
        }


def detect_intent(query: str) -> str:
    """Detect a generic, domain-neutral intent for the query."""
    lowered = normalize_space(query).lower()
    if not lowered:
        return INTENT_GENERAL

    def _hit(cues: tuple[str, ...]) -> bool:
        return any(cue in lowered for cue in cues)

    # Order matters: troubleshooting and api are more specific than inventory.
    if _hit(_TROUBLESHOOTING_CUES):
        return INTENT_TROUBLESHOOTING
    if _hit(_API_USAGE_CUES):
        return INTENT_API_USAGE
    if _hit(_COMPONENT_INVENTORY_CUES):
        return INTENT_COMPONENT_INVENTORY
    if _hit(_MECHANISM_CUES):
        return INTENT_MECHANISM
    return INTENT_GENERAL


def plan_query(
    query: str,
    *,
    memory_store: Optional[RetrievalMemoryStore] = None,
    llm_planner: Optional[Callable[[str, str], dict]] = None,
) -> QueryPlan:
    """Build a :class:`QueryPlan` for ``query``.

    ``llm_planner`` is an optional callable ``(query, intent) -> dict`` that may
    return ``expanded_queries`` / ``preferred_sections`` to enrich the plan. Any
    failure inside it is ignored so the deterministic plan always survives.
    """
    normalized = normalize_space(query)
    intent = detect_intent(query)
    plan = QueryPlan(query=query, normalized_query=normalized, intent=intent)

    # 1. Generic intent-driven expansion (component inventory / overview).
    if intent == INTENT_COMPONENT_INVENTORY:
        for term in _INVENTORY_EXPANSION_TERMS:
            plan.expanded_queries.append((term, 0.6))
        plan.preferred_sections.extend(_INVENTORY_PREFERRED_SECTIONS)

    # 2. Data-driven memory hints (replaces hard-coded platform rules).
    store = memory_store if memory_store is not None else get_default_memory_store()
    hints = store.plan_hints(query)
    if not hints.is_empty:
        plan.matched_memory_ids.extend(hints.matched_memory_ids)
        if intent == INTENT_GENERAL and hints.intents:
            plan.intent = hints.intents[0]
        plan.expanded_queries.extend(hints.expanded_queries)
        for section in hints.preferred_sections:
            if section not in plan.preferred_sections:
                plan.preferred_sections.append(section)
        plan.preferred_sources.extend(hints.preferred_sources)
        plan.negative_sources.extend(hints.negative_sources)

    # 3. Optional LLM enrichment (best-effort, never blocks).
    if llm_planner is not None:
        try:
            enrichment = llm_planner(query, intent) or {}
        except Exception:  # pragma: no cover - defensive, network errors ignored
            enrichment = {}
        if enrichment:
            plan.source = "llm"
            for term in enrichment.get("expanded_queries", []) or []:
                text = normalize_space(str(term))
                if text:
                    plan.expanded_queries.append((text, 0.8))
            for section in enrichment.get("preferred_sections", []) or []:
                section_text = str(section).strip()
                if section_text and section_text not in plan.preferred_sections:
                    plan.preferred_sections.append(section_text)
            llm_intent = str(enrichment.get("intent") or "").strip()
            if llm_intent:
                plan.intent = llm_intent

    # De-duplicate expansions, keeping the highest weight per term.
    deduped: dict[str, float] = {}
    for text, weight in plan.expanded_queries:
        key = normalize_space(text).lower()
        if not key:
            continue
        deduped[key] = max(deduped.get(key, 0.0), float(weight))
    plan.expanded_queries = sorted(deduped.items(), key=lambda item: item[1], reverse=True)
    return plan
