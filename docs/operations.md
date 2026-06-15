# Operations

## Phase 1 Operating Model

Phase 1 is a controlled prototype, not a production knowledge platform.

The normal run flow is:

```text
Collect sample documents
  -> Build or update manifest
  -> Ingest documents
  -> Generate parse quality summary
  -> Generate Context Packs
  -> Trace evidence
  -> Run baseline vs Context Pack evaluation
```

## Required Inputs

For a meaningful run, collect:

- Real documents, not placeholders.
- Document title.
- Source path.
- Owner or checker.
- Document version.
- Source type.
- Supplier or internal source when known.
- Project or module when known.
- Task cards with expected answer points and evidence hints.

Do not commit confidential raw documents to git.

## Suggested First Run

Start with a small mixed document set:

- 5 to 10 real documents.
- 3 to 5 real questions or agent tasks.
- One checker who can judge correctness.

Run inventory:

```powershell
python -m agent_knowledge_hub.cli inventory `
  --root-dir "D:\docs" `
  --output-dir ".\agent-artifacts\inventory-run" `
  --max-files 30 `
  --owner "checker" `
  --project "unknown"
```

Run manifest ingest:

```powershell
python -m agent_knowledge_hub.cli manifest `
  --manifest-path ".\agent-artifacts\inventory-run\raw-docs-sample-manifest.csv" `
  --out-dir ".\data\processed" `
  --project-root "." `
  --incremental
```

Generate quality summary:

```powershell
python -m agent_knowledge_hub.cli parse-quality-summary `
  --processed-dir ".\data\processed" `
  --output-dir ".\data\parse-quality-summary"
```

Validate Layer1 processed contract:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\data\processed" `
  --require-valid
```

Validate the public synthetic golden samples when checking a fresh checkout:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\samples\golden" `
  --require-valid
```

Run the full Layer2 acceptance loop:

```powershell
python -m agent_knowledge_hub.cli layer2-run `
  --processed-dir ".\data\processed" `
  --output-dir ".\agent-artifacts\layer2-run" `
  --query "你的真实问题" `
  --top-k 8 `
  --per-document-limit 2 `
  --require-ready
```

Expected outputs:

- `layer2-run-summary.json`
- `layer2-run-summary.md`
- `contract/processed-contract-validation.json`
- `indexes/chunks.fts.sqlite`
- `indexes/chunks.vector.json`
- `context-pack/context_pack.json`
- `context-pack/context_pack.md`
- `evidence-trace.json`

Generate Context Pack:

```powershell
python -m agent_knowledge_hub.cli context-pack `
  --processed-dir ".\data\processed" `
  --query "你的真实问题" `
  --task-type "constraint_lookup" `
  --top-k 8 `
  --per-document-limit 2 `
  --fts-index-path ".\agent-artifacts\layer2-run\indexes\chunks.fts.sqlite" `
  --vector-index-path ".\agent-artifacts\layer2-run\indexes\chunks.vector.json"
```

Prepare baseline vs Context Pack evaluation prompts:

```powershell
python -m agent_knowledge_hub.cli prepare-eval-run `
  --eval-cases ".\agent-artifacts\eval\eval_cases.jsonl" `
  --processed-dir ".\data\processed" `
  --output-dir ".\agent-artifacts\eval\run-001" `
  --run-id "run-001" `
  --agent "copilot-or-codex" `
  --model "actual-model-name" `
  --top-k 8 `
  --per-document-limit 2 `
  --fts-index-path ".\agent-artifacts\layer2-run\indexes\chunks.fts.sqlite" `
  --vector-index-path ".\agent-artifacts\layer2-run\indexes\chunks.vector.json"
```

Then generate the real-agent execution guide:

```powershell
python -m agent_knowledge_hub.cli prepare-eval-execution-pack `
  --eval-run-dir ".\agent-artifacts\eval\run-001" `
  --eval-cases ".\agent-artifacts\eval\eval_cases.jsonl"
```

## Quality Gates

Before treating results as useful:

- `pytest -q` passes.
- Processed documents have `canonical-document.json` and `chunks.jsonl`.
- `validate-processed --require-valid` passes.
- `layer2-run --require-ready` passes for at least one real question.
- Eval Context Packs are generated with the same retrieval indexes used in manual Context Pack validation.
- Parse quality summary has allowed documents.
- Context Pack evidence includes source document, version, section or page, and evidence id.
- Low-quality documents are either excluded or clearly warned.

## Production Caveats

Before production use, the project still needs:

- Authentication and authorization.
- Audit logs.
- Secret management.
- Bot platform verification.
- Permission filtering by project and document source.
- Stable local knowledge pack packaging.
- Production-grade retrieval indexes.
- Backup and data retention rules.

Historical runbooks are archived under [archive/06-operations](archive/06-operations/).
