from __future__ import annotations

from pathlib import Path

from agent_knowledge_hub.models import (
    Block,
    CANONICAL_DOCUMENT_SCHEMA_VERSION,
    CanonicalDocument,
    Document,
    DocumentVersion,
    EvidenceSpan,
    ParseReport,
    Section,
)
from agent_knowledge_hub.parsers import ParsedDocument
from agent_knowledge_hub.utils import file_sha256, sha256_text, stable_id, utc_now_iso


def _flatten_pdf_outline(
    items: list,
    reader: object,
    parent_path: list[str],
) -> list[tuple[int, list[str]]]:
    """Recursively flatten a pypdf outline into [(page_1indexed, [path_components])]."""
    result: list[tuple[int, list[str]]] = []
    prev_path: list[str] | None = None
    for item in items:
        if isinstance(item, list):
            # Nested list = children of the previous entry
            if prev_path is not None:
                result.extend(_flatten_pdf_outline(item, reader, prev_path))
        else:
            try:
                page = reader.get_destination_page_number(item) + 1  # type: ignore[attr-defined]
                path = parent_path + [item.title.strip()]
                result.append((page, path))
                prev_path = path
            except Exception:
                prev_path = None
    return result


def _find_section_path_for_page(
    sorted_entries: list[tuple[int, list[str]]],
    page: int | None,
) -> list[str]:
    """Return the deepest section_path that starts at or before the given page."""
    if not sorted_entries or page is None:
        return ["0"]
    path: list[str] = ["0"]
    for entry_page, entry_path in sorted_entries:
        if entry_page <= page:
            path = entry_path
        else:
            break
    return path


