# 14 实验预检说明

本文定义启动两周轻量实验前的自动预检。目的不是替代人工判断，而是避免在真实文档、任务卡、模板或阶段边界缺失时误以为实验已经具备条件。

## 1. 预检命令

在项目根目录或任意目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1"
```

默认模式用于检查项目结构、模板、CSV/JSON 可读性和阶段边界。真实文档和真实任务缺失会输出 `WARN`，不会让命令失败。

当准备正式开跑实验时，使用严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs
```

如果已经创建独立实验 run，需要指定 run 目录：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

不指定 `-ExperimentDir` 时，默认检查：

```text
.\experiments\templates
```

在真实文档尚未复制到 `samples/raw/` 前，可以先检查 owner 候选输入是否已经足够进入实验准备：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1"
```

严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict
```

如果需要按当前 goal 的 6 条验收标准逐条检查定义证据和真实验证证据，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-goal-acceptance.ps1"
```

如果一次实验 run 已经执行完 baseline/context_pack，并且 parser 评分、原始 Agent 输出和结果表都已填写，先检查 run 级证据是否足够进入正式评价：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-run-evidence-readiness.ps1" -ExperimentDir ".\experiments\runs\run-001" -Strict
```

如果需要验证 intake readiness 的绿灯路径是否仍然可用，可以运行 smoke：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-intake-readiness-smoke.ps1"
```

如果需要验证候选文档表到 `samples/raw/` 和 manifest 的桥接路径，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-document-intake-to-samples-smoke.ps1"
```

如果需要验证 owner 收集交付包能否生成，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-smoke.ps1"
```

如果需要验证准备发送给 owner 的目录或 zip 是否完整，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-owner-package-readiness.ps1" -PackagePath "C:\path\to\owner-package.zip" -Strict
```

如果需要验证 owner 包发送前校验脚本能否识别完整包和缺文件坏包，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-readiness-smoke.ps1"
```

如果需要验证 owner 返回包能否安全导入正式 intake 表，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-import-smoke.ps1"
```

如果需要验证 owner 返回包能否一键导入并准备实验 run，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-to-run-smoke.ps1"
```

如果需要验证 owner intake 状态报告是否能汇总缺口，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-intake-status-smoke.ps1"
```

如果需要验证 owner 候选输入到实验 run 的完整准备链路，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-prepare-experiment-run-smoke.ps1"
```

如果需要验证已选任务能否初始化 baseline/context_pack 对照结果表，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-result-initialization-smoke.ps1"
```

如果需要验证已选任务能否初始化 baseline/context_pack 成对执行 prompt，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-agent-prompt-initialization-smoke.ps1"
```

如果需要验证 goal 验收门禁的完整通过路径，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-goal-acceptance-smoke.ps1"
```

