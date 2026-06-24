from __future__ import annotations

import re
from dataclasses import asdict

from agent_knowledge_hub.models import CanonicalDocument, Chunk
from agent_knowledge_hub.utils import stable_id

# ---------------------------------------------------------------------------
# Noise section filter (封面/版权页、目录、索引、字母分组)
# ---------------------------------------------------------------------------

_NOISE_SECTION_PREFIXES: frozenset[str] = frozenset({"0", "Contents", "Index"})

# Pattern that matches the ¦-separated letter navigation typical of
# alphabetical index sections: "A ¦ B ¦ C ¦ D …"
_ALPHA_NAV_PATTERN: re.Pattern[str] = re.compile(
    r"^[A-Z](?:\s*[¦|]\s*[A-Z]){4,}",  # at least 5 letter entries
)


def _is_noise_block(section_path: list[str], block_text: str = "") -> bool:
    """Return True if this block belongs to a non-informative section.

    Named-prefix sections ("Contents", "Index", section "0") are always
    filtered.  Single-letter sections (A–Z) are only filtered when the
    block text contains an alphabetical navigation bar (e.g. "A ¦ B ¦ C …"),
    which is the giveaway for index letter-group headers.  Valid sections
    named with a single letter (e.g. "A 模块设计", appendix "A") are kept.
    """
    if not section_path:
        return False
    head = section_path[0]
    if head in _NOISE_SECTION_PREFIXES:
        return True
    # Single uppercase letter section: only noise if it contains alpha-nav
    if len(head) == 1 and head.isupper():
        return bool(_ALPHA_NAV_PATTERN.search(block_text))
    return False


# ---------------------------------------------------------------------------
# Fragment block filter (页眉/页脚/日期/版本号等碎片行)
# ---------------------------------------------------------------------------

_FRAGMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^page\s+\d+$", re.IGNORECASE),            # "Page 12"
    re.compile(r"^\d+$"),                                    # 裸页码
    re.compile(r"^[-–—]\s*\d+\s*[-–—]$"),                  # "- 5 -"
    re.compile(r"^\d{1,2}\s+\w+\.?\s+\d{4}$"),             # "8 May 2026"
    re.compile(r"^\w+\.?\s+\d{1,2},?\s+\d{4}$"),           # "May 8, 2026"
    re.compile(r"^\d{4}[-/]\d{2}[-/]\d{2}$"),              # "2026-05-08"
    re.compile(r"^[\w\s.\-]+\s+[A-Z]{1,3}$"),              # "80-82727-100 CW"
    re.compile(r"^(?:rev(?:ision)?|ver(?:sion)?|v)[\s.:]*[\d.]+$", re.IGNORECASE),
    re.compile(r"^(?:confidential|proprietary|draft|copyright).*$", re.IGNORECASE),
    re.compile(r"^(?:qnx|blackberry|©|all rights reserved).*$", re.IGNORECASE),
)


