# 11 实验执行 Runbook

本文把两周轻量实验落成可执行流程。目标不是做完整平台，而是回答：

```text
结构化 PDF + 混合检索 + Context Pack 是否明显优于直接给 Agent 文件？
```

## 1. 前置条件

必须准备：

1. 10 份真实样本文档，放入 `samples/raw/`。
2. 更新 `samples/README.md` 的文件路径、版本、owner 和文档特征。
3. 选择 3-5 个真实 Agent 任务，填入 `experiments/templates/agent-task-cards.md`。
4. 明确是否允许外部 LLM。如果不允许，第一轮只做本地解析、全文检索和向量检索。

当前默认样本范围：

```text
混合工程文档样本
```

## 2. 实验目录

```text
experiments/
  README.md
  templates/
    agent-task-cards.md
    parser-evaluation-sheet.csv
    baseline-vs-contextpack-results.csv
    agent-run-log.csv
    agent-prompt-template.md
    agent-prompt-manifest.csv
    context-pack-template.json
    scoring-rubric.md
    prompts/
    raw-outputs/
```

## 3. 执行顺序

### 3.1 样本文档登记

把真实文件放到：

```text
.\samples\raw\
```

然后补齐：

```text
.\samples\README.md
```

每份文档至少记录：

- 文件路径
- 文档类型
- 版本
- 是否扫描件
- 是否含表格
- 是否含多栏
- owner

### 3.2 任务卡定义

每个任务卡必须包含：

- 任务描述
- 目标答案要点
- 必须覆盖的关键约束
- 允许使用的文档
- 预期证据位置
- 人工评分人

同时需要填写结构化任务用例表：

```text
experiments/templates/agent-task-cases.csv
```

每个任务用例至少包含：

- 任务描述。
- 允许使用的文档。
- 标准答案要点。
- 必须覆盖的关键约束。
- 预期证据位置。
- 评分人和 owner。

任务至少覆盖：

1. 查平台约束。
2. 查接口或机制说明。
3. 生成测试关注点。

同时需要在 `experiments/templates/scenario-selection-matrix.csv` 中把至少 3 个任务标记为已选，并补齐：

- `real_source`
- `monthly_frequency`
- `has_gold_answer`
- `needs_evidence`
- `owner`

### 3.3 初始化成对结果表

baseline 和 Context Pack 组必须有同一批任务的成对结果占位行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-results-from-tasks.ps1" -RunId "run-001" -Apply
```

如果使用 `prepare-experiment-run-from-intake.ps1 -Apply` 或 `prepare-experiment-run-from-owner-package.ps1 -Apply` 准备 run，这一步会自动完成。

### 3.4 生成成对执行 prompt

baseline 和 Context Pack 组必须从同一批已选任务生成成对 prompt，保证任务意图、输出结构和评分口径一致，只改变上下文来源：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-agent-prompts-from-tasks.ps1" -RunId "run-001" -Apply
```

输出：

```text
experiments/runs/run-001/prompts/baseline/*.md
experiments/runs/run-001/prompts/context_pack/*.md
experiments/runs/run-001/agent-prompt-manifest.csv
```

prompt 中不能包含以下评分字段：

```text
gold_answer_points
required_constraints
expected_evidence
```

这些字段只允许评分人通过 `scoring-rubric.md` 使用，不能提前喂给 Agent。

### 3.5 基线组：直接给 Agent 文件

执行方式：

```text
Agent 使用 `prompts/baseline/` 中的 prompt，直接读取原始文件或由用户提供原始文档内容。
```

记录：

- 是否答对
- 漏掉哪些关键约束
- 引用是否正确
- token 成本
- 完成耗时
- 人工修正次数

结果填写到：

```text
experiments/templates/baseline-vs-contextpack-results.csv
```

原始 Agent 输出必须另存到本次 run 的目录，例如：

```text
experiments/runs/run-001/raw-outputs/
```

并在 `agent-run-log.csv` 中记录 `task_id`、`group=baseline`、`context_source=raw_files`、`raw_output_path`、模型、耗时和评分状态。

