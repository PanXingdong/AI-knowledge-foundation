# API Contract

This document describes the current Core API and the intended local-agent contract.

## Core API

The service is implemented in `src/agent_knowledge_hub/service.py`.

Start the API:

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\start-context-pack-api.ps1" `
  -BindHost "127.0.0.1" `
  -Port 8787
```

## Endpoints

| Method | Path | Status | Purpose |
|---|---|---:|---|
| `GET` | `/health` | P0 | Health check |
| `GET` | `/api/runtime-dependencies` | P0 | Report installed parser capabilities |
| `POST` | `/api/document-inventory` | P0 | Scan document directories and generate inventory data |
| `POST` | `/api/ingest-manifest` | P0 | Ingest documents from a manifest |
| `POST` | `/api/context-pack` | P0 | Retrieve and assemble a Context Pack |
| `POST` | `/api/search` | P0 | Retrieve ranked chunks |
| `POST` | `/api/build-fts-index` | P1 | Build a persistent SQLite FTS5 index |
| `POST` | `/api/build-vector-index` | P1 | Build a local JSON vector index |
| `POST` | `/api/gap-report` | P0 | Compare generated Context Pack against a reference pack |
| `GET` | `/api/evidence/{evidence_id}` | P0 | Trace evidence to source document text |
| `GET` | `/api/parse-quality-summary` | P0 | Summarize parser quality and Context Pack eligibility |

## POST /api/context-pack

Request:

```json
{
  "processed_dir": "D:/runs/processed",
  "query": "重要数据出境有什么限制？",
  "task_type": "constraint_lookup",
  "top_k": 8,
  "per_document_limit": 2,
  "fts_index_path": "D:/runs/index/chunks.db",
  "vector_index_path": "D:/runs/index/chunks.vector.json",
  "metadata_filters": {
    "supplier": ["Bosch"],
    "project": ["cockpit"],
    "document_version": ["v7.0"],
    "source_type": ["supplier spec"]
  }
}
```

Supported Context Pack task types:

- `general_query`: default compact answer context.
- `constraint_lookup`: constraints, caveats, risks, and source evidence.
- `code_review`: review-ready risks, implementation contracts, and tests.
- `impact_analysis`: likely affected areas, interfaces, tests, and open questions.
- `test_design`: behaviors, edge cases, risks, and test evidence.
- `api_usage`: signatures, arguments, returns/errors, caveats, and API evidence.

Common aliases are normalized to the stable task types above for compatibility with older eval templates and owner input forms. Current supported aliases include:

- `constraint_lookup`: `constraint-query`, `constraint_query`, `constraint`, `constraints`, `查约束`.
- `code_review`: `review`, `代码评审`.
- `impact_analysis`: `impact`, `影响分析`.
- `test_design`: `test`, `test_focus`, `test_focus_generation`, `test_review_checklist`, `qa`, `测试设计`, `生成测试关注点`, `生成测试点`.
- `api_usage`: `api`, `interface_lookup`, `interface_mechanism_lookup`, `interface_mechanism`, `接口使用`, `机制查询`, `查接口`, `查接口/机制`, `查接口机制`.

Supported P0 filter keys:

- `supplier`
- `project`
- `document_version`
- `source_type`

Response shape:

```json
{
  "data": {
    "schema_version": "context-pack.v1",
    "task_type": "constraint_lookup",
    "task_profile": {
      "label": "Constraint Lookup",
      "intent": "Surface applicable constraints, risks, caveats, and source evidence.",
      "agent_use": [
        "Prioritize constraints and caveats over background text."
      ],
      "preferred_sections": ["constraints", "risks", "evidence", "evidence_appendix"]
    },
    "contract": {
      "name": "Context Pack v1",
      "schema_version": "context-pack.v1",
      "stability": "stable_for_layer3",
      "stable_fields": [
        "schema_version",
        "task_type",
        "task_profile",
        "query",
        "normalized_query",
        "processed_dir",
        "applied_filters",
        "chunk_count",
        "document_count",
        "warnings",
        "sections",
        "selected_chunks"
      ],
      "item_stable_fields": [
        "evidence_number",
        "task_item_type",
        "summary",
        "document_title",
        "document_version",
        "project",
        "supplier",
        "source_type",
        "source_path",
        "section_titles",
        "section_path",
        "matched_clauses",
        "score",
        "retrieval_signals",
        "evidence_ids",
        "quality_status",
        "quality_score",
        "allowed_for_context_pack",
        "quality_gate_reasons",
        "warnings"
      ]
    },
    "query": "...",
    "normalized_query": "...",
    "processed_dir": "...",
    "applied_filters": {
      "supplier": ["Bosch"]
    },
    "chunk_count": 3,
    "document_count": 2,
    "warnings": [],
    "sections": [
      {
        "title": "Additional Constraints",
        "items": [
          {
            "evidence_number": 1,
            "task_item_type": "supporting_constraint",
            "summary": "...",
            "document_title": "...",
            "document_version": "v7.0",
            "supplier": "Bosch",
            "project": "cockpit",
            "source_type": "supplier spec",
            "source_path": "...",
            "section_titles": [],
            "section_path": [],
            "matched_clauses": [],
            "score": 12.34,
            "retrieval_signals": ["lexical", "bm25"],
            "evidence_ids": ["span_xxx"],
            "quality_status": "ok",
            "quality_score": 100.0,
            "allowed_for_context_pack": true,
            "quality_gate_reasons": [],
            "warnings": [],
            "chunk": {}
          }
        ]
      }
    ],
    "selected_chunks": [],
    "markdown": "# Context Pack..."
  }
}
```

`schema_version`, `task_type`, `task_profile`, `warnings`, `sections`, and `selected_chunks` are part of the Context Pack v1 contract. `contract.stable_fields` and `contract.item_stable_fields` are emitted with every pack so Layer3 callers can validate the shape they depend on.

Selected chunks include document title, document version, supplier, project, source path, source type, section path, section titles, page range, evidence ids, matched clauses, quality status, quality score, gate reasons, and warnings.

Selected chunks also include `retrieval_signals`, which explains which retrieval signals contributed to the selection. Current values can include `lexical`, `bm25`, `fts`, `vector`, `topic`, or `fallback`.

`sections[].items[]` is the stable P0/P1 transition payload for agent consumption. Each item currently includes:

- `evidence_number`
- `task_item_type`
- `summary`
- `document_title`
- `document_version`
- `supplier`
- `project`
- `source_type`
- `source_path`
- `section_titles`
- `section_path`
- `matched_clauses`
- `score`
- `retrieval_signals`
- `evidence_ids`
- `quality_status`
- `quality_score`
- `allowed_for_context_pack`
- `quality_gate_reasons`
- `warnings`

`chunk` is included in full JSON responses for debug and trace expansion, but it is not an item stable field. Summary bundles can omit the full `chunk` while preserving the stable item fields above.

## POST /api/search

Request is the same envelope as `/api/context-pack`, but `task_type` is ignored because search returns raw ranked chunks instead of a task-shaped Context Pack.

Response shape:

```json
{
  "data": {
    "query": "...",
    "normalized_query": "...",
    "applied_filters": {
      "supplier": ["Bosch"]
    },
    "result_count": 3,
    "document_count": 2,
    "results": []
  }
}
```

Use this when the caller wants raw retrieval results instead of a full Context Pack.

## POST /api/build-fts-index

Request:

```json
{
  "processed_dir": "D:/runs/processed",
  "index_path": "D:/runs/index/chunks.db"
}
```

Response shape:

```json
{
  "data": {
    "processed_dir": "D:/runs/processed",
    "index_path": "D:/runs/index/chunks.db",
    "indexed_chunk_count": 128,
    "indexed_document_count": 12
  }
}
```

This builds a persistent SQLite FTS5 index over processed chunks. `/api/context-pack` and `/api/search` can use that index through `fts_index_path`.

## POST /api/build-vector-index

Request:

