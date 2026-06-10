# 26 Agent Knowledge Hub 大功能长跑验收

## 1. 本轮目标

本轮目标是把多文档 MVP 推进成一条可长跑的 Agent Knowledge Hub 骨架：

```text
本地工程文档
  -> 文档发现
  -> 样本 manifest
  -> 增量摄取
  -> canonical-document.json / chunks.jsonl
  -> 解析质量总览
  -> Context Pack
  -> evidence trace
  -> REST / MCP
  -> eval report
  -> baseline/context_pack 成对 prompt
```

当前仍然不是完整知识图谱，也不是生产级企业知识库。它验证的是“工程文档能否被加工成 Agent 可消费、可追溯、可质量治理的上下文服务”。

## 2. 新增能力

### 2.1 文档发现

新增 CLI：

```powershell
python -m agent_knowledge_hub.cli inventory `
  --root-dir "C:\path\to\docs" `
  --output-dir "C:\path\to\inventory" `
  --max-files 30 `
  --sample-size 8
```

输出：

```text
document-inventory.json
document-inventory.md
raw-docs-sample-manifest.csv
```

发现范围只包含显式传入的目录。程序会跳过 `.git`、`node_modules`、虚拟环境和明显系统目录，并按扩展名、大小、hash、供应商关键词生成候选清单。

### 2.2 增量摄取

新增 CLI：

```powershell
python -m agent_knowledge_hub.cli manifest `
  --manifest-path "C:\path\to\raw-docs-sample-manifest.csv" `
  --out-dir "C:\path\to\processed" `
  --incremental
```

输出：

```text
ingest-run-summary.json
ingest-state.json
ingest-summary.json
```

`ingest-state.json` 保存每个源文件的 `content_hash`。文件未变化时跳过，文件变化时重新解析。

### 2.3 REST / MCP 入口

REST 新增：

```text
POST /api/document-inventory
POST /api/ingest-manifest
```

MCP 新增：

```text
get_document_inventory
```

MCP 当前保持偏只读：发现文档、查质量、查 Context Pack、查证据。批量摄取这种写入动作优先走脚本或 REST，方便审计。

### 2.4 Overnight Pipeline

新增长跑脚本：

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

长跑入口已经支持 inventory 过滤参数：`-IncludeKeyword`、`-ExcludeKeyword`、`-AllowDuplicateHash`。真实混合目录必须先过滤，否则账单、账号、重复下载文件会进入候选清单，影响安全边界和解析质量判断。

smoke：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-overnight-knowledge-hub-smoke.ps1"
```

artifact：

```text
.\agent-artifacts\knowledge-hub-overnight-<timestamp>
```

包含：

```text
inventory/document-inventory.json
inventory/raw-docs-sample-manifest.csv
processed/ingest-run-summary.json
processed/ingest-state.json
quality/parse-quality-summary.json
context-packs/*/context_pack.json
traces/first-evidence-trace.json
eval/eval-report.json
eval/eval_cases.jsonl
eval-run/agent-prompt-manifest.csv
eval-run/agent-run-log.csv
eval-run/real-agent-execution-plan.json
eval-run/real-agent-execution-guide.md
eval-run/baseline-vs-contextpack-results.csv
eval-run/prompts/
overnight-report.md
```

### 2.5 对照实验准备

新增 CLI：

```powershell
python -m agent_knowledge_hub.cli prepare-eval-run `
  --eval-cases "C:\path\to\eval_cases.jsonl" `
  --processed-dir "C:\path\to\processed" `
  --output-dir "C:\path\to\eval-run" `
  --run-id "run-001"
```

`eval_cases.jsonl` 每行一个任务。baseline prompt 只说明应附加 raw files，不包含 Context Pack；context_pack prompt 只包含生成的 Context Pack。两组 prompt 都不会泄露 `gold_answer_points`、`required_constraints`、`expected_evidence`。

真实 Agent 执行包：

```powershell
python -m agent_knowledge_hub.cli prepare-eval-execution-pack `
  --eval-run-dir "C:\path\to\eval-run" `
  --eval-cases "C:\path\to\eval_cases.jsonl"
```

输出：

```text
real-agent-execution-plan.json
real-agent-execution-guide.md
```

`real-agent-execution-guide.md` 是 A/B 执行清单，逐条列出 baseline/context_pack prompt、`record-eval-output` 记录命令、规划好的 raw output 路径和最终严格评分命令。它不会泄露 `gold_answer_points`、`required_constraints`、`expected_evidence`。

Agent 跑完后，先用 `record-eval-output` 写入原始输出并同步 run log：

```powershell
python -m agent_knowledge_hub.cli record-eval-output `
  --eval-run-dir "C:\path\to\eval-run" `
  --task-id "task-001" `
  --group "baseline" `
  --output-file "C:\path\to\agent-answer.md" `
  --agent "codex" `
  --model "gpt-5.4" `
  --refresh-execution-pack
