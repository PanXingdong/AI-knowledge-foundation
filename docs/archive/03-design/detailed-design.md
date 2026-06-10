# 29 完整详细设计

## 1. 设计范围

本文是 Agent Knowledge Hub 的详细设计文档，面向开发、评审和后续拆任务。

本文覆盖完整产品，但按阶段标注实现优先级：

- P0：阶段 1 必须实现，支撑真实实验和第一个可用 demo。
- P1：阶段 1 可选增强，或者阶段 2 入口能力。
- P2：阶段 2 及以后能力，只有在 P0 证明价值后建设。

当前产品目标：

```text
工程文档 / 供应商资料 / 内部 SPEC / 架构设计 / 测试资料
  -> 结构化处理
  -> 检索与证据追溯
  -> Context Pack
  -> 群机器人入口 / Agent 本地入口
```

## 2. 系统模块拆分

### 2.1 模块总览

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
  graph_augmentation
  context_pack_builder
  evidence_trace
  core_api
  bot_adapter
  agent_local_adapter
  eval_harness
  governance
```

### 2.2 模块职责

| 模块 | 阶段 | 职责 | 不负责 |
|---|---:|---|---|
| `document_inventory` | P0 | 扫描候选文档，生成清单和 manifest 草稿 | 解析正文 |
| `document_ingestion` | P0 | 按 manifest 导入文档，计算 hash，触发解析 | 判断业务正确性 |
| `parser_adapter` | P0 | 调用具体解析器，输出统一 ParsedDocument | 直接写索引 |
| `canonical_builder` | P0 | 把解析结果转成 Canonical Document Model | 做检索排序 |
| `chunk_builder` | P0 | 基于章节和块生成 chunks | 做语义抽取 |
| `quality_gate` | P0 | 给文档解析质量打分，决定能否进 Context Pack | 人工审核关系 |
| `index_builder` | P0/P1 | 建全文索引、向量索引、元数据索引 | 生成最终回答 |
| `retrieval_engine` | P0/P1 | 按 query 检索、融合排序、去重、质量过滤 | 图谱多跳推理 |
| `graph_augmentation` | P2 | 根据实体关系扩展上下文 | 替代原文检索 |
| `context_pack_builder` | P0 | 按 task_type 组装 Context Pack | 替 Agent 写代码 |
| `evidence_trace` | P0 | 根据 evidence_id 回溯来源 | 修正文档内容 |
| `core_api` | P0 | 暴露 query/search/context-pack/trace/status | 绑定某个群平台 |
| `bot_adapter` | P0/P1 | 对接飞书/企微/钉钉，格式化群回复 | 自己检索文档 |
| `agent_local_adapter` | P0/P1 | 本地 CLI/HTTP/SDK/knowledge pack 调用入口 | 自己实现知识逻辑 |
| `eval_harness` | P0 | 做原始文件 vs Context Pack 对比评测 | 替代人工验收 |
| `governance` | P2 | 审核、版本失效、权限、审计 | 第一阶段阻塞项 |

## 3. 部署视图

### 3.1 阶段 1 最小部署

```text
工程文档目录 / samples/raw
  -> CLI / API ingest
  -> processed/
  -> Core API
  -> 飞书机器人 demo
  -> Agent 本地 CLI/HTTP demo
```

阶段 1 可先用文件系统保存结构化产物：

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

### 3.2 目标部署

```text
             +----------------+
             |  原始文档仓库   |
             +-------+--------+
                     |
             +-------v--------+
             |  Worker/Parser |
             +-------+--------+
                     |
+--------------------+--------------------+
|                                         |
v                                         v
PostgreSQL Metadata              Object/NAS Processed Store
Qdrant / pgvector                OpenSearch / PostgreSQL FTS
Neo4j / Graph Store              Quality Reports
|                                         |
+--------------------+--------------------+
                     |
             +-------v--------+
             | Knowledge Core |
             +---+--------+---+
                 |        |
        +--------v+      +v----------------+
        | Bot API |      | Agent Local API |
        +---------+      +-----------------+
