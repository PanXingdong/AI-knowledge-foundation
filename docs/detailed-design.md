# Detailed Design

## Scope

This design covers the full product direction but marks the implementation boundary clearly.

| Phase | Meaning |
|---|---|
| P0 | Must work for the first usable prototype and evaluation |
| P1 | Next practical hardening after P0 value is proven |
| P2 | Later graph, governance, and production capabilities |

## Module Breakdown

```text
agent_knowledge_hub
  document_inventory
  document_ingestion
  parser_adapter
  canonical_builder
  chunk_builder
  quality_gate
  index_builder
  retrieval_engine
  context_pack_builder
  evidence_trace
  core_api
  bot_adapter
  agent_local_adapter
  eval_harness
  graph_augmentation
  governance
```

| Module | Phase | Responsibility |
|---|---:|---|
| `document_inventory` | P0 | Discover candidate files and generate manifest drafts |
| `document_ingestion` | P0 | Import manifest rows, calculate hash, trigger parsing |
| `parser_adapter` | P0 | Parse files into normalized parsed blocks |
| `canonical_builder` | P0 | Build the Canonical Document Model |
| `chunk_builder` | P0 | Generate section-aware chunks with evidence ids |
| `quality_gate` | P0 | Decide whether parsed output is usable for Context Pack |
| `retrieval_engine` | P0/P1 | Retrieve, rank, dedupe, and filter chunks |
| `context_pack_builder` | P0 | Assemble agent-consumable Context Packs |
| `evidence_trace` | P0 | Resolve evidence ids to source text |
| `core_api` | P0 | Expose inventory, ingest, search, context-pack, trace, status |
| `bot_adapter` | P1 | Connect a chat platform to Core |
| `agent_local_adapter` | P1 | Provide local CLI/HTTP/SDK/knowledge-pack entry |
| `graph_augmentation` | P2 | Expand retrieved context through approved relationships |
| `governance` | P2 | Review, correction, invalidation, audit, permissions |

## Canonical Document Model

The model is the stable boundary between document parsing and retrieval.

```text
Document 1--N DocumentVersion
DocumentVersion 1--N Section
DocumentVersion 1--N Block
Block 1--1 EvidenceSpan
DocumentVersion 1--N Chunk
Chunk N--N EvidenceSpan
```

Required objects:

- `Document`: stable logical document metadata.
- `DocumentVersion`: file path, hash, version, source type, owner, supplier, project.
- `Section`: section path, title, page range.
- `Block`: heading, paragraph, table, list, code, figure caption, or unknown.
- `EvidenceSpan`: traceable source span with evidence id, page, section, block, text hash, and optional bbox.
- `Chunk`: retrieval unit with text, page range, section path, metadata, and evidence ids.

Version is P0. Any query result, Context Pack item, or trace result must preserve document version.

## Manifest Contract

Phase 1 manifest is CSV-based.

| Field | Required | Notes |
|---|---:|---|
| `sample_id` | yes | Human-readable sample or row id |
| `file_path` | yes | Absolute or project-relative path |
| `document_title` | yes | Display title |
| `slot_type` | yes | Document type or source category |
| `owner` | yes | Document checker or owner |
| `project` | no | Project name |
| `supplier` | no | Supplier or internal |
| `document_version` | yes | Version string |

Future fields such as `module`, `platform`, `applicability`, and `parse_profile` must be backward-compatible.

## Parser Design

Supported P0 formats:

- Markdown.
- TXT.
- HTML.
- PDF with `pypdf` text-layer extraction.
- PDF OCR fallback when optional OCR dependencies are installed.
- DOCX with `python-docx`.

Parser output is not a final knowledge object. It must be converted to the canonical model before chunking or indexing.

Quality reports include:

- `score`
- `status`
- `fallback_used`
- `fallback_parser`
- `reason_codes`
- text quality metrics

Current quality statuses:

- `ok`
- `recovered_by_fallback`
- `low_quality`
- `unsupported`
- `ocr_unavailable`
- `failed`

