from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_knowledge_hub.retrieval import build_context_pack_for_processed_dir
from agent_knowledge_hub.utils import is_placeholder, normalize_space, utc_now_iso, write_json


RESULT_FIELDNAMES = [
    "task_id",
    "group",
    "agent",
    "source_docs",
    "answer_correct",
    "missed_constraints",
    "wrong_claims",
    "citation_correct",
    "token_cost",
    "elapsed_minutes",
    "human_fix_count",
    "context_pack_tokens",
    "retrieved_span_count",
    "useful_span_count",
    "irrelevant_span_count",
    "retrieval_failure",
    "notes",
]

RUN_LOG_FIELDNAMES = [
    "run_id",
    "task_id",
    "group",
    "attempt",
    "agent",
    "model",
    "context_source",
    "source_docs",
    "context_pack_id",
    "prompt_path",
    "started_at",
    "ended_at",
    "token_input",
    "token_output",
    "elapsed_minutes",
    "raw_output_path",
    "scorer",
    "score_status",
    "notes",
]

PROMPT_MANIFEST_FIELDNAMES = [
    "task_id",
    "group",
    "prompt_path",
    "context_source",
    "source_docs",
    "notes",
]

REVIEW_DECISION_FIELDNAMES = [
    "task_id",
    "checker",
    "reviewed_at",
    "baseline_answer_correct",
    "context_pack_answer_correct",
    "context_pack_retrieval_useful",
    "winner",
    "baseline_human_fix_count",
    "context_pack_human_fix_count",
    "notes",
]


@dataclass(frozen=True)
class EvalCase:
    task_id: str
    task_type: str
    question: str
    allowed_documents: list[str]
    gold_answer_points: list[str]
    required_constraints: list[str]
    expected_evidence: list[str]
    scorer: str


@dataclass(frozen=True)
class EvalRunSummary:
    output_dir: Path
    processed_dir: Path
    eval_cases_path: Path
    generated_at: str
    task_count: int
    prompt_pair_count: int
    context_pack_count: int
    prompt_manifest_path: Path
    run_log_path: Path
    results_path: Path
    task_cases_path: Path
    summary_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalExecutionPackSummary:
    eval_run_dir: Path
    eval_cases_path: Path | None
    generated_at: str
    task_count: int
    execution_count: int
    pending_output_count: int
    execution_plan_path: Path
    markdown_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalOutputRecordSummary:
    eval_run_dir: Path
    task_id: str
    group: str
    raw_output_path: Path
    run_log_path: Path
    recorded_at: str
    execution_pack_refreshed: bool = False
    pending_output_count: int | None = None
    execution_plan_path: Path | None = None
    execution_guide_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalScoreSummary:
    eval_run_dir: Path
    eval_cases_path: Path
    generated_at: str
    task_count: int
    scored_row_count: int
    pair_count: int
    baseline_average_coverage: float
    context_pack_average_coverage: float
    context_pack_win_count: int
    baseline_win_count: int
    tie_count: int
    missing_output_count: int
    simulated_output_count: int
    real_output_count: int
    controlled_local_output_count: int
    uses_simulated_outputs: bool
    business_evidence_ready: bool
    business_evidence_blockers: list[str]
    results_path: Path
    run_log_path: Path
    details_path: Path
    summary_path: Path
    markdown_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalReviewPackSummary:
    eval_run_dir: Path
    eval_cases_path: Path
    generated_at: str
    task_count: int
    execution_count: int
    ready_to_score_count: int
    pending_output_count: int
    review_json_path: Path
    markdown_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalReviewDecisionSummary:
    eval_run_dir: Path
    task_id: str
    checker: str
    winner: str
    reviewed_at: str
    decision_path: Path
    results_path: Path
    run_log_path: Path
    review_pack_refreshed: bool = False
    review_pack_json_path: Path | None = None
    review_pack_markdown_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalBusinessReadinessSummary:
    eval_run_dir: Path
    eval_cases_path: Path
    generated_at: str
    task_count: int
    reviewed_task_count: int
    scored_row_count: int
    real_output_count: int
    simulated_output_count: int
    controlled_local_output_count: int
    missing_output_count: int
    business_evidence_ready: bool
    business_evidence_blockers: list[str]
    readiness_json_path: Path
    markdown_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


@dataclass(frozen=True)
class EvalRunStatusSummary:
    eval_run_dir: Path
    eval_cases_path: Path
    generated_at: str
    task_count: int
    execution_count: int
    pending_output_count: int
    ready_to_score_count: int
    scored_row_count: int
    reviewed_task_count: int
    missing_manual_review_decision_count: int
    not_reviewed_decision_count: int
    business_evidence_ready: bool
    business_evidence_blockers: list[str]
    next_actions: list[str]
    status_json_path: Path
    markdown_path: Path

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Path):
                payload[key] = str(value)
        return payload


def prepare_eval_run(
    *,
    eval_cases_path: Path | str,
    processed_dir: Path | str,
    output_dir: Path | str,
    run_id: str = "eval-run-001",
    agent: str = "待填写",
    model: str = "待填写",
    top_k: int = 8,
    per_document_limit: int = 2,
    fts_index_path: Path | str | None = None,
    vector_index_path: Path | str | None = None,
) -> EvalRunSummary:
    cases_path = Path(eval_cases_path).resolve()
    processed_root = Path(processed_dir).resolve()
    run_root = Path(output_dir).resolve()
    if not cases_path.exists():
        raise FileNotFoundError(f"Eval cases file does not exist: {cases_path}")
    if not processed_root.exists():
        raise FileNotFoundError(f"Processed directory does not exist: {processed_root}")

    cases = _load_eval_cases(cases_path)
    prompts_dir = run_root / "prompts"
    context_pack_dir = run_root / "context-packs"
    raw_outputs_dir = run_root / "raw-outputs"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    context_pack_dir.mkdir(parents=True, exist_ok=True)
    raw_outputs_dir.mkdir(parents=True, exist_ok=True)

    prompt_manifest_rows: list[dict[str, str]] = []
    run_log_rows: list[dict[str, str]] = []
    result_rows: list[dict[str, str]] = []
    task_case_rows: list[dict[str, str]] = []

    for case in cases:
        context_pack = build_context_pack_for_processed_dir(
            processed_dir=processed_root,
            query=case.question,
            task_type=case.task_type,
            top_k=top_k,
            per_document_limit=per_document_limit,
            fts_index_path=fts_index_path,
            vector_index_path=vector_index_path,
        )
        case_context_dir = context_pack_dir / case.task_id
        case_context_dir.mkdir(parents=True, exist_ok=True)
        context_pack_json_path = case_context_dir / "context_pack.json"
        context_pack_md_path = case_context_dir / "context_pack.md"
        write_json(context_pack_json_path, context_pack.to_json_dict())
        context_pack_md_path.write_text(context_pack.markdown, encoding="utf-8")

        baseline_prompt_path = prompts_dir / f"{case.task_id}-baseline.md"
        context_prompt_path = prompts_dir / f"{case.task_id}-context_pack.md"
        baseline_prompt_path.write_text(
            _render_prompt(case=case, group="baseline", context_markdown=None),
            encoding="utf-8",
        )
        context_prompt_path.write_text(
            _render_prompt(
                case=case,
                group="context_pack",
                context_markdown=context_pack.markdown,
            ),
            encoding="utf-8",
        )

        source_docs = "; ".join(case.allowed_documents) if case.allowed_documents else "processed_dir"
        prompt_manifest_rows.extend(
            [
                {
                    "task_id": case.task_id,
                    "group": "baseline",
                    "prompt_path": str(baseline_prompt_path),
                    "context_source": "raw_files",
                    "source_docs": source_docs,
                    "notes": "Provide the allowed raw files directly to the Agent.",
                },
                {
                    "task_id": case.task_id,
                    "group": "context_pack",
                    "prompt_path": str(context_prompt_path),
                    "context_source": "context_pack",
                    "source_docs": str(context_pack_json_path),
                    "notes": "Context Pack generated from processed documents.",
                },
            ]
        )
        for group, prompt_path, context_source, context_pack_id in (
            ("baseline", baseline_prompt_path, "raw_files", "N/A"),
            ("context_pack", context_prompt_path, "context_pack", str(context_pack_json_path)),
        ):
            run_log_rows.append(
                {
                    "run_id": run_id,
                    "task_id": case.task_id,
                    "group": group,
                    "attempt": "1",
                    "agent": agent,
                    "model": model,
                    "context_source": context_source,
                    "source_docs": source_docs if group == "baseline" else str(context_pack_json_path),
                    "context_pack_id": context_pack_id,
                    "prompt_path": str(prompt_path),
                    "started_at": "待填写",
                    "ended_at": "待填写",
                    "token_input": "待填写",
                    "token_output": "待填写",
                    "elapsed_minutes": "待填写",
                    "raw_output_path": str(raw_outputs_dir / f"{case.task_id}-{group}.md"),
                    "scorer": case.scorer,
                    "score_status": "pending",
                    "notes": "待填写",
                }
            )
            result_rows.append(
                _build_result_placeholder_row(
                    case=case,
                    group=group,
                    agent=agent,
                    source_docs=source_docs if group == "baseline" else str(context_pack_json_path),
                    context_pack=context_pack.to_json_dict() if group == "context_pack" else None,
                )
            )

        task_case_rows.append(
            {
                "task_id": case.task_id,
                "task_type": case.task_type,
                "question": case.question,
                "allowed_documents": "; ".join(case.allowed_documents),
                "gold_answer_points": "; ".join(case.gold_answer_points),
                "required_constraints": "; ".join(case.required_constraints),
                "expected_evidence": "; ".join(case.expected_evidence),
                "scorer": case.scorer,
            }
        )

    prompt_manifest_path = run_root / "agent-prompt-manifest.csv"
    run_log_path = run_root / "agent-run-log.csv"
    results_path = run_root / "baseline-vs-contextpack-results.csv"
    task_cases_path = run_root / "agent-task-cases.csv"
    summary_path = run_root / "eval-setup-summary.json"

    _write_csv(prompt_manifest_path, PROMPT_MANIFEST_FIELDNAMES, prompt_manifest_rows)
    _write_csv(run_log_path, RUN_LOG_FIELDNAMES, run_log_rows)
    _write_csv(results_path, RESULT_FIELDNAMES, result_rows)
    _write_csv(
        task_cases_path,
        [
            "task_id",
            "task_type",
            "question",
            "allowed_documents",
            "gold_answer_points",
            "required_constraints",
            "expected_evidence",
            "scorer",
        ],
        task_case_rows,
    )

    summary = EvalRunSummary(
        output_dir=run_root,
        processed_dir=processed_root,
        eval_cases_path=cases_path,
        generated_at=utc_now_iso(),
        task_count=len(cases),
        prompt_pair_count=len(prompt_manifest_rows),
        context_pack_count=len(cases),
        prompt_manifest_path=prompt_manifest_path,
        run_log_path=run_log_path,
        results_path=results_path,
        task_cases_path=task_cases_path,
        summary_path=summary_path,
    )
    write_json(summary_path, summary.to_dict())
    return summary


