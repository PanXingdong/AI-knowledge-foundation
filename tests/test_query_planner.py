from agent_knowledge_hub.query_planner import (
    INTENT_API_USAGE,
    INTENT_COMPONENT_INVENTORY,
    INTENT_GENERAL,
    INTENT_MECHANISM,
    INTENT_TROUBLESHOOTING,
    detect_intent,
    plan_query,
)
from agent_knowledge_hub.retrieval_memory import (
    RetrievalMemoryEntry,
    RetrievalMemoryStore,
)


def test_detect_intent_generic_categories():
    assert detect_intent("这个平台包含哪些组件") == INTENT_COMPONENT_INVENTORY
    assert detect_intent("give me an overview of the architecture") == INTENT_COMPONENT_INVENTORY
    assert detect_intent("这个函数的参数和返回值是什么") == INTENT_API_USAGE
    assert detect_intent("调度的工作机制是什么原理") == INTENT_MECHANISM
    assert detect_intent("启动报错崩溃了怎么办") == INTENT_TROUBLESHOOTING
    assert detect_intent("随便聊聊") == INTENT_GENERAL


def test_plan_query_inventory_adds_structural_expansions():
    plan = plan_query("整体架构包含哪些模块", memory_store=RetrievalMemoryStore([]))
    assert plan.intent == INTENT_COMPONENT_INVENTORY
    terms = [term for term, _ in plan.expanded_queries]
    assert "overview" in terms
    assert "architecture" in terms
    assert "概述" in plan.preferred_sections


def test_plan_query_consults_memory_store():
    store = RetrievalMemoryStore(
        [
            RetrievalMemoryEntry(
                memory_id="mmap",
                intent="mechanism_lookup",
                user_patterns=("内存映射 缓存 旧数据",),
                expanded_queries=("mmap prot_nocache",),
                confidence=0.8,
            )
        ]
    )
    plan = plan_query("为什么内存映射 缓存 旧数据", memory_store=store)
    assert "mmap" in plan.matched_memory_ids
    terms = [term for term, _ in plan.expanded_queries]
    assert "mmap prot_nocache" in terms


def test_plan_query_llm_hook_enriches_plan():
    def fake_llm(query: str, intent: str) -> dict:
        return {"expanded_queries": ["llm term"], "preferred_sections": ["llm-sec"]}

    plan = plan_query(
        "随便问问",
        memory_store=RetrievalMemoryStore([]),
        llm_planner=fake_llm,
    )
    assert plan.source == "llm"
    terms = [term for term, _ in plan.expanded_queries]
    assert "llm term" in terms
    assert "llm-sec" in plan.preferred_sections


def test_plan_query_llm_hook_failure_is_ignored():
    def broken_llm(query: str, intent: str) -> dict:
        raise RuntimeError("network down")

    plan = plan_query(
        "整体架构包含哪些模块",
        memory_store=RetrievalMemoryStore([]),
        llm_planner=broken_llm,
    )
    # Deterministic plan still survives.
    assert plan.intent == INTENT_COMPONENT_INVENTORY