```

加 `--refresh-execution-pack` 后，会同步刷新 `real-agent-execution-plan.json` / `real-agent-execution-guide.md`，让 pending 数量和每条执行状态保持最新。若执行包里没有保存 `eval_cases` 路径，可额外传 `--eval-cases "C:\path\to\eval_cases.jsonl"`。

所有 baseline/context_pack 输出都记录完后，可执行启发式初评分：

```powershell
python -m agent_knowledge_hub.cli score-eval-run `
  --eval-cases "C:\path\to\eval_cases.jsonl" `
  --eval-run-dir "C:\path\to\eval-run"
```

正式 A/B 验收时建议加严格门禁：

```powershell
python -m agent_knowledge_hub.cli score-eval-run `
  --eval-cases "C:\path\to\eval_cases.jsonl" `
  --eval-run-dir "C:\path\to\eval-run" `
  --require-business-evidence
```

输出：

```text
eval-score-summary.json
eval-score-summary.md
eval-score-details.jsonl
baseline-vs-contextpack-results.csv
agent-run-log.csv
```

`score-eval-run` 按 `gold_answer_points`、`required_constraints`、`expected_evidence` 做可复现的规则初评分。`eval-score-details.jsonl` 逐行记录命中/漏掉的 gold points、required constraints、expected evidence、原始输出路径、Context Pack 路径和 `simulated_output` 标记，便于复核分数。

`eval-score-summary.json` 会给出 `business_evidence_ready` 和 `business_evidence_blockers`。只有没有模拟输出、没有缺失 raw output、baseline/context_pack 成对完成、已评分，并且 `agent-run-log.csv` 里的 `agent` / `model` 不再是占位值时，`business_evidence_ready=true`。`--require-business-evidence` 会在这些条件不满足时返回失败。

启发式评分之后，生成 checker 复核包：

```powershell
python -m agent_knowledge_hub.cli prepare-eval-review-pack `
  --eval-cases "C:\path\to\eval_cases.jsonl" `
  --eval-run-dir "C:\path\to\eval-run"
```

输出：

```text
eval-review-pack.json
eval-review-pack.md
```

`eval-review-pack.md` 面向检查者，不面向执行 Agent。它会展示 gold points、required constraints、expected evidence、baseline/context_pack prompt 路径、raw output 状态、Context Pack evidence preview 和 checker decision 字段。

检查者复核后，记录单个任务的人工结论：

```powershell
python -m agent_knowledge_hub.cli record-eval-review-decision `
  --eval-run-dir "C:\path\to\eval-run" `
  --task-id "task-001" `
  --checker "checker-name" `
  --baseline-answer-correct "partial" `
  --context-pack-answer-correct "yes" `
  --context-pack-retrieval-useful "yes" `
  --winner "context_pack" `
  --baseline-human-fix-count "2" `
  --context-pack-human-fix-count "0" `
  --notes "人工判断说明" `
  --eval-cases "C:\path\to\eval_cases.jsonl"
```

输出/更新：

```text
eval-review-decisions.csv
baseline-vs-contextpack-results.csv
agent-run-log.csv
eval-review-pack.json
eval-review-pack.md
```

若 `baseline-answer-correct` 或 `context-pack-answer-correct` 仍是 `not_reviewed`，run log 会标记为 `review_pending_output`，不能进入业务证据。

最后执行业务证据就绪检查：

```powershell
python -m agent_knowledge_hub.cli check-eval-business-readiness `
  --eval-cases "C:\path\to\eval_cases.jsonl" `
  --eval-run-dir "C:\path\to\eval-run" `
  --require-ready
```

输出：

```text
eval-business-readiness.json
eval-business-readiness.md
```

这一步严格要求真实 raw outputs、真实 agent/model、非模拟输出、非 `controlled_local_run`、启发式评分完成、人工复核完成、没有 `not_reviewed`、所有任务都有完整 baseline/context_pack 成对记录。只有这个 gate 通过，才可以把该 run 当成“Context Pack 是否优于直接给文件”的业务证据。

推荐完整顺序：

```text
prepare-eval-run
  -> prepare-eval-execution-pack
  -> record-eval-output x baseline/context_pack
  -> score-eval-run
  -> prepare-eval-review-pack
  -> record-eval-review-decision x task
  -> check-eval-business-readiness --require-ready
```

它不替代人工评分；overnight pipeline 中的评分阶段使用模拟 raw outputs，只证明评分链路可回归，不证明真实业务收益。模拟输出会在 `agent-run-log.csv`、`eval-score-summary.json` 和 `eval-score-details.jsonl` 中显式标记为 `simulated_smoke_output` / `simulated_output=true`，并让 `business_evidence_ready=false`。真正的业务证据还必须通过 `check-eval-business-readiness --require-ready`。

## 3. 和直接把文件给 Agent 的区别

