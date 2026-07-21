# Evaluation

## Purpose

Evaluation answers one question:

```text
Is Context Pack better than directly giving raw files to an agent?
```

If the answer is not clearly yes, the project should not move into heavier graph, review-console, or version-invalidation work.

## Comparison

Use the same documents, the same tasks, and the same agent.

Baseline:

```text
Agent receives or reads raw files directly.
```

Experiment:

```text
Agent receives a generated Context Pack.
```

Only the context source changes. Task wording, expected output, and scoring rules should stay the same.

## Metrics

| Metric | Target |
|---|---|
| `answer_correct` | Context Pack improves over baseline |
| `missed_constraints` | Context Pack is lower |
| `wrong_claims` | Context Pack is lower |
| `citation_correct` | At least 90% |
| `token_cost` | Context Pack ideally reduces by at least 50% |
| `elapsed_minutes` | Context Pack ideally reduces by at least 30% |
| `human_fix_count` | Context Pack is lower |

Phase 2 can be considered only if at least two of correctness, missing-constraint rate, token cost, and time improve clearly, and evidence correctness is at least 90%.

## Parser Evaluation

Parser comparison should measure:

- `page_metadata_rate`: page metadata retention.
- `span_traceability_rate`: span traceability.
- `table_accuracy`: table structure accuracy.
- `reading_order_accuracy`: reading order accuracy.
- `ocr_accuracy`: OCR accuracy.
- `critical_failures`: critical failures.

Suggested parser candidates remain Docling, MinerU, and Unstructured, but the current P0 code uses built-in parser adapters with optional OCR fallback.

## Run Evidence Rules

A valid evaluation run needs:

- Baseline and Context Pack outputs for the same task.
- Agent name and model recorded.
- Prompt files recorded.
- Raw outputs saved.
- Results scored.
- Checker review completed.

Simulated output, placeholder model names, missing raw output, or unreviewed rows must not be treated as business evidence.

## Current Harness

The evaluation harness lives in `src/agent_knowledge_hub/eval_setup.py`.

Core CLI commands include:

```text
prepare-eval-run
prepare-eval-execution-pack
record-eval-output
score-eval-run
prepare-eval-review-pack
record-eval-review-decision
check-eval-business-readiness
eval-run-status
```

When the run is meant to evaluate the current Layer2 retrieval path, pass the same indexes used for manual Context Pack checks:

```powershell
python -m agent_knowledge_hub.cli prepare-eval-run `
  --eval-cases ".\agent-artifacts\eval\eval_cases.jsonl" `
  --processed-dir ".\data\processed" `
  --output-dir ".\agent-artifacts\eval\run-001" `
  --fts-index-path ".\agent-artifacts\indexes\chunks.fts.sqlite" `
  --vector-index-path ".\agent-artifacts\indexes\chunks.vector.json"
```

Otherwise the eval Context Pack uses the default retrieval path and may not match a manually generated indexed Context Pack.

Historical detailed evaluation notes are archived under [archive/05-evaluation](archive/05-evaluation/).