def prepare_eval_execution_pack(
    *,
    eval_run_dir: Path | str,
    eval_cases_path: Path | str | None = None,
) -> EvalExecutionPackSummary:
    run_root = Path(eval_run_dir).resolve()
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")

    prompt_manifest_path = run_root / "agent-prompt-manifest.csv"
    run_log_path = run_root / "agent-run-log.csv"
    if not prompt_manifest_path.exists():
        raise FileNotFoundError(f"Prompt manifest CSV does not exist: {prompt_manifest_path}")
    if not run_log_path.exists():
        raise FileNotFoundError(f"Agent run log CSV does not exist: {run_log_path}")

    cases_path = Path(eval_cases_path).resolve() if eval_cases_path is not None else None
    prompt_rows = _read_csv(prompt_manifest_path)
    run_log_rows = _read_csv(run_log_path)
    log_by_key = {
        (row.get("task_id", ""), row.get("group", "")): row
        for row in run_log_rows
    }

    executions: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    for prompt_row in prompt_rows:
        task_id = prompt_row.get("task_id", "")
        group = prompt_row.get("group", "")
        task_ids.add(task_id)
        run_log = log_by_key.get((task_id, group), {})
        prompt_path = _resolve_run_path(run_root, prompt_row.get("prompt_path", ""))
        raw_output_path = _resolve_run_path(run_root, run_log.get("raw_output_path", ""))
        raw_output_exists = raw_output_path is not None and raw_output_path.exists()
        prompt_exists = prompt_path is not None and prompt_path.exists()
        executions.append(
            {
                "task_id": task_id,
                "group": group,
                "context_source": prompt_row.get("context_source", ""),
                "source_docs": prompt_row.get("source_docs", ""),
                "prompt_path": str(prompt_path) if prompt_path is not None else "",
                "prompt_exists": prompt_exists,
                "raw_output_path": str(raw_output_path) if raw_output_path is not None else "",
                "raw_output_exists": raw_output_exists,
                "run_log_status": run_log.get("score_status", ""),
                "execution_status": (
                    "ready_to_score" if prompt_exists and raw_output_exists else (
                        "missing_prompt" if not prompt_exists else "pending_output"
                    )
                ),
            }
        )

    strict_score_command = _build_strict_score_command(
        eval_cases_path=cases_path,
        eval_run_dir=run_root,
    )
    review_pack_command = _build_review_pack_command(
        eval_cases_path=cases_path,
        eval_run_dir=run_root,
    )
    readiness_command = _build_business_readiness_command(
        eval_cases_path=cases_path,
        eval_run_dir=run_root,
    )
    pending_output_count = sum(1 for item in executions if item["execution_status"] == "pending_output")
    plan = {
        "eval_run_dir": str(run_root),
        "eval_cases_path": str(cases_path) if cases_path is not None else "",
        "generated_at": utc_now_iso(),
        "task_count": len(task_ids),
        "execution_count": len(executions),
        "pending_output_count": pending_output_count,
        "strict_score_command": strict_score_command,
        "review_pack_command": review_pack_command,
        "business_readiness_command": readiness_command,
        "executions": executions,
    }

    execution_plan_path = run_root / "real-agent-execution-plan.json"
    markdown_path = run_root / "real-agent-execution-guide.md"
    write_json(execution_plan_path, plan)
    markdown_path.write_text(_render_execution_pack_markdown(plan), encoding="utf-8")

    summary = EvalExecutionPackSummary(
        eval_run_dir=run_root,
        eval_cases_path=cases_path,
        generated_at=plan["generated_at"],
        task_count=len(task_ids),
        execution_count=len(executions),
        pending_output_count=pending_output_count,
        execution_plan_path=execution_plan_path,
        markdown_path=markdown_path,
    )
    return summary


def record_eval_output(
    *,
    eval_run_dir: Path | str,
    task_id: str,
    group: str,
    output_text: str,
    agent: str,
    model: str,
    token_input: int | str | None = None,
    token_output: int | str | None = None,
    elapsed_minutes: float | str | None = None,
    notes: str | None = None,
    refresh_execution_pack: bool = False,
    eval_cases_path: Path | str | None = None,
) -> EvalOutputRecordSummary:
    run_root = Path(eval_run_dir).resolve()
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")
    if group not in {"baseline", "context_pack"}:
        raise ValueError("group must be baseline or context_pack.")
    if is_placeholder(agent):
        raise ValueError("agent must be a real non-placeholder value.")
    if is_placeholder(model):
        raise ValueError("model must be a real non-placeholder value.")

    run_log_path = run_root / "agent-run-log.csv"
    if not run_log_path.exists():
        raise FileNotFoundError(f"Agent run log CSV does not exist: {run_log_path}")
    rows = _read_csv(run_log_path)
    target_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row.get("task_id") == task_id and row.get("group") == group
        ),
        None,
    )
    if target_index is None:
        raise ValueError(f"No run-log row found for task_id={task_id}, group={group}.")

    raw_output_path = _resolve_run_path(run_root, rows[target_index].get("raw_output_path", ""))
    if raw_output_path is None:
        raise ValueError(f"Run-log row has no raw_output_path for task_id={task_id}, group={group}.")
    raw_output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_output_path.write_text(output_text, encoding="utf-8")

    recorded_at = utc_now_iso()
    updated_row = {
        **rows[target_index],
        "agent": agent,
        "model": model,
        "ended_at": recorded_at,
        "score_status": "ready_to_score",
    }
    if is_placeholder(updated_row.get("started_at", "")):
        updated_row["started_at"] = recorded_at
    if token_input is not None:
        updated_row["token_input"] = str(token_input)
    if token_output is not None:
        updated_row["token_output"] = str(token_output)
    if elapsed_minutes is not None:
        updated_row["elapsed_minutes"] = str(elapsed_minutes)
    if notes is not None:
        updated_row["notes"] = notes
    rows[target_index] = updated_row
    _write_csv(run_log_path, RUN_LOG_FIELDNAMES, rows)

    refreshed_pack: EvalExecutionPackSummary | None = None
    if refresh_execution_pack:
        inferred_cases_path = _resolve_eval_cases_path_for_refresh(
            eval_run_dir=run_root,
            eval_cases_path=eval_cases_path,
        )
        refreshed_pack = prepare_eval_execution_pack(
            eval_run_dir=run_root,
            eval_cases_path=inferred_cases_path,
        )

    return EvalOutputRecordSummary(
        eval_run_dir=run_root,
        task_id=task_id,
        group=group,
        raw_output_path=raw_output_path,
        run_log_path=run_log_path,
        recorded_at=recorded_at,
        execution_pack_refreshed=refreshed_pack is not None,
        pending_output_count=(
            refreshed_pack.pending_output_count if refreshed_pack is not None else None
        ),
        execution_plan_path=(
            refreshed_pack.execution_plan_path if refreshed_pack is not None else None
        ),
        execution_guide_path=refreshed_pack.markdown_path if refreshed_pack is not None else None,
    )