```

## 4. 文档接入详细设计

### 4.1 Manifest CSV 字段

阶段 1 manifest 使用 CSV。字段如下：

| 字段 | 必填 | 阶段 | 说明 |
|---|---:|---:|---|
| `sample_id` | 是 | P0 | 样本编号或行编号 |
| `file_path` | 是 | P0 | 原始文件路径，支持绝对路径和相对路径 |
| `document_title` | 是 | P0 | 文档标题 |
| `slot_type` | 是 | P0 | 文档类型，如 `supplier_pdf`、`internal_spec` |
| `owner` | 是 | P0 | 文档 owner |
| `project` | 否 | P0 | 项目 |
| `supplier` | 否 | P0 | 供应商 |
| `document_version` | 是 | P0 | 文档版本 |
| `module` | 否 | P1 | 适用模块 |
| `platform` | 否 | P1 | 平台，如 QNX/Linux/Android |
| `applicability` | 否 | P1 | 适用范围 JSON 或文本 |
| `parse_profile` | 否 | P1 | parser profile |

阶段 1 已实现字段以当前代码为准：

```text
sample_id
file_path
document_title
slot_type
owner
project
supplier
document_version
```

后续新增字段必须向后兼容，缺失时填 `unknown` 或空值，不得阻断旧 manifest。

### 4.2 文档接入状态

```text
discovered
  -> registered
  -> ingesting
  -> parsed
  -> indexed
  -> ready
