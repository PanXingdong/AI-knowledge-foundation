# Overview

AI Knowledge Foundation turns engineering documents into traceable context for humans and AI agents.

It is not a PDF chat demo and not a graph visualization project. The product target is a reusable knowledge foundation:

```text
engineering documents
  -> document inventory and manifest
  -> parsing
  -> canonical document model
  -> chunks and evidence spans
  -> quality gate
  -> retrieval
  -> task-aware Context Pack
  -> evidence trace
  -> group bot entry / local agent entry
```

## Product Shape

The project has one core and two product entries:

```text
Knowledge Hub Core
  -> group bot entry
  -> local agent entry
```

Knowledge Hub Core owns parsing outputs, retrieval, task-aware Context Pack assembly, evidence trace, and quality warnings.

The group bot is for people asking questions in a team chat.

The local agent entry is for Copilot, Codex, Cursor, or internal agents to fetch compact task context instead of reading a full document set.

MCP is not the current product route. Existing MCP code remains only as historical experimental code.

## Current Phase

The current repository is a phase-1 prototype. It validates whether structured document processing plus Context Pack retrieval is better than directly giving raw files to an agent.

The first sample scope is mixed engineering documents, also referred to as `混合工程文档样本`: supplier documents, internal specs, architecture notes, detailed design documents, interface/configuration notes, test materials, and defect or review notes.

Phase 1 focuses on:

- Document inventory and manifest.
- PDF, DOCX, Markdown, HTML, and TXT parsing.
- Canonical document model.
- Section-aware chunks and evidence spans.
- Parse quality gate.
- Lexical retrieval.
- Context Pack v1 generation with task types such as constraint lookup, code review, impact analysis, test design, and API usage.
- Evidence trace.
- API, CLI, and evaluation harness.

Phase 1 does not claim:

- Production chat bot adapter.
- Production local agent integration.
- Production hybrid retrieval.
- Full knowledge graph.
- Review console.
- Version invalidation.
- Impact analysis.

## Why Not Directly Give Files To Agents

Direct file handoff has four main problems:

- Agents repeatedly parse the same documents and waste context.
- Important clauses are easy to miss in long or mixed-format documents.
- Version, page, section, and source evidence are not consistently preserved.
- Different agents can produce inconsistent context from the same document set.

This project tries to provide a stable intermediate product:

```text
Context Pack = task-shaped compact context + source evidence + quality warnings
```

The value must be proven by evaluation. If Context Pack does not improve correctness, missing-constraint rate, token cost, or traceability, the project should not move into heavier graph work.

## Archive

Detailed historical design notes remain in [archive](archive/). New contributors should read the top-level docs first, then open archived files only when they need background or older decision details.