def score_eval_run(
    *,
    eval_cases_path: Path | str,
    eval_run_dir: Path | str,
    require_business_evidence: bool = False,
) -> EvalScoreSummary:
    cases_path = Path(eval_cases_path).resolve()
    run_root = Path(eval_run_dir).resolve()
    if not cases_path.exists():
        raise FileNotFoundError(f"Eval cases file does not exist: {cases_path}")
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")

    results_path = run_root / "baseline-vs-contextpack-results.csv"
    run_log_path = run_root / "agent-run-log.csv"
    details_path = run_root / "eval-score-details.jsonl"
    summary_path = run_root / "eval-score-summary.json"
    markdown_path = run_root / "eval-score-summary.md"
    if not results_path.exists():
        raise FileNotFoundError(f"Results CSV does not exist: {results_path}")
    if not run_log_path.exists():
        raise FileNotFoundError(f"Agent run log CSV does not exist: {run_log_path}")

    cases = {case.task_id: case for case in _load_eval_cases(cases_path)}
    result_rows = _read_csv(results_path)
    run_log_rows = _read_csv(run_log_path)
    log_by_key = {
        (row.get("task_id", ""), row.get("group", "")): row
        for row in run_log_rows
    }

    scored_rows: list[dict[str, str]] = []
    score_details: list[dict[str, Any]] = []
    coverage_by_key: dict[tuple[str, str], float] = {}
    missing_output_count = 0
    for row in result_rows:
        task_id = row.get("task_id", "")
        group = row.get("group", "")
        case = cases.get(task_id)
        run_log = log_by_key.get((task_id, group))
        if case is None or run_log is None:
            scored_rows.append(dict(row))
            continue

        raw_output_path = _resolve_run_path(run_root, run_log.get("raw_output_path", ""))
        simulated_output = _is_simulated_run_log(run_log)
        if raw_output_path is None or not raw_output_path.exists():
            missing_output_count += 1
            score = _missing_output_score(case)
            updated = {
                **row,
                "answer_correct": "missing_output",
                "missed_constraints": "; ".join(case.required_constraints),
                "wrong_claims": "",
                "citation_correct": "missing_output",
                "useful_span_count": "0" if group == "context_pack" else row.get("useful_span_count", "N/A"),
                "irrelevant_span_count": row.get("irrelevant_span_count", "N/A"),
                "retrieval_failure": "missing_output" if group == "context_pack" else "N/A",
                "notes": "raw_output_missing",
            }
            run_log["score_status"] = "missing_output"
            scored_rows.append(updated)
            coverage_by_key[(task_id, group)] = 0.0
            score_details.append(
                _build_score_detail_row(
                    case=case,
                    group=group,
                    run_log=run_log,
                    raw_output_path=raw_output_path,
                    context_pack_path=Path(row.get("source_docs", "")) if group == "context_pack" else None,
                    score=score,
                    simulated_output=simulated_output,
                    missing_output=True,
                )
            )
            continue

        output_text = raw_output_path.read_text(encoding="utf-8", errors="replace")
        score = _score_output_text(
            case=case,
            output_text=output_text,
            context_pack_path=Path(row.get("source_docs", "")) if group == "context_pack" else None,
        )
        coverage_by_key[(task_id, group)] = score["coverage"]
        updated = {
            **row,
            "answer_correct": score["answer_correct"],
            "missed_constraints": "; ".join(score["missed_constraints"]),
            "wrong_claims": "; ".join(score["wrong_claims"]),
            "citation_correct": score["citation_correct"],
            "useful_span_count": (
                str(score["useful_span_count"])
                if group == "context_pack"
                else row.get("useful_span_count", "N/A")
            ),
            "irrelevant_span_count": (
                str(score["irrelevant_span_count"])
                if group == "context_pack"
                else row.get("irrelevant_span_count", "N/A")
            ),
            "retrieval_failure": (
                "no" if group == "context_pack" and score["retrieved_span_count"] else (
                    "yes" if group == "context_pack" else "N/A"
                )
            ),
            "notes": _merge_notes(
                row.get("notes", ""),
                f"auto_score coverage={score['coverage']:.2f}",
            ),
        }
        run_log["score_status"] = "scored"
        if not run_log.get("ended_at") or run_log.get("ended_at") == "待填写":
            run_log["ended_at"] = utc_now_iso()
        scored_rows.append(updated)
        score_details.append(
            _build_score_detail_row(
                case=case,
                group=group,
                run_log=run_log,
                raw_output_path=raw_output_path,
                context_pack_path=Path(row.get("source_docs", "")) if group == "context_pack" else None,
                score=score,
                simulated_output=simulated_output,
                missing_output=False,
            )
        )

    _write_csv(results_path, RESULT_FIELDNAMES, scored_rows)
    _write_csv(run_log_path, RUN_LOG_FIELDNAMES, run_log_rows)
    _write_jsonl(details_path, score_details)

    pair_count = len(cases)
    baseline_coverages = [
        coverage
        for (task_id, group), coverage in coverage_by_key.items()
        if group == "baseline"
    ]
    context_pack_coverages = [
        coverage
        for (task_id, group), coverage in coverage_by_key.items()
        if group == "context_pack"
    ]
    context_pack_win_count = 0
    baseline_win_count = 0
    tie_count = 0
    for task_id in cases:
        baseline_score = coverage_by_key.get((task_id, "baseline"), 0.0)
        context_score = coverage_by_key.get((task_id, "context_pack"), 0.0)
        if context_score > baseline_score:
            context_pack_win_count += 1
        elif baseline_score > context_score:
            baseline_win_count += 1
        else:
            tie_count += 1

    simulated_output_count = sum(1 for detail in score_details if detail["simulated_output"])
    controlled_local_output_count = sum(
        1 for detail in score_details if detail["controlled_local_output"]
    )
    real_output_count = sum(
        1
        for detail in score_details
        if not detail["simulated_output"] and not detail["missing_output"]
    )
    business_evidence_blockers = _build_business_evidence_blockers(
        task_count=len(cases),
        scored_row_count=sum(1 for row in scored_rows if row.get("answer_correct") != "待评分"),
        missing_output_count=missing_output_count,
        simulated_output_count=simulated_output_count,
        controlled_local_output_count=controlled_local_output_count,
        run_identity_placeholder_count=sum(
            1
            for detail in score_details
            if not detail["simulated_output"]
            and not detail["missing_output"]
            and (
                is_placeholder(detail["agent"])
                or is_placeholder(detail["model"])
            )
        ),
        coverage_by_key=coverage_by_key,
    )

    summary = EvalScoreSummary(
        eval_run_dir=run_root,
        eval_cases_path=cases_path,
        generated_at=utc_now_iso(),
        task_count=len(cases),
        scored_row_count=sum(1 for row in scored_rows if row.get("answer_correct") != "待评分"),
        pair_count=pair_count,
        baseline_average_coverage=_average(baseline_coverages),
        context_pack_average_coverage=_average(context_pack_coverages),
        context_pack_win_count=context_pack_win_count,
        baseline_win_count=baseline_win_count,
        tie_count=tie_count,
        missing_output_count=missing_output_count,
        simulated_output_count=simulated_output_count,
        real_output_count=real_output_count,
        controlled_local_output_count=controlled_local_output_count,
        uses_simulated_outputs=simulated_output_count > 0,
        business_evidence_ready=not business_evidence_blockers,
        business_evidence_blockers=business_evidence_blockers,
        results_path=results_path,
        run_log_path=run_log_path,
        details_path=details_path,
        summary_path=summary_path,
        markdown_path=markdown_path,
    )
    write_json(summary_path, summary.to_dict())
    markdown_path.write_text(_render_score_summary_markdown(summary), encoding="utf-8")
    if require_business_evidence and not summary.business_evidence_ready:
        raise ValueError(
            "Eval run is not ready as business evidence: "
            + ", ".join(summary.business_evidence_blockers)
        )
    return summary


def prepare_eval_review_pack(
    *,
    eval_cases_path: Path | str,
    eval_run_dir: Path | str,
) -> EvalReviewPackSummary:
    cases_path = Path(eval_cases_path).resolve()
    run_root = Path(eval_run_dir).resolve()
    if not cases_path.exists():
        raise FileNotFoundError(f"Eval cases file does not exist: {cases_path}")
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")

    run_log_path = run_root / "agent-run-log.csv"
    results_path = run_root / "baseline-vs-contextpack-results.csv"
    decision_path = run_root / "eval-review-decisions.csv"
    if not run_log_path.exists():
        raise FileNotFoundError(f"Agent run log CSV does not exist: {run_log_path}")
    if not results_path.exists():
        raise FileNotFoundError(f"Results CSV does not exist: {results_path}")

    cases = _load_eval_cases(cases_path)
    run_log_rows = _read_csv(run_log_path)
    result_rows = _read_csv(results_path)
    decision_rows = _read_csv(decision_path) if decision_path.exists() else []
    log_by_key = {
        (row.get("task_id", ""), row.get("group", "")): row
        for row in run_log_rows
    }
    result_by_key = {
        (row.get("task_id", ""), row.get("group", "")): row
        for row in result_rows
    }
    decision_by_task = {
        row.get("task_id", ""): row
        for row in decision_rows
    }

    review_tasks: list[dict[str, Any]] = []
    ready_to_score_count = 0
    pending_output_count = 0

    for case in cases:
        group_reviews: list[dict[str, Any]] = []
        for group in ("baseline", "context_pack"):
            run_log = log_by_key.get((case.task_id, group), {})
            result_row = result_by_key.get((case.task_id, group), {})
            raw_output_path = _resolve_run_path(run_root, run_log.get("raw_output_path", ""))
            raw_output_exists = raw_output_path is not None and raw_output_path.exists()
            if raw_output_exists:
                ready_to_score_count += 1
            else:
                pending_output_count += 1
            context_pack_path = (
                _resolve_run_path(run_root, result_row.get("source_docs", ""))
                if group == "context_pack"
                else None
            )
            group_reviews.append(
                {
                    "group": group,
                    "context_source": run_log.get("context_source", ""),
                    "prompt_path": run_log.get("prompt_path", ""),
                    "raw_output_path": str(raw_output_path) if raw_output_path is not None else "",
                    "raw_output_exists": raw_output_exists,
                    "score_status": run_log.get("score_status", ""),
                    "agent": run_log.get("agent", ""),
                    "model": run_log.get("model", ""),
                    "notes": run_log.get("notes", ""),
                    "result": dict(result_row),
                    "context_pack_path": (
                        str(context_pack_path) if context_pack_path is not None else ""
                    ),
                    "context_pack_evidence": (
                        _summarize_context_pack_evidence(context_pack_path, case=case)
                        if context_pack_path is not None and context_pack_path.exists()
                        else []
                    ),
                }
            )

        review_tasks.append(
            {
                "task_id": case.task_id,
                "task_type": case.task_type,
                "question": case.question,
                "scorer": case.scorer,
                "allowed_documents": list(case.allowed_documents),
                "gold_answer_points": list(case.gold_answer_points),
                "required_constraints": list(case.required_constraints),
                "expected_evidence": list(case.expected_evidence),
                "groups": group_reviews,
                "checker_decision_fields": _build_checker_decision_fields(
                    decision_by_task.get(case.task_id)
                ),
            }
        )

    payload = {
        "eval_run_dir": str(run_root),
        "eval_cases_path": str(cases_path),
        "generated_at": utc_now_iso(),
        "task_count": len(cases),
        "execution_count": len(cases) * 2,
        "ready_to_score_count": ready_to_score_count,
        "pending_output_count": pending_output_count,
        "tasks": review_tasks,
    }
    review_json_path = run_root / "eval-review-pack.json"
    markdown_path = run_root / "eval-review-pack.md"
    write_json(review_json_path, payload)
    markdown_path.write_text(_render_eval_review_pack_markdown(payload), encoding="utf-8")

    return EvalReviewPackSummary(
        eval_run_dir=run_root,
        eval_cases_path=cases_path,
        generated_at=str(payload["generated_at"]),
        task_count=len(cases),
        execution_count=len(cases) * 2,
        ready_to_score_count=ready_to_score_count,
        pending_output_count=pending_output_count,
        review_json_path=review_json_path,
        markdown_path=markdown_path,
    )


