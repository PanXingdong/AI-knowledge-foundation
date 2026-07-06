import csv
import json
from pathlib import Path

import pytest

from agent_knowledge_hub.chunker import _estimate_tokens, _sentence_split_if_needed
from agent_knowledge_hub.models import CANONICAL_DOCUMENT_SCHEMA_VERSION
from agent_knowledge_hub.pipeline import ingest_file, ingest_manifest
from agent_knowledge_hub.parsers import (
    ParsedBlock,
    ParsedDocument,
    UnsupportedDocumentFormatError,
    _build_pdf_text_layer_blocks,
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_ingest_markdown_builds_canonical_document_and_chunks(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text(
        "\n".join(
            [
                "# Startup Manager",
                "",
                "The startup manager shall wait for dependency services.",
                "",
                "## Timeout",
                "",
                "Timeout handling must include retry and recovery.",
                "",
                "| Item | Value |",
                "| --- | --- |",
                "| boot_timeout_ms | 5000 |",
            ]
        ),
        encoding="utf-8",
    )

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "out",
        title="Startup SPEC",
        source_type="internal_spec",
        owner="checker",
        document_version="v1",
        max_chunk_chars=120,
    )

    document = read_json(result.document_json_path)
    chunks = [
        json.loads(line)
        for line in result.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]

    assert result.status == "processed"
    assert document["schema_version"] == CANONICAL_DOCUMENT_SCHEMA_VERSION
    assert document["document"]["title"] == "Startup SPEC"
    assert document["document_version"]["version"] == "v1"
    assert document["parse_report"]["source_format"] == "markdown"
    assert document["parse_report"]["quality_report"]["status"] == "ok"
    assert document["parse_report"]["quality_report"]["score"] >= 90
    assert any(section["title"] == "Timeout" for section in document["sections"])
    assert any(block["block_type"] == "table" for block in document["blocks"])
    assert all(span["text_hash"] for span in document["evidence_spans"])
    assert chunks
    assert all(chunk["evidence_ids"] for chunk in chunks)
    assert "dependency services" in " ".join(chunk["text"] for chunk in chunks)


def test_ingest_html_removes_markup_and_preserves_heading_sections(tmp_path: Path):
    source = tmp_path / "supplier.html"
    source.write_text(
        """
        <html>
          <head><style>.x { color: red; }</style></head>
          <body>
            <h1>Interface Constraints</h1>
            <p>The supplier interface requires authentication.</p>
            <script>alert("ignore")</script>
            <h2>Signal Timing</h2>
            <p>Signal updates must be synchronized before shutdown.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "out",
        source_type="supplier_html",
    )

    document = read_json(result.document_json_path)
    full_text = "\n".join(block["text"] for block in document["blocks"])

    assert document["parse_report"]["source_format"] == "html"
    assert "Interface Constraints" in full_text
    assert "Signal Timing" in full_text
    assert "alert" not in full_text
    assert any(section["title"] == "Signal Timing" for section in document["sections"])


def test_pdf_text_layer_blocks_detect_qnx_style_headings():
    blocks = _build_pdf_text_layer_blocks(
        [
            "\n".join(
                [
                    "Chapter 5",
                    "Optimizing Screen Startup Times",
                    "",
                    "This chapter describes strategies and techniques that you can use.",
                    "",
                    "Screen startup optimizations at a glance",
                    "",
                    "The more time it takes to boot your base system, the more time Screen needs.",
                ]
            )
        ]
    )

    headings = [block for block in blocks if block.block_type == "heading"]
    paragraphs = [block for block in blocks if block.block_type == "paragraph"]

    assert [heading.text for heading in headings] == [
        "Chapter 5",
        "Optimizing Screen Startup Times",
        "Screen startup optimizations at a glance",
    ]
    assert [heading.metadata["level"] for heading in headings] == [1, 2, 2]
    assert all(heading.page_start == 1 for heading in headings)
    assert any("strategies and techniques" in paragraph.text for paragraph in paragraphs)


def test_pdf_text_layer_blocks_split_page_lines_at_inline_headings():
    blocks = _build_pdf_text_layer_blocks(
        [
            "\n".join(
                [
                    "Chapter 1",
                    "About the System Startup Sequence",
                    "The boot process consists of several tasks, each handled by a specialized component.",
                    "These tasks are:",
                    "1. The operating system must load from nonvolatile storage.",
                    "PLL (phase locked loop)",
                    "PLL refers to how long it takes for the first instruction to begin executing after power is applied.",
                    "Startup program",
                    "The first program in a bootable OS image is a startup program.",
                    "Copyright © 2024, BlackBerry Limited 9",
                ]
            )
        ]
    )

    headings = [block.text for block in blocks if block.block_type == "heading"]
    paragraphs = [block.text for block in blocks if block.block_type == "paragraph"]

    assert headings == [
        "Chapter 1",
        "About the System Startup Sequence",
        "PLL (phase locked loop)",
        "Startup program",
    ]
    assert any("boot process consists" in paragraph for paragraph in paragraphs)
    assert any("first program in a bootable OS image" in paragraph for paragraph in paragraphs)
    assert all("Copyright" not in paragraph for paragraph in paragraphs)


def test_pdf_text_layer_blocks_do_not_promote_common_pdf_noise_to_headings():
    blocks = _build_pdf_text_layer_blocks(
        [
            "\n".join(
                [
                    "Chapter 2",
                    "Optimizing the Loading and Launching of the OS",
                    "Optimize the bootloader",
                    "The bootloader should avoid unnecessary initialization work.",
                    "2. Optimize the Screen configuration file",
                    "• image_scan_2()",
                    "LD_LIBRARY_PATH=:/proc/boot:/lib:/usr/lib:/lib/dll procnto –vvvv",
                    "# SPI 0",
                    "Voice: +1 519 888-7465",
                    "Web: https://www.qnx.com/",
                    "Copyright © 2024, BlackBerry Limited14",
                ]
            )
        ]
    )

    headings = [block.text for block in blocks if block.block_type == "heading"]
    paragraphs = [block.text for block in blocks if block.block_type == "paragraph"]

    assert headings == [
        "Chapter 2",
        "Optimizing the Loading and Launching of the OS",
        "Optimize the bootloader",
    ]
    assert any("image_scan_2" in paragraph for paragraph in paragraphs)
    assert any("Optimize the Screen configuration file" in paragraph for paragraph in paragraphs)
    assert any("LD_LIBRARY_PATH" in paragraph for paragraph in paragraphs)
    assert any("# SPI 0" in paragraph for paragraph in paragraphs)
    assert all("BlackBerry Limited" not in paragraph for paragraph in paragraphs)


def test_pdf_text_layer_blocks_skip_repeated_running_headers():
    blocks = _build_pdf_text_layer_blocks(
        [
            "\n".join(
                [
                    "Chapter 5",
                    "Optimizing Screen Startup Times",
                    "Screen startup optimizations at a glance",
                    "Screen can start after the base system is ready.",
                ]
            ),
            "\n".join(
                [
                    "Remove unneeded display managers",
                    "Remove any display manager that is not required by the target.",
                    "Optimizing Screen Startup Times",
                ]
            ),
        ]
    )

    headings = [block.text for block in blocks if block.block_type == "heading"]
    paragraphs = [block.text for block in blocks if block.block_type == "paragraph"]

    assert headings == [
        "Chapter 5",
        "Optimizing Screen Startup Times",
        "Screen startup optimizations at a glance",
        "Remove unneeded display managers",
    ]
    assert any("display manager" in paragraph for paragraph in paragraphs)


def test_ingest_manifest_processes_only_existing_document_paths(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    valid_doc = raw / "architecture.md"
    valid_doc.write_text("# Architecture\n\nASIL checks are required.", encoding="utf-8")

    manifest = tmp_path / "manifest.csv"
    rows = [
        {
            "sample_id": "sample-001",
            "slot_type": "内部技术架构文档",
            "file_path": str(valid_doc),
            "document_title": "Architecture",
            "document_version": "revA",
            "owner": "checker",
            "status": "ready",
        },
        {
            "sample_id": "sample-002",
            "slot_type": "待提供",
            "file_path": "待提供",
            "document_title": "待提供",
            "document_version": "待提供",
            "owner": "待提供",
            "status": "待提供",
        },
    ]
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    summary = ingest_manifest(
        manifest_path=manifest,
        out_dir=tmp_path / "processed",
        project_root=tmp_path,
    )

    assert summary.processed_count == 1
    assert summary.skipped_count == 1
    assert summary.results[0].status == "processed"
    assert summary.skipped[0]["reason"] == "missing_or_placeholder_path"


def test_ingest_chunks_do_not_carry_overlap_across_section_boundary(tmp_path: Path):
    source = tmp_path / "rollout.md"
    source.write_text(
        "\n".join(
            [
                "# Architecture",
                "",
                "This section ends with a unique tail marker: ARCH_TAIL_MARKER_12345.",
                "",
                "## Rollback",
                "",
                "ENABLE_CLAUDE_CODE_RUNTIME=false.",
                "router stops dispatching to claude_code.",
            ]
        ),
        encoding="utf-8",
    )

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "out",
        title="Rollout Plan",
        source_type="internal_spec",
        owner="checker",
        document_version="v1",
        max_chunk_chars=200,
        overlap_chars=32,
    )

    chunks = [
        json.loads(line)
        for line in result.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]

    assert len(chunks) >= 2
    assert chunks[1]["text"].startswith("Rollback")
    assert "ARCH_TAIL_MARKER_12345" not in chunks[1]["text"]
    assert "ENABLE_CLAUDE_CODE_RUNTIME=false" in chunks[1]["text"]


def test_ingest_unsupported_format_fails_explicitly(tmp_path: Path):
    source = tmp_path / "archive.bin"
    source.write_bytes(b"not a supported document")

    with pytest.raises(UnsupportedDocumentFormatError) as error:
        ingest_file(file_path=source, out_dir=tmp_path / "out")

    assert ".bin" in str(error.value)


def test_ingest_preserves_ocr_metadata_in_evidence_and_chunks(monkeypatch, tmp_path: Path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-1.4 fake scan")

    def fake_parse_document(path: Path):
        return ParsedDocument(
            source_format="pdf",
            parser_name="pypdf+rapidocr",
            page_count=1,
            blocks=[
                ParsedBlock(
                    block_type="heading",
                    text="扫描页面",
                    page_start=1,
                    page_end=1,
                    metadata={"level": 2, "ocr_page_marker": True},
                ),
                ParsedBlock(
                    block_type="paragraph",
                    text="控制器故障码 E42 需要复位并检查电源。",
                    page_start=1,
                    page_end=1,
                    metadata={
                        "ocr": True,
                        "ocr_engine": "rapidocr",
                        "content_kind": "ocr_text",
                        "confidence": 0.91,
                        "bbox": [10, 20, 200, 80],
                        "bbox_unit": "pdf_points",
                        "page_image_ref": "source:scan.pdf#page=1",
                        "media_type": "application/pdf",
                        "ocr_lines": [
                            {
                                "text": "控制器故障码 E42",
                                "confidence": 0.92,
                                "bbox": [10, 20, 120, 45],
                            },
                            {
                                "text": "需要复位并检查电源。",
                                "confidence": 0.90,
                                "bbox": [10, 48, 200, 80],
                            },
                        ],
                    },
                )
            ],
        )

    monkeypatch.setattr("agent_knowledge_hub.pipeline.parse_document", fake_parse_document)

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "out",
        title="扫描手册",
        source_type="supplier_scan",
        document_version="v1",
    )

    document = read_json(result.document_json_path)
    chunks = [
        json.loads(line)
        for line in result.chunks_jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    evidence = next(
        span for span in document["evidence_spans"] if "E42" in span["text"]
    )

    assert evidence["bbox"] == [10.0, 20.0, 200.0, 80.0]
    assert evidence["metadata"]["ocr"] is True
    assert evidence["metadata"]["confidence"] == 0.91
    assert evidence["metadata"]["page_image_ref"] == "source:scan.pdf#page=1"
    assert chunks[0]["metadata"]["ocr"] is True
    assert chunks[0]["metadata"]["content_kind"] == "ocr_text"
    assert chunks[0]["metadata"]["page_image_refs"] == ["source:scan.pdf#page=1"]


def test_ingest_image_copies_media_asset(monkeypatch, tmp_path: Path):
    source = tmp_path / "device-error.png"
    source.write_bytes(b"fake image bytes")

    def fake_parse_document(path: Path):
        return ParsedDocument(
            source_format="image",
            parser_name="rapidocr-image",
            page_count=1,
            blocks=[
                ParsedBlock(
                    block_type="heading",
                    text="截图内容",
                    page_start=1,
                    page_end=1,
                    metadata={"level": 2},
                ),
                ParsedBlock(
                    block_type="paragraph",
                    text="设备截图显示错误码 E42。",
                    page_start=1,
                    page_end=1,
                    metadata={
                        "ocr": True,
                        "content_kind": "ocr_text",
                        "media_ref": "media/device-error.png",
                        "page_image_ref": "media/device-error.png",
                        "media_type": "image/png",
                        "bbox": [2, 4, 80, 30],
                        "bbox_unit": "pixels",
                    },
                )
            ],
        )

    monkeypatch.setattr("agent_knowledge_hub.pipeline.parse_document", fake_parse_document)

    result = ingest_file(
        file_path=source,
        out_dir=tmp_path / "out",
        title="设备错误截图",
        source_type="screenshot",
    )

    document = read_json(result.document_json_path)
    evidence = next(
        span for span in document["evidence_spans"] if "E42" in span["text"]
    )

    assert (result.output_dir / "media" / "device-error.png").read_bytes() == b"fake image bytes"
    assert evidence["metadata"]["media_ref"] == "media/device-error.png"
    assert evidence["metadata"]["page_image_ref"] == "media/device-error.png"


def test_sentence_split_hard_cuts_single_line_exceeding_budget():
    # A single unbreakable line (no spaces, newlines, or sentence boundaries)
    # that far exceeds the token budget must still be split into fragments each
    # within the budget — the hard character-window fallback must fire.
    budget = 16  # ~64 ASCII chars
    long_line = "A" * (budget * 4 * 3)  # 3× the character window

    fragments = _sentence_split_if_needed(long_line, budget)

    assert len(fragments) > 1, "expected hard cut to produce multiple fragments"
    for frag in fragments:
        # Each fragment must fit within the budget (4 ASCII chars ≈ 1 token).
        assert len(frag) <= budget * 4, f"fragment too long: {len(frag)} chars"
    # Original content must be fully preserved across all fragments.
    assert "".join(fragments) == long_line


def test_sentence_split_hard_cuts_cjk_line_by_token_budget():
    budget = 16
    long_line = "中" * (budget * 5)

    fragments = _sentence_split_if_needed(long_line, budget)

    assert len(fragments) > 1
    assert all(_estimate_tokens(fragment) <= budget for fragment in fragments)
    assert "".join(fragments) == long_line
