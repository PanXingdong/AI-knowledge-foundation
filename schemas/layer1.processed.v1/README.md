# layer1.processed.v1

This directory contains the versioned public schema contract for Layer 1 processed outputs.

Files:

- `canonical-document.schema.json`: schema for `canonical-document.json`.
- `chunk.schema.json`: schema for each line in `chunks.jsonl`.

The runtime validator is implemented in `src/agent_knowledge_hub/contract.py`. These JSON Schema files are kept as the collaboration-facing contract for parser implementers and reviewers.