def record_eval_review_decision(
    *,
    eval_run_dir: Path | str,
    task_id: str,
    checker: str,
    baseline_answer_correct: str,
    context_pack_answer_correct: str,
    context_pack_retrieval_useful: str,
    winner: str,
    baseline_human_fix_count: int | str,
    context_pack_human_fix_count: int | str,
    notes: str = "",
    eval_cases_path: Path | str | None = None,
) -> EvalReviewDecisionSummary:
    run_root = Path(eval_run_dir).resolve()
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")

    normalized_task_id = normalize_space(task_id)
    normalized_checker = normalize_space(checker)
    if not normalized_task_id:
        raise ValueError("task_id must not be empty.")
    if not normalized_checker or is_placeholder(normalized_checker):
        raise ValueError("checker must be a real non-placeholder value.")

    _validate_choice(
        "baseline_answer_correct",
        baseline_answer_correct,
        {"yes", "partial", "no", "missing_output", "not_reviewed"},
    )
    _validate_choice(
        "context_pack_answer_correct",
        context_pack_answer_correct,
        {"yes", "partial", "no", "missing_output", "not_reviewed"},
    )
    _validate_choice(
        "context_pack_retrieval_useful",
        context_pack_retrieval_useful,
        {"yes", "partial", "no", "not_applicable"},
    )
    _validate_choice("winner", winner, {"baseline", "context_pack", "tie", "none"})

    results_path = run_root / "baseline-vs-contextpack-results.csv"
    run_log_path = run_root / "agent-run-log.csv"
    decision_path = run_root / "eval-review-decisions.csv"
    if not results_path.exists():
        raise FileNotFoundError(f"Results CSV does not exist: {results_path}")
    if not run_log_path.exists():
        raise FileNotFoundError(f"Agent run log CSV does not exist: {run_log_path}")

    reviewed_at = utc_now_iso()
    result_rows = _read_csv(results_path)
    matching_groups = {row.get("group") for row in result_rows if row.get("task_id") == normalized_task_id}
    if {"baseline", "context_pack"} - matching_groups:
        raise ValueError(f"Results CSV does not contain a full pair for task_id={normalized_task_id}.")
    updated_results: list[dict[str, str]] = []
    for row in result_rows:
        if row.get("task_id") != normalized_task_id:
            updated_results.append(row)
            continue
        group = row.get("group")
        group_answer = (
            baseline_answer_correct if group == "baseline" else context_pack_answer_correct
        )
        group_fix_count = (
            baseline_human_fix_count if group == "baseline" else context_pack_human_fix_count
        )
        retrieval_failure = row.get("retrieval_failure", "")
        if group == "context_pack":
            retrieval_failure = (
                "no"
                if context_pack_retrieval_useful in {"yes", "partial"}
                else ("yes" if context_pack_retrieval_useful == "no" else retrieval_failure)
            )
        updated_results.append(
            {
                **row,
                "answer_correct": group_answer,
                "human_fix_count": str(group_fix_count),
                "retrieval_failure": retrieval_failure,
                "notes": _merge_notes(
                    row.get("notes", ""),
                    f"manual_review winner={winner}; reviewer={normalized_checker}; {normalize_space(notes)}",
                ),
            }
        )
    _write_csv(results_path, RESULT_FIELDNAMES, updated_results)

    run_log_rows = _read_csv(run_log_path)
    review_status = (
        "review_pending_output"
        if baseline_answer_correct == "not_reviewed"
        or context_pack_answer_correct == "not_reviewed"
        else "reviewed"
    )
    updated_log_rows: list[dict[str, str]] = []
    for row in run_log_rows:
        if row.get("task_id") != normalized_task_id:
            updated_log_rows.append(row)
            continue
        updated_log_rows.append(
            {
                **row,
                "scorer": normalized_checker,
                "score_status": review_status,
                "ended_at": (
                    reviewed_at
                    if review_status == "reviewed" and is_placeholder(row.get("ended_at", ""))
                    else row.get("ended_at", "")
                ),
                "notes": _merge_notes(
                    row.get("notes", ""),
                    f"manual_review winner={winner}; {normalize_space(notes)}",
                ),
            }
        )
    _write_csv(run_log_path, RUN_LOG_FIELDNAMES, updated_log_rows)

    decision_rows = _read_csv(decision_path) if decision_path.exists() else []
    decision_row = {
        "task_id": normalized_task_id,
        "checker": normalized_checker,
        "reviewed_at": reviewed_at,
        "baseline_answer_correct": baseline_answer_correct,
        "context_pack_answer_correct": context_pack_answer_correct,
        "context_pack_retrieval_useful": context_pack_retrieval_useful,
        "winner": winner,
        "baseline_human_fix_count": str(baseline_human_fix_count),
        "context_pack_human_fix_count": str(context_pack_human_fix_count),
        "notes": normalize_space(notes),
    }
    decision_rows = [
        row for row in decision_rows if row.get("task_id") != normalized_task_id
    ]
    decision_rows.append(decision_row)
    decision_rows.sort(key=lambda row: row.get("task_id", ""))
    _write_csv(decision_path, REVIEW_DECISION_FIELDNAMES, decision_rows)

    refreshed_pack: EvalReviewPackSummary | None = None
    if eval_cases_path is not None:
        refreshed_pack = prepare_eval_review_pack(
            eval_cases_path=eval_cases_path,
            eval_run_dir=run_root,
        )

    return EvalReviewDecisionSummary(
        eval_run_dir=run_root,
        task_id=normalized_task_id,
        checker=normalized_checker,
        winner=winner,
        reviewed_at=reviewed_at,
        decision_path=decision_path,
        results_path=results_path,
        run_log_path=run_log_path,
        review_pack_refreshed=refreshed_pack is not None,
        review_pack_json_path=(
            refreshed_pack.review_json_path if refreshed_pack is not None else None
        ),
        review_pack_markdown_path=(
            refreshed_pack.markdown_path if refreshed_pack is not None else None
        ),
    )


