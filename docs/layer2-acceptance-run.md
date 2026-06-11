# Layer2 Acceptance Run

Layer2 consumes Layer1 processed outputs. It does not parse PDF, DOCX, or other
raw documents directly.

Required input shape:

```text
processed/
  <document-id>/
    <document-version-id>/
      canonical-document.json
      chunks.jsonl
```

The one-command acceptance entry is:

```powershell
python -m agent_knowledge_hub.cli layer2-run `
  --processed-dir ".\samples\golden" `
  --output-dir ".\agent-artifacts\layer2-golden-run" `
  --query "What constraints should the agent use?" `
  --top-k 6 `
  --per-document-limit 3 `
  --require-ready
```

It performs:

1. Layer1 processed contract validation.
2. SQLite FTS5 index build.
3. Local sparse-vector index build.
4. Hybrid retrieval through Context Pack generation.
5. Evidence trace for the first selected evidence id.
6. Summary output.

Expected output files:

```text
layer2-run-summary.json
layer2-run-summary.md
contract/processed-contract-validation.json
contract/processed-contract-validation.md
indexes/chunks.fts.sqlite
indexes/chunks.vector.json
context-pack/context_pack.json
context-pack/context_pack.md
evidence-trace.json
```

The run is considered ready only when `layer2-run-summary.json` contains:

```json
{
  "contract_valid": true,
  "selected_chunk_count": 1,
  "trace_found": true,
  "is_ready": true,
  "blockers": []
}
```

`selected_chunk_count` can be greater than `1`. The key requirement is that it is
not zero.

## Local Real Samples

Real supplier or internal documents must stay outside Git. Use ignored paths:

```text
data/local/
agent-artifacts/
```

Do not commit raw PDF/DOCX files or processed content derived from confidential
documents.
