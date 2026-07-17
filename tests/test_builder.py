"""Unit tests for agent_knowledge_hub.builder.build_canonical_document.

Coverage targets:
- PDF bookmark sections drive block section_path assignment
- Same-page bookmarks never produce page_end < page_start
- Parser-detected headings create sub-sections within bookmark sections
- Heading counters reset when the bookmark section changes
- Bookmark parse failure falls back to heading-based mode
- Duplicate bookmark paths keep block/section consistency
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_knowledge_hub.builder import build_canonical_document
from agent_knowledge_hub.parsers import ParsedBlock, ParsedDocument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parsed(blocks: list[ParsedBlock], page_count: int = 20) -> ParsedDocument:
    return ParsedDocument(
        source_format="pdf",
        parser_name="test_parser",
        page_count=page_count,
        blocks=blocks,
    )


def _build_with_bookmarks(
    tmp_path: Path,
    blocks: list[ParsedBlock],
    outline_entries: list[tuple[int, list[str]]],
    page_count: int = 20,
):
    """Call build_canonical_document with a mocked PDF reader.

    outline_entries: [(page_1indexed, path), ...] – what _flatten_pdf_outline would return.
    """
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(b"fake-pdf")

    reader_mock = MagicMock()
    reader_mock.outline = [object()]  # non-empty → triggers bookmark branch

    with (
        patch("agent_knowledge_hub.builder.file_sha256", return_value="deadbeef"),
        patch("pypdf.PdfReader", return_value=reader_mock),
        patch(
            "agent_knowledge_hub.builder._flatten_pdf_outline",
            return_value=outline_entries,
        ),
    ):
        return build_canonical_document(
            parsed=_parsed(blocks, page_count=page_count),
            file_path=pdf_file,
            title="TestDoc",
        )


# ---------------------------------------------------------------------------
# Test 1: bookmark sections drive block section_path
# ---------------------------------------------------------------------------

def test_pdf_bookmark_sections_assign_block_path(tmp_path):
    outline = [(1, ["Chapter 1"]), (3, ["Chapter 2"])]
    blocks = [
        ParsedBlock(block_type="paragraph", text="intro",   page_start=1),
        ParsedBlock(block_type="paragraph", text="body",    page_start=2),
        ParsedBlock(block_type="paragraph", text="ch2body", page_start=3),
    ]
    doc = _build_with_bookmarks(tmp_path, blocks, outline, page_count=4)

    paths = [b.section_path for b in doc.blocks]
    assert paths[0] == ["Chapter 1"]
    assert paths[1] == ["Chapter 1"]
    # Block on Chapter 2's start page must belong to Chapter 2, not Chapter 1.
    assert paths[2] == ["Chapter 2"]


# ---------------------------------------------------------------------------
# Test 2: same-page bookmarks never produce page_end < page_start
# ---------------------------------------------------------------------------

def test_same_page_bookmarks_no_invalid_page_range(tmp_path):
    # Two bookmarks on page 1; with naive "next_page - 1" the first would get
    # page_end = 1-1 = 0.  The max() guard must prevent that.
    outline = [(1, ["Section A"]), (1, ["Section B"]), (5, ["Chapter 2"])]
    blocks = [ParsedBlock(block_type="paragraph", text="text", page_start=1)]
    doc = _build_with_bookmarks(tmp_path, blocks, outline, page_count=10)

    for section in doc.sections:
        if section.page_start is not None and section.page_end is not None:
            assert section.page_end >= section.page_start, (
                f"Section {section.section_path} has "
                f"page_end={section.page_end} < page_start={section.page_start}"
            )


# ---------------------------------------------------------------------------
# Test 3: parser-detected headings create sub-sections inside bookmark sections
# ---------------------------------------------------------------------------

def test_pdf_bookmarks_and_headings_create_sub_sections(tmp_path):
    outline = [(1, ["Chapter 1"]), (10, ["Chapter 2"])]
    blocks = [
        ParsedBlock(block_type="paragraph", text="intro",      page_start=1),
        ParsedBlock(block_type="heading",   text="Sub A",      page_start=2, metadata={"level": 2}),
        ParsedBlock(block_type="paragraph", text="sub A body", page_start=2),
        ParsedBlock(block_type="heading",   text="Sub B",      page_start=4, metadata={"level": 2}),
        ParsedBlock(block_type="paragraph", text="sub B body", page_start=5),
    ]
    doc = _build_with_bookmarks(tmp_path, blocks, outline, page_count=15)

    paths = [b.section_path for b in doc.blocks]
    # heading_counts pads missing levels with 0, so a level-2 heading with no
    # preceding level-1 heading produces heading_suffix=["0","1"], not ["1"].
    assert paths[0] == ["Chapter 1"]              # plain para before first heading → bookmark path
    assert paths[1] == ["Chapter 1", "0", "1"]   # "Sub A" heading block itself
    assert paths[2] == ["Chapter 1", "0", "1"]   # body following Sub A
    assert paths[3] == ["Chapter 1", "0", "2"]   # "Sub B" heading block
    assert paths[4] == ["Chapter 1", "0", "2"]   # body following Sub B

    section_paths = [s.section_path for s in doc.sections]
    assert ["Chapter 1", "0", "1"] in section_paths
    assert ["Chapter 1", "0", "2"] in section_paths


# ---------------------------------------------------------------------------
# Test 4: heading counters reset when the bookmark section changes
# ---------------------------------------------------------------------------

def test_heading_counters_reset_on_bookmark_change(tmp_path):
    outline = [(1, ["Chapter 1"]), (10, ["Chapter 2"])]
    blocks = [
        # Two headings inside Chapter 1 (pages 1-9)
        ParsedBlock(block_type="heading", text="Sec A", page_start=2, metadata={"level": 2}),
        ParsedBlock(block_type="heading", text="Sec B", page_start=3, metadata={"level": 2}),
        # Chapter 2 starts on page 10; a block on that page must land in Chapter 2.
        ParsedBlock(block_type="heading", text="Sec C", page_start=10, metadata={"level": 2}),
    ]
    doc = _build_with_bookmarks(tmp_path, blocks, outline, page_count=15)

    paths = [b.section_path for b in doc.blocks]
    # Level-2 headings with no preceding level-1: suffix is ["0", n].
    assert paths[0] == ["Chapter 1", "0", "1"]   # first heading in Chapter 1
    assert paths[1] == ["Chapter 1", "0", "2"]   # second heading in Chapter 1
    assert paths[2] == ["Chapter 2", "0", "1"]   # counter resets after bookmark change


# ---------------------------------------------------------------------------
# Test 5: bookmark parse failure falls back to heading-based mode
# ---------------------------------------------------------------------------

def test_bookmark_parse_failure_falls_back_to_heading_mode(tmp_path):
    pdf_file = tmp_path / "broken.pdf"
    pdf_file.write_bytes(b"fake")

    parsed = _parsed(
        blocks=[
            ParsedBlock(block_type="heading",   text="Chapter 1", page_start=1, metadata={"level": 1}),
            ParsedBlock(block_type="paragraph", text="body",       page_start=1),
        ],
        page_count=5,
    )

    with (
        patch("agent_knowledge_hub.builder.file_sha256", return_value="deadbeef"),
        patch("pypdf.PdfReader", side_effect=Exception("corrupt PDF")),
    ):
        doc = build_canonical_document(parsed=parsed, file_path=pdf_file, title="Broken")

    paths = [b.section_path for b in doc.blocks]
    assert paths[0] == ["1"]   # heading-based fallback creates numeric path
    assert paths[1] == ["1"]


# ---------------------------------------------------------------------------
# Test 6: duplicate bookmark paths – block/section consistency maintained
# ---------------------------------------------------------------------------

def test_duplicate_bookmark_paths_block_section_consistent(tmp_path):
    # "Chapter 1" appears twice (PDF outline anomaly / repeated chapter).
    # Without the fix, the second occurrence is skipped but blocks there still
    # reference ["Chapter 1"], whose Section page_end only covers the first span.
    outline = [
        (1, ["Chapter 1"]),
        (5, ["Chapter 1"]),   # duplicate path
        (10, ["Chapter 2"]),
    ]
    blocks = [
        ParsedBlock(block_type="paragraph", text="ch1a", page_start=1),
        ParsedBlock(block_type="paragraph", text="ch1b", page_start=7),  # beyond original page_end=4
    ]
    doc = _build_with_bookmarks(tmp_path, blocks, outline, page_count=15)

    # Every block's section_path must have a matching Section.
    section_paths_present = {"\x00".join(s.section_path) for s in doc.sections}
    for block in doc.blocks:
        key = "\x00".join(block.section_path)
        assert key in section_paths_present, (
            f"Block section_path={block.section_path!r} has no matching Section"
        )

    # "Chapter 1" must be deduplicated to exactly one Section.
    ch1_sections = [s for s in doc.sections if s.section_path == ["Chapter 1"]]
    assert len(ch1_sections) == 1

    # page_end must be extended to cover the re-occurrence range (pages 5-9).
    assert ch1_sections[0].page_end is not None
    assert ch1_sections[0].page_end >= 7