def check_eval_business_readiness(
    *,
    eval_cases_path: Path | str,
    eval_run_dir: Path | str,
) -> EvalBusinessReadinessSummary:
    cases_path = Path(eval_cases_path).resolve()
    run_root = Path(eval_run_dir).resolve()
    if not cases_path.exists():
        raise FileNotFoundError(f"Eval cases file does not exist: {cases_path}")
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")

    cases = _load_eval_cases(cases_path)
    task_ids = {case.task_id for case in cases}
    results_path = run_root / "baseline-vs-contextpack-results.csv"
    run_log_path = run_root / "agent-run-log.csv"
    decisions_path = run_root / "eval-review-decisions.csv"
    details_path = run_root / "eval-score-details.jsonl"
    readiness_json_path = run_root / "eval-business-readiness.json"
    markdown_path = run_root / "eval-business-readiness.md"
    for required_path in (results_path, run_log_path):
        if not required_path.exists():
            raise FileNotFoundError(f"Required eval file does not exist: {required_path}")

    result_rows = _read_csv(results_path)
    run_log_rows = _read_csv(run_log_path)
    decision_rows = _read_csv(decisions_path) if decisions_path.exists() else []
    score_details = _read_jsonl(details_path) if details_path.exists() else []

    result_by_key = {
        (row.get("task_id", ""), row.get("group", "")): row
        for row in result_rows
    }
    log_by_key = {
        (row.get("task_id", ""), row.get("group", "")): row
        for row in run_log_rows
    }
    decision_by_task = {
        row.get("task_id", ""): row
        for row in decision_rows
    }

    blockers: list[str] = []
    missing_output_count = 0
    real_output_count = 0
    simulated_output_count = 0
    controlled_local_output_count = 0
    scored_row_count = 0
    unreviewed_rows_present = False
    missing_manual_review_decisions = False
    not_reviewed_decisions_present = False
    incomplete_pairs = False
    run_identity_placeholders_present = False

    for task_id in task_ids:
        if task_id not in decision_by_task:
            missing_manual_review_decisions = True
        else:
            decision = decision_by_task[task_id]
            if (
                decision.get("baseline_answer_correct") == "not_reviewed"
                or decision.get("context_pack_answer_correct") == "not_reviewed"
                or decision.get("winner") == "none"
            ):
                not_reviewed_decisions_present = True

        for group in ("baseline", "context_pack"):
            result = result_by_key.get((task_id, group))
            run_log = log_by_key.get((task_id, group))
            if result is None or run_log is None:
                incomplete_pairs = True
                missing_output_count += 1
                continue

            raw_output_path = _resolve_run_path(run_root, run_log.get("raw_output_path", ""))
            if raw_output_path is None or not raw_output_path.exists():
                missing_output_count += 1
            else:
                real_output_count += 1

            if _is_simulated_run_log(run_log):
                simulated_output_count += 1
            if _is_controlled_local_run_log(run_log):
                controlled_local_output_count += 1
            if is_placeholder(run_log.get("agent", "")) or is_placeholder(run_log.get("model", "")):
                run_identity_placeholders_present = True

            score_status = normalize_space(run_log.get("score_status", ""))
            if score_status in {"scored", "reviewed"}:
                scored_row_count += 1
            if score_status != "reviewed":
                unreviewed_rows_present = True

    if score_details:
        simulated_output_count = max(
            simulated_output_count,
            sum(1 for detail in score_details if detail.get("simulated_output") is True),
        )
        controlled_local_output_count = max(
            controlled_local_output_count,
            sum(1 for detail in score_details if detail.get("controlled_local_output") is True),
        )

    if missing_output_count > 0:
        blockers.append("missing_outputs_present")
    if simulated_output_count > 0:
        blockers.append("simulated_outputs_present")
    if controlled_local_output_count > 0:
        blockers.append("controlled_local_outputs_present")
    if run_identity_placeholders_present:
        blockers.append("run_identity_placeholders_present")
    if incomplete_pairs:
        blockers.append("incomplete_baseline_context_pairs")
    if scored_row_count < len(task_ids) * 2:
        blockers.append("unscored_rows_present")
    if missing_manual_review_decisions:
        blockers.append("missing_manual_review_decisions")
    if not_reviewed_decisions_present:
        blockers.append("not_reviewed_decisions_present")
    if unreviewed_rows_present:
        blockers.append("unreviewed_rows_present")

    summary = EvalBusinessReadinessSummary(
        eval_run_dir=run_root,
        eval_cases_path=cases_path,
        generated_at=utc_now_iso(),
        task_count=len(task_ids),
        reviewed_task_count=len(
            [
                task_id
                for task_id in task_ids
                if task_id in decision_by_task
                and decision_by_task[task_id].get("baseline_answer_correct") != "not_reviewed"
                and decision_by_task[task_id].get("context_pack_answer_correct") != "not_reviewed"
                and decision_by_task[task_id].get("winner") != "none"
            ]
        ),
        scored_row_count=scored_row_count,
        real_output_count=real_output_count,
        simulated_output_count=simulated_output_count,
        controlled_local_output_count=controlled_local_output_count,
        missing_output_count=missing_output_count,
        business_evidence_ready=not blockers,
        business_evidence_blockers=blockers,
        readiness_json_path=readiness_json_path,
        markdown_path=markdown_path,
    )
    write_json(readiness_json_path, summary.to_dict())
    markdown_path.write_text(_render_business_readiness_markdown(summary), encoding="utf-8")
    return summary


def build_eval_run_status(
    *,
    eval_cases_path: Path | str,
    eval_run_dir: Path | str,
) -> EvalRunStatusSummary:
    cases_path = Path(eval_cases_path).resolve()
    run_root = Path(eval_run_dir).resolve()
    if not cases_path.exists():
        raise FileNotFoundError(f"Eval cases file does not exist: {cases_path}")
    if not run_root.exists():
        raise FileNotFoundError(f"Eval run directory does not exist: {run_root}")

    cases = _load_eval_cases(cases_path)
    task_ids = {case.task_id for case in cases}
    run_log_path = run_root / "agent-run-log.csv"
    results_path = run_root / "baseline-vs-contextpack-results.csv"
    decisions_path = run_root / "eval-review-decisions.csv"
    status_json_path = run_root / "eval-run-status.json"
    markdown_path = run_root / "eval-run-status.md"
    if not run_log_path.exists():
        raise FileNotFoundError(f"Agent run log CSV does not exist: {run_log_path}")
    if not results_path.exists():
        raise FileNotFoundError(f"Results CSV does not exist: {results_path}")

    run_log_rows = _read_csv(run_log_path)
    result_rows = _read_csv(results_path)
    decision_rows = _read_csv(decisions_path) if decisions_path.exists() else []
    decision_by_task = {
        row.get("task_id", ""): row
        for row in decision_rows
    }

    executions: list[dict[str, Any]] = []
    pending_output_count = 0
    ready_to_score_count = 0
    scored_row_count = 0
    for row in run_log_rows:
        task_id = row.get("task_id", "")
        group = row.get("group", "")
        raw_output_path = _resolve_run_path(run_root, row.get("raw_output_path", ""))
        raw_output_exists = raw_output_path is not None and raw_output_path.exists()
        score_status = normalize_space(row.get("score_status", ""))
        if not raw_output_exists:
            execution_status = "pending_output"
            pending_output_count += 1
        elif score_status in {"scored", "reviewed"}:
            execution_status = score_status
            scored_row_count += 1
        else:
            execution_status = "ready_to_score"
            ready_to_score_count += 1

        executions.append(
            {
                "task_id": task_id,
                "group": group,
                "context_source": row.get("context_source", ""),
                "prompt_path": row.get("prompt_path", ""),
                "raw_output_path": str(raw_output_path) if raw_output_path is not None else "",
                "raw_output_exists": raw_output_exists,
                "agent": row.get("agent", ""),
                "model": row.get("model", ""),
                "score_status": score_status,
                "execution_status": execution_status,
                "notes": row.get("notes", ""),
            }
        )

    reviewed_task_count = 0
    missing_manual_review_decision_count = 0
    not_reviewed_decision_count = 0
    for task_id in task_ids:
        decision = decision_by_task.get(task_id)
        if decision is None:
            missing_manual_review_decision_count += 1
            continue
        if (
            decision.get("baseline_answer_correct") == "not_reviewed"
            or decision.get("context_pack_answer_correct") == "not_reviewed"
            or decision.get("winner") == "none"
        ):
            not_reviewed_decision_count += 1
            continue
        reviewed_task_count += 1

    readiness = check_eval_business_readiness(
        eval_cases_path=cases_path,
        eval_run_dir=run_root,
    )
    next_actions = _build_eval_run_next_actions(
        pending_output_count=pending_output_count,
        ready_to_score_count=ready_to_score_count,
        scored_row_count=scored_row_count,
        execution_count=len(run_log_rows),
        missing_manual_review_decision_count=missing_manual_review_decision_count,
        not_reviewed_decision_count=not_reviewed_decision_count,
        business_evidence_ready=readiness.business_evidence_ready,
    )

    summary = EvalRunStatusSummary(
        eval_run_dir=run_root,
        eval_cases_path=cases_path,
        generated_at=utc_now_iso(),
        task_count=len(task_ids),
        execution_count=len(run_log_rows),
        pending_output_count=pending_output_count,
        ready_to_score_count=ready_to_score_count,
        scored_row_count=scored_row_count,
        reviewed_task_count=reviewed_task_count,
        missing_manual_review_decision_count=missing_manual_review_decision_count,
        not_reviewed_decision_count=not_reviewed_decision_count,
        business_evidence_ready=readiness.business_evidence_ready,
        business_evidence_blockers=readiness.business_evidence_blockers,
        next_actions=next_actions,
        status_json_path=status_json_path,
        markdown_path=markdown_path,
    )
    payload = {
        **summary.to_dict(),
        "executions": executions,
    }
    write_json(status_json_path, payload)
    markdown_path.write_text(_render_eval_run_status_markdown(payload), encoding="utf-8")
    return summary


def _load_eval_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        task_id = normalize_space(str(payload.get("task_id") or f"case-{line_number:03d}"))
        question = normalize_space(str(payload.get("question") or ""))
        if not question:
            raise ValueError(f"Eval case {task_id} is missing question.")
        cases.append(
            EvalCase(
                task_id=task_id,
                task_type=normalize_space(str(payload.get("task_type") or "unknown")),
                question=question,
                allowed_documents=_string_list(payload.get("allowed_documents")),
                gold_answer_points=_string_list(payload.get("gold_answer_points")),
                required_constraints=_string_list(payload.get("required_constraints")),
                expected_evidence=_string_list(payload.get("expected_evidence")),
                scorer=normalize_space(str(payload.get("scorer") or "checker")),
            )
        )
    if not cases:
        raise ValueError(f"Eval cases file has no cases: {path}")
    return cases


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_space(str(item)) for item in value if normalize_space(str(item))]
    text = normalize_space(str(value))
    if not text:
        return []
    return [item.strip() for item in text.split(";") if item.strip()]


def _build_checker_decision_fields(decision_row: dict[str, str] | None) -> dict[str, str]:
    if decision_row is None:
        return {
            "baseline_answer_correct": "",
            "context_pack_answer_correct": "",
            "context_pack_retrieval_useful": "",
            "winner": "",
            "baseline_human_fix_count": "",
            "context_pack_human_fix_count": "",
            "notes": "",
        }
    return {
        "baseline_answer_correct": decision_row.get("baseline_answer_correct", ""),
        "context_pack_answer_correct": decision_row.get("context_pack_answer_correct", ""),
        "context_pack_retrieval_useful": decision_row.get(
            "context_pack_retrieval_useful",
            "",
        ),
        "winner": decision_row.get("winner", ""),
        "baseline_human_fix_count": decision_row.get("baseline_human_fix_count", ""),
        "context_pack_human_fix_count": decision_row.get("context_pack_human_fix_count", ""),
        "notes": decision_row.get("notes", ""),
    }


