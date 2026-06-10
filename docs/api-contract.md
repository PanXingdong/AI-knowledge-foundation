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
| `POST` | `/api/gap-report` | P0 | Compare generated Context Pack against a reference pack |
| `GET` | `/api/evidence/{evidence_id}` | P0 | Trace evidence to source document text |
| `GET` | `/api/parse-quality-summary` | P0 | Summarize parser quality and Context Pack eligibility |

## POST /api/context-pack

Request:

```json
{
  "processed_dir": "D:/runs/processed",
  "query": "重要数据出境有什么限制？",
  "top_k": 8,
  "per_document_limit": 2
}
```

Response shape:

```json
{
  "data": {
    "query": "...",
    "normalized_query": "...",
    "processed_dir": "...",
    "chunk_count": 3,
    "document_count": 2,
    "sections": [],
    "selected_chunks": [],
    "markdown": "# Context Pack..."
  }
}
```

Selected chunks include document title, source path, source type, section path, section titles, page range, evidence ids, matched clauses, quality status, quality score, gate reasons, and warnings.

## POST /api/search

Request is the same as `/api/context-pack`.

Response shape:

```json
{
  "data": {
    "query": "...",
    "normalized_query": "...",
    "result_count": 3,
    "document_count": 2,
    "results": []
  }
}
```

Use this when the caller wants raw retrieval results instead of a full Context Pack.

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
