# 24 文档接入解析程序说明

## 1. 程序定位

第一版程序负责把工程文档加工成 Agent 后续可检索、可追溯、可组装 Context Pack 的基础数据。

当前程序做：

```text
PDF / Markdown / HTML / TXT / DOCX
  -> document inventory
  -> sample manifest
  -> 解析 blocks
  -> 统一 Document / DocumentVersion / Section / Block / EvidenceSpan
  -> 生成 section-aware chunks
  -> 输出 canonical-document.json 和 chunks.jsonl
```

当前程序本身不做：

```text
embedding
全文索引
向量索引
知识图谱
MCP/API 服务
```

这些是下一层能力，输入就是本程序产出的 `chunks.jsonl` 和 `canonical-document.json`。

但仓库当前已经补上了紧邻下一层的第一版能力：

```text
processed/chunks
  -> lexical retrieval
  -> dedupe / rerank
  -> Context Pack markdown/json
  -> gap report
```

也就是说，接入解析程序和 Auto Context Pack Engine 现在已经能串成一条可运行链路。

## 2. 程序和 Agent 的分工

程序负责稳定结构化：

- 本地候选文档发现。
- 文档读取。
- 格式解析。
- 章节、段落、表格识别。
- 页码保留，PDF 场景下可用。
- 原文证据 span。
- chunk 切分。
- JSON/JSONL 输出。

Agent/LLM 后续负责语义加工：

- 摘要。
- 约束提取。
- 接口、模块、配置项识别。
- checklist 生成。
- Context Pack 组装。

当前第一版里，这个分工已经部分落地为“程序先组装候选 Context Pack，Agent 再消费”：

- 程序负责从 `processed/` 里检索和拼装证据块。
- Agent 负责基于 `context_pack.md` / `context_pack.json` 生成最终回答、设计说明、review 结论或测试建议。

## 3. 运行单个文件

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\ingest-documents.ps1" `
  -FilePath ".\samples\raw\example.md" `
  -Title "Example SPEC" `
  -SourceType "内部需求/SPEC 文档" `
  -Owner "检查者" `
  -DocumentVersion "v1"
```

默认输出目录：

```text
.\data\processed\
```

## 4. 发现本地候选文档

可以先让程序在显式指定目录下发现可处理文档，并生成 inventory 和样本 manifest：

```powershell
python -m agent_knowledge_hub.cli inventory `
  --root-dir "C:\path\to\docs" `
  --output-dir ".\agent-artifacts\inventory-demo" `
  --max-files 30 `
  --max-file-mb 100 `
  --sample-size 8 `
  --owner "checker" `
  --project "vehicle-data"
```

输出：

```text
document-inventory.json
document-inventory.md
raw-docs-sample-manifest.csv
```

这个步骤只读取文件元数据、大小和 hash，不移动源文件。

## 5. 按 manifest 批量运行

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\ingest-documents.ps1" `
  -ManifestPath ".\samples\sample-manifest.csv"
```

没有传 `-ManifestPath` 时，默认读取：

```text
.\samples\sample-manifest.csv
```

manifest 中 `file_path` 仍为 `待提供` 的行会被跳过，不会伪造解析结果。

若要启用 hash 增量摄取，可直接用 CLI：

```powershell
python -m agent_knowledge_hub.cli manifest `
  --manifest-path "C:\path\to\raw-docs-sample-manifest.csv" `
  --out-dir "C:\path\to\processed" `
  --project-root "." `
  --incremental
```

增量模式会输出：

```text
ingest-run-summary.json
ingest-state.json
```

未变化文档会按 `content_hash` 跳过，变化文档会重新解析。

## 6. 输出结构

每个文档版本输出：

```text
data/processed/
  <document-title>/
    <document-version-id>/
      canonical-document.json
      chunks.jsonl