def _build_eval_run_next_actions(
    *,
    pending_output_count: int,
    ready_to_score_count: int,
    scored_row_count: int,
    execution_count: int,
    missing_manual_review_decision_count: int,
    not_reviewed_decision_count: int,
    business_evidence_ready: bool,
) -> list[str]:
    actions: list[str] = []
    if pending_output_count > 0:
        actions.append("record_missing_raw_outputs")
    if pending_output_count == 0 and ready_to_score_count > 0:
        actions.append("score_eval_run")
    if execution_count > 0 and scored_row_count >= execution_count:
        if missing_manual_review_decision_count > 0:
            actions.append("prepare_eval_review_pack")
            actions.append("record_missing_review_decisions")
        if not_reviewed_decision_count > 0:
            actions.append("resolve_not_reviewed_decisions")
    if (
        execution_count > 0
        and scored_row_count >= execution_count
        and missing_manual_review_decision_count == 0
        and not_reviewed_decision_count == 0
    ):
        actions.append("check_business_readiness")
    if business_evidence_ready:
        actions.append("business_evidence_ready")
    if not actions:
        actions.append("inspect_eval_run")
    return actions


def _validate_choice(field_name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {', '.join(sorted(allowed))}; got {value!r}."
        )


def _score_output_text(
    *,
    case: EvalCase,
    output_text: str,
    context_pack_path: Path | None,
) -> dict[str, Any]:
    normalized_output = _normalize_for_match(output_text)
    gold_hits = [
        point
        for point in case.gold_answer_points
        if _contains_phrase(normalized_output, point)
    ]
    missed_gold_points = [
        point
        for point in case.gold_answer_points
        if point not in gold_hits
    ]
    required_hits = [
        constraint
        for constraint in case.required_constraints
        if _contains_phrase(normalized_output, constraint)
    ]
    missed_constraints = [
        constraint
        for constraint in case.required_constraints
        if constraint not in required_hits
    ]
    evidence_hits = [
        evidence
        for evidence in case.expected_evidence
        if _contains_phrase(normalized_output, evidence)
    ]
    missed_evidence = [
        evidence
        for evidence in case.expected_evidence
        if evidence not in evidence_hits
    ]
    coverage_denominator = max(1, len(case.gold_answer_points) + len(case.required_constraints))
    coverage = (len(gold_hits) + len(required_hits)) / coverage_denominator
    if coverage >= 0.999:
        answer_correct = "yes"
    elif coverage > 0:
        answer_correct = "partial"
    else:
        answer_correct = "no"

    retrieved_span_count = 0
    useful_span_count = 0
    irrelevant_span_count = 0
    if context_pack_path is not None and context_pack_path.exists():
        payload = json.loads(context_pack_path.read_text(encoding="utf-8"))
        selected_chunks = payload.get("selected_chunks") or []
        retrieved_span_count = len(selected_chunks)
        useful_span_count = sum(
            1
            for chunk in selected_chunks
            if _chunk_matches_case(chunk, case)
        )
        irrelevant_span_count = max(0, retrieved_span_count - useful_span_count)

    return {
        "answer_correct": answer_correct,
        "coverage": coverage,
        "matched_gold_answer_points": gold_hits,
        "missed_gold_answer_points": missed_gold_points,
        "matched_required_constraints": required_hits,
        "missed_required_constraints": missed_constraints,
        "missed_constraints": missed_constraints,
        "matched_expected_evidence": evidence_hits,
        "missed_expected_evidence": missed_evidence,
        "wrong_claims": _detect_wrong_claims(output_text),
        "citation_correct": "yes" if evidence_hits else ("N/A" if not case.expected_evidence else "no"),
        "retrieved_span_count": retrieved_span_count,
        "useful_span_count": useful_span_count,
        "irrelevant_span_count": irrelevant_span_count,
    }


