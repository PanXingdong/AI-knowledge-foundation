# Development

## Setup

Install runtime dependencies:

```powershell
pip install -r requirements.txt
```

Optional OCR dependencies:

```powershell
pip install -r requirements-ocr.txt
```

Run tests:

```powershell
$env:PYTHONPATH = "$PWD\src"
pytest -q
```

## Repository Layout

```text
src/agent_knowledge_hub/   Core Python package
scripts/                   PowerShell wrappers and smoke tests
schemas/                   Versioned public contracts for processed outputs
tests/                     pytest tests
docs/                      GitHub-facing docs and archive
samples/                   sample manifests and raw sample placeholder
experiments/               evaluation templates and run structure
requirements.txt           runtime dependencies
requirements-ocr.txt       optional OCR dependencies
pyproject.toml             project metadata and pytest config
```

## Main Code Paths

| Area | File |
|---|---|
| Data model | `src/agent_knowledge_hub/models.py` |
| Inventory | `src/agent_knowledge_hub/inventory.py` |
| Parser adapters | `src/agent_knowledge_hub/parsers.py` |
| Canonical builder | `src/agent_knowledge_hub/builder.py` |
| Chunking | `src/agent_knowledge_hub/chunker.py` |
| Manifest ingest | `src/agent_knowledge_hub/pipeline.py` |
| Incremental ingest | `src/agent_knowledge_hub/incremental.py` |
| Quality gate | `src/agent_knowledge_hub/quality.py` |
| Retrieval and Context Pack | `src/agent_knowledge_hub/retrieval.py` |
| Layer2 acceptance runner | `src/agent_knowledge_hub/layer2_run.py` |
| API | `src/agent_knowledge_hub/service.py` |
| CLI | `src/agent_knowledge_hub/cli.py` |
| Eval harness | `src/agent_knowledge_hub/eval_setup.py` |

## Common Commands

Runtime dependency check:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m agent_knowledge_hub.cli dependency-check
```

Inventory:

```powershell
python -m agent_knowledge_hub.cli inventory `
  --root-dir "D:\docs" `
  --output-dir ".\agent-artifacts\inventory-demo" `
  --max-files 30 `
  --max-file-mb 100 `
  --owner "checker" `
  --project "unknown"
```

Manifest ingest:

```powershell
python -m agent_knowledge_hub.cli manifest `
  --manifest-path ".\samples\sample-manifest.csv" `
  --out-dir ".\data\processed" `
  --project-root "." `
  --incremental
```

Context Pack:

```powershell
python -m agent_knowledge_hub.cli context-pack `
  --processed-dir ".\data\processed" `
  --query "这个文档说明了什么？" `
  --top-k 5 `
  --per-document-limit 2
```

Parse quality summary:

```powershell
python -m agent_knowledge_hub.cli parse-quality-summary `
  --processed-dir ".\data\processed" `
  --output-dir ".\data\parse-quality-summary"
```

Layer1 processed contract validation:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\data\processed" `
  --require-valid
```

Validate the public synthetic golden samples:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\samples\golden" `
  --require-valid
```

Layer2 acceptance run:

```powershell
python -m agent_knowledge_hub.cli layer2-run `
  --processed-dir ".\samples\golden" `
  --output-dir ".\agent-artifacts\layer2-golden-run" `
  --query "What constraints should the agent use?" `
  --top-k 6 `
  --per-document-limit 3 `
  --require-ready
```

This command is the local acceptance entry for Layer2. It validates the Layer1
processed contract, builds FTS and local vector indexes, assembles a Context Pack,
traces one selected evidence id, and writes `layer2-run-summary.json/md`.

## Development Rules

- Keep Core logic in `src/agent_knowledge_hub`.
- Keep bot and local agent adapters thin.
- Do not duplicate retrieval logic in scripts or adapters.
- Preserve evidence trace fields when changing ingestion, retrieval, or Context Pack output.
- Add tests for behavior changes.
- Do not commit confidential source documents.
- Do not commit generated `data/`, processed output, eval run output, cache files, or local artifacts.

## Documentation Rules

- Top-level docs are stable entry documents for collaborators.
- Detailed historical notes belong under `docs/archive/`.
- New design work should update the relevant top-level doc first.
- Archive files should not be the first place a new contributor has to read.

## Verification

Before pushing:

```powershell
$env:PYTHONPATH = "$PWD\src"
pytest -q
```

Useful smoke tests:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-auto-context-pack-smoke.ps1"
powershell -ExecutionPolicy Bypass -File ".\scripts\test-parse-quality-summary-smoke.ps1"
```
