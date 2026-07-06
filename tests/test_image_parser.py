"""Tests for image parsing via parse_image() and parse_document() routing."""
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_knowledge_hub.parsers import (
    DocumentParseError,
    ParsedBlock,
    ParsedDocument,
    UnsupportedDocumentFormatError,
    _IMAGE_EXTENSIONS,
    parse_document,
    parse_image,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ocr_result(lines: list[str]):
    """Build a fake rapidocr result list matching the existing _rapidocr_result_to_lines contract."""
    return [[None, line, 0.9] for line in lines]


@contextmanager
def _mock_rapidocr(return_value=None, side_effect=None):
    """Inject a fake rapidocr module so the lazy import inside parse_image() resolves."""
    fake_ocr_instance = MagicMock()
    if side_effect is not None:
        fake_ocr_instance.side_effect = side_effect
    else:
        fake_ocr_instance.return_value = return_value

    fake_rapidocr_module = MagicMock()
    fake_rapidocr_module.RapidOCR = MagicMock(return_value=fake_ocr_instance)

    with patch.dict(sys.modules, {"rapidocr": fake_rapidocr_module}):
        yield fake_ocr_instance


# ---------------------------------------------------------------------------
# SUPPORTED_EXTENSIONS coverage
# ---------------------------------------------------------------------------

def test_image_extensions_are_in_supported_extensions():
    from agent_knowledge_hub.parsers import SUPPORTED_EXTENSIONS

    for ext in _IMAGE_EXTENSIONS:
        assert ext in SUPPORTED_EXTENSIONS, f"{ext} missing from SUPPORTED_EXTENSIONS"


# ---------------------------------------------------------------------------
# parse_document routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("suffix", [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"])
def test_parse_document_routes_image_formats_to_parse_image(tmp_path: Path, suffix: str):
    img_path = tmp_path / f"sample{suffix}"
    img_path.write_bytes(b"\x00" * 16)  # dummy bytes

    fake_result = ParsedDocument(
        source_format="image",
        parser_name="rapidocr",
        page_count=1,
        blocks=[ParsedBlock(block_type="paragraph", text="test text", page_start=1, page_end=1)],
    )

    with patch("agent_knowledge_hub.parsers.parse_image", return_value=fake_result) as mock_parse:
        result = parse_document(img_path)

    mock_parse.assert_called_once_with(img_path)
    assert result.source_format == "image"


def test_parse_document_still_raises_for_unsupported_format(tmp_path: Path):
    bad_path = tmp_path / "file.xyz"
    bad_path.write_bytes(b"data")

    with pytest.raises(UnsupportedDocumentFormatError):
        parse_document(bad_path)


# ---------------------------------------------------------------------------
# parse_image — OCR succeeds
# ---------------------------------------------------------------------------

def test_parse_image_returns_ocr_text_as_paragraph(tmp_path: Path):
    img_path = tmp_path / "diagram.png"
    img_path.write_bytes(b"\x89PNG\r\n")

    fake_ocr_lines = ["系统架构图", "模块A 连接 模块B"]

    with _mock_rapidocr(return_value=_make_ocr_result(fake_ocr_lines)):
        result = parse_image(img_path)

    assert result.source_format == "image"
    assert result.parser_name == "rapidocr"
    assert result.page_count == 1
    assert len(result.blocks) == 1
    block = result.blocks[0]
    assert block.block_type == "paragraph"
    assert "系统架构图" in block.text
    assert "模块A 连接 模块B" in block.text
    assert block.metadata.get("ocr") is True
    assert result.warnings == []


def test_parse_image_quality_report_is_ok_when_text_extracted(tmp_path: Path):
    img_path = tmp_path / "photo.jpg"
    img_path.write_bytes(b"\xff\xd8\xff")

    with _mock_rapidocr(return_value=_make_ocr_result(["Some extracted text from the image document, long enough to pass quality gate"])):
        result = parse_image(img_path)

    assert result.quality_report is not None
    assert result.quality_report["status"] == "ok"


# ---------------------------------------------------------------------------
# parse_image — no text extracted
# ---------------------------------------------------------------------------

def test_parse_image_warns_when_no_text_extracted(tmp_path: Path):
    img_path = tmp_path / "blank.png"
    img_path.write_bytes(b"\x89PNG\r\n")

    with _mock_rapidocr(return_value=None):  # RapidOCR returns None for blank images
        result = parse_image(img_path)

    assert result.blocks == []
    assert "no_ocr_text_extracted" in result.warnings
    assert result.quality_report["status"] == "low_quality"


# ---------------------------------------------------------------------------
# parse_image — OCR runtime failure
# ---------------------------------------------------------------------------

def test_parse_image_warns_on_ocr_runtime_error(tmp_path: Path):
    img_path = tmp_path / "corrupt.jpg"
    img_path.write_bytes(b"\xff\xd8\xff")

    with _mock_rapidocr(side_effect=RuntimeError("OCR engine crashed")):
        result = parse_image(img_path)

    assert result.blocks == []
    assert any("image_ocr_failed" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# parse_image — missing dependency
# ---------------------------------------------------------------------------

def test_parse_image_raises_document_parse_error_when_rapidocr_missing(tmp_path: Path):
    img_path = tmp_path / "sample.png"
    img_path.write_bytes(b"\x89PNG\r\n")

    with patch.dict("sys.modules", {"rapidocr": None}):
        with pytest.raises(DocumentParseError, match="rapidocr"):
            parse_image(img_path)