def _render_prompt(
    *,
    case: EvalCase,
    group: str,
    context_markdown: str | None,
) -> str:
    context_source = "raw_files" if group == "baseline" else "context_pack"
    lines = [
        "# Agent Evaluation Prompt",
        "",
        f"Task ID: {case.task_id}",
        f"Context Source: {context_source}",
        "",
        "## Task",
        "",
        case.question,
        "",
        "## Allowed Context",
        "",
    ]
    if group == "baseline":
        if case.allowed_documents:
            lines.extend(f"- {document}" for document in case.allowed_documents)
        else:
            lines.append("- Use the raw source files supplied with this prompt.")
        lines.extend(
            [
                "",
                "The evaluator must attach the listed raw files separately. Do not use the Context Pack for this baseline run.",
            ]
        )
    else:
        lines.extend(
            [
                "Use only the Context Pack below. Do not use raw files or outside knowledge.",
                "",
                "## Context Pack",
                "",
                context_markdown or "",
            ]
        )

    lines.extend(
        [
            "",
            "## Output Shape",
            "",
            "```text",
            "## Answer",
            "",
            "## Evidence",
            "| Claim | Source document | Version/scope | Page/section/span | Support |",
            "",
            "## Gaps Or Assumptions",
            "",
            "## Follow-up Needed",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _build_result_placeholder_row(
    *,
    case: EvalCase,
    group: str,
    agent: str,
    source_docs: str,
    context_pack: dict[str, Any] | None,
) -> dict[str, str]:
    selected_chunks = context_pack.get("selected_chunks", []) if context_pack else []
    return {
        "task_id": case.task_id,
        "group": group,
        "agent": agent,
        "source_docs": source_docs,
        "answer_correct": "待评分",
        "missed_constraints": "待评分",
        "wrong_claims": "待评分",
        "citation_correct": "待评分",
        "token_cost": "待填写",
        "elapsed_minutes": "待填写",
        "human_fix_count": "待填写",
        "context_pack_tokens": "N/A" if group == "baseline" else "待填写",
        "retrieved_span_count": "N/A" if group == "baseline" else str(len(selected_chunks)),
        "useful_span_count": "N/A" if group == "baseline" else "待评分",
        "irrelevant_span_count": "N/A" if group == "baseline" else "待评分",
        "retrieval_failure": "N/A" if group == "baseline" else ("no" if selected_chunks else "yes"),
        "notes": "待填写",
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    if text:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _resolve_run_path(run_root: Path, raw_path: str) -> Path | None:
    value = normalize_space(raw_path)
    if not value or value == "待填写":
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (run_root / path).resolve()


def _normalize_for_match(text: str) -> str:
    lowered = text.lower()
    return re.sub(r"\s+", " ", lowered).strip()


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_for_match(phrase)
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_text:
        return True
    tokens = [token for token in re.split(r"[\s,;，；、。.!?！？:：/\\|()\[\]{}<>`\"']+", normalized_phrase) if token]
    if not tokens:
        return False
    return all(token in normalized_text for token in tokens)


def _chunk_matches_case(chunk: dict[str, Any], case: EvalCase) -> bool:
    text = _normalize_for_match(str(chunk.get("text") or ""))
    return any(_contains_phrase(text, phrase) for phrase in [*case.gold_answer_points, *case.required_constraints])


def _detect_wrong_claims(output_text: str) -> list[str]:
    wrong_claim_patterns = [
        r"\bnot\s+required\b",
        r"\bno\s+need\b",
        r"\bwithout\s+evidence\b",
        "无需",
        "不需要",
        "没有要求",
    ]
    normalized = _normalize_for_match(output_text)
    return [pattern for pattern in wrong_claim_patterns if re.search(pattern, normalized)]


def _is_simulated_run_log(row: dict[str, str]) -> bool:
    notes = _normalize_for_match(row.get("notes", ""))
    agent = _normalize_for_match(row.get("agent", ""))
    model = _normalize_for_match(row.get("model", ""))
    return (
        "simulated_smoke_output" in notes
        or agent.startswith("simulated")
        or model.startswith("simulated")
    )


def _is_controlled_local_run_log(row: dict[str, str]) -> bool:
    notes = _normalize_for_match(row.get("notes", ""))
    return "controlled_local_run" in notes


def _missing_output_score(case: EvalCase) -> dict[str, Any]:
    return {
        "answer_correct": "missing_output",
        "coverage": 0.0,
        "matched_gold_answer_points": [],
        "missed_gold_answer_points": case.gold_answer_points,
        "matched_required_constraints": [],
        "missed_required_constraints": case.required_constraints,
        "missed_constraints": case.required_constraints,
        "matched_expected_evidence": [],
        "missed_expected_evidence": case.expected_evidence,
        "wrong_claims": [],
        "citation_correct": "missing_output",
        "retrieved_span_count": 0,
        "useful_span_count": 0,
        "irrelevant_span_count": 0,
    }


def _build_score_detail_row(
    *,
    case: EvalCase,
    group: str,
    run_log: dict[str, str],
    raw_output_path: Path | None,
    context_pack_path: Path | None,
    score: dict[str, Any],
    simulated_output: bool,
    missing_output: bool,
) -> dict[str, Any]:
    return {
        "task_id": case.task_id,
        "task_type": case.task_type,
        "group": group,
        "run_id": run_log.get("run_id", ""),
        "attempt": run_log.get("attempt", ""),
        "agent": run_log.get("agent", ""),
        "model": run_log.get("model", ""),
        "scorer": run_log.get("scorer", case.scorer),
        "scoring_method": "heuristic_v1",
        "simulated_output": simulated_output,
        "controlled_local_output": _is_controlled_local_run_log(run_log),
        "missing_output": missing_output,
        "raw_output_path": str(raw_output_path) if raw_output_path is not None else "",
        "context_pack_path": str(context_pack_path) if context_pack_path is not None else "",
        "coverage": round(float(score["coverage"]), 4),
        "answer_correct": score["answer_correct"],
        "citation_correct": score["citation_correct"],
        "matched_gold_answer_points": score["matched_gold_answer_points"],
        "missed_gold_answer_points": score["missed_gold_answer_points"],
        "matched_required_constraints": score["matched_required_constraints"],
        "missed_required_constraints": score["missed_required_constraints"],
        "matched_expected_evidence": score["matched_expected_evidence"],
        "missed_expected_evidence": score["missed_expected_evidence"],
        "wrong_claims": score["wrong_claims"],
        "retrieved_span_count": score["retrieved_span_count"],
        "useful_span_count": score["useful_span_count"],
        "irrelevant_span_count": score["irrelevant_span_count"],
        "notes": run_log.get("notes", ""),
    }


def _build_business_evidence_blockers(
    *,
    task_count: int,
    scored_row_count: int,
    missing_output_count: int,
    simulated_output_count: int,
    controlled_local_output_count: int,
    run_identity_placeholder_count: int,
    coverage_by_key: dict[tuple[str, str], float],
) -> list[str]:
    blockers: list[str] = []
    if task_count <= 0:
        blockers.append("no_eval_cases")
    if scored_row_count < task_count * 2:
        blockers.append("unscored_rows_present")
    if missing_output_count > 0:
        blockers.append("missing_outputs_present")
    if simulated_output_count > 0:
        blockers.append("simulated_outputs_present")
    if controlled_local_output_count > 0:
        blockers.append("controlled_local_outputs_present")
    if run_identity_placeholder_count > 0:
        blockers.append("run_identity_placeholders_present")

    incomplete_pairs = [
        task_id
        for task_id in {key[0] for key in coverage_by_key}
        if (task_id, "baseline") not in coverage_by_key
        or (task_id, "context_pack") not in coverage_by_key
    ]
    if incomplete_pairs:
        blockers.append("incomplete_baseline_context_pairs")

    return blockers


def _build_strict_score_command(
    *,
    eval_cases_path: Path | None,
    eval_run_dir: Path,
) -> str:
    cases_arg = str(eval_cases_path) if eval_cases_path is not None else "C:\\path\\to\\eval_cases.jsonl"
    return (
        "python -m agent_knowledge_hub.cli score-eval-run "
        f'--eval-cases "{cases_arg}" '
        f'--eval-run-dir "{eval_run_dir}" '
        "--require-business-evidence"
    )


def _build_review_pack_command(
    *,
    eval_cases_path: Path | None,
    eval_run_dir: Path,
) -> str:
    cases_arg = str(eval_cases_path) if eval_cases_path is not None else "C:\\path\\to\\eval_cases.jsonl"
    return (
        "python -m agent_knowledge_hub.cli prepare-eval-review-pack "
        f'--eval-cases "{cases_arg}" '
        f'--eval-run-dir "{eval_run_dir}"'
    )


def _build_business_readiness_command(
    *,
    eval_cases_path: Path | None,
    eval_run_dir: Path,
) -> str:
    cases_arg = str(eval_cases_path) if eval_cases_path is not None else "C:\\path\\to\\eval_cases.jsonl"
    return (
        "python -m agent_knowledge_hub.cli check-eval-business-readiness "
        f'--eval-cases "{cases_arg}" '
        f'--eval-run-dir "{eval_run_dir}" '
        "--require-ready"
    )


def _resolve_eval_cases_path_for_refresh(
    *,
    eval_run_dir: Path,
    eval_cases_path: Path | str | None,
) -> Path | None:
    if eval_cases_path is not None:
        return Path(eval_cases_path).resolve()

    execution_plan_path = eval_run_dir / "real-agent-execution-plan.json"
    if not execution_plan_path.exists():
        return None
    try:
        plan = json.loads(execution_plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    plan_cases_path = normalize_space(str(plan.get("eval_cases_path", "")))
    if not plan_cases_path or is_placeholder(plan_cases_path):
        return None
    return Path(plan_cases_path).resolve()


def _build_record_output_command(
    *,
    eval_run_dir: Path,
    task_id: str,
    group: str,
) -> str:
    return (
        "python -m agent_knowledge_hub.cli record-eval-output "
        f'--eval-run-dir "{eval_run_dir}" '
        f'--task-id "{task_id}" '
        f'--group "{group}" '
        '--output-file "C:\\path\\to\\agent-answer.md" '
        '--agent "<agent-name>" '
        '--model "<model-name>" '
        "--refresh-execution-pack"
    )


def _render_execution_pack_markdown(plan: dict[str, Any]) -> str:
    eval_cases_arg = plan["eval_cases_path"] or "C:\\path\\to\\eval_cases.jsonl"
    lines = [
        "# Real Agent Execution Guide",
        "",
        f"- Eval run: `{plan['eval_run_dir']}`",
        f"- Tasks: {plan['task_count']}",
        f"- Executions: {plan['execution_count']}",
        f"- Pending outputs: {plan['pending_output_count']}",
        "",
        "## How To Run",
        "",
        "Run each prompt with the specified context source. Save the raw Agent answer with `record-eval-output` instead of editing CSV files by hand.",
        "",
        "Strict order:",
        "",
        "```text",
        "record-eval-output x baseline/context_pack",
        "  -> score-eval-run",
        "  -> prepare-eval-review-pack",
        "  -> record-eval-review-decision x task",
        "  -> check-eval-business-readiness --require-ready",
        "```",
        "",
        "Do not use `eval-review-pack.md` as an Agent prompt. It is checker-facing and contains scoring expectations.",
        "",
        "After all raw outputs are present, run the heuristic scorer:",
        "",
        "```powershell",
        plan["strict_score_command"],
        "```",
        "",
        "Then generate the checker review pack:",
        "",
        "```powershell",
        plan["review_pack_command"],
        "```",
        "",
        "For each task, record a checker decision after reviewing `eval-review-pack.md`:",
        "",
        "```powershell",
        "python -m agent_knowledge_hub.cli record-eval-review-decision "
        f'--eval-run-dir "{plan["eval_run_dir"]}" '
        '--task-id "<task-id>" '
        '--checker "<checker-name>" '
        '--baseline-answer-correct "<yes|partial|no|missing_output>" '
        '--context-pack-answer-correct "<yes|partial|no|missing_output>" '
        '--context-pack-retrieval-useful "<yes|partial|no|not_applicable>" '
        '--winner "<baseline|context_pack|tie>" '
        '--baseline-human-fix-count "<number>" '
        '--context-pack-human-fix-count "<number>" '
        '--notes "<review notes>" '
        f'--eval-cases "{eval_cases_arg}"',
        "```",
        "",
        "Finally check whether the run is usable as business evidence:",
        "",
        "```powershell",
        plan["business_readiness_command"],
        "```",
        "",
        "The readiness gate must fail for missing outputs, placeholder agent/model values, simulated outputs, controlled local runs, unscored rows, missing manual review decisions, or `not_reviewed` decisions.",
        "",
        "## Execution Items",
        "",
    ]
    for item in plan["executions"]:
        record_command = _build_record_output_command(
            eval_run_dir=Path(plan["eval_run_dir"]),
            task_id=item["task_id"],
            group=item["group"],
        )
        lines.extend(
            [
                f"### {item['task_id']} / {item['group']}",
                "",
                f"- Context source: `{item['context_source']}`",
                f"- Prompt: `{item['prompt_path']}`",
                f"- Raw output: `{item['raw_output_path']}`",
                f"- Status: `{item['execution_status']}`",
                "",
                "```powershell",
                record_command,
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _summarize_context_pack_evidence(
    context_pack_path: Path,
    *,
    case: EvalCase,
) -> list[dict[str, Any]]:
    payload = json.loads(context_pack_path.read_text(encoding="utf-8"))
    evidence_items: list[dict[str, Any]] = []
    for index, chunk in enumerate(payload.get("selected_chunks") or [], start=1):
        relevance = _classify_context_pack_evidence(chunk, case)
        evidence_items.append(
            {
                "index": index,
                "document_title": normalize_space(str(chunk.get("document_title") or "")),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "section_titles": [
                    normalize_space(str(title))
                    for title in (chunk.get("section_titles") or [])
                    if normalize_space(str(title))
                ],
                "score": chunk.get("score"),
                "quality_status": chunk.get("quality_status"),
                "text_preview": normalize_space(str(chunk.get("text") or ""))[:360],
                "relevance_label": relevance["label"],
                "relevance_reasons": relevance["reasons"],
            }
        )
    return evidence_items


def _classify_context_pack_evidence(
    chunk: dict[str, Any],
    case: EvalCase,
) -> dict[str, Any]:
    chunk_text = _normalize_for_match(
        "\n".join(
            [
                str(chunk.get("document_title") or ""),
                " ".join(str(title) for title in (chunk.get("section_titles") or [])),
                str(chunk.get("text") or ""),
            ]
        )
    )
    reasons: list[str] = []
    for evidence in case.expected_evidence:
        if _evidence_hint_matches_chunk(evidence=evidence, chunk=chunk, chunk_text=chunk_text):
            reasons.append(f"expected_evidence: {evidence}")
    for constraint in case.required_constraints:
        if _contains_phrase(chunk_text, constraint):
            reasons.append(f"required_constraint: {constraint}")
    for point in case.gold_answer_points:
        if _contains_phrase(chunk_text, point):
            reasons.append(f"gold_point: {point}")

    weak_evidence_hits = [
        evidence
        for evidence in case.expected_evidence
        if _is_weak_evidence_hint(evidence) and _contains_phrase(chunk_text, evidence)
    ]
    if reasons:
        reasons.extend(f"weak_evidence: {evidence}" for evidence in weak_evidence_hits)

    return {
        "label": "likely_useful" if reasons else "possibly_irrelevant",
        "reasons": reasons,
    }


def _is_weak_evidence_hint(evidence: str) -> bool:
    normalized = normalize_space(evidence)
    if not normalized:
        return True
    if re.fullmatch(r"[A-Za-z]\.\d+(?:\.\d+)*", normalized):
        return True
    if re.fullmatch(r"\d+(?:\.\d+){1,4}", normalized):
        return True
    return len(normalized) <= 3


def _evidence_hint_matches_chunk(
    *,
    evidence: str,
    chunk: dict[str, Any],
    chunk_text: str,
) -> bool:
    normalized = normalize_space(evidence)
    if not normalized or _is_weak_evidence_hint(normalized):
        return False

    page_match = re.fullmatch(r"page\s+(\d+)", normalized, flags=re.IGNORECASE)
    if page_match:
        expected_page = int(page_match.group(1))
        page_start = _optional_int(chunk.get("page_start"))
        page_end = _optional_int(chunk.get("page_end")) or page_start
        if page_start is not None and page_end is not None:
            return page_start <= expected_page <= page_end
        section_titles = [
            normalize_space(str(title)).lower()
            for title in (chunk.get("section_titles") or [])
        ]
        return f"page {expected_page}" in section_titles

    return _contains_phrase(chunk_text, normalized)


def _optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _render_eval_review_pack_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Eval Review Pack",
        "",
        f"- Eval run: `{payload['eval_run_dir']}`",
        f"- Eval cases: `{payload['eval_cases_path']}`",
        f"- Tasks: {payload['task_count']}",
        f"- Executions: {payload['execution_count']}",
        f"- Ready to score: {payload['ready_to_score_count']}",
        f"- Pending outputs: {payload['pending_output_count']}",
        "",
        "## Checker Rules",
        "",
        "- Compare baseline and Context Pack answers for the same task.",
        "- Mark whether the answer covers the gold points and required constraints.",
        "- Treat Context Pack retrieval as useful only when the cited evidence supports the answer.",
        "- Do not mark the run as business evidence until both groups have real non-placeholder Agent/model identity.",
        "",
    ]
    for task in payload["tasks"]:
        lines.extend(
            [
                f"## {task['task_id']}",
                "",
                f"- Type: `{task['task_type']}`",
                f"- Scorer: `{task['scorer']}`",
                f"- Question: {task['question']}",
                "",
                "### Expected Answer",
                "",
                "**Gold points**",
                "",
            ]
        )
        lines.extend(_render_list_or_none(task["gold_answer_points"]))
        lines.extend(["", "**Required constraints**", ""])
        lines.extend(_render_list_or_none(task["required_constraints"]))
        lines.extend(["", "**Expected evidence**", ""])
        lines.extend(_render_list_or_none(task["expected_evidence"]))
        lines.extend(["", "### Runs", ""])
        for group in task["groups"]:
            lines.extend(
                [
                    f"#### {group['group']}",
                    "",
                    f"- Context source: `{group['context_source']}`",
                    f"- Prompt: `{group['prompt_path']}`",
                    f"- Raw output: `{group['raw_output_path']}`",
                    f"- Raw output exists: {str(group['raw_output_exists']).lower()}",
                    f"- Score status: `{group['score_status']}`",
                    f"- Agent/model: `{group['agent']}` / `{group['model']}`",
                    f"- Notes: {group['notes'] or 'none'}",
                    "",
                ]
            )
            if group["group"] == "context_pack":
                lines.extend(["Evidence preview:", ""])
                evidence_items = group.get("context_pack_evidence") or []
                if not evidence_items:
                    lines.append("- None")
                for evidence in evidence_items:
                    page = _format_page_span(evidence.get("page_start"), evidence.get("page_end"))
                    section = " > ".join(evidence.get("section_titles") or [])
                    reasons = "; ".join(evidence.get("relevance_reasons") or [])
                    lines.append(
                        "- Evidence "
                        f"{evidence['index']}: `{evidence['document_title']}`"
                        f"{page}; score={evidence.get('score')}; quality={evidence.get('quality_status')}"
                        f"; relevance={evidence.get('relevance_label')}"
                    )
                    if reasons:
                        lines.append(f"  Reasons: {reasons}")
                    if section:
                        lines.append(f"  Section: {section}")
                    lines.append(f"  Preview: {evidence.get('text_preview') or ''}")
                lines.append("")
        lines.extend(
            [
                "### Checker Decision",
                "",
                f"- Baseline answer correct: {task['checker_decision_fields'].get('baseline_answer_correct', '')}",
                f"- Context Pack answer correct: {task['checker_decision_fields'].get('context_pack_answer_correct', '')}",
                f"- Context Pack retrieval useful: {task['checker_decision_fields'].get('context_pack_retrieval_useful', '')}",
                f"- Winner: {task['checker_decision_fields'].get('winner', '')}",
                f"- Baseline human fix count: {task['checker_decision_fields'].get('baseline_human_fix_count', '')}",
                f"- Context Pack human fix count: {task['checker_decision_fields'].get('context_pack_human_fix_count', '')}",
                f"- Notes: {task['checker_decision_fields'].get('notes', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_list_or_none(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def _format_page_span(page_start: object, page_end: object) -> str:
    if page_start in {None, ""}:
        return ""
    if page_end in {None, "", page_start}:
        return f"; page={page_start}"
    return f"; pages={page_start}..{page_end}"


def _merge_notes(existing: str, addition: str) -> str:
    current = normalize_space(existing)
    if not current or current == "待填写":
        return addition
    return f"{current}; {addition}"


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _render_score_summary_markdown(summary: EvalScoreSummary) -> str:
    return (
        "# Eval Score Summary\n\n"
        f"- Eval run: `{summary.eval_run_dir}`\n"
        f"- Tasks: {summary.task_count}\n"
        f"- Scored rows: {summary.scored_row_count}\n"
        f"- Missing outputs: {summary.missing_output_count}\n"
        f"- Simulated outputs: {summary.simulated_output_count}\n"
        f"- Controlled local outputs: {summary.controlled_local_output_count}\n"
        f"- Real outputs: {summary.real_output_count}\n"
        f"- Business evidence ready: {str(summary.business_evidence_ready).lower()}\n"
        f"- Business evidence blockers: {', '.join(summary.business_evidence_blockers) if summary.business_evidence_blockers else 'none'}\n"
        f"- Baseline average coverage: {summary.baseline_average_coverage:.2f}\n"
        f"- Context Pack average coverage: {summary.context_pack_average_coverage:.2f}\n"
        f"- Context Pack wins: {summary.context_pack_win_count}\n"
        f"- Baseline wins: {summary.baseline_win_count}\n"
        f"- Ties: {summary.tie_count}\n"
        f"- Details: `{summary.details_path}`\n"
        + (
            "\nWarning: this run includes simulated smoke outputs. Do not use these scores as business evidence.\n"
            if summary.uses_simulated_outputs
            else ""
        )
    )


def _render_business_readiness_markdown(summary: EvalBusinessReadinessSummary) -> str:
    return (
        "# Eval Business Evidence Readiness\n\n"
        f"- Eval run: `{summary.eval_run_dir}`\n"
        f"- Eval cases: `{summary.eval_cases_path}`\n"
        f"- Tasks: {summary.task_count}\n"
        f"- Reviewed tasks: {summary.reviewed_task_count}\n"
        f"- Scored rows: {summary.scored_row_count}\n"
        f"- Real outputs: {summary.real_output_count}\n"
        f"- Missing outputs: {summary.missing_output_count}\n"
        f"- Simulated outputs: {summary.simulated_output_count}\n"
        f"- Controlled local outputs: {summary.controlled_local_output_count}\n"
        f"- Business evidence ready: {str(summary.business_evidence_ready).lower()}\n"
        f"- Business evidence blockers: {', '.join(summary.business_evidence_blockers) if summary.business_evidence_blockers else 'none'}\n"
    )


def _render_eval_run_status_markdown(payload: dict[str, Any]) -> str:
    blockers = ", ".join(payload["business_evidence_blockers"]) or "none"
    next_actions = ", ".join(payload["next_actions"]) or "none"
    lines = [
        "# Eval Run Status",
        "",
        f"- Eval run: `{payload['eval_run_dir']}`",
        f"- Eval cases: `{payload['eval_cases_path']}`",
        f"- Tasks: {payload['task_count']}",
        f"- Executions: {payload['execution_count']}",
        f"- Pending outputs: {payload['pending_output_count']}",
        f"- Ready to score: {payload['ready_to_score_count']}",
        f"- Scored rows: {payload['scored_row_count']}",
        f"- Reviewed tasks: {payload['reviewed_task_count']}",
        f"- Missing review decisions: {payload['missing_manual_review_decision_count']}",
        f"- Not-reviewed decisions: {payload['not_reviewed_decision_count']}",
        f"- Business evidence ready: {str(payload['business_evidence_ready']).lower()}",
        f"- Business evidence blockers: {blockers}",
        f"- Next actions: {next_actions}",
        "",
        "## Executions",
        "",
    ]
    for item in payload["executions"]:
        lines.extend(
            [
                f"### {item['task_id']} / {item['group']}",
                "",
                f"- Context source: `{item['context_source']}`",
                f"- Raw output exists: {str(item['raw_output_exists']).lower()}",
                f"- Execution status: `{item['execution_status']}`",
                f"- Score status: `{item['score_status']}`",
                f"- Agent/model: `{item['agent']}` / `{item['model']}`",
                f"- Prompt: `{item['prompt_path']}`",
                f"- Raw output: `{item['raw_output_path']}`",
                "",
            ]
        )
    return "\n".join(lines)
