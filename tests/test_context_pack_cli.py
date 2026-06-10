from pathlib import Path
import json
import csv

from agent_knowledge_hub.cli import main
from agent_knowledge_hub.pipeline import ingest_file


def test_context_pack_cli_writes_markdown_json_and_summary(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "architecture.md"
    source.write_text(
        "\n".join(
            [
                "# 架构",
                "",
                "采用第三种 runtime 模式。",
                "默认不写主仓库。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="架构",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    output_dir = tmp_path / "bundle"
    exit_code = main(
        [
            "context-pack",
            "--processed-dir",
            str(processed_root),
            "--query",
            "为什么选第三种 runtime，默认规则是什么？",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "context_pack.md").exists()
    assert (output_dir / "context_pack.json").exists()
    assert (output_dir / "context_pack-summary.json").exists()

    context_pack_markdown = (output_dir / "context_pack.md").read_text(encoding="utf-8")
    context_pack_json = json.loads((output_dir / "context_pack.json").read_text(encoding="utf-8"))
    context_pack_summary = json.loads(
        (output_dir / "context_pack-summary.json").read_text(encoding="utf-8")
    )

    assert "## Summary" in context_pack_markdown
    assert "## Evidence Appendix" in context_pack_markdown
    assert context_pack_json["sections"][0]["title"] == "Architecture Decision"
    assert context_pack_summary["sections"][0]["title"] == "Architecture Decision"


def test_gap_report_cli_writes_markdown_and_json(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "safety.md"
    source.write_text(
        "\n".join(
            [
                "# 安全治理",
                "",
                "默认不写主仓库。",
                "默认不开放无限网络。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="安全治理",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    bundle_dir = tmp_path / "bundle"
    exit_code = main(
        [
            "context-pack",
            "--processed-dir",
            str(processed_root),
            "--query",
            "默认安全规则是什么？",
            "--output-dir",
            str(bundle_dir),
        ]
    )
    assert exit_code == 0

    reference = tmp_path / "reference.md"
    reference.write_text(
        "\n".join(
            [
                "# Context Pack",
                "",
                "- 默认不写主仓库",
                "- 默认不开放无限网络",
                "- 默认不绕过审批",
            ]
        ),
        encoding="utf-8",
    )

    gap_dir = tmp_path / "gap"
    gap_exit_code = main(
        [
            "gap-report",
            "--auto-context-pack-json",
            str(bundle_dir / "context_pack.json"),
            "--reference-markdown",
            str(reference),
            "--output-dir",
            str(gap_dir),
        ]
    )

    assert gap_exit_code == 0
    assert (gap_dir / "context_pack_gap_report.md").exists()
    assert (gap_dir / "context_pack_gap_report.json").exists()


def test_context_pack_cli_accepts_query_file_with_utf8_bom(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "api.md"
    source.write_text(
        "\n".join(
            [
                "# API",
                "",
                "GET /runtime-runs/{run_id}/events",
                "runtime_requires_approval",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="API",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    query_file = tmp_path / "question.md"
    query_file.write_text(
        "# Question\n\n1. 第一阶段 API/事件能力需要什么？\n",
        encoding="utf-8-sig",
    )

    output_dir = tmp_path / "bundle"
    exit_code = main(
        [
            "context-pack",
            "--processed-dir",
            str(processed_root),
            "--query-file",
            str(query_file),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    context_pack = (output_dir / "context_pack.md").read_text(encoding="utf-8")
    summary = (output_dir / "context_pack-summary.json").read_text(encoding="utf-8")

    assert "\ufeff" not in context_pack
    assert "\ufeff" not in summary
    assert "GET /runtime-runs/{run_id}/events" in context_pack


def test_inventory_cli_writes_inventory_and_sample_manifest(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "bosch-diagnostic.txt").write_text(
        "Bosch diagnostic constraints require DTC synchronization.",
        encoding="utf-8",
    )

    output_dir = tmp_path / "inventory"
    exit_code = main(
        [
            "inventory",
            "--root-dir",
            str(docs),
            "--output-dir",
            str(output_dir),
            "--max-files",
            "10",
            "--max-file-mb",
            "1",
            "--sample-size",
            "1",
            "--project",
            "cli-test",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "document-inventory.json").exists()
    assert (output_dir / "document-inventory.md").exists()
    assert (output_dir / "raw-docs-sample-manifest.csv").exists()

    inventory = json.loads((output_dir / "document-inventory.json").read_text(encoding="utf-8"))
    assert inventory["document_count"] == 1
    assert inventory["documents"][0]["supplier"] == "Bosch"


def test_manifest_cli_incremental_skips_unchanged_second_run(tmp_path: Path):
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control.",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.csv"
    rows = [
        {
            "sample_id": "sample-001",
            "file_path": str(source),
            "document_title": "Vehicle Data SPEC",
            "slot_type": "internal spec",
            "owner": "checker",
            "project": "cli-test",
            "supplier": "internal",
            "document_version": "v1",
        }
    ]
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    processed = tmp_path / "processed"
    first_exit = main(
        [
            "manifest",
            "--manifest-path",
            str(manifest),
            "--out-dir",
            str(processed),
            "--project-root",
            str(tmp_path),
            "--incremental",
        ]
    )
    second_exit = main(
        [
            "manifest",
            "--manifest-path",
            str(manifest),
            "--out-dir",
            str(processed),
            "--project-root",
            str(tmp_path),
            "--incremental",
        ]
    )

    assert first_exit == 0
    assert second_exit == 0
    summary = json.loads((processed / "ingest-run-summary.json").read_text(encoding="utf-8"))
    assert summary["processed_count"] == 0
    assert summary["unchanged_count"] == 1


def test_prepare_eval_run_cli_writes_paired_prompt_artifacts(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage?",
                "gold_answer_points": ["permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "eval-run"
    exit_code = main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "cli-eval",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "eval-setup-summary.json").exists()
    assert (output_dir / "agent-run-log.csv").exists()
    assert (output_dir / "baseline-vs-contextpack-results.csv").exists()
    assert (output_dir / "prompts" / "case-001-baseline.md").exists()
    assert (output_dir / "prompts" / "case-001-context_pack.md").exists()


def test_prepare_eval_execution_pack_cli_writes_real_agent_guide(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage?",
                "gold_answer_points": ["permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "cli-eval",
        ]
    ) == 0

    exit_code = main(
        [
            "prepare-eval-execution-pack",
            "--eval-run-dir",
            str(output_dir),
            "--eval-cases",
            str(eval_cases),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "real-agent-execution-plan.json").exists()
    assert (output_dir / "real-agent-execution-guide.md").exists()
    guide = (output_dir / "real-agent-execution-guide.md").read_text(encoding="utf-8")
    assert "case-001-baseline.md" in guide
    assert "case-001-context_pack.md" in guide
    assert "record-eval-output" in guide
    assert "--require-business-evidence" in guide
    assert "prepare-eval-review-pack" in guide
    assert "record-eval-review-decision" in guide
    assert "check-eval-business-readiness --require-ready" in guide
    assert "gold_answer_points" not in guide


def test_record_eval_output_cli_writes_raw_output_and_updates_run_log(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage?",
                "gold_answer_points": ["permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "cli-eval",
        ]
    ) == 0

    agent_output = tmp_path / "agent-output.md"
    agent_output.write_text(
        "Storage requires permission control and encryption. Evidence: SPEC.",
        encoding="utf-8",
    )
    exit_code = main(
        [
            "record-eval-output",
            "--eval-run-dir",
            str(output_dir),
            "--task-id",
            "case-001",
            "--group",
            "baseline",
            "--output-file",
            str(agent_output),
            "--agent",
            "codex",
            "--model",
            "gpt-5.4",
            "--token-input",
            "900",
            "--token-output",
            "120",
            "--elapsed-minutes",
            "1.5",
            "--notes",
            "real cli run",
        ]
    )

    assert exit_code == 0
    raw_output = output_dir / "raw-outputs" / "case-001-baseline.md"
    assert raw_output.read_text(encoding="utf-8") == agent_output.read_text(encoding="utf-8")
    with (output_dir / "agent-run-log.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    baseline = next(row for row in rows if row["group"] == "baseline")
    assert baseline["agent"] == "codex"
    assert baseline["model"] == "gpt-5.4"
    assert baseline["token_input"] == "900"
    assert baseline["token_output"] == "120"
    assert baseline["elapsed_minutes"] == "1.5"
    assert baseline["score_status"] == "ready_to_score"
    assert baseline["notes"] == "real cli run"


def test_record_eval_output_cli_refreshes_execution_pack_when_requested(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage?",
                "gold_answer_points": ["permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "cli-eval",
        ]
    ) == 0
    assert main(
        [
            "prepare-eval-execution-pack",
            "--eval-run-dir",
            str(output_dir),
            "--eval-cases",
            str(eval_cases),
        ]
    ) == 0

    exit_code = main(
        [
            "record-eval-output",
            "--eval-run-dir",
            str(output_dir),
            "--task-id",
            "case-001",
            "--group",
            "baseline",
            "--output-text",
            "Storage requires permission control and encryption. Evidence: SPEC.",
            "--agent",
            "codex",
            "--model",
            "gpt-5.4",
            "--refresh-execution-pack",
        ]
    )

    assert exit_code == 0
    plan = json.loads((output_dir / "real-agent-execution-plan.json").read_text(encoding="utf-8"))
    assert plan["pending_output_count"] == 1
    assert str(eval_cases) in plan["strict_score_command"]
    executions = {(item["task_id"], item["group"]): item for item in plan["executions"]}
    assert executions[("case-001", "baseline")]["execution_status"] == "ready_to_score"
    assert executions[("case-001", "context_pack")]["execution_status"] == "pending_output"

    guide = (output_dir / "real-agent-execution-guide.md").read_text(encoding="utf-8")
    assert "- Pending outputs: 1" in guide
    assert "--refresh-execution-pack" in guide


def test_score_eval_run_cli_require_business_evidence_blocks_simulated_outputs(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage?",
                "gold_answer_points": ["permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "cli-eval",
        ]
    ) == 0

    raw_outputs = output_dir / "raw-outputs"
    (raw_outputs / "case-001-baseline.md").write_text(
        "Storage requires permission control and encryption. Evidence: SPEC.",
        encoding="utf-8",
    )
    (raw_outputs / "case-001-context_pack.md").write_text(
        "Storage requires permission control and encryption. Evidence: SPEC.",
        encoding="utf-8",
    )

    run_log_path = output_dir / "agent-run-log.csv"
    with run_log_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0].keys())
    for row in rows:
        row["notes"] = "simulated_smoke_output"
    with run_log_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    exit_code = main(
        [
            "score-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--eval-run-dir",
            str(output_dir),
            "--require-business-evidence",
        ]
    )

    assert exit_code == 1
    summary = json.loads((output_dir / "eval-score-summary.json").read_text(encoding="utf-8"))
    assert summary["business_evidence_ready"] is False
    assert "simulated_outputs_present" in summary["business_evidence_blockers"]


def test_readiness_blocks_controlled_local_outputs_even_after_review(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nImportant data storage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage?",
                "gold_answer_points": ["permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    for group in ("baseline", "context_pack"):
        assert main(
            [
                "record-eval-output",
                "--eval-run-dir",
                str(output_dir),
                "--task-id",
                "case-001",
                "--group",
                group,
                "--output-text",
                "Storage requires permission control and encryption. Evidence: SPEC.",
                "--agent",
                "codex-controlled-local",
                "--model",
                "gpt-controlled-local",
                "--notes",
                "controlled_local_run; rehearsal output, not business evidence",
            ]
        ) == 0

    assert main(
        [
            "score-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--eval-run-dir",
            str(output_dir),
        ]
    ) == 0
    assert main(
        [
            "record-eval-review-decision",
            "--eval-run-dir",
            str(output_dir),
            "--task-id",
            "case-001",
            "--checker",
            "checker",
            "--baseline-answer-correct",
            "yes",
            "--context-pack-answer-correct",
            "yes",
            "--context-pack-retrieval-useful",
            "yes",
            "--winner",
            "tie",
            "--baseline-human-fix-count",
            "0",
            "--context-pack-human-fix-count",
            "0",
            "--notes",
            "controlled_local_run review rehearsal",
            "--eval-cases",
            str(eval_cases),
        ]
    ) == 0

    exit_code = main(
        [
            "check-eval-business-readiness",
            "--eval-cases",
            str(eval_cases),
            "--eval-run-dir",
            str(output_dir),
            "--require-ready",
        ]
    )

    assert exit_code == 1
    readiness = json.loads((output_dir / "eval-business-readiness.json").read_text(encoding="utf-8"))
    assert readiness["business_evidence_ready"] is False
    assert readiness["controlled_local_output_count"] == 2
    assert readiness["missing_output_count"] == 0
    assert readiness["reviewed_task_count"] == 1
    assert readiness["business_evidence_blockers"] == ["controlled_local_outputs_present"]


def test_prepare_eval_review_pack_cli_writes_checker_report(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "\n".join(
            [
                "# SPEC",
                "",
                "Storage requires permission control and encryption.",
                "Transfer requires confidentiality protection.",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to storage and transfer?",
                "gold_answer_points": [
                    "storage requires permission control and encryption",
                    "transfer requires confidentiality protection",
                ],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"

    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
        ]
    ) == 0
    assert main(
        [
            "prepare-eval-review-pack",
            "--eval-cases",
            str(eval_cases),
            "--eval-run-dir",
            str(output_dir),
        ]
    ) == 0

    review_json = output_dir / "eval-review-pack.json"
    review_markdown = output_dir / "eval-review-pack.md"
    assert review_json.exists()
    assert review_markdown.exists()
    payload = json.loads(review_json.read_text(encoding="utf-8"))
    assert payload["task_count"] == 1
    assert payload["pending_output_count"] == 2
    assert payload["tasks"][0]["gold_answer_points"] == [
        "storage requires permission control and encryption",
        "transfer requires confidentiality protection",
    ]
    assert "Checker Decision" in review_markdown.read_text(encoding="utf-8")


def test_record_eval_review_decision_cli_updates_review_outputs(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nStorage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to storage?",
                "gold_answer_points": ["storage requires permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    exit_code = main(
        [
            "record-eval-review-decision",
            "--eval-run-dir",
            str(output_dir),
            "--task-id",
            "case-001",
            "--checker",
            "checker",
            "--baseline-answer-correct",
            "partial",
            "--context-pack-answer-correct",
            "yes",
            "--context-pack-retrieval-useful",
            "yes",
            "--winner",
            "context_pack",
            "--baseline-human-fix-count",
            "1",
            "--context-pack-human-fix-count",
            "0",
            "--notes",
            "checker accepted context pack result",
            "--eval-cases",
            str(eval_cases),
        ]
    )

    assert exit_code == 0
    decisions = list(
        csv.DictReader(
            (output_dir / "eval-review-decisions.csv").open(
                "r", encoding="utf-8-sig", newline=""
            )
        )
    )
    assert decisions[0]["winner"] == "context_pack"
    review_payload = json.loads((output_dir / "eval-review-pack.json").read_text(encoding="utf-8"))
    assert review_payload["tasks"][0]["checker_decision_fields"]["winner"] == "context_pack"
    review_markdown = (output_dir / "eval-review-pack.md").read_text(encoding="utf-8")
    assert "Winner: context_pack" in review_markdown


def test_check_eval_business_readiness_cli_fails_when_required_and_not_ready(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nStorage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to storage?",
                "gold_answer_points": ["storage requires permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    exit_code = main(
        [
            "check-eval-business-readiness",
            "--eval-cases",
            str(eval_cases),
            "--eval-run-dir",
            str(output_dir),
            "--require-ready",
        ]
    )

    assert exit_code == 1
    readiness = json.loads((output_dir / "eval-business-readiness.json").read_text(encoding="utf-8"))
    assert readiness["business_evidence_ready"] is False
    assert "missing_outputs_present" in readiness["business_evidence_blockers"]


def test_eval_run_status_cli_writes_status_bundle(tmp_path: Path):
    processed_root = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "# SPEC\n\nStorage requires permission control and encryption.",
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed_root,
        title="SPEC",
        source_type="internal spec",
        owner="checker",
        document_version="v1",
    )
    eval_cases = tmp_path / "eval_cases.jsonl"
    eval_cases.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to storage?",
                "gold_answer_points": ["storage requires permission control and encryption"],
                "required_constraints": ["permission control", "encryption"],
                "expected_evidence": ["SPEC"],
                "allowed_documents": ["SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-run"
    assert main(
        [
            "prepare-eval-run",
            "--eval-cases",
            str(eval_cases),
            "--processed-dir",
            str(processed_root),
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    exit_code = main(
        [
            "eval-run-status",
            "--eval-cases",
            str(eval_cases),
            "--eval-run-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads((output_dir / "eval-run-status.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "eval-run-status.md").read_text(encoding="utf-8")
    assert payload["pending_output_count"] == 2
    assert payload["next_actions"] == ["record_missing_raw_outputs"]
    assert "record_missing_raw_outputs" in markdown


def test_dependency_check_cli_writes_report(tmp_path: Path):
    output_dir = tmp_path / "deps"

    exit_code = main(
        [
            "dependency-check",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "runtime-dependencies.json").exists()
    assert (output_dir / "runtime-dependencies.md").exists()
    payload = json.loads((output_dir / "runtime-dependencies.json").read_text(encoding="utf-8"))
    assert any(item["capability"] == "pdf_text" for item in payload["capabilities"])
