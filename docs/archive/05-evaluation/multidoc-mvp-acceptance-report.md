# 25 多文档 MVP 验收报告

## 1. 验收目标

本次验收验证第一版 Agent Knowledge Hub 是否已经具备从多格式工程文档到 Agent Context Pack 的端到端链路：

```text
raw docs
  -> ingest
  -> canonical-document.json / chunks.jsonl
  -> parse-quality-summary
  -> context pack
  -> evidence trace
  -> REST / MCP smoke
```

本次验收不证明知识图谱已经完成，也不证明 Context Pack 已经优于直接给 Agent 文件。它只证明第一版多文档知识服务原型可以被稳定调用，并且能暴露质量、证据和边界。

## 2. 可复跑命令

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-multidoc-mvp-e2e.ps1" -KeepArtifacts
```

最近一次产物：

```text
.\agent-artifacts\knowledge-hub-multidoc-mvp
```

摘要文件：

```text
.\agent-artifacts\knowledge-hub-multidoc-mvp\mvp-e2e-summary.json
```

## 3. 输入文档

| Title | Format | Parser | Status | Score | Gate |
| --- | --- | --- | --- | ---: | --- |
| GBT 44464-2024 vehicle data requirements | pdf | pypdf | low_quality | 56.22 | blocked |
| Internal vehicle data SPEC | markdown | stdlib-markdown-block-parser | ok | 100.00 | allowed |
| Vehicle data architecture | html | stdlib-html-parser | ok | 100.00 | allowed |
| Important data review checklist | text | stdlib-text-block-parser | ok | 100.00 | allowed |
| Supplier vehicle data interface | docx | python-docx | ok | 100.00 | allowed |
| Legacy supplier DOC | doc | unsupported | unsupported | - | blocked |

本次真实 PDF：

```text
C:\path\to\docs\GBT 44464-2024 汽车数据通用要求.pdf
```

## 4. 质量分布

```text
processed_count = 5
failed_count = 1
allowed_document_count = 4
blocked_document_count = 2
status_counts.ok = 4
status_counts.low_quality = 1
status_counts.unsupported = 1
```

GBT PDF 在本次运行中触发：

```text
quality_status = low_quality
allowed_for_context_pack = false
warning_count = 3
reason_codes = ["mojibake_suspect_ratio_high"]
```

原因是当前 E2E 环境没有 OCR 依赖，PDF 只能使用 `pypdf` 文本层，存在中文乱码。系统没有静默采信，而是把它降权并返回 warning。

## 5. 三个查询场景

| Scenario | Selected Chunks | Selected Documents | Missing Reference Items | Trace |
| --- | ---: | ---: | ---: | --- |
| constraint-query | 5 | 4 | 1 | `traces\constraint-query-trace.json` |
| impact-analysis | 5 | 4 | 0 | `traces\impact-analysis-trace.json` |
| test-review-checklist | 5 | 4 | 0 | `traces\test-review-checklist-trace.json` |

每个场景输出：

```text
context_pack.md
context_pack.json
context_pack-summary.json
gap-report/context_pack_gap_report.md
gap-report/context_pack_gap_report.json
```

每个 Context Pack 的 Evidence 都带：

```text
quality_status
quality_score
allowed_for_context_pack
quality_gate_reasons
warnings
source_path
evidence_ids
section_path
section_titles
page_start/page_end
```

## 6. Agent 调用入口

REST API 当前支持：

```text
GET  /health
POST /api/context-pack
POST /api/search
POST /api/gap-report
GET  /api/evidence/{evidence_id}
GET  /api/parse-quality-summary
```

Remote MCP 当前支持：

```text
get_context_pack
search_knowledge
trace_evidence
get_parse_quality_summary
```

已通过 smoke：

```text
scripts/test-parse-quality-summary-smoke.ps1
scripts/test-auto-context-pack-smoke.ps1
scripts/test-context-pack-mcp-smoke.ps1
```

## 7. 当前结论

第一版多文档 Agent Knowledge Hub 原型已经具备：

- 多格式接入：PDF、Markdown、HTML、TXT、DOCX。
- 统一模型：Document、DocumentVersion、Section、Block、EvidenceSpan、Chunk。
- 质量总览：`parse-quality-summary.json/.md`。
- 多文档 Context Pack：跨文档检索、质量降权、Evidence 顺序一致。
- Agent 入口：REST API 和 Remote MCP。
- 证据追溯：Context Pack evidence id 可 trace 回文档、版本、section、page/source。

## 8. 仍然不能夸大的部分

当前还不能说：

- 已经完成知识图谱。
- 已经证明 Context Pack 一定优于直接给 Agent 文件。
- 已经解决复杂 PDF 表格、多栏阅读顺序和版面还原。
- 已经具备生产权限、租户隔离、审计和部署能力。

当前最关键的技术边界：

- PDF OCR fallback 依赖 `pymupdf`、`rapidocr`、`onnxruntime`。缺依赖时系统会返回 `low_quality` 和 warning。
- Context Pack gate 当前默认排除 `allowed_for_context_pack=false` 的文档；只有没有任何 allowed 候选时才回退到 blocked 文档。
- 本次 `constraint-query` 缺失 `重要数据出境`，直接原因是 GBT PDF 在缺 OCR 环境下被 gate 拦截，内部 SPEC 中没有充分覆盖该 reference。
- retrieval 仍然是 lexical / rule-biased，不是 embedding / hybrid retrieval。

## 9. 下一步

下一步应该围绕真实工程价值继续收敛：

1. 给 E2E 环境补齐 OCR 依赖，复跑 GBT PDF，确认 `recovered_by_fallback` 路径稳定。
2. 接入 5-10 份真实供应商和内部文档，替换当前部分测试夹具。
3. 做 baseline vs Context Pack 对照实验，量化准确率、遗漏率、token 和耗时。
4. 再决定是否进入知识图谱、人工审核台和版本失效建设。