```

批量运行还会输出：

```text
data/processed/ingest-summary.json
data/processed/ingest-run-summary.json
data/processed/ingest-state.json
```

`canonical-document.json` 中的 `parse_report.quality_report` 会记录解析质量评分，供后续检索、验收和排障使用。当前字段包括：

```json
{
  "score": 74.22,
  "status": "recovered_by_fallback",
  "fallback_used": true,
  "fallback_parser": "rapidocr",
  "reason_codes": ["mojibake_suspect_ratio_high"],
  "metrics": {
    "char_count": 25223,
    "cjk_count": 10827,
    "mojibake_suspect_count": 1896,
    "mojibake_per_1k_cjk": 175.12,
    "latin1_mojibake_ratio": 0.0
  }
}
```

非 PDF 文档也会生成基础质量报告；PDF 文档会额外记录乱码嫌疑、OCR fallback 和 fallback parser 信息。

可以对一个 `processed/` 目录生成全局质量总览：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\generate-parse-quality-summary.ps1" `
  -ProcessedDir ".\data\processed" `
  -OutputDir ".\data\parse-quality-summary"
```

输出：

```text
parse-quality-summary.json
parse-quality-summary.md
```

质量总览会给每份文档生成 Context Pack gate：

- `ok`、`recovered_by_fallback`：允许进入 Context Pack。
- `low_quality`、`unsupported`、`ocr_unavailable`、`failed`：标记为 blocked。
- 质量分低于 40 或缺失 `chunks.jsonl`：标记为 blocked。

注意：当前 retrieval 层默认只从 `allowed_for_context_pack=true` 的文档里组装 Context Pack。只有整个 `processed/` 没有任何 allowed 候选时，才会回退到 blocked 文档。回退或质量异常时，证据会带：

```text
quality_status
quality_score
allowed_for_context_pack
quality_gate_reasons
warnings
```

Agent 消费 Context Pack 时必须读取这些字段，不能把低质量证据当成同等可信正文证据。

## 7. 当前格式支持

已支持：

- Markdown：`.md`, `.markdown`
- HTML：`.html`, `.htm`
- Text：`.txt`
- PDF：`.pdf`，默认依赖 `pypdf`
- DOCX：`.docx`，依赖 `python-docx`

PDF 解析链路现在是：

```text
pypdf 文本层抽取
  -> PDF 文本质量评估
  -> 文本可信则直接进入统一模型
  -> 文本过短/疑似乱码则尝试 RapidOCR 兜底
  -> OCR 结果按页生成 blocks，保留 page_start/page_end
```

OCR 是可选能力，不是基础依赖。若未安装 OCR 依赖，程序不会静默失败，而是返回 pypdf 文本层结果，并在 `parse_report.warnings` 中写入：

```text
pdf_text_quality_low_ocr_unavailable
pdf_ocr_fallback_failed: ...
```

若 OCR 工具调用成功但没有识别出可用正文，也会回退到 pypdf 文本层结果，并写入：

```text
pdf_text_quality_low_ocr_unusable
no_ocr_text_blocks_extracted
```

建议依赖：

```powershell
pip install -r requirements.txt
pip install -r requirements-ocr.txt
```

也可以只安装基础依赖：

```powershell
pip install -r requirements.txt
```

安装基础依赖后，Markdown/HTML/TXT/PDF 文本层/DOCX 可用；低质量 PDF 的 OCR fallback 需要额外安装 `requirements-ocr.txt`。

运行时依赖自检：

```powershell
$env:PYTHONPATH = ".\src"
python -m agent_knowledge_hub.cli dependency-check
```

自检会输出 `plain_text`、`pdf_text`、`docx`、`pdf_ocr` 四类能力是否 ready。长跑脚本也会自动生成：

```text
dependencies/runtime-dependencies.json
dependencies/runtime-dependencies.md
```

注意：Windows 上 PowerShell 7 和 Windows PowerShell 可能解析到不同的 `python.exe`。长跑脚本支持显式指定解释器：

```powershell
$pythonExe = (Get-Command python).Definition
powershell -ExecutionPolicy Bypass -File ".\scripts\run-overnight-knowledge-hub.ps1" `
  -PythonExe $pythonExe
