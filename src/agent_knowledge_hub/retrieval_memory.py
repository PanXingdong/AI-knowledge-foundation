"""Retrieval memory: a data-driven layer that turns recurring user phrasings into
reusable retrieval hints (expanded queries, preferred / negative sources).

Goal: replace hard-coded ``_looks_like_*`` rules in ``retrieval.py`` with editable,
inspectable, roll-back-able memory entries. A failed retrieval should become a new
memory entry, not another ``if`` branch.

The store is a JSONL file (one entry per line). Default location is
``data/retrieval_memory.jsonl`` (overridable via ``RETRIEVAL_MEMORY_PATH``). If the
file is missing, the store is simply empty and callers see no behaviour change.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_knowledge_hub.utils import normalize_space

DEFAULT_MEMORY_ENV = "RETRIEVAL_MEMORY_PATH"
DEFAULT_MEMORY_PATH = "data/retrieval_memory.jsonl"

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9_./-]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _tokenize(text: str) -> set[str]:
    """Lightweight, self-contained tokenizer (ASCII tokens + CJK bigrams)."""
    lowered = normalize_space(text).lower()
    if not lowered:
        return set()
    tokens: set[str] = set()
    for token in _ASCII_TOKEN_RE.findall(lowered):
        if len(token) >= 2:
            tokens.add(token)
    for sequence in _CJK_RE.findall(lowered):
        if len(sequence) <= 2:
            tokens.add(sequence)
            continue
        for index in range(len(sequence) - 1):
            tokens.add(sequence[index : index + 2])
    return tokens


@dataclass(frozen=True)
class RetrievalMemoryEntry:
    """A single recurring retrieval pattern and how it should be resolved."""

    memory_id: str
    intent: str
    user_patterns: tuple[str, ...]
    expanded_queries: tuple[str, ...] = ()
    preferred_sources: tuple[str, ...] = ()
    preferred_sections: tuple[str, ...] = ()
    negative_sources: tuple[str, ...] = ()
    confidence: float = 0.7
    last_verified_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> "RetrievalMemoryEntry":
        def _tuple(key: str) -> tuple[str, ...]:
            value = payload.get(key) or []
            return tuple(str(item) for item in value if str(item).strip())

        return cls(
            memory_id=str(payload.get("memory_id") or "").strip(),
            intent=str(payload.get("intent") or "general").strip(),
            user_patterns=_tuple("user_patterns"),
            expanded_queries=_tuple("expanded_queries"),
            preferred_sources=_tuple("preferred_sources"),
            preferred_sections=_tuple("preferred_sections"),
            negative_sources=_tuple("negative_sources"),
            confidence=float(payload.get("confidence") or 0.7),
            last_verified_at=str(payload.get("last_verified_at") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "intent": self.intent,
            "user_patterns": list(self.user_patterns),
            "expanded_queries": list(self.expanded_queries),
            "preferred_sources": list(self.preferred_sources),
            "preferred_sections": list(self.preferred_sections),
            "negative_sources": list(self.negative_sources),
            "confidence": self.confidence,
            "last_verified_at": self.last_verified_at,
        }

    def match_score(self, query: str) -> float:
        """How strongly this entry applies to ``query`` (0.0 = no match)."""
        normalized = normalize_space(query).lower()
        if not normalized or not self.user_patterns:
            return 0.0

        query_tokens = _tokenize(query)
        best = 0.0
        for pattern in self.user_patterns:
            pattern_norm = normalize_space(pattern).lower()
            if not pattern_norm:
                continue
            # Strong signal: the pattern phrase appears verbatim.
            if pattern_norm in normalized:
                best = max(best, 1.0)
                continue
            # Weak signal: token overlap between the pattern and the query.
            pattern_tokens = _tokenize(pattern)
            if not pattern_tokens:
                continue
            overlap = len(pattern_tokens & query_tokens) / len(pattern_tokens)
            best = max(best, overlap)
        return best


@dataclass
class RetrievalPlanHints:
    """Aggregated hints from all memory entries that matched a query."""

    matched_memory_ids: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    expanded_queries: list[tuple[str, float]] = field(default_factory=list)
    preferred_sources: list[str] = field(default_factory=list)
    preferred_sections: list[str] = field(default_factory=list)
    negative_sources: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.matched_memory_ids


class RetrievalMemoryStore:
    """In-memory view over the JSONL memory file."""

    def __init__(self, entries: list[RetrievalMemoryEntry] | None = None) -> None:
        self.entries: list[RetrievalMemoryEntry] = list(entries or [])

    @classmethod
    def load(cls, path: Path | str | None = None) -> "RetrievalMemoryStore":
        resolved = cls._resolve_path(path)
        if resolved is None or not resolved.exists():
            return cls([])
        entries: list[RetrievalMemoryEntry] = []
        for line in resolved.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            entry = RetrievalMemoryEntry.from_dict(payload)
            if entry.user_patterns:
                entries.append(entry)
        return cls(entries)

    @staticmethod
    def _resolve_path(path: Path | str | None) -> Path | None:
        if path is not None:
            return Path(path)
        env_value = os.getenv(DEFAULT_MEMORY_ENV, "").strip()
        if env_value:
            return Path(env_value)
        return Path(DEFAULT_MEMORY_PATH)

    def save(self, path: Path | str | None = None) -> Path:
        resolved = self._resolve_path(path)
        if resolved is None:
            raise ValueError("No memory path provided and no default available.")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(entry.to_dict(), ensure_ascii=False) for entry in self.entries]
        resolved.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return resolved

    def match(self, query: str, *, threshold: float = 0.5) -> list[tuple[RetrievalMemoryEntry, float]]:
        scored = [
            (entry, entry.match_score(query))
            for entry in self.entries
        ]
        matched = [(entry, score) for entry, score in scored if score >= threshold]
        matched.sort(key=lambda item: item[1] * max(item[0].confidence, 0.01), reverse=True)
        return matched

    def plan_hints(self, query: str, *, threshold: float = 0.5) -> RetrievalPlanHints:
        hints = RetrievalPlanHints()
        seen_queries: dict[str, float] = {}
        for entry, score in self.match(query, threshold=threshold):
            hints.matched_memory_ids.append(entry.memory_id)
            if entry.intent and entry.intent not in hints.intents:
                hints.intents.append(entry.intent)
            weight = max(0.1, min(3.0, 1.0 + score * entry.confidence * 2.0))
            for expanded in entry.expanded_queries:
                key = normalize_space(expanded).lower()
                if not key:
                    continue
                seen_queries[key] = max(seen_queries.get(key, 0.0), weight)
            for source in entry.preferred_sources:
                if source not in hints.preferred_sources:
                    hints.preferred_sources.append(source)
            for section in entry.preferred_sections:
                if section not in hints.preferred_sections:
                    hints.preferred_sections.append(section)
            for source in entry.negative_sources:
                if source not in hints.negative_sources:
                    hints.negative_sources.append(source)
        hints.expanded_queries = sorted(
            seen_queries.items(), key=lambda item: item[1], reverse=True
        )
        return hints


# Process-level cache so repeated queries do not re-read the file every call.
_DEFAULT_STORE_CACHE: dict[str, RetrievalMemoryStore] = {}


def get_default_memory_store() -> RetrievalMemoryStore:
    """Load (and cache) the default memory store. Empty if no file exists."""
    resolved = RetrievalMemoryStore._resolve_path(None)
    cache_key = str(resolved)
    cached = _DEFAULT_STORE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    store = RetrievalMemoryStore.load(resolved)
    _DEFAULT_STORE_CACHE[cache_key] = store
    return store


def reset_default_memory_cache() -> None:
    """Clear the cached default store (useful for tests)."""
    _DEFAULT_STORE_CACHE.clear()
