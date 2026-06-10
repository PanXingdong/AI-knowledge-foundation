from pathlib import Path

from agent_knowledge_hub.parsers import (
    ParsedBlock,
    ParsedDocument,
    assess_pdf_text_quality,
    parse_pdf,
)


def test_pdf_text_quality_accepts_readable_chinese_text():
    text = "\n".join(
        [
            "汽车数据通用要求",
            "5 个人信息保护要求",
            "除非驾驶人自主设定，车辆应默认设定为不收集个人信息的状态。",
            "6.3 重要数据存储",
            "车辆应采取安全访问技术、加密技术或其他安全技术保护存储在车内的重要数据。",
        ]
    )

    report = assess_pdf_text_quality(text)

    assert report.should_use_ocr is False
    assert report.mojibake_suspect_count == 0
    assert report.reason_codes == []


def test_pdf_text_quality_flags_mojibake_heavy_chinese_text():
    text = "\n".join(
        [
            "ち车数据通用要求",
            "个人信息な巧まホ",
            "重要数据存輔",
            "车辆应采取安全访问技术、加密技术或其他安全技术。",
        ]
    )

    report = assess_pdf_text_quality(text)

    assert report.should_use_ocr is True
    assert "mojibake_suspect_ratio_high" in report.reason_codes


def test_pdf_text_quality_flags_empty_text():
    report = assess_pdf_text_quality("")

    assert report.should_use_ocr is True
    assert "text_too_short" in report.reason_codes


def test_parse_pdf_uses_rapidocr_fallback_when_text_layer_quality_is_low(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "standard.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def fake_text_layer(path: Path):
        return (["ち车数据通用要求\n个人信息な巧まホ"], 1, [])

    def fake_ocr(path: Path):
        return ParsedDocument(
            source_format="pdf",
            parser_name="rapidocr",
            page_count=1,
            blocks=[
                ParsedBlock(
                    block_type="paragraph",
                    text="汽车数据通用要求 个人信息保护要求",
                    page_start=1,
                    page_end=1,
                )
            ],
        )

    monkeypatch.setattr("agent_knowledge_hub.parsers._extract_pdf_text_pages_with_pypdf", fake_text_layer)
    monkeypatch.setattr("agent_knowledge_hub.parsers._parse_pdf_with_rapidocr", fake_ocr)

    parsed = parse_pdf(pdf_path)

    assert parsed.parser_name == "pypdf+rapidocr"
    assert parsed.blocks[0].text == "汽车数据通用要求 个人信息保护要求"
    assert "pdf_text_quality_low_using_ocr" in parsed.warnings
    assert any(warning.startswith("pdf_text_quality:") for warning in parsed.warnings)


def test_parse_pdf_returns_text_layer_with_warning_when_ocr_is_unavailable(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "standard.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def fake_text_layer(path: Path):
        return (["ち车数据通用要求\n个人信息な巧まホ"], 1, [])

    def fake_ocr(path: Path):
        raise RuntimeError("RapidOCR dependencies are not installed")

    monkeypatch.setattr("agent_knowledge_hub.parsers._extract_pdf_text_pages_with_pypdf", fake_text_layer)
    monkeypatch.setattr("agent_knowledge_hub.parsers._parse_pdf_with_rapidocr", fake_ocr)

    parsed = parse_pdf(pdf_path)

    assert parsed.parser_name == "pypdf"
    assert "ち车数据通用要求" in parsed.blocks[0].text
    assert "个人信息な巧まホ" in parsed.blocks[0].text
    assert "pdf_text_quality_low_ocr_unavailable" in parsed.warnings
    assert any("RapidOCR dependencies are not installed" in warning for warning in parsed.warnings)


def test_parse_pdf_returns_text_layer_when_ocr_result_has_no_text(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "standard.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def fake_text_layer(path: Path):
        return (["ち车数据通用要求\n个人信息な巧まホ"], 1, [])

    def fake_ocr(path: Path):
        return ParsedDocument(
            source_format="pdf",
            parser_name="rapidocr",
            page_count=1,
            blocks=[
                ParsedBlock(
                    block_type="heading",
                    text="Page 1",
                    page_start=1,
                    page_end=1,
                    metadata={"level": 2, "ocr_page_marker": True},
                )
            ],
            warnings=["no_ocr_text_blocks_extracted"],
        )

    monkeypatch.setattr("agent_knowledge_hub.parsers._extract_pdf_text_pages_with_pypdf", fake_text_layer)
    monkeypatch.setattr("agent_knowledge_hub.parsers._parse_pdf_with_rapidocr", fake_ocr)

    parsed = parse_pdf(pdf_path)

    assert parsed.parser_name == "pypdf"
    assert "ち车数据通用要求" in parsed.blocks[0].text
    assert "pdf_text_quality_low_ocr_unusable" in parsed.warnings
    assert "no_ocr_text_blocks_extracted" in parsed.warnings


def test_parse_pdf_exposes_structured_quality_report(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "standard.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def fake_text_layer(path: Path):
        return (
            [
                "\n".join(
                    [
                        "汽车数据通用要求",
                        "个人信息保护要求",
                        "重要数据存储",
                        "车辆应采取安全访问技术、加密技术或其他安全技术保护存储在车内的重要数据。",
                    ]
                )
            ],
            1,
            [],
        )

    monkeypatch.setattr("agent_knowledge_hub.parsers._extract_pdf_text_pages_with_pypdf", fake_text_layer)

    parsed = parse_pdf(pdf_path)

    assert parsed.quality_report is not None
    assert parsed.quality_report["score"] >= 90
    assert parsed.quality_report["status"] == "ok"
    assert parsed.quality_report["metrics"]["cjk_count"] >= 20
    assert parsed.quality_report["reason_codes"] == []
