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
# Sentence splitter — semantic boundary awareness
# ---------------------------------------------------------------------------

# Words (lower-cased) whose trailing "." must NOT be treated as a sentence
# boundary.  Tuned for English technical / embedded-systems documentation.
_ABBREVS: frozenset[str] = frozenset({
    # Latin discourse markers
    "e.g", "i.e", "etc", "vs", "cf",
    # Document-structure references
    "fig", "figs", "eq", "sec", "ch", "vol", "no", "ref", "p", "pp",
    # Quantity qualifiers
    "approx", "incl", "excl", "max", "min", "avg", "est",
    # Abbreviated month names
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    # Titles
    "dr", "mr", "mrs", "ms", "prof",
})

# CJK sentence-ending punctuation — always a safe split point.
_CJK_SENT_END_RE: re.Pattern[str] = re.compile(r"(?<=[。！？])\s*")

# Blank-line paragraph break — always safe.
_BLANK_LINE_RE: re.Pattern[str] = re.compile(r"\n{2,}")

# Match any word characters that precede a dot so we can check abbreviations.
_WORD_BEFORE_DOT_RE: re.Pattern[str] = re.compile(r"[A-Za-z]+$")


def _is_eng_sentence_boundary(text: str, dot_pos: int) -> bool:
    """Return True if the dot at *dot_pos* ends an English sentence.

    Conservative rules tuned for English technical documentation:

    - Dot must be followed by whitespace then an uppercase letter or CJK char.
    - Dot preceded by a digit → version / decimal number (7.1, 1.2.3).
    - Dot preceded by an uppercase letter → acronym (U.S., API., QNX.).
    - Dot preceded by a known abbreviation word → not a sentence end.
    """
    after = text[dot_pos + 1:]
    if not after or not after[0].isspace():
        return False
    tail = after.lstrip()
    if not tail:
        return False
    first = tail[0]
    if not (first.isupper() or "\u4e00" <= first <= "\u9fff"):
        return False

    before = text[:dot_pos]
    if not before:
        return False
    prev_char = before[-1]
    if prev_char.isdigit():          # version / decimal: 3.14, v7.1
        return False
    if prev_char.isupper():          # acronym dot: U.S.A., QNX.
        return False
    m = _WORD_BEFORE_DOT_RE.search(before)
    if m and m.group().lower() in _ABBREVS:
        return False

    return True


def _split_sentences(text: str) -> list[str]:
    """Split *text* into sentence-level fragments.

    Split priority:
    1. Blank lines (``\\n\\n``) — paragraph boundary, always safe.
    2. CJK sentence-ending punctuation (。！？) — always safe.
    3. English sentence boundaries (``". "`` + uppercase) with abbreviation
       and version-number protection.

    Returns ``[text]`` when no split points are found so callers can always
    iterate the result safely.
    """
    # Phase 1 — macro splits: blank lines then CJK punctuation.
    macro_parts: list[str] = []
    for para in _BLANK_LINE_RE.split(text):
        if not para.strip():
            continue
        for seg in _CJK_SENT_END_RE.split(para):
            s = seg.strip()
            if s:
                macro_parts.append(s)

    if not macro_parts:
        return [text] if text.strip() else []

    # Phase 2 — English sentence boundaries within each macro part.
    result: list[str] = []
    for part in macro_parts:
        start = 0
        for m in re.finditer(r"\.", part):
            pos = m.start()
            if _is_eng_sentence_boundary(part, pos):
                fragment = part[start: pos + 1].strip()
                if fragment:
                    result.append(fragment)
                start = pos + 1
                while start < len(part) and part[start].isspace():
                    start += 1
        tail = part[start:].strip()
        if tail:
            result.append(tail)

    return result or [text]


def _sentence_split_if_needed(text: str, token_budget: int) -> list[str]:
    """Return *text* split at sentence boundaries when it exceeds *token_budget*.

    Falls back to line-level splitting, then to a character-window hard cut for
    any fragment still above the budget (e.g. a single long code line or API
    signature with no natural break points).  Always returns at least one
    non-empty string.
    """
    if _estimate_tokens(text) <= token_budget:
        return [text]

    fragments: list[str] = []
    for sent in _split_sentences(text):
        if _estimate_tokens(sent) <= token_budget:
            fragments.append(sent)
        else:
            for line in sent.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if _estimate_tokens(line) <= token_budget:
                    fragments.append(line)
                else:
                    # Hard cut: token-budget-aware split for lines that still
                    # exceed the budget (e.g. a long code line with no spaces).
                    fragments.extend(_hard_cut_to_token_budget(line, token_budget))

    return fragments or [text]