```

异常状态：

```text
skipped
failed
unsupported
low_quality
blocked_by_quality_gate
```

状态含义：

| 状态 | 含义 |
|---|---|
| `discovered` | inventory 发现文件，但尚未登记 |
| `registered` | 已进入 manifest |
| `ingesting` | 正在读取、hash、解析 |
| `parsed` | 已产出 canonical-document.json 和 chunks.jsonl |
| `indexed` | 已写入全文/向量索引 |
| `ready` | 可被 Core 查询 |
| `skipped` | 路径缺失或占位，跳过 |
| `failed` | 解析或写入失败 |
| `unsupported` | 文件格式不支持 |
| `low_quality` | 解析质量低 |
| `blocked_by_quality_gate` | 不允许进入 Context Pack |

### 4.3 Hash 与幂等

每个文件必须计算 `file_hash`。

`DocumentVersion` ID 生成原则：

```text
document_version_id = stable_id(document_id, document_version, file_hash)
```

同一文件 hash 未变化时，增量摄取可以跳过。

## 5. Parser Adapter 详细设计

### 5.1 输入输出接口

输入：

```text
file_path
parse_profile
source_type
document_version
```

输出 `ParsedDocument`：

```json
{
  "source_format": "pdf",
  "parser_name": "pypdf+rapidocr",
  "page_count": 12,
  "blocks": [],
  "warnings": [],
  "quality_report": {}
}
```

`ParsedBlock`：

```json
{
  "block_type": "paragraph",
  "text": "...",
  "page_start": 1,
  "page_end": 1,
  "metadata": {}
}
```

### 5.2 支持格式

| 格式 | 阶段 | 默认解析方式 |
|---|---:|---|
| Markdown | P0 | 标题/段落解析 |
| TXT | P0 | 段落解析 |
| HTML | P0 | HTML block parser |
| PDF | P0 | pypdf text layer；低质量时 OCR fallback |
| DOCX | P0 | python-docx |
| 扫描 PDF | P1 | OCR fallback |
| 复杂版面 PDF | P1 | Docling / MinerU |

### 5.3 Parser Profile

通用 profile：

```text
generic_pdf
generic_docx
generic_markdown
generic_html
generic_txt
```

领域 profile：

```text
api_reference_profile
architecture_guide_profile
bsp_manual_profile
internal_spec_profile
test_report_profile
```

领域 profile 只做结构增强，不改变 Canonical Model。

### 5.4 质量报告

质量报告字段：

```json
{
  "score": 74.22,
  "status": "recovered_by_fallback",
  "fallback_used": true,
  "fallback_parser": "rapidocr",
  "reason_codes": [],
  "metrics": {
    "char_count": 25223,
    "cjk_count": 10827,
    "mojibake_suspect_count": 0,
    "mojibake_per_1k_cjk": 0.0,
    "latin1_mojibake_ratio": 0.0
  }
}
```

质量状态：

```text
ok
recovered_by_fallback
low_quality
unsupported
ocr_unavailable
failed
```

## 6. Canonical Document Model

### 6.1 逻辑模型

```text
Document 1--N DocumentVersion
DocumentVersion 1--N Section
DocumentVersion 1--N Block
Block 1--1 EvidenceSpan
DocumentVersion 1--N Chunk
Chunk N--N EvidenceSpan
```

### 6.2 Document

```json
{
  "document_id": "doc_xxx",
  "title": "Diagnostic SPEC",
  "source_type": "internal_spec",
  "owner": "checker",
  "project": "ProjectA",
  "supplier": "internal",
  "created_at": "2026-06-09T00:00:00Z"
}
```

### 6.3 DocumentVersion

```json
{
  "document_version_id": "docver_xxx",
  "document_id": "doc_xxx",
  "version": "v1.0",
  "file_path": "C:/path/to/docs/spec.docx",
  "file_hash": "sha256...",
  "created_at": "2026-06-09T00:00:00Z"
}
```

版本是 P0 字段。查询、Context Pack、trace 均必须返回版本。

### 6.4 Section

```json
{
  "section_id": "sec_xxx",
  "document_version_id": "docver_xxx",
  "section_path": ["3", "2"],
  "title": "DTC 状态同步",
  "page_start": 18,
  "page_end": 20
}
```

### 6.5 Block

```json
{
  "block_id": "blk_xxx",
  "document_version_id": "docver_xxx",
  "block_type": "paragraph",
  "text": "...",
  "page_start": 18,
  "page_end": 18,
  "section_path": ["3", "2"],
  "order": 42,
  "metadata": {}
}
```

`block_type` 允许值：

```text
heading
paragraph
table
list
code
figure_caption
unknown
```

### 6.6 EvidenceSpan

```json
{
  "evidence_id": "span_xxx",
  "document_version_id": "docver_xxx",
  "page": 18,
  "section_path": ["3", "2"],
  "block_id": "blk_xxx",
  "bbox": null,
  "text": "原文片段",
  "text_hash": "sha256..."
}
```

规则：

- `evidence_id` 是 trace 的唯一入口。
- P0 必须支持文档、版本、章节、页码、原文追溯。
- bbox 可为空，但字段必须保留。

### 6.7 Chunk

```json
{
  "chunk_id": "chunk_xxx",
  "document_version_id": "docver_xxx",
  "section_path": ["3", "2"],
  "page_start": 18,
  "page_end": 19,
  "text": "...",
  "evidence_ids": ["span_xxx"],
  "embedding_id": null,
  "metadata": {
    "document_id": "doc_xxx",
    "document_title": "Diagnostic SPEC",
    "source_type": "internal_spec"
  }
}
```

### 6.8 文件落盘格式

每个文档版本：

```text
processed/<document_slug>/<document_version_id>/
  canonical-document.json
  chunks.jsonl
