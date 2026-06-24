from dataclasses import dataclass, field

from agent_knowledge_hub.query_planner import (
    INTENT_COMPONENT_INVENTORY,
    INTENT_GENERAL,
    QueryPlan,
)
from agent_knowledge_hub.reranker import rerank_chunks


@dataclass
class _FakeChunk:
    chunk_id: str
    section_titles: list[str] = field(default_factory=list)
    text: str = ""
    score: float = 0.0


def test_inventory_intent_promotes_overview_sections():
    detail = _FakeChunk(chunk_id="detail", section_titles=["Register map"], text="bit fields")
    overview = _FakeChunk(chunk_id="overview", section_titles=["Architecture Overview"], text="components list")
    plan = QueryPlan(query="组件清单", normalized_query="组件清单", intent=INTENT_COMPONENT_INVENTORY)

    ranked = rerank_chunks(plan, [detail, overview])
    assert ranked[0].chunk_id == "overview"


def test_general_intent_is_identity():
    a = _FakeChunk(chunk_id="a", section_titles=["X"])
    b = _FakeChunk(chunk_id="b", section_titles=["Architecture"])
    plan = QueryPlan(query="q", normalized_query="q", intent=INTENT_GENERAL)
    ranked = rerank_chunks(plan, [a, b])
    assert [c.chunk_id for c in ranked] == ["a", "b"]


def test_empty_input_returns_empty():
    plan = QueryPlan(query="q", normalized_query="q", intent=INTENT_COMPONENT_INVENTORY)
    assert rerank_chunks(plan, []) == []