def _is_fragment_block(text: str) -> bool:
    """Return True if text is a header/footer/date/version fragment with no
    retrieval value.  Only applied to short texts to avoid false positives.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    return any(pat.fullmatch(stripped) for pat in _FRAGMENT_PATTERNS)


# ---------------------------------------------------------------------------
# Token estimation (无需外部 tokenizer 依赖)
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """Lightweight token count estimate for multilingual text.

    CJK characters map to ~1 token each in BGE-M3 / mBERT tokenizers.
    ASCII/Latin text averages ~4 characters per token.
    This avoids a hard tokenizer dependency while giving a reasonable budget
    for mixed Chinese-English technical documents.
    """
    cjk = sum(
        1 for c in text
        if "\u4e00" <= c <= "\u9fff"   # CJK Unified Ideographs
        or "\u3040" <= c <= "\u30ff"   # Hiragana + Katakana
        or "\uac00" <= c <= "\ud7af"   # Korean Hangul
    )
    non_cjk = len(text) - cjk
    # max(1, ...) applied to the whole expression so empty strings still
    # return 1, but pure-CJK text is not inflated by a phantom non-CJK token.
    return max(1, cjk + non_cjk // 4)


# ---------------------------------------------------------------------------
# Main chunker
# ---------------------------------------------------------------------------

def build_chunks(
    canonical: CanonicalDocument,
    *,
    max_chunk_chars: int = 1600,
    max_tokens: int | None = None,
    overlap_chars: int = 160,
    min_chunk_chars: int = 10,
) -> list[Chunk]:
    """Build section-aware chunks from canonical blocks.

    Parameters
    ----------
    max_chunk_chars:
        Hard character limit per chunk.  Ignored when *max_tokens* is set.
    max_tokens:
        Preferred token budget per chunk (CJK-aware estimate).  When set this
        takes precedence over *max_chunk_chars* and adapts to mixed-language
        content — important for BGE-M3 whose 8 192-token window makes a fixed
        character limit unstable across Chinese/English documents.
        Typical value: 512 (dense retrieval) or 256 (high-precision RAG).
    overlap_chars:
        Characters to carry forward between chunks within the same section.
        Hard-capped so a single oversized block cannot inflate the window.
    min_chunk_chars:
        Chunks shorter than this threshold are silently dropped.  Catches
        residual page-header / footer fragments that survive the per-block
        filter (e.g. a lone copyright line that follows a section boundary).
        Default is 10 — low enough to allow short CJK sentences (semantically
        dense per character) while still filtering lone page numbers or dates.

    Changes vs. original implementation
    ------------------------------------
    - Noise sections (cover, Contents, Index, A-Z groups) are skipped.
    - Fragment blocks (dates, version numbers, bare page numbers …) are skipped.
    - chunk_id is derived from content only — stable across re-runs.
    - Overlap is hard-capped at *overlap_chars* characters.
    - ``block_type="table"`` blocks are treated as atomic: the size check is
      skipped so a table is never split across chunks.
    - ``block_type="heading"`` blocks are not emitted as standalone chunks;
      they are carried into the following content block for context.
    - Token-aware budget replaces the fixed character limit when *max_tokens*
      is provided.
    """
    if max_chunk_chars < 50:
        raise ValueError("max_chunk_chars must be >= 50")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")
    if overlap_chars >= max_chunk_chars:
        overlap_chars = max(0, max_chunk_chars // 10)
    if min_chunk_chars < 0:
        raise ValueError("min_chunk_chars must be >= 0")

    def _over_budget(texts: list[str], next_text: str) -> bool:
        combined = "\n\n".join([*texts, next_text])
        if max_tokens is not None:
            return _estimate_tokens(combined) > max_tokens
        return len(combined) > max_chunk_chars

    evidence_by_block = {
        evidence.block_id: evidence.evidence_id for evidence in canonical.evidence_spans
    }
    chunks: list[Chunk] = []
    current_texts: list[str] = []
    current_evidence: list[str] = []
    current_section_path: list[str] = []
    current_page_start: int | None = None
    current_page_end: int | None = None

    def _absorb_page(page_start: int | None, page_end: int | None) -> None:
        nonlocal current_page_start, current_page_end
        if page_start is not None:
            current_page_start = (
                page_start if current_page_start is None
                else min(current_page_start, page_start)
            )
        if page_end is not None:
            current_page_end = (
                page_end if current_page_end is None
                else max(current_page_end, page_end)
            )

    def flush(*, preserve_overlap: bool = True) -> None:
        nonlocal current_texts, current_evidence
        nonlocal current_page_start, current_page_end

        text = "\n\n".join(part for part in current_texts if part.strip()).strip()
        if not text or len(text) < min_chunk_chars:
            # Too short — drop and reset without keeping overlap.
            current_texts = []
            current_evidence = []
            current_page_start = None
            current_page_end = None
            return

        # Stable ID: content-addressed, no sequential counter.
        chunk_id = stable_id(
            "chunk",
            canonical.document_version.document_version_id,
            text,
        )
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                document_version_id=canonical.document_version.document_version_id,
                section_path=list(current_section_path),
                page_start=current_page_start,
                page_end=current_page_end,
                text=text,
                evidence_ids=list(dict.fromkeys(current_evidence)),
                embedding_id=None,
                metadata={
                    "document_id": canonical.document.document_id,
                    "document_title": canonical.document.title,
                    "source_type": canonical.document.source_type,
                },
            )
        )

        if preserve_overlap and overlap_chars and len(text) > overlap_chars:
            overlap_text = _select_overlap_text(current_texts, overlap_chars)
            current_texts = [overlap_text] if overlap_text else []
            current_evidence = list(dict.fromkeys(current_evidence[-1:])) if current_texts else []
        else:
            current_texts = []
            current_evidence = []
        current_page_start = None
        current_page_end = None

    for block in canonical.blocks:
        block_text = block.text.strip()
        if not block_text:
            continue

        # --- Filter 1: noise sections ---
        if _is_noise_block(block.section_path, block_text):
            continue

        # --- Filter 2: fragment blocks (page headers/footers, dates, etc.) ---
        if _is_fragment_block(block_text):
            continue

        block_type = block.block_type  # "paragraph" | "heading" | "table"
        block_evidence = evidence_by_block.get(block.block_id)
        section_changed = (
            bool(current_section_path) and block.section_path != current_section_path
        )

        # --- Heading blocks ---
        # Headings update section context but are not emitted as standalone
        # chunks.  They are prepended to the next content block so the heading
        # text provides retrieval signal in the chunk it introduces.
        if block_type == "heading":
            if section_changed and current_texts:
                flush(preserve_overlap=False)
            current_section_path = list(block.section_path)
            current_texts.append(block_text)
            if block_evidence:
                current_evidence.append(block_evidence)
            _absorb_page(block.page_start, block.page_end)
            continue

        # --- Table blocks (atomic — never split mid-table) ---
        if block_type == "table":
            if section_changed and current_texts:
                flush(preserve_overlap=False)
            elif current_texts:
                # Flush any accumulated paragraph text before the table so
                # the table lands in its own chunk.
                flush(preserve_overlap=True)
            current_section_path = list(block.section_path)
            current_texts.append(block_text)
            if block_evidence:
                current_evidence.append(block_evidence)
            _absorb_page(block.page_start, block.page_end)
            # Immediately flush: tables are always their own chunk.
            flush(preserve_overlap=False)
            continue

        # --- Regular paragraph blocks ---
        if current_texts and (section_changed or _over_budget(current_texts, block_text)):
            flush(preserve_overlap=not section_changed)

        current_section_path = list(block.section_path)
        current_texts.append(block_text)
        if block_evidence:
            current_evidence.append(block_evidence)
        _absorb_page(block.page_start, block.page_end)

    flush()
    return chunks


def chunks_to_dicts(chunks: list[Chunk]) -> list[dict]:
    return [asdict(chunk) for chunk in chunks]


def _select_overlap_text(texts: list[str], overlap_chars: int) -> str:
    """Return a single overlap string of at most *overlap_chars* characters.

    Collects blocks from the end of the current window and trims to exactly
    *overlap_chars* so a single oversized block cannot inflate the overlap
    beyond its intended budget.
    """
    if overlap_chars <= 0 or not texts:
        return ""

    selected: list[str] = []
    total = 0
    for text in reversed(texts):
        selected.append(text)
        total += len(text)
        if total >= overlap_chars:
            break

    combined = "\n\n".join(reversed(selected))
    return combined[-overlap_chars:]
