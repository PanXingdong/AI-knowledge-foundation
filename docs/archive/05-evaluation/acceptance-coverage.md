# 10 验收覆盖清单

本文用于核对轻量实验路线是否覆盖当前 goal 的 6 条验收标准。

## 1. 明确第一批样本范围和 10 份样本文档

当前状态：

- 第一批样本范围已明确为：混合工程文档样本。
- 10 份样本文档类型已定义。
- 真实文件尚未提供，`<workspace-root>` 当前未发现 PDF/Word 样本。

证据位置：

- [06-MVP路线.md](06-MVP路线.md)
- [08-两周轻量实验设计.md](08-两周轻量实验设计.md)
- [12-领域样本文档与场景选择依据.md](12-领域样本文档与场景选择依据.md)
- [../samples/README.md](../samples/README.md)
- [../samples/sample-manifest.csv](../samples/sample-manifest.csv)
- [16-样本文档接入说明.md](16-样本文档接入说明.md)
- [../scripts/import-sample-docs.ps1](../scripts/import-sample-docs.ps1)

结论：

```text
样本范围和样本文档槽位已明确；真实样本文档路径仍待补齐。
```

## 2. 定义“直接给 Agent 文件”的基线测试

已定义：

- 基线组输入。
- 执行方式。
- 记录项。
- 与 Context Pack 组的对照方式。

证据位置：

- [08-两周轻量实验设计.md](08-两周轻量实验设计.md)
- [09-评估指标与基线对比.md](09-评估指标与基线对比.md)
- [11-实验执行Runbook.md](11-实验执行Runbook.md)
- [../experiments/templates/agent-task-cases.csv](../experiments/templates/agent-task-cases.csv)
- [../experiments/templates/agent-task-cards.md](../experiments/templates/agent-task-cards.md)
- [../experiments/templates/baseline-vs-contextpack-results.csv](../experiments/templates/baseline-vs-contextpack-results.csv)
- [../experiments/runs/README.md](../experiments/runs/README.md)
- [../scripts/new-experiment-run.ps1](../scripts/new-experiment-run.ps1)

## 3. 定义 Context Pack 实验方案

已定义：

- `get_context_pack` 调用方式。
- Context Pack 最小字段。
- 对照实验流程。
- 两周执行计划。

证据位置：

- [04-Agent调用方式.md](04-Agent调用方式.md)
- [08-两周轻量实验设计.md](08-两周轻量实验设计.md)
- [09-评估指标与基线对比.md](09-评估指标与基线对比.md)
- [11-实验执行Runbook.md](11-实验执行Runbook.md)
- [../experiments/templates/agent-task-cases.csv](../experiments/templates/agent-task-cases.csv)
- [../experiments/templates/context-pack-template.json](../experiments/templates/context-pack-template.json)
- [../experiments/runs/README.md](../experiments/runs/README.md)

## 4. 定义解析器对比指标

已定义指标：

- 页码保留率。
- Span 可追溯率。
- 表格结构准确率。
- 阅读顺序准确率。
- OCR 准确率。

证据位置：

- [09-评估指标与基线对比.md](09-评估指标与基线对比.md)
- [../experiments/templates/parser-evaluation-sheet.csv](../experiments/templates/parser-evaluation-sheet.csv)

## 5. 定义 Agent 使用效果指标

已定义指标：

- 答案准确率。
- 关键约束遗漏率。
- Token 成本。
- 完成耗时。
- 证据正确率。
- 人工修正次数。

证据位置：

- [09-评估指标与基线对比.md](09-评估指标与基线对比.md)
- [../experiments/templates/baseline-vs-contextpack-results.csv](../experiments/templates/baseline-vs-contextpack-results.csv)
- [../experiments/templates/agent-task-cases.csv](../experiments/templates/agent-task-cases.csv)
- [../experiments/templates/scenario-selection-matrix.csv](../experiments/templates/scenario-selection-matrix.csv)

## 6. 明确图谱/审核/版本管理是二阶段

已明确：

- 第一阶段只做结构化 PDF、混合检索、Context Pack、REST/MCP。
- 图谱、人工审核、版本失效、正式影响分析进入第二阶段。

证据位置：

- [README.md](../README.md)
- [01-需求定义.md](01-需求定义.md)
- [02-系统架构.md](02-系统架构.md)
- [03-技术栈选型.md](03-技术栈选型.md)
- [04-Agent调用方式.md](04-Agent调用方式.md)
- [05-数据模型与图谱Schema.md](05-数据模型与图谱Schema.md)
- [06-MVP路线.md](06-MVP路线.md)
- [07-决策与待确认问题.md](07-决策与待确认问题.md)
- [11-实验执行Runbook.md](11-实验执行Runbook.md)
- [18-方向冻结与阶段门.md](18-方向冻结与阶段门.md)

## 7. 当前不能宣称完成的事项

以下事项需要真实文档后才能完成：

- 10 份样本文档的真实路径和版本登记。
- 解析器真实对比结果。
- Agent 基线测试结果。
- Context Pack 实验结果。

这些是实验执行阶段产物，不属于当前文档路线补齐阶段的已完成事实。

## 8. 自动预检

已补充预检脚本，用于检查实验结构是否可用、真实样本文档是否到位、模板是否可解析、阶段边界是否仍然清晰。

更细的 goal 级证据矩阵见：

- [22-goal验收证据矩阵.md](22-goal验收证据矩阵.md)

证据位置：

- [14-实验预检说明.md](14-实验预检说明.md)
- [../scripts/preflight.ps1](../scripts/preflight.ps1)
- [15-实验结果判定说明.md](15-实验结果判定说明.md)
- [../scripts/evaluate-results.ps1](../scripts/evaluate-results.ps1)
- [16-样本文档接入说明.md](16-样本文档接入说明.md)
- [../scripts/import-sample-docs.ps1](../scripts/import-sample-docs.ps1)
- [../experiments/runs/README.md](../experiments/runs/README.md)
- [../scripts/new-experiment-run.ps1](../scripts/new-experiment-run.ps1)
- [18-方向冻结与阶段门.md](18-方向冻结与阶段门.md)

默认模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1"
```

严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs
```

Run 级严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

严格预检现在还会检查：

- `agent-task-cases.csv` 至少有 3 个完整任务用例。
- `scenario-selection-matrix.csv` 至少选出 3 个真实任务。
- 已选任务具备 owner、真实来源、标准答案、证据要求和完整任务用例。
- `agent-task-cards.md` 不再包含 `待填写`、`待提供`、`待确认` 等占位符。
- 真实实验结果必须写入 `experiments/runs/<run-id>/`，不能覆盖模板目录。

当前判断：

```text
预检能证明文档结构和实验模板是否准备好；
不能替代真实 PDF、真实任务和真实 Agent 实验结果。
```