### 3.6 解析器对比

候选解析器：

```text
Docling
MinerU
Unstructured
```

评分文件：

```text
experiments/templates/parser-evaluation-sheet.csv
```

如果通过 `prepare-experiment-run-from-intake.ps1 -Apply` 或 `prepare-experiment-run-from-owner-package.ps1 -Apply` 创建 run，脚本会自动根据样本文档 manifest 生成 `10 份文档 × Docling/MinerU/Unstructured` 的待评分行。

手工创建 run 时，可单独初始化：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-parser-evaluation-from-manifest.ps1" -RunId "run-001" -Apply
```

初始化只说明“评估矩阵准备好”，不代表解析器已经跑完，也不代表 parser 指标已经有真实证据。

评分维度：

- 页码保留率
- span 可追溯率
- 表格结构准确率
- 阅读顺序准确率
- OCR 准确率
- 解析耗时
- 失败原因

评分后运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

### 3.7 Context Pack 组

执行方式：

```text
文档 -> 结构化 blocks -> 全文/向量检索 -> Context Pack -> Agent 使用 `prompts/context_pack/` 中的 prompt 回答
```

Context Pack 最小结构参考：

```text
experiments/templates/context-pack-template.json
```

记录同基线组，额外记录：

- Context Pack token 大小
- 召回 span 数
- 有用 span 数
- 无关 span 数
- 检索失败原因

Context Pack 组同样必须保存原始 Agent 输出，并在 `agent-run-log.csv` 中记录 `group=context_pack`、`context_source=context_pack` 和对应的 `raw_output_path`。

## 3.8 执行追溯和评分

每次 Agent 执行都要有两类记录：

- 原始输出文件：建议放在 `experiments/runs/<run-id>/raw-outputs/`。
- 执行日志：写入 `experiments/runs/<run-id>/agent-run-log.csv`，并记录本次执行使用的 `prompt_path`。

评分时按照 `scoring-rubric.md` 读取原始输出，再填写 `baseline-vs-contextpack-results.csv`。结果表中的一个任务只有在以下条件都满足时才算有效：

- baseline 和 context_pack 两组结果行都完整。
- `agent-run-log.csv` 中有同一 `task_id` 的 baseline 和 context_pack 记录。
- 两条执行记录都能通过 `prompt_path` 回到对应的 baseline/context_pack prompt。
- 两条执行记录的 `raw_output_path` 都指向真实存在的原始输出文件。
- 评分人能从原始输出解释 `answer_correct`、`missed_constraints`、`wrong_claims` 和 `citation_correct`。

评分和解析器指标都填写后，先运行 run 级证据齐备检查：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-run-evidence-readiness.ps1" -ExperimentDir ".\experiments\runs\run-001" -Strict
```

只有输出 `READY_FOR_EVALUATION`，才进入 `evaluate-parser-results.ps1` 和 `evaluate-results.ps1`。如果输出 `INCOMPLETE_EVIDENCE` 或 `BLOCKED_ON_RUN_SETUP`，先补齐对应的 parser 指标、prompt 文件、run-log、原始输出或结果表。

## 4. 判定规则

进入阶段 2 的最低条件：

```text
准确率、遗漏率、token、耗时中至少 2 项明显优于基线；
且证据正确率 >= 90%。
```

不进入阶段 2 的情况：

- 只是 token 降低，但准确率没有提升。
- 证据正确率低于 90%。
- Agent 直接给文件已经足够稳定。
- 真实任务中没有跨文档关系需求。

自动判定命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1"
```

判定脚本只作为证据输入，最终仍需要结合实验结论模板做人工决策。

## 5. 实验结论模板

实验结束后必须输出：

```text
1. 直接给文件的主要失败模式是什么？
2. Context Pack 改善了哪些指标？
3. 哪个解析器最适合第一阶段？
4. 是否需要知识图谱？
5. 是否需要人工审核？
6. 是否需要版本失效？
7. 下一阶段投入是否值得？
```
