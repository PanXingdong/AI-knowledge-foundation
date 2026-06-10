# 22 Goal 验收证据矩阵

本文用于把当前 goal 的 6 条验收标准逐条映射到可检查证据，避免把“文档路线已补齐”和“真实实验已完成”混在一起。

当前 goal 不是要求直接建设完整知识图谱，而是先推进轻量实验路线：

```text
结构化文档 + 检索 + Context Pack + Core API
```

用真实文档和真实 Agent 任务验证它是否明显优于直接给 Agent 文件，再决定是否进入知识图谱、人工审核和版本失效建设。

## 0. Auto Context Pack Engine v1 当前实证

针对当前线程 goal：

```text
Auto Context Pack Engine v1
```

仓库里已经有两组真实工程文档自动产物完成对人工 Context Pack 的对照：

| 轮次 | 自动产物目录 | covered | missing | 结论 |
|---|---|---:|---:|---|
| round2 | `.\agent-artifacts\knowledge-hub-round2\auto-bundle-top12-v3` | 106 | 0 | 自动检索、重排、组装、gap report 已跑通 |
| round3 | `.\agent-artifacts\knowledge-hub-round3\auto-bundle-top12-v16` | 117 | 0 | 加入治理文档后，跨文档默认规则和禁止项也已覆盖 |

这说明第一阶段“processed 文档 -> 自动 Context Pack -> gap report -> Agent 调用入口”这条主链已经有真实材料证据，不再停留在模板或 smoke。

## 1. 验收标准到证据映射

| 验收项 | 当前证据 | 当前状态 | 仍缺什么 |
|---|---|---|---|
| 明确第一批样本范围和 10 份样本文档 | `README.md`、`docs/overview.md`、`samples/sample-manifest.csv`、`samples/document-intake-template.csv` | 部分满足 | 样本范围已定为混合工程文档样本，10 个槽位已定义；真实文件路径、版本、owner、密级仍待 owner 提供 |
| 定义“直接给 Agent 文件”的基线测试 | `docs/evaluation.md`、`docs/archive/05-evaluation/two-week-experiment-design.md`、`docs/archive/06-operations/experiment-runbook.md`、`experiments/templates/baseline-vs-contextpack-results.csv` | 已定义 | 真实 baseline 执行结果仍待实验 run 产生 |
| 定义 Context Pack 实验方案 | `docs/api-contract.md`、`docs/evaluation.md`、`docs/archive/03-design/agent-local-integration.md`、`experiments/templates/context-pack-template.json` | 已定义 | 第一版真实 Context Pack 仍待文档解析和检索结果生成 |
| 定义解析器对比指标 | `docs/evaluation.md`、`docs/archive/05-evaluation/result-decision-guide.md`、`experiments/templates/parser-evaluation-sheet.csv` | 已定义 | Docling / MinerU / Unstructured 的真实解析评分仍待 10 份文档到位后填写 |
| 定义 Agent 使用效果指标 | `docs/evaluation.md`、`experiments/templates/baseline-vs-contextpack-results.csv` | 已定义 | 准确率、遗漏率、token、耗时、证据正确率需要真实任务对照结果 |
| 明确图谱/审核/版本管理是二阶段 | `README.md`、`docs/overview.md`、`docs/architecture.md`、`docs/detailed-design.md` | 已满足 | 阶段 2 是否启动必须等 `evaluate-results.ps1` 输出和人工评审 |

## 2. 当前不能宣称完成的内容

以下事项必须等真实输入和实验结果，不应靠模板或示例替代：

- 10 份真实样本文档已经接入。
- 真实文档解析质量已经对比。
- Agent 直接读文件的 baseline 已经完成。
- Context Pack 实验组已经完成。
- Context Pack 已证明优于直接给 Agent 文件。
- 需要进入完整知识图谱、人工审核或版本失效建设。

## 3. 三个完成层级

### 3.1 路线材料完成

可以宣称“路线材料完成”的最低证据：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1"
powershell -ExecutionPolicy Bypass -File ".\scripts\check-goal-acceptance.ps1"
```

要求：

```text
FAIL = 0
Definitions ready = 6/6
```

此时只代表方向、模板、指标、脚本和阶段边界可用，不代表真实输入齐全，也不代表实验已经开跑。

### 3.2 真实实验可开跑

可以宣称“真实实验可开跑”的最低证据：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-intake.ps1" -RunId "run-001" -Apply
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
powershell -ExecutionPolicy Bypass -File ".\scripts\check-goal-acceptance.ps1" -ExperimentDir ".\experiments\runs\run-001" -RequireRealInputs
```

要求：

```text
READY_TO_CREATE_EXPERIMENT_RUN
run 级严格预检 FAIL = 0
Real input gate = True
```

此时只代表可以执行 baseline 和 Context Pack 对照实验，不代表 Context Pack 已经胜出。

### 3.3 阶段 2 可评审

可以宣称“进入阶段 2 评审”的最低证据：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-run-evidence-readiness.ps1" -ExperimentDir ".\experiments\runs\run-001" -Strict
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1" -ResultsPath ".\experiments\runs\run-001\baseline-vs-contextpack-results.csv"
powershell -ExecutionPolicy Bypass -File ".\scripts\check-goal-acceptance.ps1" -ExperimentDir ".\experiments\runs\run-001" -RequireRealInputs -RequireExperimentResults
```

要求：

```text
Run evidence readiness = READY_FOR_EVALUATION
baseline/context_pack 至少 3 个完整任务对
每个任务对能回到成对 prompt、agent-run-log 和原始 Agent 输出
Context Pack 证据正确率 >= 90%
准确率、遗漏率、token、耗时 4 个维度中至少 2 个明显优于 baseline
Experiment result gate = True
```

此时也只是进入阶段 2 人工评审或决策，不是自动启动完整知识图谱建设。

## 4. 当前下一步

当前最短路径仍然是收集真实混合工程文档输入：

1. 向文档 owner、领域确认人或任务评分人发送 `docs/archive/06-operations/owner-collection-package.md`。
2. owner 或确认人填写 `samples/document-intake-template.csv`。
3. owner 或评分人填写 `experiments/templates/task-intake-template.csv`。
4. 用 `samples/owner-response-tracker.csv` 跟踪请求、回收和阻塞。
5. 运行 `check-intake-readiness.ps1 -Strict`，只在 ready 后创建真实 run。

在这一步完成前，不应启动 Neo4j、审核台、版本失效、正式影响分析或 IDE 插件。
