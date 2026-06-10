# 17 真实实验填表指南

本文说明真实文档到位后，如何填写一次可判定的 baseline vs Context Pack 实验。模板只用于复制，不直接记录正式结果；正式结果写入 `experiments/runs/<run-id>/`。

## 1. 创建实验 run

先创建独立目录：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\new-experiment-run.ps1" -RunId "run-001"
```

后续只填写：

```text
.\experiments\runs\run-001\
```

不要直接修改 `experiments/templates/` 作为正式实验结果。

## 2. 填写任务用例表

文件：

```text
experiments\runs\run-001\agent-task-cases.csv
```

如果 `experiments/templates/task-intake-template.csv` 中已经有 3 个以上已选、完整的真实任务，可以用脚本生成 run 目录里的任务文件：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-task-intake-to-run.ps1" -RunId "run-001"
```

脚本会写入：

```text
experiments\runs\run-001\agent-task-cases.csv
experiments\runs\run-001\scenario-selection-matrix.csv
experiments\runs\run-001\agent-task-cards.md
```

每个任务至少补齐：

- `task_id`
- `task_type`
- `domain`
- `task_description`
- `allowed_documents`
- `gold_answer_points`
- `required_constraints`
- `expected_evidence`
- `scorer`
- `owner`

最低要求：

```text
至少 3 个完整任务用例。
```

任务应该来自真实工作，不要写泛化问题。合格例子：

```text
修改某供应商接口调用逻辑时，Agent 需要找出供应商文档、内部 SPEC 和测试资料中的接口限制、配置要求、超时和失败恢复约束。
```

不合格例子：

```text
总结这个文档讲了什么。
```

## 3. 填写场景选择表

文件：

```text
experiments\runs\run-001\scenario-selection-matrix.csv
```

至少选择 3 个真实任务。`selected` 字段可填写：

```text
yes
true
已选
选中
```

已选任务必须能在 `agent-task-cases.csv` 中找到同名 `task_id`，并且字段完整。

## 4. 填写任务卡

文件：

```text
experiments\runs\run-001\agent-task-cards.md
```

删除所有占位符，包括：

```text
待填写
待提供
待确认
TODO
TBD
placeholder
```

任务卡用于人工执行实验时保持输入一致。baseline 组和 Context Pack 组应使用同一个任务意图，只改变上下文来源。

## 5. 生成成对执行 prompt

任务用例和场景选择表准备好后，生成两组成对 prompt：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-agent-prompts-from-tasks.ps1" -RunId "run-001" -Apply
```

脚本会生成：

```text
experiments\runs\run-001\prompts\baseline\*.md
experiments\runs\run-001\prompts\context_pack\*.md
experiments\runs\run-001\agent-prompt-manifest.csv
```

baseline prompt 的 `context_source` 必须是 `raw_files`，Context Pack prompt 的 `context_source` 必须是 `context_pack`。两组 prompt 必须保持同一个任务意图和输出结构。

prompt 不能包含：

```text
gold_answer_points
required_constraints
expected_evidence
```

这些字段是评分用的标准答案和约束，只能给评分人看，不能给执行任务的 Agent 看。

## 6. 填写解析器评分表

文件：

```text
experiments\runs\run-001\parser-evaluation-sheet.csv
```

如果通过 `prepare-experiment-run-from-intake.ps1 -Apply` 或 `prepare-experiment-run-from-owner-package.ps1 -Apply` 准备 run，解析器评分表会自动按 10 份样本文档和 3 个解析器初始化。

如果是手工创建 run，可先初始化评分矩阵：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-parser-evaluation-from-manifest.ps1" -RunId "run-001" -Apply
```

初始化只生成待评分行，不填写真实指标。

对同一批文档记录：

- 页码是否保留。
- span 是否能回到原文。
- 表格结构是否正确。
- 多栏阅读顺序是否正确。
- OCR 是否可接受。

这一步用于决定第一阶段解析器选择，不直接证明 Context Pack 有业务价值。

填写后运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

## 7. 填写对照结果表

先保存原始 Agent 输出。建议每次 run 建一个目录：

```text
experiments\runs\run-001\raw-outputs\
```

每个任务至少保留两份原始输出：

```text
raw-outputs\task-001-baseline.md
raw-outputs\task-001-context_pack.md
```

然后填写执行日志：

```text
experiments\runs\run-001\agent-run-log.csv
```

每条执行日志至少要能说明：

- `task_id`
- `group`
- `attempt`
- `agent`
- `model`
- `context_source`
- `source_docs`
- `prompt_path`
- `started_at`
- `ended_at`
- `raw_output_path`
- `scorer`
- `score_status`

`raw_output_path` 可以是相对 run 目录的路径，例如 `raw-outputs\task-001-baseline.md`，但文件必须真实存在。

文件：

```text
experiments\runs\run-001\baseline-vs-contextpack-results.csv
```

如果通过 `prepare-experiment-run-from-intake.ps1 -Apply` 或 `prepare-experiment-run-from-owner-package.ps1 -Apply` 准备 run，结果表会自动按已选任务初始化。

如果是手工创建 run 并应用任务，则先根据已选任务初始化结果表：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-results-from-tasks.ps1" -RunId "run-001" -Apply
```

脚本只生成 baseline/context_pack 成对占位行，不填写任何实验结果。

再初始化待执行日志：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-agent-run-log-from-tasks.ps1" -RunId "run-001" -Apply
```

这个脚本只生成 baseline/context_pack 成对的 `pending` 执行记录，并创建 `raw-outputs/` 目录。它不会创建原始回答文件，也不会填写模型、时间、token 或评分结果。

每个任务至少两行：

```text
group = baseline
group = context_pack
```

必须填写：

- `answer_correct`
- `missed_constraints`
- `wrong_claims`
- `citation_correct`
- `token_cost`
- `elapsed_minutes`
- `human_fix_count`

只有 baseline 和 context_pack 都完整的任务，才进入统计。

评分必须参考同目录下的 `scoring-rubric.md`。如果某个结果行没有对应 `agent-run-log.csv` 记录，或者日志里的 `raw_output_path` 找不到原始输出文件，这个任务对不能算作已验证结果。

同理，如果执行日志没有记录 `prompt_path`，或者 `agent-prompt-manifest.csv` 不能证明 baseline/context_pack 使用的是同一任务生成的成对 prompt，这个任务对也不能算作严格可比。

## 8. 运行预检和判定

开跑前：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

实验后先检查证据齐备性：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-run-evidence-readiness.ps1" -ExperimentDir ".\experiments\runs\run-001" -Strict
```

只有输出 `READY_FOR_EVALUATION`，才说明 parser 评分、prompt、run-log、原始输出和结果表已经能支撑正式判定。

然后分别运行解析器判定和对照结果判定：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1" -ResultsPath ".\experiments\runs\run-001\baseline-vs-contextpack-results.csv"
```

只有输出 `READY_FOR_PHASE_2_REVIEW`，才说明可以讨论知识图谱、人工审核和版本失效。否则继续停留在阶段 1，优先修解析、检索和 Context Pack 组装。