```json
{
  "processed_dir": "D:/runs/processed",
  "index_path": "D:/runs/index/chunks.vector.json"
}
```

Response shape:

```json
{
  "data": {
    "processed_dir": "D:/runs/processed",
    "index_path": "D:/runs/index/chunks.vector.json",
    "indexed_chunk_count": 128,
    "indexed_document_count": 12,
    "embedding_strategy": "local-hashed-token-v1"
  }
}
```

This builds a local JSON sparse-vector index over processed chunks. It is a dependency-free retrieval plumbing prototype, not a production semantic embedding model. `/api/context-pack` and `/api/search` can use that index through `vector_index_path`.

## GET /api/evidence/{evidence_id}

Request:

```text
GET /api/evidence/span_xxx?processed_dir=D:/runs/processed
```

Response shape:

```json
{
  "data": {
    "evidence_id": "span_xxx",
    "document_title": "...",
    "document_version": "v1",
    "source_path": "...",
    "page": 18,
    "section_titles": [],
    "text": "..."
  }
}
```

## POST /api/document-inventory

Request:

```json
{
  "root_dirs": ["D:/docs"],
  "max_files": 200,
  "max_file_mb": 100,
  "owner": "checker",
  "project": "unknown",
  "document_version": "unknown",
  "include_keywords": [],
  "exclude_keywords": [],
  "dedupe_content_hash": true
}
```

Response includes inventory rows and Markdown for human review.

## POST /api/ingest-manifest

Request:

```json
{
  "manifest_path": "D:/runs/raw-docs-sample-manifest.csv",
  "out_dir": "D:/runs/processed",
  "project_root": "D:/repo",
  "max_chunk_chars": 1600,
  "overlap_chars": 160,
  "fail_fast": false,
  "incremental": true
}
```

Response includes processed, skipped, and failed document records.

## Error Handling

Current API errors use FastAPI `detail` responses:

- Missing files or directories return `404`.
- Invalid request data returns `400`.
- Unknown evidence ids return `404`.

P1 can introduce a structured error envelope, but P0 keeps the implementation simple.

## Local Agent Contract

The stable agent-facing contract is not raw files. It is:

```text
query / task context
  -> Context Pack
  -> evidence trace when needed
```

Local agent entry can be implemented as:

- CLI.
- Local HTTP.
- SDK.
- Read-only knowledge pack.

The local entry should call Core functions or Core API. It must not duplicate retrieval or evidence logic.

The future command shape is:

```powershell
agent-knowledge query "重要数据出境有什么限制？"
agent-knowledge search "D.8 出境试验方法"
agent-knowledge context-pack --task code_review --query "诊断模块修改需要注意什么"
agent-knowledge trace --evidence-id "span_xxx"
agent-knowledge status
```

Current CLI implementation is still under `python -m agent_knowledge_hub.cli`.

Current internal CLI filter shape:

```powershell
python -m agent_knowledge_hub.cli context-pack `
  --processed-dir ".\\data\\processed" `
  --task-type "code_review" `
  --query "诊断模块修改需要注意什么？" `
  --supplier "Bosch" `
  --document-version "v7.0" `
  --project-filter "cockpit" `
  --source-type "supplier spec"
```

Current internal CLI FTS shape:

```powershell
python -m agent_knowledge_hub.cli build-fts-index `
  --processed-dir ".\\data\\processed" `
  --index-path ".\\data\\index\\chunks.db"

python -m agent_knowledge_hub.cli context-pack `
  --processed-dir ".\\data\\processed" `
  --query "runtime_requir" `
  --fts-index-path ".\\data\\index\\chunks.db"
```

Current internal CLI local vector shape:

```powershell
python -m agent_knowledge_hub.cli build-vector-index `
  --processed-dir ".\\data\\processed" `
  --index-path ".\\data\\index\\chunks.vector.json"

python -m agent_knowledge_hub.cli context-pack `
  --processed-dir ".\\data\\processed" `
  --query "海外批准要求" `
  --vector-index-path ".\\data\\index\\chunks.vector.json"
```