```

`canonical-document.json` 包含：

```text
document
document_version
sections
blocks
evidence_spans
parse_report
```

`chunks.jsonl` 每行一个 Chunk。

## 7. Chunking 详细设计

### 7.1 目标

Chunk 用于检索和 Context Pack 组装。Chunk 不是任意长度文本片段，必须保留结构和证据。

### 7.2 切分策略

P0 策略：

1. 按 Section 聚合 blocks。
2. 超过 `max_chunk_chars` 时切分。
3. 切分时保留 `overlap_chars`。
4. section 变化时 flush，不跨章节强行拼接。
5. 每个 chunk 记录所有 evidence_ids。

默认参数：

```text
max_chunk_chars = 1600
overlap_chars = 160
```

P1 增强：

1. 表格不切散。
2. API 签名和 Arguments/Returns 不切散。
3. Errors/Safety/Caveats 等高价值章节单独成块或强绑定。
4. 按 document_family 使用不同 chunk profile。

## 8. 质量 Gate 详细设计

### 8.1 输入

```text
processed_dir
canonical-document.json
chunks.jsonl
parse_report.quality_report
```

### 8.2 输出

`parse-quality-summary.json`：

```json
{
  "processed_document_count": 2,
  "failed_input_count": 0,
  "allowed_document_count": 1,
  "blocked_document_count": 1,
  "status_counts": {},
  "documents": []
}
```

### 8.3 Gate 规则

允许进入 Context Pack：

```text
quality_status in {ok, recovered_by_fallback}
and quality_score >= 40 if quality_score exists
and chunks.jsonl exists
```

否则：

```text
allowed_for_context_pack = false
gate_reasons = [...]
```

### 8.4 检索时处理

检索默认只使用 `allowed_for_context_pack=true` 的文档。

只有当没有任何 allowed 文档时，才允许回退到 blocked 文档，并且必须在 Context Pack 中带 warning。

## 9. 索引设计

### 9.1 索引类型

| 索引 | 阶段 | 用途 |
|---|---:|---|
| 元数据索引 | P0 | project、module、supplier、version 过滤 |
| Lexical/BM25/FTS | P0 | 精确符号、错误码、条款、关键词 |
| Vector | P1 | 语义召回 |
| Graph Index | P2 | 实体关系、多跳、影响分析 |

### 9.2 P0 检索实现

当前 P0 可以使用 `chunks.jsonl` + 程序化 lexical retrieval。

输入：

```text
processed_dir
query
top_k
per_document_limit
```

输出：

```text
RetrievedChunk[]
```

### 9.3 P1 Hybrid Retrieval

目标链路：

```text
query
  -> metadata filter
  -> BM25/FTS retrieve
  -> vector retrieve
  -> RRF merge
  -> rule boost / penalty
  -> dedupe
  -> quality gate
