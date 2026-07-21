# Retrieval And Context Pack Status

This document describes the current implementation status of the second product segment:

```text
structured document outputs
  -> retrieval
  -> Context Pack
  -> evidence trace
  -> bot or agent consumption
```

It focuses on what is already implemented, what is still missing, and what the next engineering tasks should be.

## Scope

The second segment starts after document parsing and canonical modeling are already complete.

```text
processed_dir
  -> chunks.jsonl and canonical metadata
  -> retrieval
  -> Context Pack assembly
  -> evidence trace
  -> API / CLI
```

This is not the full product status. It is only the status of retrieval, Context Pack, and trace.

## Current Implemented Chain

The current implemented chain is:

```text
processed_dir
  -> load latest processed chunks
  -> apply metadata filters
  -> optionally load SQLite FTS5 hits
  -> optionally load local vector index hits
  -> normalize query
  -> split query clauses
  -> tokenize and derive topics
  -> score candidate chunks with rule-based lexical scoring, BM25 signal, optional FTS signal, and optional vector signal
  -> dedupe and apply per-document limit
  -> apply parse quality gate
  -> assemble Context Pack
  -> expose JSON / Markdown / evidence trace
```

Main implementation entry points:

| Responsibility | File | Main functions |
|---|---|---|
| Retrieval and Context Pack | `src/agent_knowledge_hub/retrieval.py` | `build_context_pack_for_processed_dir`, `search_processed_dir`, `trace_evidence_in_processed_dir`, `compare_context_pack_against_reference` |
| Parse quality gate | `src/agent_knowledge_hub/quality.py` | `build_parse_quality_summary` |
| Service layer | `src/agent_knowledge_hub/service.py` | `/api/context-pack`, `/api/search`, `/api/evidence/{evidence_id}`, `/api/parse-quality-summary` |
| CLI layer | `src/agent_knowledge_hub/cli.py` | `context-pack`, `gap-report`, `parse-quality-summary` |
| Persistent FTS index | `src/agent_knowledge_hub/fts_index.py` | `build_fts_index`, `query_fts_index` |
| Local vector index | `src/agent_knowledge_hub/vector_index.py` | `build_vector_index`, `query_vector_index` |

## What Is Already Implemented

### 1. Processed output loading

The system can already load processed document outputs from disk and read chunk-level retrieval units from `chunks.jsonl`.

Current internal loader path:

- `_iter_latest_processed_versions`
- `_load_processed_chunks`

This means retrieval is already connected to the structured document outputs instead of reading raw files directly.

### 2. Lexical retrieval and ranking

The current retrieval engine is implemented and usable as a P0 baseline.

Implemented behaviors:

- query normalization
- query clause splitting
- token-based lexical scoring
- in-memory BM25 scoring
- optional SQLite FTS5 signal
- optional local sparse-vector signal
- topic derivation
- candidate scoring
- overlap-aware selection
- per-document limit
- ranking output with matched clauses

Current internal ranking path:

- `_split_query_clauses`
- `_derive_query_topics`
- `_build_candidate_scores`
- `_select_candidates`

This is still not a full production hybrid retrieval engine, but it is no longer only a simple lexical scorer. It now combines rule-based lexical scoring, an in-memory BM25 signal, an optional persistent SQLite FTS5 signal, and an optional local sparse-vector signal.

### 3. Parse quality gate integration

Context Pack retrieval already respects parse quality.

Current behavior:

- prefer documents with `allowed_for_context_pack = true`
- preserve quality score and warnings on selected chunks
- allow blocked or low-quality documents to still be traced and reported

This is important because the second segment already distinguishes:

- retrieval-usable documents
- trace-only or warning-carrying documents

### 4. Context Pack assembly

The system already assembles agent-consumable Context Packs from selected chunks.

Current output fields include:

- schema version
- task type
- task profile
- emitted v1 contract
- query
- normalized query
- applied filters
- pack-level warnings
- selected chunks
- document version id
- document version
- document title
- source type
- project
- supplier
- source path
- section path
- section titles
- page range
- evidence ids
- score
- matched clauses
- retrieval signals
- quality status
- quality score
- quality gate reasons
- warnings

Current output forms:

- JSON
- Markdown

