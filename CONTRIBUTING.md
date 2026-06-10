# Contributing

## Before You Start

1. Read [docs/README.md](docs/README.md) and [docs/detailed-design.md](docs/detailed-design.md).
2. Read [docs/branching-strategy.md](docs/branching-strategy.md) before opening a PR.
3. Check the current phase boundary before adding new platform features.
4. Keep generated artifacts and confidential documents out of git.

## Development Setup

```powershell
pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
pytest -q
```

Optional OCR dependencies:

```powershell
pip install -r requirements-ocr.txt
```

## Code Guidelines

- Keep Core logic inside `src/agent_knowledge_hub`.
- Keep adapters thin. Bot and local agent entry code should call Core APIs or Core functions.
- Do not duplicate retrieval logic in scripts or adapters.
- Preserve evidence trace fields when changing ingestion, retrieval, or Context Pack output.
- Add tests for behavior changes.

## Documentation Guidelines

- Architecture and product decisions belong in the relevant top-level document under `docs/`.
- Historical or detailed supporting notes belong under `docs/archive/`.
- Do not add new top-level docs unless they are stable project-entry documents.

## Pull Request Checklist

- [ ] Tests pass with `pytest -q`.
- [ ] The PR targets the correct branch: normal work to `main`, stable promotion to `R2`.
- [ ] The PR has at least one approval from someone other than the author before merge.
- [ ] No raw confidential documents are committed.
- [ ] No generated `data/`, `processed/`, eval output, cache, or pyc files are committed.
- [ ] README or docs are updated when behavior changes.
- [ ] Context Pack evidence trace remains intact.
