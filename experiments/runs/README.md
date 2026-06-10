# Experiment Runs

本目录用于保存每一次真实对照实验的独立结果。不要直接在 `experiments/templates/` 里填写真实实验结果，模板目录只保留可复用模板。

## 创建新实验

执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\new-experiment-run.ps1" -RunId "run-001"
```

如果不指定 `RunId`，脚本会按当前时间生成：

```text
run-yyyyMMdd-HHmmss
```

如果已有 10 份样本文档 manifest，可先初始化解析器评分矩阵：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-parser-evaluation-from-manifest.ps1" -RunId "run-001" -Apply
```

如果使用 `scripts/prepare-experiment-run-from-intake.ps1 -RunId "run-001" -Apply` 或 `scripts/prepare-experiment-run-from-owner-package.ps1 -RunId "run-001" -Apply`，parser 评分矩阵会在准备 run 时自动生成。初始化只写入待评分行，不代表解析器已经跑完。

如果已在候选任务表中选出真实任务，可以同步到 run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-task-intake-to-run.ps1" -RunId "run-001"
```

该脚本会根据已选候选任务生成：

```text
agent-task-cases.csv
scenario-selection-matrix.csv
agent-task-cards.md
```

任务同步完成后，生成 baseline/context_pack 成对执行 prompt：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-agent-prompts-from-tasks.ps1" -RunId "run-001" -Apply
```

该脚本会写入：

```text
prompts/baseline/*.md
prompts/context_pack/*.md
agent-prompt-manifest.csv
```

如果使用 `scripts/prepare-experiment-run-from-intake.ps1 -RunId "run-001" -Apply`，prompt 会在准备 run 时自动生成。

随后初始化待执行日志：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-agent-run-log-from-tasks.ps1" -RunId "run-001" -Apply
```

如果使用 `scripts/prepare-experiment-run-from-intake.ps1 -RunId "run-001" -Apply` 或 `scripts/prepare-experiment-run-from-owner-package.ps1 -RunId "run-001" -Apply`，run-log 会在准备 run 时自动生成。初始化只写入 `pending` 记录并创建 `raw-outputs/` 目录，不会生成假的 Agent 输出。

## 每个 run 应包含

- `agent-task-cards.md`
- `agent-task-cases.csv`
- `scenario-selection-matrix.csv`
- `parser-evaluation-sheet.csv`
- `baseline-vs-contextpack-results.csv`
- `agent-run-log.csv`
- `agent-prompt-template.md`
- `agent-prompt-manifest.csv`
- `prompts/`
- `scoring-rubric.md`
- `raw-outputs/`
- `context-pack-template.json`
- `experiment-summary.md`
- `README.md`

`prompts/` 用于保存实际投喂给 Agent 的成对 prompt。baseline 和 context_pack 两组只允许改变上下文来源，不能改变任务意图和输出结构。

`raw-outputs/` 用于保存每次 Agent 执行的原始回答。`agent-run-log.csv` 中的 `prompt_path` 必须指向本次执行使用的 prompt，`raw_output_path` 必须指向这些原始输出文件，`baseline-vs-contextpack-results.csv` 的评分必须能回到这些原始输出。

## 判定结果

填写真实实验结果后，先检查证据是否齐备：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-run-evidence-readiness.ps1" -ExperimentDir ".\experiments\runs\run-001" -Strict
```

只有输出 `READY_FOR_EVALUATION`，才进入 parser 和 baseline/context_pack 结果判定。这个检查会确认：

- 至少 3 个已选任务具备完整任务用例。
- 解析器评分覆盖 10 份文档和 3 个解析器。
- baseline/context_pack 成对 prompt 文件存在。
- `agent-run-log.csv` 指向真实存在且非空的原始输出。
- `baseline-vs-contextpack-results.csv` 已完成评分。

证据齐备后执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1" -ResultsPath ".\experiments\runs\run-001\baseline-vs-contextpack-results.csv"
```

判定输出只回答是否具备进入阶段 2 评审的证据，不自动代表立项结论。

## Run 级预检

正式开跑前，先对具体 run 目录执行严格预检：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

只有严格预检 `FAIL=0`，才进入 baseline 和 Context Pack 对照实验。
