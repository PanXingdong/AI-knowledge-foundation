from __future__ import annotations

from dataclasses import asdict

from agent_knowledge_hub.models import CanonicalDocument, Chunk
from agent_knowledge_hub.utils import stable_id


def build_chunks(
    canonical: CanonicalDocument,
    *,
    max_chunk_chars: int = 1600,
    overlap_chars: int = 160,
) -> list[Chunk]:
    """Build section-aware chunks from canonical blocks."""
    if max_chunk_chars < 50:
        raise ValueError("max_chunk_chars must be >= 50")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")
    if overlap_chars >= max_chunk_chars:
        overlap_chars = max(0, max_chunk_chars // 10)

    evidence_by_block = {
        evidence.block_id: evidence.evidence_id for evidence in canonical.evidence_spans
    }
    chunks: list[Chunk] = []
    current_texts: list[str] = []
    current_evidence: list[str] = []
    current_section_path: list[str] = []
    current_page_start: int | None = None
    current_page_end: int | None = None

    def flush(*, preserve_overlap: bool = True) -> None:
        nonlocal current_texts, current_evidence, current_section_path
        nonlocal current_page_start, current_page_end
        text = "\n\n".join(part for part in current_texts if part.strip()).strip()
        if not text:
            current_texts = []
            current_evidence = []
            return
        chunk_id = stable_id(
            "chunk",
            canonical.document_version.document_version_id,
            len(chunks) + 1,
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
            overlap_texts = _select_overlap_texts(current_texts, overlap_chars)
            current_texts = overlap_texts
            current_evidence = list(dict.fromkeys(current_evidence[-len(overlap_texts) :]))
        else:
            current_texts = []
            current_evidence = []
        current_page_start = None
        current_page_end = None

    for block in canonical.blocks:
        block_text = block.text.strip()
        if not block_text:
            continue

        block_evidence = evidence_by_block.get(block.block_id)
        next_len = len("\n\n".join([*current_texts, block_text]))
        section_changed = current_section_path and block.section_path != current_section_path
        if current_texts and (section_changed or next_len > max_chunk_chars):
            flush(preserve_overlap=not section_changed)

        current_section_path = list(block.section_path)
        current_texts.append(block_text)
        if block_evidence:
            current_evidence.append(block_evidence)
        if block.page_start is not None:
            current_page_start = (
                block.page_start
                if current_page_start is None
                else min(current_page_start, block.page_start)
            )
        if block.page_end is not None:
            current_page_end = (
                block.page_end
                if current_page_end is None
                else max(current_page_end, block.page_end)
            )

    flush()
    return chunks


def chunks_to_dicts(chunks: list[Chunk]) -> list[dict]:
    return [asdict(chunk) for chunk in chunks]


def _select_overlap_texts(texts: list[str], overlap_chars: int) -> list[str]:
    if overlap_chars <= 0 or not texts:
        return []

    selected: list[str] = []
    total_chars = 0
    for text in reversed(texts):
        selected.append(text)
        total_chars += len(text)
        if total_chars >= overlap_chars:
            break
    return list(reversed(selected))