```

若未安装 `python-docx`，处理 DOCX 时会明确报错。若未安装 `pymupdf` / `rapidocr` / `onnxruntime`，只有低质量 PDF 文本触发 OCR fallback 时才会产生 warning。

暂不支持：

- `.doc`
- Excel
- 复杂版面还原
- 表格结构还原

## 8. 本地 PDF OCR fallback 验证

已用本地候选文档验证 PDF 文本质量门禁和 RapidOCR fallback：

```text
C:\path\to\docs\GBT 44464-2024 汽车数据通用要求.pdf
```

验证结果：

- 原始 `pypdf` 文本层存在明显中文乱码。
- 程序自动识别 `mojibake_suspect_ratio_high`。
- 解析结果自动切换为 `parser_name = pypdf+rapidocr`。
- `parse_report.quality_report.status = recovered_by_fallback`。
- `parse_report.quality_report.score = 74.22`。
- `parse_report.quality_report.fallback_used = true`，`fallback_parser = rapidocr`。
- `page_count = 13`，`block_count = 26`，`has_page_numbers = true`。
- `parse_report.warnings` 包含 `pdf_text_quality_low_using_ocr`。
- 下游 Context Pack 的 `selected_chunks[0]` 和 markdown `Evidence 1` 都指向第 7 页正文约束，而不是第 13 页附录试验方法。
- 第 1 条证据的 `section_titles = ["Page 7"]`，retrieval 会裁掉 OCR/chunker 粘在正文 chunk 尾部的 `附录A` 噪声。
- 第 1 条证据包含 `6.3重要数据存储`、`6.5重要数据传输`、`6.6重要数据删除`、`6.7重要数据出境`。
- 第 1 条证据包含 `车辆应采取安全访问技术`、`车辆应对向车外发送的重要数据实施保密性保护措施`、`被删除的重要数据应不可检索且不可访问`、`车辆不应直接向境外传输重要数据`。
- 第 13 页 `个人信息和重要数据处理试验方法` 仍可作为补充证据进入 Context Pack，但因属于附录试验方法，排序低于正文要求。

本次验证说明 OCR fallback 能救回部分中文乱码 PDF，但不代表已经解决复杂表格结构、多栏阅读顺序和版面还原。

## 9. 下一步接口

下一层程序应读取：

```text
chunks.jsonl
canonical-document.json
```

并继续做：

```text
全文索引
向量索引
REST API / Remote MCP
```

其中 `Context Pack 检索组装` 这一层当前已经有可运行的 v1：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\generate-auto-context-pack.ps1" `
  -ProcessedDir ".\data\processed" `
  -QuestionPath "C:\path\to\question.md" `
  -ReferenceContextPackPath "C:\path\to\manual-context-pack.md" `
  -OutputDir "C:\path\to\auto-bundle" `
  -TopK 10 `
  -PerDocumentLimit 3
```

输出：

```text
context_pack.md
context_pack.json
context_pack-summary.json
gap-report/context_pack_gap_report.md
gap-report/context_pack_gap_report.json
```

## 10. REST API / Remote MCP

当前 REST API 已经能直接给 Agent 返回 Context Pack、搜索结果、证据追溯和解析质量总览。

REST endpoint：

```text
GET  /health
POST /api/document-inventory
POST /api/ingest-manifest
POST /api/context-pack
POST /api/search
POST /api/gap-report
GET  /api/evidence/{evidence_id}
GET  /api/parse-quality-summary
```

Remote MCP tools：

```text
get_context_pack
search_knowledge
trace_evidence
get_parse_quality_summary
get_document_inventory
```

Context Pack 返回结构里，`selected_chunks[]` 和 `sections[].items[]` 都包含：

```text
document_title
source_path
section_path
section_titles
page_start/page_end
evidence_ids
matched_clauses
quality_status
quality_score
allowed_for_context_pack
quality_gate_reasons
warnings
```

## 11. 一键长跑验证

当前新增了一条 overnight pipeline，用于一次跑通：

```text
document inventory
  -> raw-docs-sample-manifest.csv
  -> incremental ingest
  -> parse-quality-summary
  -> 3 个 Context Pack 场景
  -> evidence trace
  -> eval-report
```

