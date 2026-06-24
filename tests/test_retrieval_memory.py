from pathlib import Path

from agent_knowledge_hub.retrieval_memory import (
    RetrievalMemoryEntry,
    RetrievalMemoryStore,
)


def test_entry_match_score_verbatim_and_token_overlap():
    entry = RetrievalMemoryEntry(
        memory_id="m1",
        intent="mechanism_lookup",
        user_patterns=("内存映射 缓存 旧数据", "mmap stale data"),
        expanded_queries=("mmap prot_nocache",),
        confidence=0.8,
    )
    assert entry.match_score("为什么内存映射 缓存 旧数据没刷新") == 1.0
    assert entry.match_score("mmap stale data problem") == 1.0
    # Unrelated query should not match.
    assert entry.match_score("如何配置网络代理") < 0.5


def test_store_roundtrip_and_plan_hints(tmp_path: Path):
    path = tmp_path / "memory.jsonl"
    store = RetrievalMemoryStore(
        [
            RetrievalMemoryEntry(
                memory_id="inv",
                intent="component_inventory",
                user_patterns=("包含哪些组件",),
                expanded_queries=("overview", "architecture"),
                preferred_sections=("概述",),
                confidence=0.6,
            )
        ]
    )
    store.save(path)

    reloaded = RetrievalMemoryStore.load(path)
    assert len(reloaded.entries) == 1

    hints = reloaded.plan_hints("这个平台包含哪些组件")
    assert hints.matched_memory_ids == ["inv"]
    assert "component_inventory" in hints.intents
    expanded_terms = [term for term, _ in hints.expanded_queries]
    assert "overview" in expanded_terms
    assert "architecture" in expanded_terms
    assert "概述" in hints.preferred_sections


def test_missing_file_yields_empty_store(tmp_path: Path):
    store = RetrievalMemoryStore.load(tmp_path / "does-not-exist.jsonl")
    assert store.entries == []
    assert store.plan_hints("anything").is_empty