## Chunking Design

P0 chunking rules:

1. Group blocks by section.
2. Do not intentionally cross unrelated section boundaries.
3. Split large sections by `max_chunk_chars`.
4. Preserve overlap by `overlap_chars`.
5. Attach all source `evidence_ids`.

Default parameters:

```text
max_chunk_chars = 1600
overlap_chars = 160
```

P1 should add table-preserving and API-reference-aware chunking.

## Quality Gate

Only documents with usable parse quality enter Context Pack retrieval by default.

Allowed:

```text
quality_status in {ok, recovered_by_fallback}
and quality_score >= 40 when score exists
and chunks.jsonl exists
```

Blocked documents can still be reported and traced, but selected evidence must carry warnings.

## Retrieval Design

P0 retrieval is lexical and file-based. It reads `chunks.jsonl`, scores candidates, dedupes overlapping chunks, applies document limits, and preserves evidence metadata.

P1 retrieval should become hybrid:

```text
query
  -> metadata filter
  -> BM25 / FTS retrieve
  -> vector retrieve
  -> RRF merge
  -> rule boost / penalty
  -> dedupe
  -> quality gate
```

Precise symbols, error codes, section numbers, API names, and version strings need lexical search. Semantic search should supplement it, not replace it.

## Context Pack Design

Context Pack is the main agent-facing artifact.

It must contain:

- Query or task summary.
- Selected evidence chunks.
- Document title, source type, version, page, section, and evidence ids.
- Matched clauses.
- Quality warnings.
- Evidence appendix.

Current P0 output includes JSON and Markdown. The API returns both structured fields and `markdown`.

## Evidence Trace

Trace input:

```text
processed_dir
evidence_id
```

Trace output must include:

- `evidence_id`
- document id and title
- document version id and version
- source type and source path
- page
- section path and titles
- block id
- original text
- optional bbox
- chunk references

## Product Entries

The bot and local agent entries are adapters. They do not own parsing, retrieval, ranking, or trace logic.

```text
Group message
  -> bot adapter
  -> Core API
  -> formatted reply

Local agent
  -> CLI / local HTTP / SDK / knowledge pack
  -> Core API or local Core functions
  -> Context Pack / trace result
```

## Graph Augmentation

Graph is P2 unless evaluation proves retrieval alone cannot handle key use cases.

Graph entities may include:

```text
Document, DocumentVersion, Section, EvidenceSpan, Module, Interface, API,
Service, Signal, Configuration, ErrorCode, Requirement, Constraint, Risk,
Platform, Supplier, Version, TestItem, DesignDecision, Defect
```

Graph relations may include:

```text
HAS_VERSION, HAS_SECTION, HAS_EVIDENCE, DEFINED_IN, MENTIONED_IN,
IMPLEMENTS, DEPENDS_ON, CALLS, CONSTRAINS, AFFECTS, VERIFIES,
REPLACES, CONFLICTS_WITH, VALID_FOR_VERSION, INVALIDATED_BY,
SUPPORTED_BY_EVIDENCE
```

No relation should become a strong fact without evidence and review state.

## Implementation Status

Currently implemented:

- P0 document inventory.
- P0 manifest ingest and incremental ingest.
- P0 parser adapters for PDF, DOCX, Markdown, HTML, TXT.
- P0 canonical model and chunks.
- P0 parse quality summary and gate.
- P0 lexical retrieval and Context Pack.
- P0 evidence trace.
- P0 FastAPI service.
- P0 CLI.
- P0 evaluation harness.

Not implemented as production features:

- Production Feishu bot adapter.
- Production local agent adapter.
- BM25/FTS plus vector hybrid retrieval.
- Stable local knowledge pack schema.
- Graph augmentation.
- Review console.
- Version invalidation.
- Impact analysis.

The fuller historical design is archived at [archive/03-design/detailed-design.md](archive/03-design/detailed-design.md).