def _hard_cut_to_token_budget(text: str, token_budget: int) -> list[str]:
    """Split an unsplittable line into pieces that fit *token_budget*.

    Uses the same estimator as the chunker itself, so CJK-dense text gets a
    much smaller character window than ASCII text. The upper bound remains
    ``token_budget * 4`` to preserve the previous ASCII behaviour.
    """
    if token_budget <= 0:
        return [text]

    pieces: list[str] = []
    start = 0
    max_chars = max(1, token_budget * 4)
    while start < len(text):
        low = start + 1
        high = min(len(text), start + max_chars)
        best = low
        while low <= high:
            mid = (low + high) // 2
            candidate = text[start:mid]
            if _estimate_tokens(candidate) <= token_budget:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        pieces.append(text[start:best])
        start = best
    return pieces


# ---------------------------------------------------------------------------
# Main chunker
# ---------------------------------------------------------------------------

def build_chunks(
    canonical: CanonicalDocument,
    *,
    max_chunk_chars: int = 1600,
    max_tokens: int = 512,
    overlap_chars: int = 160,
    min_chunk_chars: int = 10,
) -> list[Chunk]:
    """Build section-aware chunks from canonical blocks.

    Parameters
    ----------
    max_chunk_chars:
        Character limit per chunk used only when *max_tokens* is explicitly
        set to 0 (disabled).  In normal operation *max_tokens* takes
        precedence, so this parameter mainly serves as a hard safety cap.
    max_tokens:
        Token budget per chunk (CJK-aware estimate).  Defaults to 512, which
        matches the sweet spot for BGE-M3 dense retrieval and correctly
        handles mixed Chinese/English technical documents where a fixed
        character limit would either under-fill (pure ASCII) or overflow
        (pure CJK) the model's effective encoding window.
        Set to 0 to disable token budgeting and fall back to *max_chunk_chars*.
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
    - ``block_type="heading"`` blocks are buffered separately and prepended to
      the *next* content block (paragraph or table).  A heading immediately
      preceding a table is therefore always included in the table's chunk
      rather than being flushed as a useless standalone chunk.
    - Pending-heading text is included in the budget check so that the
      combined heading + paragraph text never silently exceeds *max_tokens*.
    - Token-aware budget (CJK-adjusted) is the default; character limit is the
      fallback when ``max_tokens=0``.
    """
    if max_chunk_chars < 50:
        raise ValueError("max_chunk_chars must be >= 50")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")
    if overlap_chars >= max_chunk_chars:
        overlap_chars = max(0, max_chunk_chars // 10)
    if min_chunk_chars < 0:
        raise ValueError("min_chunk_chars must be >= 0")

    # pending_heading_texts is captured by _over_budget closure; must be
    # declared before _over_budget so Python's late-binding resolution works.
    pending_heading_texts: list[str] = []
    pending_heading_evidence: list[str] = []
    _ph_page_start: int | None = None
    _ph_page_end: int | None = None

    def _over_budget(texts: list[str], next_text: str) -> bool:
        # Include pending headings: they will be drained into the chunk before
        # next_text is appended, so they must count toward the budget now.
        all_texts = [*texts, *pending_heading_texts, next_text]
        combined = "\n\n".join(all_texts)
        if max_tokens:
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

    def _drain_pending_headings() -> None:
        """Merge the pending-heading buffer into the current chunk window.

        Called immediately before a paragraph or table block is appended so
        the heading text and its page range are incorporated into the same
        chunk as the content it introduces.
        """
        nonlocal pending_heading_texts, pending_heading_evidence
        nonlocal _ph_page_start, _ph_page_end
        if not pending_heading_texts:
            return
        current_texts.extend(pending_heading_texts)
        current_evidence.extend(e for e in pending_heading_evidence if e)
        _absorb_page(_ph_page_start, _ph_page_end)
        pending_heading_texts = []
        pending_heading_evidence = []
        _ph_page_start = None
        _ph_page_end = None

    def _discard_pending_headings() -> None:
        """Drop stale headings when a section boundary invalidates them."""
        nonlocal pending_heading_texts, pending_heading_evidence
        nonlocal _ph_page_start, _ph_page_end
        pending_heading_texts = []
        pending_heading_evidence = []
        _ph_page_start = None
        _ph_page_end = None

    for block in canonical.blocks:
        block_text = block.text.strip()
        if not block_text:
            continue

        block_type = block.block_type  # "paragraph" | "heading" | "table"
        # Code blocks may carry synthetic section path "0" and identifier-like
        # lines that look like fragments; keep them to preserve source retrieval.
        if block_type != "code":
            # --- Filter 1: noise sections ---
            if _is_noise_block(block.section_path, block_text):
                continue

            # --- Filter 2: fragment blocks (page headers/footers, dates, etc.) ---
            if _is_fragment_block(block_text):
                continue

        block_evidence = evidence_by_block.get(block.block_id)
        section_changed = (
            bool(current_section_path) and block.section_path != current_section_path
        )

        # --- Code blocks (atomic — never sentence-split) ---
        # Code blocks arrive pre-sized from parse_source_code() (≤ _CODE_CHUNK_LINES
        # lines each).  They are flushed individually so sentence-splitting logic
        # never sees code text, preserving indentation, blank lines, and structure.
        if block_type == "code":
            if current_texts and (
                section_changed or _over_budget(current_texts, block_text)
            ):
                flush(preserve_overlap=False)
                if section_changed:
                    _discard_pending_headings()
            current_section_path = list(block.section_path)
            _drain_pending_headings()
            current_texts.append(block_text)
            if block_evidence:
                current_evidence.append(block_evidence)
            _absorb_page(block.page_start, block.page_end)
            # Flush immediately: each code block is its own chunk.
            flush(preserve_overlap=False)
            continue

        # --- Heading blocks ---
        # Headings are buffered in *pending_heading_texts* rather than appended
        # directly to current_texts.  They are merged into the chunk only when
        # the next content block (paragraph or table) is about to be added.
        # This guarantees that a heading immediately preceding a table always
        # lands in the same chunk as that table instead of being flushed alone.
        if block_type == "heading":
            if section_changed:
                if current_texts:
                    flush(preserve_overlap=False)
                _discard_pending_headings()
            current_section_path = list(block.section_path)
            pending_heading_texts.append(block_text)
            if block_evidence:
                pending_heading_evidence.append(block_evidence)
            # Track page range in the pending buffer (not in current chunk).
            if block.page_start is not None:
                _ph_page_start = (
                    block.page_start if _ph_page_start is None
                    else min(_ph_page_start, block.page_start)
                )
            if block.page_end is not None:
                _ph_page_end = (
                    block.page_end if _ph_page_end is None
                    else max(_ph_page_end, block.page_end)
                )
            continue

        # --- Table blocks (atomic — never split mid-table) ---
        if block_type == "table":
            if section_changed:
                if current_texts:
                    flush(preserve_overlap=False)
                _discard_pending_headings()
            elif current_texts:
                # Flush any accumulated paragraph text before the table so
                # the table lands in its own chunk.  Pending headings are
                # intentionally *not* discarded here — they belong to this
                # table, not to the preceding paragraph chunk.
                flush(preserve_overlap=True)
            current_section_path = list(block.section_path)
            _drain_pending_headings()  # heading joins the table chunk
            current_texts.append(block_text)
            if block_evidence:
                current_evidence.append(block_evidence)
            _absorb_page(block.page_start, block.page_end)
            # Immediately flush: tables are always their own chunk.
            flush(preserve_overlap=False)
            continue

        # --- Regular paragraph blocks ---
        # Split oversized blocks at sentence boundaries before accumulating.
        # Each sub-block is processed as if it were a separate paragraph so
        # the accumulator can group multiple short sentences into one chunk,
        # keeping sub-blocks within the token budget on a best-effort basis.
        #
        # Token budget for splitting: use max_tokens when enabled, otherwise
        # approximate from max_chunk_chars (4 ASCII chars ≈ 1 token).
        _split_budget = max_tokens if max_tokens else max(64, max_chunk_chars // 4)
        sub_blocks = _sentence_split_if_needed(block_text, _split_budget)

        first_sub = True
        for sub_text in sub_blocks:
            # section_changed applies only to the first sub-block; subsequent
            # sub-blocks from the same source block are in the same section.
            effective_section_changed = section_changed and first_sub

            if current_texts and (
                effective_section_changed or _over_budget(current_texts, sub_text)
            ):
                flush(preserve_overlap=not effective_section_changed)
                if effective_section_changed:
                    _discard_pending_headings()

            current_section_path = list(block.section_path)
            if first_sub:
                _drain_pending_headings()  # heading joins the first sub-block
            current_texts.append(sub_text)
            if block_evidence:
                current_evidence.append(block_evidence)
            _absorb_page(block.page_start, block.page_end)
            first_sub = False

    # Final drain: a document that ends with heading(s) and no trailing content
    # emits those headings as a small standalone chunk rather than losing them.
    _drain_pending_headings()
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
