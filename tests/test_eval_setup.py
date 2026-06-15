import csv
import json
from pathlib import Path

from agent_knowledge_hub.fts_index import build_fts_index
from agent_knowledge_hub.eval_setup import (
    check_eval_business_readiness,
    build_eval_run_status,
    prepare_eval_execution_pack,
    prepare_eval_review_pack,
    prepare_eval_run,
    record_eval_output,
    record_eval_review_decision,
    score_eval_run,
)
from agent_knowledge_hub.pipeline import ingest_file


def _prepare_single_case_eval_run(tmp_path: Path):
    processed = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "\n".join(
            [
                "# Vehicle Data SPEC",
                "",
                "Important data storage requires permission control and encryption.",
                "Important data transfer requires confidentiality protection.",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed,
        title="Vehicle Data SPEC",
        source_type="internal spec",
        owner="checker",
        project="eval-test",
        supplier="internal",
        document_version="v1",
    )

    cases_path = tmp_path / "eval_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage and transfer?",
                "gold_answer_points": [
                    "storage requires permission control and encryption",
                    "transfer requires confidentiality protection",
                ],
                "required_constraints": [
                    "permission control",
                    "encryption",
                    "confidentiality protection",
                ],
                "expected_evidence": ["Vehicle Data SPEC", "Page 99"],
                "allowed_documents": ["Vehicle Data SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    run = prepare_eval_run(
        eval_cases_path=cases_path,
        processed_dir=processed,
        output_dir=tmp_path / "eval-run",
        top_k=3,
        per_document_limit=2,
    )
    return cases_path, run


def test_prepare_eval_run_writes_paired_prompts_and_manifests(tmp_path: Path):
    processed = tmp_path / "processed"
    source = tmp_path / "spec.md"
    source.write_text(
        "\n".join(
            [
                "# Vehicle Data SPEC",
                "",
                "Important data storage requires permission control and encryption.",
                "Important data transfer requires confidentiality protection.",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed,
        title="Vehicle Data SPEC",
        source_type="internal spec",
        owner="checker",
        project="eval-test",
        supplier="internal",
        document_version="v1",
    )

    cases_path = tmp_path / "eval_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "constraint-query",
                "question": "What constraints apply to important data storage and transfer?",
                "gold_answer_points": [
                    "storage requires permission control and encryption",
                    "transfer requires confidentiality protection",
                ],
                "required_constraints": [
                    "permission control",
                    "encryption",
                    "confidentiality protection",
                ],
                "expected_evidence": ["Vehicle Data SPEC"],
                "allowed_documents": ["Vehicle Data SPEC"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    run = prepare_eval_run(
        eval_cases_path=cases_path,
        processed_dir=processed,
        output_dir=tmp_path / "eval-run",
        top_k=3,
        per_document_limit=2,
    )

    assert run.task_count == 1
    assert run.prompt_pair_count == 2
    assert run.context_pack_count == 1
    assert run.summary_path.exists()

    baseline_prompt = run.output_dir / "prompts" / "case-001-baseline.md"
    context_prompt = run.output_dir / "prompts" / "case-001-context_pack.md"
    assert baseline_prompt.exists()
    assert context_prompt.exists()

    baseline_text = baseline_prompt.read_text(encoding="utf-8")
    context_text = context_prompt.read_text(encoding="utf-8")
    assert "gold_answer_points" not in baseline_text
    assert "required_constraints" not in context_text
    assert "Context Source: raw_files" in baseline_text
    assert "Context Source: context_pack" in context_text
    assert "# Context Pack" in context_text
    assert "Task Type: `constraint_lookup`" in context_text
    context_payload = json.loads(
        (run.output_dir / "context-packs" / "case-001" / "context_pack.json").read_text(
            encoding="utf-8"
        )
    )
    assert context_payload["task_type"] == "constraint_lookup"
    assert context_payload["contract"]["stability"] == "stable_for_layer3"

    with (run.output_dir / "agent-prompt-manifest.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        prompt_rows = list(csv.DictReader(handle))
    assert [row["group"] for row in prompt_rows] == ["baseline", "context_pack"]

    with (run.output_dir / "baseline-vs-contextpack-results.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        result_rows = list(csv.DictReader(handle))
    assert len(result_rows) == 2
    assert result_rows[0]["answer_correct"] == "待评分"


def test_prepare_eval_run_can_use_fts_index_for_context_pack(tmp_path: Path):
    processed = tmp_path / "processed"
    api = tmp_path / "api.md"
    api.write_text(
        "# API\n\nruntime_requires_approval is the exact event name for approval flow.\n",
        encoding="utf-8",
    )
    generic = tmp_path / "generic.md"
    generic.write_text(
        "# Generic\n\nRuntime requirement guidance for broad workflow reviews.\n",
        encoding="utf-8",
    )
    ingest_file(
        file_path=api,
        out_dir=processed,
        title="Z API",
        source_type="internal api",
        owner="checker",
        document_version="v1",
    )
    ingest_file(
        file_path=generic,
        out_dir=processed,
        title="A Generic",
        source_type="internal guide",
        owner="checker",
        document_version="v1",
    )
    fts_index = tmp_path / "indexes" / "chunks.fts.sqlite"
    build_fts_index(processed_dir=processed, index_path=fts_index)

    cases_path = tmp_path / "eval_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "task_id": "case-001",
                "task_type": "api_usage",
                "question": "approval",
                "gold_answer_points": ["runtime_requires_approval"],
                "required_constraints": ["runtime_requires_approval"],
                "expected_evidence": ["Z API"],
                "allowed_documents": ["Z API"],
                "scorer": "checker",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    run = prepare_eval_run(
        eval_cases_path=cases_path,
        processed_dir=processed,
        output_dir=tmp_path / "eval-run",
        top_k=1,
        per_document_limit=1,
        fts_index_path=fts_index,
    )

    context_payload = json.loads(
        (run.output_dir / "context-packs" / "case-001" / "context_pack.json").read_text(
            encoding="utf-8"
        )
    )
    assert context_payload["selected_chunks"][0]["document_title"] == "Z API"
    assert "fts" in context_payload["selected_chunks"][0]["retrieval_signals"]


def test_prepare_eval_run_normalizes_legacy_task_type_aliases(tmp_path: Path):
    processed = tmp_path / "processed"
    source = tmp_path / "api-and-tests.md"
    source.write_text(
        "\n".join(
            [
                "# 接口与测试",
                "",
                "接口使用时必须检查错误码、超时和版本限制。",
                "测试设计必须覆盖接口失败、超时恢复和版本兼容。",
            ]
        ),
        encoding="utf-8",
    )
    ingest_file(
        file_path=source,
        out_dir=processed,
        title="接口与测试",
        source_type="内部设计文档",
        owner="checker",
        document_version="v1",
    )

    cases_path = tmp_path / "eval_cases.jsonl"
    cases = [
        {
            "task_id": "case-api-legacy",
            "task_type": "查接口/机制",
            "question": "查接口机制需要注意什么？",
            "gold_answer_points": ["错误码", "超时", "版本限制"],
            "required_constraints": ["错误码", "超时", "版本限制"],
            "expected_evidence": ["接口与测试"],
            "allowed_documents": ["接口与测试"],
            "scorer": "checker",
        },
        {
            "task_id": "case-test-legacy",
            "task_type": "test_focus_generation",
            "question": "生成测试关注点",
            "gold_answer_points": ["接口失败", "超时恢复", "版本兼容"],
            "required_constraints": ["接口失败", "超时恢复", "版本兼容"],
            "expected_evidence": ["接口与测试"],
            "allowed_documents": ["接口与测试"],
            "scorer": "checker",
        },
    ]
    cases_path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )

    run = prepare_eval_run(
        eval_cases_path=cases_path,
        processed_dir=processed,
        output_dir=tmp_path / "eval-run",
        top_k=1,
        per_document_limit=1,
    )

    api_payload = json.loads(
        (run.output_dir / "context-packs" / "case-api-legacy" / "context_pack.json").read_text(
            encoding="utf-8"
        )
    )
    test_payload = json.loads(
        (run.output_dir / "context-packs" / "case-test-legacy" / "context_pack.json").read_text(
            encoding="utf-8"
        )
    )
    assert api_payload["task_type"] == "api_usage"
    assert test_payload["task_type"] == "test_design"


def test_prepare_eval_run_rejects_cases_without_question(tmp_path: Path):
    cases_path = tmp_path / "eval_cases.jsonl"
    cases_path.write_text('{"task_id":"bad"}\n', encoding="utf-8")

    try:
        prepare_eval_run(
            eval_cases_path=cases_path,
            processed_dir=tmp_path,
            output_dir=tmp_path / "eval-run",
        )
    except ValueError as exc:
        assert "question" in str(exc)
    else:
        raise AssertionError("Expected missing question to fail.")


def test_prepare_eval_execution_pack_writes_real_agent_run_guide(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)

    pack = prepare_eval_execution_pack(
        eval_run_dir=run.output_dir,
        eval_cases_path=cases_path,
    )

    assert pack.task_count == 1
    assert pack.execution_count == 2
    assert pack.pending_output_count == 2
    assert pack.execution_plan_path.exists()
    assert pack.markdown_path.exists()

    plan = json.loads(pack.execution_plan_path.read_text(encoding="utf-8"))
    assert plan["task_count"] == 1
    assert plan["execution_count"] == 2
    assert plan["pending_output_count"] == 2
    assert "--require-business-evidence" in plan["strict_score_command"]
    assert str(cases_path) in plan["strict_score_command"]
    assert "prepare-eval-review-pack" in plan["review_pack_command"]
    assert str(cases_path) in plan["review_pack_command"]
    assert "check-eval-business-readiness" in plan["business_readiness_command"]
    assert "--require-ready" in plan["business_readiness_command"]

    executions = {(item["task_id"], item["group"]): item for item in plan["executions"]}
    baseline = executions[("case-001", "baseline")]
    context_pack = executions[("case-001", "context_pack")]
    assert baseline["context_source"] == "raw_files"
    assert context_pack["context_source"] == "context_pack"
    assert baseline["prompt_exists"] is True
    assert context_pack["prompt_exists"] is True
    assert baseline["raw_output_exists"] is False
    assert context_pack["raw_output_exists"] is False
    assert baseline["execution_status"] == "pending_output"
    assert context_pack["execution_status"] == "pending_output"

    guide = pack.markdown_path.read_text(encoding="utf-8")
    assert "gold_answer_points" not in guide
    assert "required_constraints" not in guide
    assert "expected_evidence" not in guide
    assert "case-001-baseline.md" in guide
    assert "case-001-context_pack.md" in guide
    assert "record-eval-output" in guide
    assert "--require-business-evidence" in guide
    assert "prepare-eval-review-pack" in guide
    assert "record-eval-review-decision" in guide
    assert "check-eval-business-readiness --require-ready" in guide
    assert "Do not use `eval-review-pack.md` as an Agent prompt" in guide


def test_prepare_eval_review_pack_writes_checker_facing_report(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="context_pack",
        output_text="\n".join(
            [
                "Storage requires permission control and encryption.",
                "Transfer requires confidentiality protection.",
                "Evidence: Vehicle Data SPEC.",
            ]
        ),
        agent="codex",
        model="gpt-5.4",
        notes="controlled_local_run",
    )
    context_pack_path = run.output_dir / "context-packs" / "case-001" / "context_pack.json"
    context_payload = json.loads(context_pack_path.read_text(encoding="utf-8"))
    context_payload["selected_chunks"].append(
        {
            "chunk_id": "chunk-unrelated",
            "document_version_id": "docver-unrelated",
            "document_title": "Unrelated rollout plan",
            "source_type": "internal note",
            "source_path": "unrelated.md",
            "section_path": ["0"],
            "section_titles": ["Rollout"],
            "page_start": None,
            "page_end": None,
            "text": "Rollout tasks and migration checkpoints unrelated to storage or transfer constraints.",
            "evidence_ids": [],
            "score": 1.0,
            "matched_clauses": [],
            "quality_status": "ok",
            "quality_score": 100.0,
            "allowed_for_context_pack": True,
            "quality_gate_reasons": [],
            "warnings": [],
        }
    )
    context_payload["selected_chunks"].append(
        {
            "chunk_id": "chunk-short-token-noise",
            "document_version_id": "docver-noise",
            "document_title": "Migration note",
            "source_type": "internal note",
            "source_path": "migration.md",
            "section_path": ["0"],
            "section_titles": ["Migration"],
            "page_start": None,
            "page_end": None,
            "text": "Phase D.8 migration task mentions 6.7 as an internal milestone but does not discuss vehicle data constraints.",
            "evidence_ids": [],
            "score": 2.0,
            "matched_clauses": [],
            "quality_status": "ok",
            "quality_score": 100.0,
            "allowed_for_context_pack": True,
            "quality_gate_reasons": [],
            "warnings": [],
        }
    )
    context_pack_path.write_text(
        json.dumps(context_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    review_pack = prepare_eval_review_pack(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert review_pack.task_count == 1
    assert review_pack.execution_count == 2
    assert review_pack.ready_to_score_count == 1
    assert review_pack.pending_output_count == 1
    assert review_pack.review_json_path.exists()
    assert review_pack.markdown_path.exists()

    payload = json.loads(review_pack.review_json_path.read_text(encoding="utf-8"))
    task = payload["tasks"][0]
    assert task["task_id"] == "case-001"
    assert task["gold_answer_points"] == [
        "storage requires permission control and encryption",
        "transfer requires confidentiality protection",
    ]
    assert task["required_constraints"] == [
        "permission control",
        "encryption",
        "confidentiality protection",
    ]
    group_by_name = {group["group"]: group for group in task["groups"]}
    assert group_by_name["baseline"]["raw_output_exists"] is False
    assert group_by_name["context_pack"]["raw_output_exists"] is True
    assert group_by_name["context_pack"]["context_pack_evidence"]
    evidence_by_title = {
        evidence["document_title"]: evidence
        for evidence in group_by_name["context_pack"]["context_pack_evidence"]
    }
    assert evidence_by_title["Vehicle Data SPEC"]["relevance_label"] == "likely_useful"
    assert evidence_by_title["Unrelated rollout plan"]["relevance_label"] == "possibly_irrelevant"
    assert evidence_by_title["Migration note"]["relevance_label"] == "possibly_irrelevant"
    assert "expected_evidence: Vehicle Data SPEC" in evidence_by_title["Vehicle Data SPEC"][
        "relevance_reasons"
    ]
    assert "expected_evidence: Page 99" not in evidence_by_title["Vehicle Data SPEC"][
        "relevance_reasons"
    ]
    assert task["checker_decision_fields"]["winner"] == ""

    markdown = review_pack.markdown_path.read_text(encoding="utf-8")
    assert "# Eval Review Pack" in markdown
    assert "storage requires permission control and encryption" in markdown
    assert "confidentiality protection" in markdown
    assert "relevance=likely_useful" in markdown
    assert "relevance=possibly_irrelevant" in markdown
    assert "Context Pack retrieval useful" in markdown
    assert "controlled_local_run" in markdown


def test_record_eval_review_decision_updates_results_log_and_review_pack(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)

    decision = record_eval_review_decision(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        checker="checker",
        baseline_answer_correct="partial",
        context_pack_answer_correct="yes",
        context_pack_retrieval_useful="yes",
        winner="context_pack",
        baseline_human_fix_count=2,
        context_pack_human_fix_count=0,
        notes="context pack covered both constraints with useful evidence",
        eval_cases_path=cases_path,
    )

    assert decision.task_id == "case-001"
    assert decision.winner == "context_pack"
    assert decision.decision_path == run.output_dir / "eval-review-decisions.csv"
    assert decision.review_pack_refreshed is True
    assert decision.review_pack_markdown_path == run.output_dir / "eval-review-pack.md"

    with decision.decision_path.open("r", encoding="utf-8-sig", newline="") as handle:
        decision_rows = list(csv.DictReader(handle))
    assert len(decision_rows) == 1
    assert decision_rows[0]["task_id"] == "case-001"
    assert decision_rows[0]["winner"] == "context_pack"
    assert decision_rows[0]["context_pack_retrieval_useful"] == "yes"

    with (run.output_dir / "baseline-vs-contextpack-results.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        result_rows = list(csv.DictReader(handle))
    result_by_group = {row["group"]: row for row in result_rows}
    assert result_by_group["baseline"]["answer_correct"] == "partial"
    assert result_by_group["baseline"]["human_fix_count"] == "2"
    assert result_by_group["context_pack"]["answer_correct"] == "yes"
    assert result_by_group["context_pack"]["human_fix_count"] == "0"
    assert result_by_group["context_pack"]["retrieval_failure"] == "no"
    assert "manual_review winner=context_pack" in result_by_group["context_pack"]["notes"]

    with (run.output_dir / "agent-run-log.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        log_rows = list(csv.DictReader(handle))
    assert {row["score_status"] for row in log_rows} == {"reviewed"}
    assert {row["scorer"] for row in log_rows} == {"checker"}

    review_payload = json.loads((run.output_dir / "eval-review-pack.json").read_text(encoding="utf-8"))
    decision_fields = review_payload["tasks"][0]["checker_decision_fields"]
    assert decision_fields["baseline_answer_correct"] == "partial"
    assert decision_fields["context_pack_answer_correct"] == "yes"
    assert decision_fields["context_pack_retrieval_useful"] == "yes"
    assert decision_fields["winner"] == "context_pack"


def test_record_eval_review_decision_does_not_mark_unreviewed_answers_as_reviewed(
    tmp_path: Path,
):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)

    record_eval_review_decision(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        checker="checker",
        baseline_answer_correct="not_reviewed",
        context_pack_answer_correct="not_reviewed",
        context_pack_retrieval_useful="yes",
        winner="none",
        baseline_human_fix_count=0,
        context_pack_human_fix_count=0,
        notes="retrieval-only smoke",
        eval_cases_path=cases_path,
    )

    with (run.output_dir / "agent-run-log.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        log_rows = list(csv.DictReader(handle))
    assert {row["score_status"] for row in log_rows} == {"review_pending_output"}

    with (run.output_dir / "baseline-vs-contextpack-results.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        result_rows = list(csv.DictReader(handle))
    assert {row["answer_correct"] for row in result_rows} == {"not_reviewed"}


def test_check_eval_business_readiness_requires_real_outputs_scoring_and_review(
    tmp_path: Path,
):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)

    initial = check_eval_business_readiness(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )
    assert initial.business_evidence_ready is False
    assert "missing_outputs_present" in initial.business_evidence_blockers
    assert "missing_manual_review_decisions" in initial.business_evidence_blockers

    answer = "\n".join(
        [
            "Storage requires permission control and encryption.",
            "Transfer requires confidentiality protection.",
            "Evidence: Vehicle Data SPEC.",
        ]
    )
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="baseline",
        output_text=answer,
        agent="codex",
        model="gpt-5.4",
    )
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="context_pack",
        output_text=answer,
        agent="codex",
        model="gpt-5.4",
    )
    score_eval_run(eval_cases_path=cases_path, eval_run_dir=run.output_dir)

    before_review = check_eval_business_readiness(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )
    assert before_review.business_evidence_ready is False
    assert "missing_manual_review_decisions" in before_review.business_evidence_blockers
    assert "unreviewed_rows_present" in before_review.business_evidence_blockers

    record_eval_review_decision(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        checker="checker",
        baseline_answer_correct="yes",
        context_pack_answer_correct="yes",
        context_pack_retrieval_useful="yes",
        winner="tie",
        baseline_human_fix_count=0,
        context_pack_human_fix_count=0,
        notes="both answered correctly",
        eval_cases_path=cases_path,
    )

    ready = check_eval_business_readiness(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )
    assert ready.business_evidence_ready is True
    assert ready.business_evidence_blockers == []
    assert ready.reviewed_task_count == 1
    assert ready.real_output_count == 2
    assert ready.markdown_path.exists()
    assert "Business evidence ready: true" in ready.markdown_path.read_text(encoding="utf-8")


def test_check_eval_business_readiness_blocks_controlled_local_and_not_reviewed(
    tmp_path: Path,
):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    answer = "\n".join(
        [
            "Storage requires permission control and encryption.",
            "Transfer requires confidentiality protection.",
            "Evidence: Vehicle Data SPEC.",
        ]
    )
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="baseline",
        output_text=answer,
        agent="codex",
        model="gpt-5.4",
        notes="controlled_local_run",
    )
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="context_pack",
        output_text=answer,
        agent="codex",
        model="gpt-5.4",
        notes="controlled_local_run",
    )
    score_eval_run(eval_cases_path=cases_path, eval_run_dir=run.output_dir)
    record_eval_review_decision(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        checker="checker",
        baseline_answer_correct="not_reviewed",
        context_pack_answer_correct="not_reviewed",
        context_pack_retrieval_useful="yes",
        winner="none",
        baseline_human_fix_count=0,
        context_pack_human_fix_count=0,
        notes="retrieval-only smoke",
    )

    readiness = check_eval_business_readiness(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert readiness.business_evidence_ready is False
    assert "controlled_local_outputs_present" in readiness.business_evidence_blockers
    assert "not_reviewed_decisions_present" in readiness.business_evidence_blockers
    assert "unreviewed_rows_present" in readiness.business_evidence_blockers


def test_record_eval_output_writes_raw_output_and_updates_run_log(tmp_path: Path):
    _, run = _prepare_single_case_eval_run(tmp_path)
    output_text = "Storage requires permission control and encryption. Evidence: Vehicle Data SPEC."

    record = record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="baseline",
        output_text=output_text,
        agent="codex",
        model="gpt-5.4",
        token_input=1200,
        token_output=180,
        elapsed_minutes=2.5,
        notes="real run from execution guide",
    )

    assert record.task_id == "case-001"
    assert record.group == "baseline"
    assert record.raw_output_path.exists()
    assert record.raw_output_path.read_text(encoding="utf-8") == output_text
    assert record.run_log_path == run.output_dir / "agent-run-log.csv"

    with record.run_log_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    row_by_group = {row["group"]: row for row in rows}
    baseline = row_by_group["baseline"]
    context_pack = row_by_group["context_pack"]
    assert baseline["agent"] == "codex"
    assert baseline["model"] == "gpt-5.4"
    assert baseline["token_input"] == "1200"
    assert baseline["token_output"] == "180"
    assert baseline["elapsed_minutes"] == "2.5"
    assert baseline["score_status"] == "ready_to_score"
    assert baseline["notes"] == "real run from execution guide"
    assert context_pack["score_status"] == "pending"


def test_record_eval_output_can_refresh_execution_pack_status(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    initial_pack = prepare_eval_execution_pack(
        eval_run_dir=run.output_dir,
        eval_cases_path=cases_path,
    )
    assert initial_pack.pending_output_count == 2

    record = record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="baseline",
        output_text="Storage requires permission control and encryption. Evidence: Vehicle Data SPEC.",
        agent="codex",
        model="gpt-5.4",
        refresh_execution_pack=True,
    )

    assert record.execution_pack_refreshed is True
    assert record.pending_output_count == 1
    assert record.execution_plan_path == run.output_dir / "real-agent-execution-plan.json"
    assert record.execution_guide_path == run.output_dir / "real-agent-execution-guide.md"

    plan = json.loads(record.execution_plan_path.read_text(encoding="utf-8"))
    assert plan["pending_output_count"] == 1
    executions = {(item["task_id"], item["group"]): item for item in plan["executions"]}
    assert executions[("case-001", "baseline")]["execution_status"] == "ready_to_score"
    assert executions[("case-001", "context_pack")]["execution_status"] == "pending_output"
    assert str(cases_path) in plan["strict_score_command"]

    guide = record.execution_guide_path.read_text(encoding="utf-8")
    assert "- Pending outputs: 1" in guide
    assert "### case-001 / baseline" in guide
    assert "- Status: `ready_to_score`" in guide
    assert "--refresh-execution-pack" in guide


def test_build_eval_run_status_reports_pending_outputs_and_next_actions(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="baseline",
        output_text="Storage requires permission control. Evidence: Vehicle Data SPEC.",
        agent="codex",
        model="gpt-5.4",
    )

    status = build_eval_run_status(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert status.task_count == 1
    assert status.execution_count == 2
    assert status.pending_output_count == 1
    assert status.ready_to_score_count == 1
    assert status.scored_row_count == 0
    assert status.reviewed_task_count == 0
    assert status.business_evidence_ready is False
    assert status.next_actions[0] == "record_missing_raw_outputs"
    assert status.status_json_path.exists()
    assert status.markdown_path.exists()

    payload = json.loads(status.status_json_path.read_text(encoding="utf-8"))
    assert payload["executions"][0]["task_id"] == "case-001"
    assert {item["execution_status"] for item in payload["executions"]} == {
        "ready_to_score",
        "pending_output",
    }
    markdown = status.markdown_path.read_text(encoding="utf-8")
    assert "- Pending outputs: 1" in markdown
    assert "record_missing_raw_outputs" in markdown


def test_score_eval_run_scores_raw_outputs_and_updates_results(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    raw_outputs = run.output_dir / "raw-outputs"
    (raw_outputs / "case-001-baseline.md").write_text(
        "Storage requires permission control. Source: Vehicle Data SPEC.",
        encoding="utf-8",
    )
    (raw_outputs / "case-001-context_pack.md").write_text(
        "\n".join(
            [
                "Storage requires permission control and encryption.",
                "Transfer requires confidentiality protection.",
                "Evidence: Vehicle Data SPEC.",
            ]
        ),
        encoding="utf-8",
    )
    run_log_path = run.output_dir / "agent-run-log.csv"
    with run_log_path.open("r", encoding="utf-8-sig", newline="") as handle:
        log_rows = list(csv.DictReader(handle))
        log_fieldnames = list(log_rows[0].keys())
    for row in log_rows:
        if row["group"] == "context_pack":
            row["notes"] = "simulated_smoke_output generated for overnight pipeline smoke"
    with run_log_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=log_fieldnames)
        writer.writeheader()
        writer.writerows(log_rows)

    score_summary = score_eval_run(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert score_summary.task_count == 1
    assert score_summary.pair_count == 1
    assert score_summary.context_pack_win_count == 1
    assert score_summary.summary_path.exists()
    assert score_summary.details_path.exists()
    assert score_summary.simulated_output_count == 1
    assert score_summary.real_output_count == 1

    with (run.output_dir / "baseline-vs-contextpack-results.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    by_group = {row["group"]: row for row in rows}

    assert by_group["baseline"]["answer_correct"] == "partial"
    assert "encryption" in by_group["baseline"]["missed_constraints"]
    assert by_group["context_pack"]["answer_correct"] == "yes"
    assert by_group["context_pack"]["missed_constraints"] == ""
    assert by_group["context_pack"]["citation_correct"] == "yes"
    assert int(by_group["context_pack"]["useful_span_count"]) >= 1

    with (run.output_dir / "agent-run-log.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        log_rows = list(csv.DictReader(handle))
    assert {row["score_status"] for row in log_rows} == {"scored"}

    summary_payload = json.loads(
        (run.output_dir / "eval-score-summary.json").read_text(encoding="utf-8")
    )
    assert summary_payload["context_pack_average_coverage"] > summary_payload["baseline_average_coverage"]
    assert summary_payload["details_path"] == str(run.output_dir / "eval-score-details.jsonl")
    assert summary_payload["simulated_output_count"] == 1
    assert summary_payload["real_output_count"] == 1
    assert summary_payload["business_evidence_ready"] is False
    assert "simulated_outputs_present" in summary_payload["business_evidence_blockers"]

    details = [
        json.loads(line)
        for line in (run.output_dir / "eval-score-details.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    details_by_group = {row["group"]: row for row in details}
    assert details_by_group["baseline"]["scoring_method"] == "heuristic_v1"
    assert details_by_group["baseline"]["simulated_output"] is False
    assert details_by_group["context_pack"]["simulated_output"] is True
    assert details_by_group["context_pack"]["matched_gold_answer_points"] == [
        "storage requires permission control and encryption",
        "transfer requires confidentiality protection",
    ]
    assert details_by_group["context_pack"]["missed_gold_answer_points"] == []
    assert details_by_group["context_pack"]["matched_required_constraints"] == [
        "permission control",
        "encryption",
        "confidentiality protection",
    ]
    assert details_by_group["context_pack"]["missed_required_constraints"] == []
    assert details_by_group["context_pack"]["matched_expected_evidence"] == ["Vehicle Data SPEC"]


def test_score_eval_run_blocks_business_evidence_when_run_identity_is_placeholder(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    raw_outputs = run.output_dir / "raw-outputs"
    answer = "\n".join(
        [
            "Storage requires permission control and encryption.",
            "Transfer requires confidentiality protection.",
            "Evidence: Vehicle Data SPEC.",
        ]
    )
    (raw_outputs / "case-001-baseline.md").write_text(answer, encoding="utf-8")
    (raw_outputs / "case-001-context_pack.md").write_text(answer, encoding="utf-8")

    score_summary = score_eval_run(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert score_summary.missing_output_count == 0
    assert score_summary.simulated_output_count == 0
    assert score_summary.real_output_count == 2
    assert score_summary.business_evidence_ready is False
    assert score_summary.business_evidence_blockers == ["run_identity_placeholders_present"]

    summary_payload = json.loads(
        (run.output_dir / "eval-score-summary.json").read_text(encoding="utf-8")
    )
    assert summary_payload["business_evidence_ready"] is False
    assert summary_payload["business_evidence_blockers"] == ["run_identity_placeholders_present"]


def test_score_eval_run_blocks_business_evidence_for_controlled_local_runs(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    answer = "\n".join(
        [
            "Storage requires permission control and encryption.",
            "Transfer requires confidentiality protection.",
            "Evidence: Vehicle Data SPEC.",
        ]
    )
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="baseline",
        output_text=answer,
        agent="codex",
        model="gpt-5.4",
        notes="controlled_local_run",
    )
    record_eval_output(
        eval_run_dir=run.output_dir,
        task_id="case-001",
        group="context_pack",
        output_text=answer,
        agent="codex",
        model="gpt-5.4",
        notes="controlled_local_run",
    )

    score_summary = score_eval_run(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert score_summary.missing_output_count == 0
    assert score_summary.simulated_output_count == 0
    assert score_summary.real_output_count == 2
    assert score_summary.business_evidence_ready is False
    assert score_summary.business_evidence_blockers == ["controlled_local_outputs_present"]

    try:
        score_eval_run(
            eval_cases_path=cases_path,
            eval_run_dir=run.output_dir,
            require_business_evidence=True,
        )
    except ValueError as exc:
        assert "controlled_local_outputs_present" in str(exc)
    else:
        raise AssertionError("Expected controlled local output to fail strict business evidence.")


def test_score_eval_run_marks_real_identified_pairs_as_business_evidence_ready(tmp_path: Path):
    cases_path, run = _prepare_single_case_eval_run(tmp_path)
    raw_outputs = run.output_dir / "raw-outputs"
    answer = "\n".join(
        [
            "Storage requires permission control and encryption.",
            "Transfer requires confidentiality protection.",
            "Evidence: Vehicle Data SPEC.",
        ]
    )
    (raw_outputs / "case-001-baseline.md").write_text(answer, encoding="utf-8")
    (raw_outputs / "case-001-context_pack.md").write_text(answer, encoding="utf-8")

    run_log_path = run.output_dir / "agent-run-log.csv"
    with run_log_path.open("r", encoding="utf-8-sig", newline="") as handle:
        log_rows = list(csv.DictReader(handle))
        log_fieldnames = list(log_rows[0].keys())
    for row in log_rows:
        row["agent"] = "codex"
        row["model"] = "gpt-5.4"
    with run_log_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=log_fieldnames)
        writer.writeheader()
        writer.writerows(log_rows)

    score_summary = score_eval_run(
        eval_cases_path=cases_path,
        eval_run_dir=run.output_dir,
    )

    assert score_summary.missing_output_count == 0
    assert score_summary.simulated_output_count == 0
    assert score_summary.real_output_count == 2
    assert score_summary.business_evidence_ready is True
    assert score_summary.business_evidence_blockers == []
