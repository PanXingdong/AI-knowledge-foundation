from pathlib import Path

from agent_knowledge_hub.dependencies import (
    check_runtime_dependencies,
    write_runtime_dependency_report_bundle,
)


def test_runtime_dependency_report_marks_missing_capabilities():
    installed = {"pypdf", "onnxruntime"}

    def fake_find_spec(name: str):
        return object() if name in installed else None

    report = check_runtime_dependencies(find_spec=fake_find_spec)
    capabilities = {capability.capability: capability for capability in report.capabilities}

    assert capabilities["plain_text"].ready is True
    assert capabilities["pdf_text"].ready is True
    assert capabilities["docx"].ready is False
    assert capabilities["docx"].missing_packages == ["python-docx"]
    assert capabilities["pdf_ocr"].ready is False
    assert capabilities["pdf_ocr"].missing_packages == ["pymupdf", "rapidocr"]
    assert "Runtime Dependency Report" in report.markdown


def test_runtime_dependency_report_writes_json_and_markdown(tmp_path: Path):
    def fake_find_spec(name: str):
        return object()

    report = check_runtime_dependencies(find_spec=fake_find_spec)
    bundle = write_runtime_dependency_report_bundle(
        output_dir=tmp_path / "deps",
        report=report,
    )

    assert bundle["json_path"].exists()
    assert bundle["markdown_path"].exists()
    assert "pdf_ocr" in bundle["markdown_path"].read_text(encoding="utf-8")
