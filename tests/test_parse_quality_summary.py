import csv
import json
from pathlib import Path

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.pipeline import ingest_manifest
from agent_knowledge_hub.quality import (
    build_parse_quality_summary,
    write_parse_quality_summary_bundle,
)


def test_build_parse_quality_summary_includes_processed_and_failed_manifest_rows(
    tmp_path: Path,
):
    source_dir = tmp_path / "raw"
    source_dir.mkdir()
    good_doc = source_dir / "architecture.md"
    good_doc.write_text(
        "\n".join(
            [
                "# 架构设计",
                "",
                "第一阶段采用第三种 runtime 模式，默认不写主仓库，并保留审批与审计能力。",
                "该设计用于验证多文档 Agent Knowledge Hub 的上下文组装能力。",
            ]
        ),
        encoding="utf-8",
    )
    short_doc = source_dir / "short.txt"
    short_doc.write_text("短文本", encoding="utf-8")
    unsupported_doc = source_dir / "legacy.doc"
    unsupported_doc.write_text("legacy binary placeholder", encoding="utf-8")

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "file_path",
                "document_title",
                "slot_type",
                "owner",
                "project",
                "supplier",
                "document_version",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "sample_id": "doc-001",
                "file_path": str(good_doc),
                "document_title": "架构设计",
                "slot_type": "内部设计文档",
                "owner": "checker",
                "project": "knowledge-hub",
                "supplier": "internal",
                "document_version": "v1",
            }
        )
        writer.writerow(
            {
                "sample_id": "doc-002",
                "file_path": str(short_doc),
                "document_title": "短文本",
                "slot_type": "内部说明",
                "owner": "checker",
                "project": "knowledge-hub",
                "supplier": "internal",
                "document_version": "v1",
            }
        )
        writer.writerow(
            {
                "sample_id": "doc-003",
                "file_path": str(unsupported_doc),
                "document_title": "旧版 Word",
                "slot_type": "供应商资料",
                "owner": "checker",
                "project": "knowledge-hub",
                "supplier": "unknown",
                "document_version": "legacy",
            }
        )

    processed_root = tmp_path / "processed"
    ingest_summary = ingest_manifest(
        manifest_path=manifest,
        out_dir=processed_root,
        project_root=tmp_path,
    )

    assert ingest_summary.processed_count == 2
    assert ingest_summary.failed_count == 1

    summary = build_parse_quality_summary(processed_root)
    payload = summary.to_dict()

    assert payload["processed_document_count"] == 2
    assert payload["failed_input_count"] == 1
    assert payload["status_counts"]["ok"] == 1
    assert payload["status_counts"]["low_quality"] == 1
    assert payload["status_counts"]["unsupported"] == 1

    architecture = next(item for item in payload["documents"] if item["title"] == "架构设计")
    short = next(item for item in payload["documents"] if item["title"] == "短文本")
    failed = payload["failed_inputs"][0]

    assert architecture["project"] == "knowledge-hub"
    assert architecture["supplier"] == "internal"
    assert architecture["quality_status"] == "ok"
    assert architecture["allowed_for_context_pack"] is True
    assert short["quality_status"] == "low_quality"
    assert short["gate_reasons"] == ["quality_status_low_quality"]
    assert failed["quality_status"] == "unsupported"
    assert failed["allowed_for_context_pack"] is False
    assert "Unsupported document format" in failed["reason"]
    assert "## Documents" in summary.markdown
    assert "旧版 Word" in summary.markdown


def test_write_parse_quality_summary_bundle_writes_json_and_markdown(tmp_path: Path):
    source = tmp_path / "doc.md"
    source.write_text(
        "# 文档\n\n这是一个足够长的文档，用于生成解析质量报告和 markdown 汇总。"
        "它包含多段正文、稳定的结构和明确的上下文，应该允许进入 Context Pack 检索。",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "\n".join(
            [
                "sample_id,file_path,document_title,slot_type,owner,project,supplier,document_version",
                f"doc-001,{source},文档,内部文档,checker,quality-test,internal,v1",
            ]
        ),
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    ingest_manifest(manifest_path=manifest, out_dir=processed_root)

    summary = build_parse_quality_summary(processed_root)
    output_paths = write_parse_quality_summary_bundle(
        output_dir=tmp_path / "quality",
        summary=summary,
    )

    assert output_paths["json_path"].name == "parse-quality-summary.json"
    assert output_paths["markdown_path"].name == "parse-quality-summary.md"
    assert output_paths["json_path"].exists()
    assert output_paths["markdown_path"].exists()
    payload = json.loads(output_paths["json_path"].read_text(encoding="utf-8"))
    markdown = output_paths["markdown_path"].read_text(encoding="utf-8")

    assert payload["processed_document_count"] == 1
    assert payload["status_counts"]["ok"] == 1
    assert "# Parse Quality Summary" in markdown


def test_parse_quality_summary_cli_writes_json_and_markdown(tmp_path: Path):
    source = tmp_path / "doc.md"
    source.write_text(
        "# 文档\n\n这是一个足够长的文档，用于验证 CLI 质量汇总输出。"
        "它包含可检索的正文内容、解析质量指标和 Context Pack 所需的上下文信息。",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "\n".join(
            [
                "sample_id,file_path,document_title,slot_type,owner,project,supplier,document_version",
                f"doc-001,{source},文档,内部文档,checker,quality-test,internal,v1",
            ]
        ),
        encoding="utf-8",
    )
    processed_root = tmp_path / "processed"
    ingest_manifest(manifest_path=manifest, out_dir=processed_root)

    output_dir = tmp_path / "quality"
    exit_code = main(
        [
            "parse-quality-summary",
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "parse-quality-summary.json").exists()
    assert (output_dir / "parse-quality-summary.md").exists()
