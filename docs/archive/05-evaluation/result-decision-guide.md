# 15 实验结果判定说明

本文定义真实对照实验完成后，如何从结果表中判断是否进入阶段 2。

## 1. 判定脚本

默认读取：

```text
.\experiments\templates\baseline-vs-contextpack-results.csv
```

执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1"
```

如果要读取正式实验结果文件：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1" -ResultsPath ".\experiments\runs\run-001\baseline-vs-contextpack-results.csv"
```

如果要求结果必须完整，使用严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1" -Strict
```

正式判定前，应先检查整个 run 的证据是否齐备：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-run-evidence-readiness.ps1" -ExperimentDir ".\experiments\runs\run-001" -Strict
```

只有输出 `READY_FOR_EVALUATION`，才说明 parser 评分、prompt、run-log、原始 Agent 输出和结果表都已经足够支撑后续判定。

## 2. 输入要求

结果表至少需要以下列：

- `task_id`
- `group`
- `answer_correct`
- `missed_constraints`
- `wrong_claims`
- `citation_correct`
- `token_cost`
- `elapsed_minutes`
- `human_fix_count`

每个任务至少有两行：

```text
group = baseline
group = context_pack
```

只有 baseline 和 context_pack 两行都完整的任务，才会进入统计。

此外，每个进入统计的任务对都必须能在 `agent-run-log.csv` 中找到 baseline 和 context_pack 两条执行记录，并且两条记录的 `prompt_path` 与 `raw_output_path` 都指向真实存在的文件。否则即使结果表字段完整，也不能作为阶段 2 评审证据。

## 3. 通过规则

脚本会比较 4 个维度：

| 维度 | 通过线 |
|---|---|
| 答案准确率 | Context Pack 比 baseline 提升 >= 30 个百分点 |
| 关键约束遗漏 | Context Pack 平均遗漏数降低 >= 30% |
| Token 成本 | Context Pack 平均 token 降低 >= 50% |
| 完成耗时 | Context Pack 平均耗时降低 >= 30% |

证据正确率是硬门槛：

```text
Context Pack 组 citation_correct >= 90%
```

进入阶段 2 的最低条件：

```text
4 个维度中至少 2 个通过；
且 Context Pack 证据正确率 >= 90%。
```

否则继续停留在阶段 1，优先修解析、检索、Context Pack 组装或任务定义。

## 4. 输出解释

脚本输出：

- 完整 baseline/context_pack 任务对数量。
- baseline 与 Context Pack 的准确率、证据正确率、平均遗漏、平均 token、平均耗时。
- 4 个决策维度是否通过。
- 最终建议：
  - `READY_FOR_PHASE_2_REVIEW`
  - `STAY_IN_PHASE_1`

该建议不是自动立项结论，而是进入人工决策会的证据输入。

## 5. 解析器判定脚本

解析器评分表填写后，运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -Strict -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

通过规则：

| 维度 | 通过线 |
|---|---|
| 页码保留率 | >= 95% |
| span 可追溯率 | >= 90% |
| 表格结构准确率 | >= 80% |
| 阅读顺序准确率 | >= 90% |
| OCR 准确率 | >= 95% |
| critical_failures | 0 |

默认要求至少 3 个解析器各覆盖 10 份文档。输出 `PARSER_READY` 时，只代表可以选择第一阶段默认解析器，不代表 Context Pack 业务价值已经被证明。