直接给 Agent 文件的问题：

- 每次任务都重新读，成本和耗时不可控。
- 大 PDF、扫描 PDF、乱码 PDF 进入上下文后，Agent 很难知道哪些内容不可信。
- 多文档时容易混淆版本、来源和证据。
- Agent 输出结论后，很难回到页码、章节、原文 span。
- 无法稳定复用同一套检索、质量 gate 和评测流程。

Agent Knowledge Hub 的区别：

- 先把文档结构化成统一模型。
- 先做解析质量 gate，低质量文档默认不进入 Context Pack。
- Context Pack 返回的是任务相关证据，不是整份文件。
- 每条证据带来源路径、页码、章节、evidence id 和 warning。
- REST/MCP 给不同 Agent 使用同一套上下文服务。
- overnight pipeline 可以持续回归，知道哪一步坏了。

## 4. 当前仍不证明的事

本轮不证明：

- 完整知识图谱已经完成。
- Context Pack 在所有场景都优于直接给文件。
- 复杂 PDF 表格、扫描件、多栏阅读顺序已经解决。
- 已具备生产认证、权限、租户隔离、审计和部署。

当前只证明：

- 多格式文档可以进入统一模型。
- 质量结果可以被汇总和 gate。
- Context Pack 可以跨文档生成并追溯证据。
- REST/MCP 有可调用入口。
- 一条命令可以长跑产出 inventory、ingest、quality、context、trace、eval artifact。
- 可以自动生成 direct-file vs Context Pack 的成对实验材料，但评分仍需真实 Agent 输出和人工/规则评分。

## 5. 验证结果

已通过：

```text
pytest -q tests/test_document_inventory.py tests/test_incremental_ingest.py tests/test_service_api.py tests/test_mcp_server.py
pytest -q tests/test_context_pack_cli.py
pytest -q tests/test_eval_setup.py
powershell -ExecutionPolicy Bypass -File scripts/test-overnight-knowledge-hub-smoke.ps1
```

最终全量验证以本轮最终 `pytest -q` 和 smoke 输出为准。

## 6. 真实本地过滤样本验证

已对 `C:\path\to\docs` 跑过一次真实 inventory，但没有直接使用全量候选，因为全量候选里包含账单、账号、个人文档等无关或敏感材料。

安全过滤条件：

```text
include: gbt, openclaw, spec, api
exclude: 账单, 账号, credit, picaweb
```

过滤后 inventory：

```text
.\agent-artifacts\knowledge-hub-real-filtered-inventory-20260608-142238
```

真实过滤样本 run：

```text
.\agent-artifacts\knowledge-hub-real-filtered-run-20260608-142559
```

结果：

- 候选文档：4
- 成功处理：3
- 失败：1，`us_trading_system_master_spec.docx` 因当前 Python 环境缺 `python-docx`
- allowed for Context Pack：2
- blocked：2
- `GBT 44464-2024 汽车数据通用要求.pdf` 状态为 `low_quality`，原因是 pypdf 文本存在中文乱码且当前环境缺 OCR 依赖
- Context Pack 和 eval-run setup 均已生成

补齐依赖和 Python 解释器固定后，已复跑最新真实过滤样本：

```text
.\agent-artifacts\knowledge-hub-overnight-20260608-145111
```

结果：

- Python：`python`
- `dependency-check`：`plain_text`、`pdf_text`、`docx`、`pdf_ocr` 全部 ready
- 候选文档：4
- 成功处理：4
- 失败：0
- allowed for Context Pack：3
- blocked：1
- `GBT 44464-2024 汽车数据通用要求.pdf` 状态从 `low_quality` 恢复为 `recovered_by_fallback`，parser 为 `pypdf+rapidocr`
- `us_trading_system_master_spec.docx` 已可解析，但正文只有 27 字，质量状态为 `low_quality`，被 gate 拦截
- 三个 Context Pack 场景均生成证据，每个场景 `chunk_count = 5`、`document_count = 3`

这个结果说明：真实目录接入必须有 include/exclude 过滤、hash 去重和质量 gate。不能把 `Downloads` 这类混杂目录直接全量丢给 Agent Knowledge Hub。

同时说明：长跑必须记录并固定 Python 解释器，否则 PowerShell 7 与 Windows PowerShell 可能解析到不同环境，导致“外层已安装依赖、内层仍提示缺包”的假失败。

## 7. 下一阶段

下一阶段应该优先做：

1. 接真实供应商/内部文档样本，不再只靠合成样本。
2. 增加 `eval_cases.jsonl`，做 direct-file prompt vs Context Pack prompt 对照。
3. 接 Docling/MinerU/Unstructured parser adapter，对比表格、页码、span、多栏、OCR。
4. 引入本地 embedding 或混合检索，但不要让第一版依赖外部服务。
5. 再做 Domain Graph、人工审核台、版本失效机制。
