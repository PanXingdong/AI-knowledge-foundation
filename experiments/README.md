# experiments

本目录存放 Agent Knowledge Hub 两周轻量实验的执行模板和结果记录。

当前实验目标：

```text
比较“直接给 Agent 文件”和“Context Pack”两种方式在真实工程任务中的效果差异。
```

## 模板

- [templates/agent-task-cards.md](templates/agent-task-cards.md)：真实 Agent 任务卡。
- [templates/agent-task-cases.csv](templates/agent-task-cases.csv)：可机器检查的 Agent 任务用例表。
- [templates/parser-evaluation-sheet.csv](templates/parser-evaluation-sheet.csv)：Docling / MinerU / Unstructured 解析质量评分表。
- [templates/baseline-vs-contextpack-results.csv](templates/baseline-vs-contextpack-results.csv)：直接给文件 vs Context Pack 结果对比表。
- [templates/agent-run-log.csv](templates/agent-run-log.csv)：每次 Agent 执行记录，必须指向保留下来的原始输出。
- [templates/agent-prompt-template.md](templates/agent-prompt-template.md)：baseline/context_pack 成对 prompt 的统一输出格式和执行约束。
- [templates/agent-prompt-manifest.csv](templates/agent-prompt-manifest.csv)：记录每个任务的 baseline/context_pack prompt 路径、上下文来源和 source docs。
- [templates/context-pack-template.json](templates/context-pack-template.json)：Context Pack 最小结构模板。
- [templates/scenario-selection-matrix.csv](templates/scenario-selection-matrix.csv)：真实 Agent 任务选择矩阵。
- [templates/scoring-rubric.md](templates/scoring-rubric.md)：把原始 Agent 输出转换为评分字段的规则。
- [templates/task-intake-template.csv](templates/task-intake-template.csv)：模块 owner 提供候选真实 Agent 任务的收集表。
- [templates/task-intake-example.csv](templates/task-intake-example.csv)：候选真实 Agent 任务填表示例，不作为真实输入。
- [templates/experiment-summary-template.md](templates/experiment-summary-template.md)：实验结束后的决策汇总模板。

## 使用顺序

1. 让模块 owner 按 `docs/archive/06-operations/owner-collection-package.md` 填写候选文档和候选任务收集表。
2. 把入选真实 PDF/Word 文档放到 `samples/raw/`。
3. 更新 `samples/README.md` 和 `samples/sample-manifest.csv`。
4. 用 `scripts/new-experiment-run.ps1` 创建独立 run 目录。
5. 在 run 目录中填写 `agent-task-cards.md` 和 `agent-task-cases.csv`。
6. 运行 `scripts/initialize-results-from-tasks.ps1 -RunId <run-id> -Apply`，生成 baseline/context_pack 成对结果占位行。
7. 运行 `scripts/initialize-agent-prompts-from-tasks.ps1 -RunId <run-id> -Apply`，生成成对 prompt 和 `agent-prompt-manifest.csv`。
8. 跑直接给文件的基线组。
9. 跑解析器对比。
10. 跑 Context Pack 组。
11. 保存每次 Agent 原始输出到 run 目录，例如 `raw-outputs/`。
12. 填写 `agent-run-log.csv`，把任务、组别、prompt、上下文来源和原始输出路径连起来。
13. 按 `scoring-rubric.md` 填写 run 目录中的结果对比表。
14. 运行 `scripts/evaluate-results.ps1` 计算是否满足阶段 2 进入条件。
15. 根据指标决定是否进入阶段 2。

如果使用 `scripts/prepare-experiment-run-from-intake.ps1 -RunId <run-id> -Apply`，第 4-7 步会自动完成。

`baseline-vs-contextpack-results.csv` 只记录评分结果，不保存原始回答。每个有效任务对都必须能通过 `agent-run-log.csv` 追溯到 baseline 和 context_pack 两份原始 Agent 输出。

成对 prompt 的要求：

- baseline 和 context_pack 使用同一个任务意图、同一个输出结构、同一个评分口径。
- baseline 的 `context_source` 固定为 `raw_files`，context_pack 的 `context_source` 固定为 `context_pack`。
- prompt 中不能包含 `gold_answer_points`、`required_constraints`、`expected_evidence`；这些字段只给评分人和 `scoring-rubric.md` 使用。

## 结果判定

默认判定命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1"
```

正式实验建议把结果复制到 `experiments/runs/<run-id>/` 后再指定 `-ResultsPath`。