def build_canonical_document(
    *,
    parsed: ParsedDocument,
    file_path: Path,
    title: str | None = None,
    source_type: str = "unknown",
    owner: str = "unknown",
    project: str = "unknown",
    supplier: str = "unknown",
    document_version: str = "unknown",
    sample_id: str | None = None,
) -> CanonicalDocument:
    resolved_path = file_path.resolve()
    file_hash = file_sha256(resolved_path)
    resolved_title = title or resolved_path.stem
    created_at = utc_now_iso()

    document_id = stable_id("doc", resolved_title, source_type, supplier, project)
    document_version_id = stable_id("docver", document_id, document_version, file_hash)

    document = Document(
        document_id=document_id,
        title=resolved_title,
        source_type=source_type,
        owner=owner,
        project=project,
        supplier=supplier,
        created_at=created_at,
    )
    version = DocumentVersion(
        document_version_id=document_version_id,
        document_id=document_id,
        version=document_version,
        file_path=str(resolved_path),
        file_hash=file_hash,
        created_at=created_at,
    )

    # Extract PDF bookmarks and build a sorted page→section_path lookup.
    # Falls back to heading-based detection for non-PDF or PDFs without bookmarks.
    pdf_sorted_entries: list[tuple[int, list[str]]] = []
    if file_path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            _reader = PdfReader(str(resolved_path))
            if _reader.outline:
                pdf_sorted_entries = sorted(
                    _flatten_pdf_outline(_reader.outline, _reader, []),
                    key=lambda x: x[0],
                )
        except Exception:
            pass

    # Pre-build Section objects from bookmarks (PDF mode only).
    sections: list[Section] = []
    if pdf_sorted_entries:
        first_bm_page = pdf_sorted_entries[0][0]
        # Always add a ["0"] section so blocks before the first bookmark
        # (cover, TOC, colophon) have a valid section to reference.
        sections.append(
            Section(
                section_id=stable_id("sec", document_version_id, "0", "Document"),
                document_version_id=document_version_id,
                section_path=["0"],
                title="Document",
                page_start=1,
                page_end=first_bm_page - 1 if first_bm_page > 1 else None,
            )
        )
        seen_keys: set[str] = {"0"}
        total_pages = parsed.page_count or 0
        for i, (page_start, path) in enumerate(pdf_sorted_entries):
            page_end = (
                pdf_sorted_entries[i + 1][0] - 1
                if i + 1 < len(pdf_sorted_entries)
                else total_pages
            )
            section_key = "\x00".join(path)
            if section_key not in seen_keys:
                seen_keys.add(section_key)
                sections.append(
                    Section(
                        section_id=stable_id("sec", document_version_id, section_key),
                        document_version_id=document_version_id,
                        section_path=list(path),
                        title=path[-1],
                        page_start=page_start,
                        page_end=page_end,
                    )
                )

    blocks: list[Block] = []
    evidence_spans: list[EvidenceSpan] = []
    current_section_path = ["0"]
    current_section_id: str | None = None
    heading_counts: list[int] = []

    def ensure_default_section() -> None:
        nonlocal current_section_id
        if current_section_id is not None:
            return
        current_section_id = stable_id("sec", document_version_id, "0", "Document")
        sections.append(
            Section(
                section_id=current_section_id,
                document_version_id=document_version_id,
                section_path=["0"],
                title="Document",
                page_start=None,
                page_end=None,
            )
        )

    for order, parsed_block in enumerate(parsed.blocks, start=1):
        if pdf_sorted_entries:
            # PDF bookmark mode: assign section by page number
            current_section_path = _find_section_path_for_page(
                pdf_sorted_entries, parsed_block.page_start
            )
        elif parsed_block.block_type == "heading":
            # Heading-based mode: Markdown / DOCX / HTML
            level = int(parsed_block.metadata.get("level", 1))
            level = max(1, min(level, 6))
            while len(heading_counts) < level:
                heading_counts.append(0)
            heading_counts[level - 1] += 1
            heading_counts = heading_counts[:level]
            current_section_path = [str(value) for value in heading_counts]
            current_section_id = stable_id(
                "sec", document_version_id, ".".join(current_section_path), parsed_block.text
            )
            sections.append(
                Section(
                    section_id=current_section_id,
                    document_version_id=document_version_id,
                    section_path=list(current_section_path),
                    title=parsed_block.text,
                    page_start=parsed_block.page_start,
                    page_end=parsed_block.page_end,
                )
            )
        else:
            ensure_default_section()

        block_id = stable_id("blk", document_version_id, order, parsed_block.text)
        block = Block(
            block_id=block_id,
            document_version_id=document_version_id,
            block_type=parsed_block.block_type,
            text=parsed_block.text,
            page_start=parsed_block.page_start,
            page_end=parsed_block.page_end,
            section_path=list(current_section_path),
            order=order,
            metadata={
                **parsed_block.metadata,
                **({"sample_id": sample_id} if sample_id else {}),
            },
        )
        blocks.append(block)

        evidence_id = stable_id("span", document_version_id, block_id, parsed_block.text)
        evidence_spans.append(
            EvidenceSpan(
                evidence_id=evidence_id,
                document_version_id=document_version_id,
                page=parsed_block.page_start,
                section_path=list(current_section_path),
                block_id=block_id,
                bbox=None,
                text=parsed_block.text,
                text_hash=sha256_text(parsed_block.text),
            )
        )

    table_count = sum(1 for block in blocks if block.block_type == "table")
    parse_report = ParseReport(
        parser_name=parsed.parser_name,
        source_format=parsed.source_format,
        page_count=parsed.page_count,
        section_count=len(sections),
        block_count=len(blocks),
        table_count=table_count,
        has_page_numbers=any(block.page_start is not None for block in blocks),
        warnings=list(parsed.warnings),
        quality_report=parsed.quality_report,
    )

    return CanonicalDocument(
        schema_version=CANONICAL_DOCUMENT_SCHEMA_VERSION,
        document=document,
        document_version=version,
        sections=sections,
        blocks=blocks,
        evidence_spans=evidence_spans,
        parse_report=parse_report,
    )