```

规则：

- 精确命中 API 名、错误码、标准条款号时提权。
- 目录、索引、附录目录页降权。
- 文档版本匹配时提权。
- 同一文档超过 `per_document_limit` 时截断。

## 10. Retrieval Engine 详细设计

### 10.1 输入契约

```json
{
  "processed_dir": "C:/runs/processed",
  "query": "重要数据出境有什么限制？",
  "top_k": 8,
  "per_document_limit": 2,
  "filters": {
    "project": "ProjectA",
    "module": "diagnostics",
    "supplier": "Bosch",
    "document_version": "v1"
  }
}
```

P0 已实现 `processed_dir/query/top_k/per_document_limit`。`filters` 是 P1。

### 10.2 RetrievedChunk

```json
{
  "chunk_id": "chunk_xxx",
  "document_version_id": "docver_xxx",
  "document_title": "Diagnostic SPEC",
  "source_type": "internal_spec",
  "source_path": "C:/path/to/docs/spec.docx",
  "section_path": ["3", "2"],
  "section_titles": ["DTC 状态同步"],
  "page_start": 18,
  "page_end": 19,
  "text": "...",
  "evidence_ids": ["span_xxx"],
  "score": 12.34,
  "matched_clauses": ["DTC 状态"],
  "quality_status": "ok",
  "quality_score": 96.0,
  "allowed_for_context_pack": true,
  "quality_gate_reasons": [],
  "warnings": []
}
```

### 10.3 错误处理

| 场景 | 错误 |
|---|---|
| `processed_dir` 不存在 | 404 / FileNotFoundError |
| query 为空 | 400 / ValueError |
| top_k <= 0 | 400 / ValueError |
| 无 chunks.jsonl | 400 / ValueError |
| 只有低质量文档 | 200，但 Context Pack 带 warning |

## 11. Context Pack 详细设计

### 11.1 Context Pack Result

P0 输出：

```json
{
  "query": "...",
  "normalized_query": "...",
  "processed_dir": "...",
  "chunk_count": 3,
  "document_count": 2,
  "sections": [],
  "selected_chunks": []
}
```

同时输出 markdown：

```text
# Context Pack
...
## Evidence Appendix
...
```

### 11.2 Sections

`sections[]` 是面向 Agent 的结构化摘要。建议字段：

```json
{
  "title": "Architecture Decision",
  "items": [
    {
      "evidence_number": 1,
      "document_title": "...",
      "summary": "...",
      "section_titles": [],
      "matched_clauses": [],
      "chunk": {}
    }
  ]
}
```

### 11.3 Task Type 映射

P0 可以先用 query 自动分类。P1 增加显式 `task_type`。

| task_type | 必须优先返回 |
|---|---|
| `question_answer` | 结论证据、章节、页码 |
| `code_change` | 接口、约束、风险、测试项 |
| `code_review` | checklist、限制、风险、证据 |
| `bug_analysis` | 现象相关约束、错误码、配置、影响范围 |
| `design_check` | 需求、设计约束、供应商限制 |
| `impact_analysis` | 关系扩展、影响模块、测试项 |
| `test_design` | 需求、约束、验证方法、覆盖点 |

### 11.4 输出规则

1. 必须包含 evidence appendix。
2. 必须返回文档标题、版本、章节、页码。
3. 低质量证据必须显示 warning。
4. 不允许生成没有证据支撑的强结论。
5. 多版本冲突时必须提示，不得静默合并。

## 12. Evidence Trace 详细设计

### 12.1 输入

```text
processed_dir
evidence_id
```

### 12.2 输出

```json
{
  "evidence_id": "span_xxx",
  "document_id": "doc_xxx",
  "document_title": "Diagnostic SPEC",
  "document_version_id": "docver_xxx",
  "document_version": "v1",
  "source_type": "internal_spec",
  "source_path": "C:/path/to/docs/spec.docx",
  "created_at": "2026-06-09T00:00:00Z",
  "page": 18,
  "section_path": ["3", "2"],
  "section_titles": ["DTC 状态同步"],
  "block_id": "blk_xxx",
  "text": "原文片段",
  "bbox": null,
  "chunk_references": []
}
```

### 12.3 错误处理

| 场景 | 处理 |
|---|---|
| evidence_id 为空 | 400 |
| processed_dir 不存在 | 404 |
| evidence_id 找不到 | 404 |

## 13. Core API 详细设计

### 13.1 已实现接口 P0

```text
GET  /health
GET  /api/runtime-dependencies
POST /api/document-inventory
POST /api/ingest-manifest
POST /api/context-pack
POST /api/search
POST /api/gap-report
GET  /api/evidence/{evidence_id}
GET  /api/parse-quality-summary
```

### 13.2 POST /api/context-pack

Request：

```json
{
  "processed_dir": "C:/runs/processed",
  "query": "重要数据出境有什么限制？",
  "top_k": 8,
  "per_document_limit": 2
}
```

Response：

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

### 13.3 POST /api/search

Request 同 `/api/context-pack`。

Response：

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

### 13.4 GET /api/evidence/{evidence_id}

Request：

```text
GET /api/evidence/span_xxx?processed_dir=C:/runs/processed
```

Response：

```json
{
  "data": {
    "evidence_id": "span_xxx",
    "document_title": "...",
    "document_version": "v1",
    "page": 18,
    "section_titles": [],
    "text": "..."
  }
}
```

### 13.5 POST /api/document-inventory

Request：

```json
{
  "root_dirs": ["C:/path/to/docs"],
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

Response：

```json
{
  "data": {
    "document_count": 10,
    "skipped_count": 2,
    "documents": [],
    "skipped": [],
    "markdown": "..."
  }
}
```

### 13.6 POST /api/ingest-manifest

Request：

```json
{
  "manifest_path": "C:/runs/raw-docs-sample-manifest.csv",
  "out_dir": "C:/runs/processed",
  "project_root": "C:/path/to/repo",
  "max_chunk_chars": 1600,
  "overlap_chars": 160,
  "fail_fast": false,
  "incremental": true
}
```

Response：

```json
{
  "data": {
    "processed_count": 8,
    "skipped_count": 1,
    "failed_count": 1,
    "results": [],
    "skipped": [],
    "failed": []
  }
}
```

### 13.7 P1/P2 规划接口

```text
POST /api/query
GET  /api/status
GET  /api/documents
GET  /api/documents/{document_id}
GET  /api/documents/{document_id}/versions
GET  /api/entities/{entity_id}
GET  /api/entities/{entity_id}/related
POST /api/impact-analysis
POST /api/review/items/{item_id}/decision
POST /api/document-version-diff
```

## 14. CLI 详细设计

### 14.1 P0 命令

当前 CLI 子命令：

```text
inventory
file
manifest
context-pack
gap-report
parse-quality-summary
dependency-check
prepare-eval-run
prepare-eval-execution-pack
prepare-eval-review-pack
record-eval-output
record-eval-review-decision
score-eval-run
check-eval-business-readiness
eval-run-status
```

### 14.2 Agent 本地入口命令规划

P1 收敛为面向 Agent 的命令名：

```text
agent-knowledge query
agent-knowledge search
agent-knowledge context-pack
agent-knowledge trace
agent-knowledge status
```

说明：

- CLI 是 Agent 调用边界或调试入口，不是最终给普通用户手敲的主界面。
- CLI 默认输出 JSON。
- `--format markdown` 只用于人工调试。

## 15. Bot Adapter 详细设计

### 15.1 飞书机器人时序

```text
飞书群消息
  -> Feishu webhook
  -> 验签/鉴权
  -> 提取 user/group/message
  -> 构造 Core 请求
  -> Core /api/context-pack 或 /api/search
  -> 格式化群回复
  -> 调飞书 reply API
```

### 15.2 Bot Request 内部对象

```json
{
  "platform": "feishu",
  "group_id": "oc_xxx",
  "user_id": "ou_xxx",
  "message_id": "om_xxx",
  "text": "GB/T 44464 里重要数据出境有什么限制？",
  "filters": {
    "project": "",
    "supplier": "",
    "document_version": ""
  }
}
```

### 15.3 群回复格式

```text
结论：
...

关键依据：
1. ...
2. ...

证据：
- 文档：...
- 版本：...
- 页码：...
- 章节：...

注意：
...
```

### 15.4 LLM 策略

P0 不依赖 LLM：

```text
Core 检索 + 模板回复
```

P1 可选服务端 LLM：

```text
Core evidence -> LLM 摘要/压缩 -> 群回复
```

限制：

- LLM 不能绕过 Core 直接读文档。
- LLM 生成内容必须保留 evidence 引用。
- 涉密场景必须走内网模型或关闭 LLM 摘要。

## 16. Agent 本地入口详细设计

### 16.1 目标

Agent 本地入口向 Copilot/Codex/Cursor 等提供 Context Pack，不提供原始文件大包。

### 16.2 本地调用形态

P0/P1 支持：

```text
CLI
local HTTP
SDK
readonly knowledge pack
```

不走 MCP 作为当前产品主路线。

### 16.3 本地 HTTP

```text
POST /context-pack
POST /search
GET  /trace/{evidence_id}
GET  /status
```

本地 HTTP 可直接代理中央 Core，也可以读取本地 knowledge pack。

### 16.4 Knowledge Pack

本地分发包：

```text
knowledge-pack/
  manifest.json
  documents.jsonl
  document_versions.jsonl
  sections.jsonl
  blocks.jsonl
  evidence.jsonl
  chunks.jsonl
  entities.jsonl
  relations.jsonl
  fts.db
  vector.index
  quality-report.json
```

P0 可先使用 `processed/` 目录作为 knowledge pack 原型。

P1 再固化 pack manifest：

```json
{
  "pack_id": "pack_xxx",
  "generated_at": "2026-06-09T00:00:00Z",
  "source_dataset": "dept-docs",
  "schema_version": "1.0",
  "document_count": 30,
  "index": {
    "fts": "fts.db",
    "vector": "vector.index"
  }
}
```

## 17. Graph Augmentation 详细设计

### 17.1 阶段定位

Graph Augmentation 是 P2，不是 P0 主链路。

P0 允许轻量关系字段，但不要求图数据库。

### 17.2 图谱实体

```text
Document
DocumentVersion
Section
EvidenceSpan
Module
Interface
API
Service
Signal
Configuration
ErrorCode
Requirement
Constraint
Risk
Platform
Supplier
Version
TestItem
DesignDecision
Defect
```

### 17.3 图谱关系

```text
HAS_VERSION
HAS_SECTION
HAS_EVIDENCE
DEFINED_IN
MENTIONED_IN
IMPLEMENTS
DEPENDS_ON
CALLS
CONSTRAINS
AFFECTS
VERIFIES
REPLACES
CONFLICTS_WITH
VALID_FOR_VERSION
INVALIDATED_BY
SUPPORTED_BY_EVIDENCE
```

### 17.4 在线增强流程

```text
retrieved chunks
  -> extract linked entities
  -> expand 1-hop / 2-hop by allowlisted relation types
  -> fetch evidence for expanded facts
  -> merge into Context Pack related_entities / related_relations
```

规则：

- 不返回没有 evidence 的裸关系。
- 默认只扩 1 跳。
- impact_analysis 可扩 2 跳。
- 版本不匹配的关系必须降权或提示冲突。

## 18. Governance 详细设计

### 18.1 审核对象

```text
candidate_entity
candidate_relation
version_applicability
conflict
low_quality_evidence
invalidated_fact
```

### 18.2 状态机

```text
extracted
  -> pending_review
  -> approved
  -> corrected
  -> superseded
  -> invalidated

pending_review
  -> rejected
```

### 18.3 审核记录

```json
{
  "review_id": "review_xxx",
  "target_type": "relation",
  "target_id": "rel_xxx",
  "decision": "approved",
  "reviewer": "checker",
  "comment": "...",
  "created_at": "..."
}
```

P0 不做审核台，但数据模型和接口必须预留审核状态字段。

## 19. 权限与审计

### 19.1 权限对象

```text
user
group
project
document
document_version
knowledge_pack
```

### 19.2 操作权限

```text
document:upload
document:read
document:parse
knowledge:query
entity:review
relation:review
version:invalidate
admin:manage
```

### 19.3 审计日志

```json
{
  "event_id": "audit_xxx",
  "actor": "user_xxx",
  "action": "knowledge.query",
  "target": "context_pack",
  "request_id": "req_xxx",
  "evidence_ids": [],
  "created_at": "..."
}
```

P0 至少记录 eval run 和 API 调用日志。P2 再做完整审计台。

## 20. Eval Harness 详细设计

### 20.1 对比对象

```text
baseline：Agent 直接读原始文档
context_pack：Agent 使用 Context Pack
```

### 20.2 评测用例

```json
{
  "task_id": "task-001",
  "question": "...",
  "expected_evidence": [],
  "documents": [],
  "scoring_notes": "..."
}
```

### 20.3 评价指标

```text
answer_correct
evidence_correct
missing_key_constraints
hallucination_count
human_fix_count
token_input
token_output
elapsed_minutes
winner
```

### 20.4 Readiness Gate

正式业务证据必须满足：

- baseline 和 context_pack 都有真实 Agent 输出。
- Agent/model 身份不是 placeholder。
- 已人工 review。
- 评分表完整。
- 不包含 controlled local rehearsal 输出。

## 21. 错误处理规范

### 21.1 API 错误响应

```json
{
  "detail": "Processed directory does not exist: ..."
}
```

P1 可统一成：

```json
{
  "error": {
    "code": "processed_dir_not_found",
    "message": "...",
    "request_id": "req_xxx"
  }
}
```

### 21.2 错误码建议

```text
invalid_request
processed_dir_not_found
manifest_not_found
document_not_found
unsupported_document_format
parse_failed
no_chunks_found
evidence_not_found
quality_gate_blocked
permission_denied
version_conflict
```

## 22. 性能与容量假设

### 22.1 阶段 1

```text
文档量：10-30 份
chunk 数：1k-20k
并发：低
部署：单机或轻量内网服务
```

### 22.2 阶段 2

```text
文档量：100-1000+
chunk 数：10万+
并发：部门级
部署：中心服务 + worker + 独立索引
```

### 22.3 性能目标

P0：

- context-pack 查询小于 5 秒。
- trace 查询小于 1 秒。
- 10-30 份文档 ingest 可在可接受时间内离线完成。

P1/P2：

- 索引增量更新。
- 查询缓存。
- 常用问题缓存。

## 23. 阶段落地任务

### 23.1 P0 必须完成

```text
1. manifest 字段与版本字段稳定
2. 文档解析到 Canonical Model
3. chunks.jsonl 生成
4. parse quality summary
5. lexical retrieval
6. context_pack.md/json
7. trace evidence
8. Core API
9. 飞书机器人 demo
10. Agent 本地入口 demo
11. baseline vs context_pack eval
```

### 23.2 P1 增强

```text
1. filters 支持 project/module/supplier/version
2. BM25/FTS 索引
3. 向量索引
4. RRF 融合
5. task_type 显式输入
6. knowledge pack 规范固化
7. bot 权限和日志
```

### 23.3 P2 后续

```text
1. 实体抽取
2. 关系抽取
3. 审核台
4. Neo4j/图谱存储
5. 版本失效
6. 影响分析
7. 实体卡片
8. 多数据源接入
```

## 24. 当前实现映射

| 设计模块 | 当前文件 |
|---|---|
| Document Inventory | `src/agent_knowledge_hub/inventory.py` |
| Ingestion | `src/agent_knowledge_hub/pipeline.py`, `incremental.py` |
| Parser Adapter | `src/agent_knowledge_hub/parsers.py` |
| Canonical Builder | `src/agent_knowledge_hub/builder.py` |
| Chunk Builder | `src/agent_knowledge_hub/chunker.py` |
| Quality Gate | `src/agent_knowledge_hub/quality.py` |
| Retrieval / Context Pack | `src/agent_knowledge_hub/retrieval.py` |
| Core API | `src/agent_knowledge_hub/service.py` |
| CLI | `src/agent_knowledge_hub/cli.py` |
| Eval Harness | `src/agent_knowledge_hub/eval_setup.py` |

当前已完成：

- P0 文档解析链路原型。
- P0 processed 目录结构。
- P0 lexical retrieval 和 Context Pack 原型。
- P0 evidence trace。
- P0 Core API。
- P0 eval harness。

当前未完成：

- 正式飞书机器人 adapter。
- 正式 Agent 本地入口产品化。
- P1 BM25/FTS + vector hybrid。
- P1 knowledge pack 规范固化。
- P2 图谱、审核、版本失效、影响分析。

## 25. 评审重点

评审本文时重点看：

1. Manifest 字段是否足够支撑真实文档接入。
2. DocumentVersion 是否贯穿检索、Context Pack 和 trace。
3. Context Pack 输出是否足够给 Agent 使用。
4. Bot adapter 是否只做入口，不重复实现 Core。
5. P0/P1/P2 边界是否合理。
6. 当前实现是否应该优先补飞书机器人，还是先补 hybrid retrieval。
