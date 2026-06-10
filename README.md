# AI Knowledge Foundation

AI Knowledge Foundation is an internal engineering knowledge foundation for turning project documents, supplier references, specifications, architecture notes, and test materials into traceable context that humans and AI agents can use.

The current codebase is a phase-1 prototype of the core pipeline:

```text
documents
  -> inventory / manifest
  -> parsing
  -> canonical document model
  -> chunks + evidence spans
  -> parse quality gate
  -> retrieval
  -> Context Pack
  -> evidence trace
  -> API / CLI / eval harness
```

The product direction is:

```text
Knowledge Hub Core
  -> group bot entry
  -> local agent entry
```

MCP is not the current product route. Existing MCP code is kept only as historical experimental code.

The first sample scope is mixed engineering documents (`混合工程文档样本`): supplier documents, internal specs, architecture notes, detailed design documents, interface/configuration notes, test materials, and defect or review notes.

## What Exists

- Document inventory and manifest generation.
- Document ingestion for PDF, DOCX, Markdown, HTML, and TXT.
- Canonical document model: `Document`, `DocumentVersion`, `Section`, `Block`, `EvidenceSpan`, `Chunk`.
- Section-aware chunk generation.
- Parse quality summary and context-pack quality gate.
- Lexical/rule-based retrieval prototype.
- Context Pack generation in Markdown and JSON.
- Evidence trace by `evidence_id`.
- FastAPI service for core operations.
- CLI and PowerShell wrappers.
- Evaluation harness for baseline vs Context Pack comparison.

## What Does Not Exist Yet

- Production Feishu / WeCom / DingTalk bot adapter.
- Productized local agent integration.
- Production BM25/FTS + vector hybrid retrieval.
- Stable local knowledge pack schema.
- Graph augmentation, review console, version invalidation, and impact analysis.

## Repository Layout

```text
src/agent_knowledge_hub/   Python package for ingestion, parsing, retrieval, API, CLI, eval
scripts/                   PowerShell wrappers and smoke test scripts
tests/                     pytest test suite
docs/                      GitHub-facing docs plus archived historical notes
samples/                   sample manifest templates; no real confidential docs
experiments/               eval templates and run structure
requirements.txt           phase-1 runtime dependencies
requirements-ocr.txt       optional OCR dependencies
pyproject.toml             pytest config
```

## Quick Start

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run tests:

```powershell
$env:PYTHONPATH = "$PWD\src"
pytest -q
```

Start the API:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\start-context-pack-api.ps1" `
  -BindHost "127.0.0.1" `
  -Port 8787
```

Run one document ingest:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\ingest-documents.ps1" `
  -FilePath ".\samples\raw\README.md" `
  -Title "Sample Raw README" `
  -SourceType "sample" `
  -Owner "checker" `
  -DocumentVersion "v1" `
  -OutDir ".\data\processed"
```

Generate a Context Pack after ingest:

```powershell
python -m agent_knowledge_hub.cli context-pack `
  --processed-dir ".\data\processed" `
  --query "这个文档说明了什么？" `
  --top-k 5 `
  --per-document-limit 2
```

## Documentation

Start here:

- [docs/README.md](docs/README.md)
- [Overview](docs/overview.md)
- [Architecture](docs/architecture.md)
- [Detailed design](docs/detailed-design.md)
- [API contract](docs/api-contract.md)
- [Development](docs/development.md)
- [Evaluation](docs/evaluation.md)
- [Operations](docs/operations.md)

## Development Rules

- Do not commit confidential source documents.
- Do not commit generated `data/processed`, eval run outputs, cache files, or local artifacts.
- Keep bot adapters and agent local adapters as thin entry layers. They must call Core APIs instead of reimplementing retrieval.
- Keep evidence trace intact for every Context Pack item.
- Run tests before pushing changes.

## Current Verification

The cleaned project is expected to pass:

```text
96 passed, 6 skipped
```