可复跑入口：

```powershell
$pythonExe = (Get-Command python).Definition
powershell -ExecutionPolicy Bypass -File ".\scripts\run-overnight-knowledge-hub.ps1" `
  -PythonExe $pythonExe `
  -RootDir "C:\path\to\docs" `
  -MaxFiles 30 `
  -SampleSize 8 `
  -IncludeKeyword "gbt","openclaw","spec","api" `
  -ExcludeKeyword "账单","账号","credit","password"
```

真实个人目录通常会混入账单、账号、重复下载件和非工程资料。长跑脚本支持 `-IncludeKeyword`、`-ExcludeKeyword` 和 `-AllowDuplicateHash`，第一版建议先用关键词过滤生成 inventory，再决定是否进入解析和 Context Pack。

smoke 验证：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-overnight-knowledge-hub-smoke.ps1"
```

artifact 默认写入：

```text
.\agent-artifacts\knowledge-hub-overnight-<timestamp>
```

## 12. 多文档 MVP E2E 验证

当前可复跑入口：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-multidoc-mvp-e2e.ps1" -KeepArtifacts
```

最近一次验收 artifact：

```text
.\agent-artifacts\knowledge-hub-multidoc-mvp
```

本次覆盖：

- `pdf`：`GBT 44464-2024 vehicle data requirements`
- `markdown`：`Internal vehicle data SPEC`
- `html`：`Vehicle data architecture`
- `text`：`Important data review checklist`
- `docx`：`Supplier vehicle data interface`
- `unsupported`：`.doc` 旧版供应商文档

结果：

- processed inputs: 5
- failed inputs: 1
- status counts: `ok = 4`、`low_quality = 1`、`unsupported = 1`
- 3 个场景均生成 Context Pack、gap report 和 evidence trace：
  - `constraint-query`
  - `impact-analysis`
  - `test-review-checklist`

重要边界：

- 当前环境这次运行没有 OCR 依赖，GBT PDF 由 `pypdf` 输出，质量状态为 `low_quality`。
- GBT PDF 被 gate 标记为 `allowed_for_context_pack=false`，本次多文档 Context Pack 默认不再选择它；若要恢复 GBT 正文证据，需要安装 OCR 依赖并让该 PDF 进入 `recovered_by_fallback` 或 `ok`。
- 如果安装 `pymupdf`、`rapidocr`、`onnxruntime`，同一 PDF 可触发 OCR fallback，之前单 PDF 验证中已出现 `recovered_by_fallback`。

## 13. A/B 评测闭环

当前 direct-file vs Context Pack 的正式验收链路已经从“生成 prompt 和初评分”扩展到“真实 Agent 输出 + checker 人工复核 + 业务证据就绪门槛”：

```text
prepare-eval-run
  -> prepare-eval-execution-pack
  -> record-eval-output x baseline/context_pack
  -> score-eval-run
  -> prepare-eval-review-pack
  -> record-eval-review-decision x task
  -> check-eval-business-readiness --require-ready
```

其中：

- `prepare-eval-review-pack` 生成检查者复核包，包含 gold points、required constraints、expected evidence、raw output 状态和 Context Pack evidence preview。
- `record-eval-review-decision` 记录检查者对 baseline/context_pack 的人工结论和人工修正次数。
- `check-eval-business-readiness --require-ready` 用于阻止模拟输出、缺失输出、占位 agent/model、未评分、未复核或 `not_reviewed` 的 run 被当成业务证据。

因此，解析质量和 Context Pack 检索 smoke 只能证明链路可运行；只有真实 Agent 原始输出完成记录、启发式评分完成、checker 复核完成，并通过 readiness gate，才可以讨论 Context Pack 是否真的优于直接给文件。

## 14. 后续缺口

下一阶段真正缺的，是继续增强：

```text
更强的 retrieval / ranking
更细的 gap scoring
OCR/版面/表格解析稳定性
认证、租户隔离和生产部署配置
```