如果需要验证 run 级证据齐备门禁是否仍能区分完整证据和缺失原始输出，可以运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-run-evidence-readiness-smoke.ps1"
```

严格模式下，以下问题会变成 `FAIL`：

- `samples/raw/` 中不足 10 份真实 PDF/Word/HTML 文档。
- `samples/sample-manifest.csv` 仍有 `file_path` 为 `待提供`。
- 指定实验目录中的 `agent-task-cards.md` 仍有 `待填写`、`待提供`、`待确认`。
- 指定实验目录中的 `agent-task-cases.csv` 不足 3 个完整任务用例。
- 指定实验目录中的 `scenario-selection-matrix.csv` 未选出至少 3 个真实任务。
- 对照结果已经填写，但缺少 `agent-run-log.csv` 或原始 Agent 输出文件时，goal/status 检查不会把结果视为可追溯验证。
- run 级证据检查发现 parser 指标、prompt 文件、run-log、原始输出或结果评分不完整时，`check-run-evidence-readiness.ps1 -Strict` 会失败。
- 已选任务缺少 baseline/context_pack 成对 prompt、`agent-prompt-manifest.csv` 缺列、prompt 文件不存在、上下文来源不正确，或 prompt 泄露 `gold_answer_points`、`required_constraints`、`expected_evidence` 时，严格预检会失败。

## 2. 预检覆盖范围

脚本会检查：

- 核心文档和实验模板是否存在。
- 文档 owner、领域确认人或评分人的候选文档表和任务候选表是否存在、能解析、列完整。
- owner 输入到实验 run 的编排脚本是否存在、PowerShell 语法是否正确。
- owner 收集包导出脚本是否存在、PowerShell 语法是否正确。
- owner 收集包发送前校验脚本是否存在、PowerShell 语法是否正确。
- owner 返回包导入脚本是否存在、PowerShell 语法是否正确。
- owner 返回包到实验 run 的一键准备脚本是否存在、PowerShell 语法是否正确。
- owner intake 状态报告脚本是否存在、PowerShell 语法是否正确。
- owner 输入到实验 run 的完整链路 smoke 脚本是否存在、PowerShell 语法是否正确。
- owner 收集包导出 smoke 脚本是否存在、PowerShell 语法是否正确。
- owner 收集包发送前校验 smoke 脚本是否存在、PowerShell 语法是否正确。
- owner 返回包导入 smoke 脚本是否存在、PowerShell 语法是否正确。
- owner 返回包到实验 run 的一键准备 smoke 脚本是否存在、PowerShell 语法是否正确。
- owner intake 状态报告 smoke 脚本是否存在、PowerShell 语法是否正确。
- intake readiness 脚本和任务同步脚本是否存在、PowerShell 语法是否正确。
- intake readiness smoke 脚本是否存在、PowerShell 语法是否正确。
- run 级证据齐备检查脚本和 smoke 脚本是否存在、PowerShell 语法是否正确。
- 候选文档接入脚本和 smoke 脚本是否存在、PowerShell 语法是否正确。
- 解析器评分判定脚本和 smoke 脚本是否存在、PowerShell 语法是否正确。
- 统一实验状态报告脚本和 smoke 脚本是否存在、PowerShell 语法是否正确。
- 对照结果表初始化脚本是否存在、PowerShell 语法是否正确。
- 对照结果表初始化 smoke 脚本是否存在、PowerShell 语法是否正确。
- 解析器评分表初始化脚本是否存在、PowerShell 语法是否正确。
- 解析器评分表初始化 smoke 脚本是否存在、PowerShell 语法是否正确。
- Agent prompt 初始化脚本是否存在、PowerShell 语法是否正确。
- Agent prompt 初始化 smoke 脚本是否存在、PowerShell 语法是否正确。
- Agent run-log 初始化脚本是否存在、PowerShell 语法是否正确。
- Agent run-log 初始化 smoke 脚本是否存在、PowerShell 语法是否正确。
- Agent prompt 模板和 manifest 是否存在且列完整。
- 已选完整任务是否都有 baseline/context_pack 两条 prompt manifest 记录。
- prompt 文件是否存在、是否包含统一输出结构、是否包含任务描述、是否没有泄露评分字段。
- goal 验收门禁脚本是否存在、PowerShell 语法是否正确。
- goal 验收门禁 smoke 脚本是否存在、PowerShell 语法是否正确。
- owner 收集执行包、文档候选示例和任务候选示例是否存在且 CSV 列完整。
- 样本文档 manifest 是否能被 CSV 解析。
- manifest 是否至少有 10 行样本文档槽位。
- manifest 的列是否完整。
- manifest 中已填写的文件路径是否真实存在。
- `samples/raw/` 中是否有真实 PDF/Word/HTML 文档。
- 解析器评分表、基线对照表、Agent 执行日志、场景选择表是否能被 CSV 解析。
- 指定实验目录是否包含任务卡、任务用例、解析器评分表、基线对照表、Agent 执行日志、评分 rubric、Context Pack 模板和场景选择表。
- Agent 执行日志是否具备 `run_id`、`task_id`、`group`、`context_source`、`raw_output_path`、`scorer` 和 `score_status` 等必要列。
- 结构化任务用例表是否至少有 3 个完整任务用例。
- 场景选择表是否已经选出至少 3 个真实 Agent 任务。
- 已选任务是否具备 `owner`、真实来源、标准答案、证据要求和对应的完整任务用例。
- Context Pack 模板是否能被 JSON 解析。
- Agent 任务卡是否仍有占位符。
- 预检脚本、结果判定脚本、run 初始化脚本和样本文档接入脚本是否能通过 PowerShell 语法解析。
- README、Agent 调用文档和验收清单是否仍保留阶段边界：
  - 第一阶段：结构化 PDF、检索、Context Pack、REST API/Remote MCP。
  - 第二阶段：知识图谱、人工审核、版本失效。
- 方向冻结文档是否仍保留 Agent Knowledge Hub、Context Pack、baseline、Remote MCP 和阶段 2 评审门。
- goal 验收证据矩阵是否仍保留 6 条验收标准、真实实验可开跑门和阶段 2 可评审门。
- owner 收集说明是否仍包含候选文档、候选任务和真实实验输入要求。
- owner 回填自检清单是否仍包含文档候选表、任务候选表、标准答案字段、证据字段和 `READY_TO_CREATE_EXPERIMENT_RUN` 绿灯口径。

## 3. 通过标准

结构预检通过不代表实验已经验证，只代表项目文件和实验模板可用。

正式实验开跑前，严格模式应满足：

```text
FAIL = 0
真实样本文档 >= 10
任务卡无占位符
完整任务用例 >= 3
已选真实任务 >= 3
manifest 文件路径全部存在
baseline/context_pack prompt pairs ready >= 3
baseline/context_pack 结果有 agent-run-log 和 raw output 可追溯
run 级证据检查输出 READY_FOR_EVALUATION 后，才进入结果评价
```

`initialize-agent-run-log-from-tasks.ps1` 只能证明执行记录框架已准备好。它生成的 `score_status=pending` 行不会让状态脚本把实验误判为完成；只有真实 `raw_output_path` 文件存在、模型/时间等字段填写完整、评分结果完整时，才算可追溯结果。

`initialize-parser-evaluation-from-manifest.ps1` 只能证明解析器评分矩阵已准备好。它生成的 30 行待评分记录不会让状态脚本把 parser 对比误判为完成；只有页码、span、表格、阅读顺序、OCR、耗时和失败数都填入真实指标时，才算 parser 评估完成。

如果默认模式只有 `WARN`，当前状态可以继续做准备工作，但不能宣称已经完成真实文档验证。

owner 候选输入进入实验准备的建议标准：

```text
READY_TO_CREATE_EXPERIMENT_RUN
候选文档 >= 10
候选文档 source_location 本地/共享路径可达，或外部 URL 已人工确认
候选任务 >= 3
至少 1 份表格文档
至少 1 份多栏文档
至少 1 份扫描件或 OCR 风险文档
候选任务至少覆盖 3 类任务类型
```

`test-intake-readiness-smoke.ps1` 不替代真实输入检查。它只会临时生成 10 个可达文档路径和 3 个完整任务，确认 readiness 脚本在输入齐全时能返回 `READY_TO_CREATE_EXPERIMENT_RUN`，并默认清理临时文件。

## 4. 当前用途

当前阶段建议每次补充真实文档或任务卡后运行一次预检。预检通过后，再按 [11-实验执行Runbook.md](11-实验执行Runbook.md) 执行：

1. 直接给 Agent 文件的基线组。
2. 解析器对比。
3. Context Pack 组。
4. 基线 vs Context Pack 指标对比。
5. 是否进入知识图谱、人工审核和版本失效建设的决策。
