# Architecture

## Target Architecture

```text
Document sources
  -> Ingestion
  -> Parser adapters
  -> Canonical Document Model
  -> Quality gate
  -> Retrieval indexes
  -> Context Pack builder
  -> Evidence trace
  -> Core API
  -> Group bot / Local agent entry
```

The architecture is retrieval-first. Graph augmentation is a later capability for relationship-heavy use cases, not the first retrieval path.

## Runtime Layers

| Layer | Responsibility |
|---|---|
| Document source | PDF, DOCX, Markdown, HTML, TXT, internal specs, supplier docs, architecture notes, test materials |
| Ingestion | Manifest handling, hash calculation, document version records, idempotent batch ingest |
| Parser adapter | Convert each format into parsed blocks with page and warning metadata |
| Canonical model | Normalize output into Document, DocumentVersion, Section, Block, EvidenceSpan, Chunk |
| Quality gate | Mark whether parsed output can enter Context Pack retrieval |
| Retrieval | Search processed chunks, rank, dedupe, limit per document, preserve evidence |
| Context Pack | Assemble task-ready context with evidence appendix |
| Evidence trace | Resolve `evidence_id` back to document, version, page, section, and text |
| Product entry | Group bot and local agent calls into Core; they do not reimplement retrieval |

## Phase 1 Deployment

Phase 1 can run as a single Python application:

```text
raw documents / manifest
  -> Python package
  -> processed/
  -> FastAPI service
  -> CLI / bot demo / local agent demo
```

Phase 1 storage is file-based:

```text
processed/
  <document_slug>/
    <document_version_id>/
      canonical-document.json
      chunks.jsonl
  ingest-summary.json
  ingest-run-summary.json
  ingest-state.json
```

This is enough for local validation and team demos. It is not the final production storage design.

## Target Deployment

The production direction can evolve to:

```text
Parser workers
  -> PostgreSQL metadata
  -> Object/NAS processed store
  -> FTS/BM25 index
  -> Vector index
  -> Optional graph store
  -> Knowledge Hub Core
  -> Bot gateway / Local knowledge pack / Local HTTP
```

Recommended target components:

- PostgreSQL for metadata and document version records.
- OpenSearch, PostgreSQL FTS, or another BM25-capable index for lexical search.
- Qdrant or pgvector for vector search.
- Neo4j or another graph store only after relationship-heavy requirements are proven.
- Object storage or NAS for source files and processed artifacts.

## Design Principles

- Evidence first: key context must trace back to source document, version, page, section, and text.
- Version first: document version is part of the core model, not a later annotation.
- Retrieval first: lexical and semantic retrieval should carry v1 value before graph work starts.
- Thin adapters: bot and local agent entry layers call Core instead of owning retrieval logic.
- Evaluation first: heavier graph, review, and version invalidation work depends on measured value.

## Current Implementation Mapping

| Capability | Current module |
|---|---|
| Inventory | `src/agent_knowledge_hub/inventory.py` |
| Ingestion | `src/agent_knowledge_hub/pipeline.py`, `src/agent_knowledge_hub/incremental.py` |
| Parsing | `src/agent_knowledge_hub/parsers.py` |
| Canonical model | `src/agent_knowledge_hub/models.py`, `src/agent_knowledge_hub/builder.py` |
| Chunking | `src/agent_knowledge_hub/chunker.py` |
| Quality gate | `src/agent_knowledge_hub/quality.py` |
| Retrieval and Context Pack | `src/agent_knowledge_hub/retrieval.py` |
| API | `src/agent_knowledge_hub/service.py` |
| CLI | `src/agent_knowledge_hub/cli.py` |
| Evaluation | `src/agent_knowledge_hub/eval_setup.py` |