The current Context Pack contract is `context-pack.v1`. It is task-type-aware and currently supports:

- `general_query`
- `constraint_lookup`
- `code_review`
- `impact_analysis`
- `test_design`
- `api_usage`

The task type changes section labels, item roles, task intent, and agent-use guidance. It does not yet perform a full production rerank policy per task type.

Relevant functions:

- `build_context_pack_for_processed_dir`
- `_render_context_pack_markdown`
- `write_context_pack_bundle`

### 5. Evidence trace

The second segment already supports evidence trace by `evidence_id`.

Current trace output includes:

- evidence id
- document id and title
- document version id and version
- source type and source path
- page
- section path and section titles
- block id
- original text
- optional bbox
- chunk references

Relevant function:

- `trace_evidence_in_processed_dir`

This is already enough for traceability demos and API integration.

### 6. API endpoints

The retrieval and Context Pack chain is already exposed through FastAPI.

Current endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/context-pack` | retrieve and assemble Context Pack |
| `POST` | `/api/search` | return ranked retrieved chunks |
| `POST` | `/api/build-fts-index` | build a persistent SQLite FTS5 index |
| `POST` | `/api/build-vector-index` | build a local JSON vector index |
| `GET` | `/api/evidence/{evidence_id}` | trace evidence back to source text |
| `GET` | `/api/parse-quality-summary` | summarize parser quality and eligibility |
| `POST` | `/api/gap-report` | compare generated pack against reference |

This means the second segment is not only library code. It already has a service boundary.

### 7. CLI support

The current repository already exposes retrieval and Context Pack operations through the Python CLI.

Current commands:

- `python -m agent_knowledge_hub.cli context-pack`
- `python -m agent_knowledge_hub.cli build-fts-index`
- `python -m agent_knowledge_hub.cli build-vector-index`
- `python -m agent_knowledge_hub.cli trace`
- `python -m agent_knowledge_hub.cli parse-quality-summary`
- `python -m agent_knowledge_hub.cli gap-report`
- `python -m agent_knowledge_hub.cli prepare-eval-run`
- `python -m agent_knowledge_hub.cli prepare-eval-execution-pack`

This CLI is usable for engineering validation, but it is still an internal project CLI, not the final agent-facing product interface.

### 8. Evaluation support

The repository already contains supporting evaluation workflows for the second segment.

Current capabilities include:

- preparing eval runs
- collecting Context Pack outputs
- passing the same FTS/vector index paths into eval Context Pack generation
- recording agent outputs
- recording review decisions
- scoring eval runs
- comparing auto Context Pack against references

This is the foundation needed to prove whether processed retrieval is actually better than direct file handoff.

## What Is Not Finished Yet

The second segment is implemented as a usable P0 chain, but it is not yet product-hardened.

### 1. Metadata filtering is implemented for P0

The current retrieval contract now supports P0 metadata filters for:

- supplier
- project
- source type
- document version

These filters are available in:

- retrieval function calls
- `/api/context-pack`
- `/api/search`
- internal project CLI `context-pack`

Still missing:

- module
- platform
- broader applicability scopes
- richer filter syntax such as include and exclude rules

### 2. Production hybrid retrieval is not implemented yet

The current implementation is still file-based, but it now includes:

- rule-based lexical scoring
- in-memory BM25 scoring
- persistent SQLite FTS5 indexing
- optional FTS signal in Context Pack retrieval
- local JSON vector indexing with `local-hashed-token-v1`
- optional vector signal in Context Pack retrieval
- metadata filtering

It still does not include a full hybrid retrieval stack.

Not yet implemented:

- production semantic embeddings
- hybrid merge such as RRF
- stable boost and penalty policy across retrieval modes

So the current answer is:

```text
retrieval exists
but production hybrid retrieval does not exist yet
```

### 3. Task-type-aware Context Pack exists as a v1 contract

The current Context Pack is no longer only generic retrieval output. It now accepts a `task_type`, normalizes common aliases, emits a task profile, and groups section items with task-aware labels and `task_item_type`.

Implemented task types:

- `general_query`
- `constraint_lookup`
- `code_review`
- `impact_analysis`
- `test_design`
- `api_usage`

Still missing:

- production task-specific reranking
- domain-specific extraction such as API signatures, arguments, return values, and error codes from parser-level structured sections
- task-specific completeness checks
- `design_review` as a separate first-class task type if the team needs it

### 4. Stable Core contract exists, but product adapters are not done

The current API and CLI expose the stable Core-side `context-pack.v1` payload. This is enough for Layer3 implementation to depend on the Core response shape.

The API and CLI are still engineering interfaces, not yet the final group-bot or local-agent product entry.

Missing product-level hardening includes:

- stable query request schema for local agents
- stable response schema for bot and local agent adapters
- packaging strategy for local knowledge runtime
- adapter contracts for group bot and local agent consumers

### 5. Graph augmentation is not in the active chain

There is currently no graph-based expansion in the retrieval path.

That means the current second segment is:

```text
retrieval first
graph later
```

Graph should only enter the main path after P0 and P1 evaluation proves retrieval alone is insufficient for key use cases.

### 6. Real-document proof is still missing

This is the largest remaining product gap.

The repository has the framework for evaluation, but it still needs business proof from real engineering documents:

- real PDF, DOCX, or spec samples
- real question sets
- baseline runs with direct raw-file handoff
- Context Pack runs with the same tasks
- reviewer scoring
- result summary

Without this, the second segment is technically real but not yet business-proven.

## Current Status Summary

The current status should be described like this:

```text
The second segment already has a working P0 chain:
processed outputs -> retrieval -> Context Pack -> evidence trace -> API/CLI

  It does not yet have:
production hybrid retrieval,
stable product adapters,
or graph augmentation.
```

## Recommended Backlog

The next work should be split into P0 closeout, P1 hardening, and P2 enhancement.

### P0 closeout

Goal: prove the current second segment works on real documents and can be demonstrated clearly.

Tasks:

1. keep Context Pack v1 schema documented and covered by tests
2. document the current retrieval chain for collaborators
3. run the chain on real sample documents
4. produce first A/B comparison:
   - raw files directly to agent
   - Context Pack to agent
5. summarize:
   - correctness
   - missed constraints
   - token cost
   - human fix count
   - traceability quality

### P1 hardening

Goal: turn the current P0 chain into a stronger reusable core.

Tasks:

1. add metadata filters
   - supplier
   - project
   - document type
   - module
   - version
2. add BM25 or FTS retrieval
3. replace or supplement the local vector prototype with production semantic embeddings when allowed
4. add hybrid merge and rerank policy
5. harden task-type-aware Context Pack assembly with task-specific rerank and completeness checks
6. define a stable local agent request and response contract
7. define a stable bot request and response contract

### P2 enhancement

Goal: add relation-based expansion only after retrieval value is proven.

Tasks:

1. relation extraction
2. graph augmentation
3. impact analysis
4. version-difference reasoning
5. governance and review workflow

## Priority Order

The practical engineering order should be:

1. real-document eval
2. keep Context Pack v1 schema frozen through tests and docs
3. metadata filters
4. hybrid retrieval
5. task-type-aware assembly hardening
6. adapter contracts
7. graph augmentation if needed

This ordering matters.

The current system does not need graph work first. It needs proof and retrieval hardening first.

## Done Versus Missing

| Area | Current state |
|---|---|
| Processed output loading | done |
| Lexical retrieval | done |
| Candidate ranking and selection | done |
| Parse quality gate integration | done |
| Context Pack JSON and Markdown output | done |
| Evidence trace | done |
| Search and Context Pack API | done |
| Internal CLI support | done |
| Eval support framework | done |
| Metadata filters | done for P0 |
| In-memory BM25 scoring | done |
| Persistent SQLite FTS5 retrieval engine | done for P1 prototype |
| Local vector retrieval prototype | done |
| Hybrid retrieval merge | missing |
| Context Pack v1 schema contract | done |
| Task-type-aware Context Pack | done as v1 baseline |
| Task-specific rerank and completeness checks | missing |
| Stable product adapter contract | missing |
| Graph augmentation | missing |
| Real-document business proof | missing |

## Decision

The current repository should treat the second segment as:

```text
already implemented as a P0 engineering chain,
not yet finished as a P1 product capability
```

That is the correct status description for collaboration, planning, and external explanation.
