# 13 下一步执行待办

当前文档路线、实验设计、指标和模板已准备好。下一步需要真实文档和真实任务才能进入实验执行。

## 1. 必须补齐的输入

可以先按 [20-owner收集执行包.md](20-owner收集执行包.md) 向文档 owner、领域确认人或任务评分人收集候选文档和候选任务，再从候选项中选择第一轮实验输入。

owner 填表参考：

```text
.\samples\document-intake-example.csv
.\experiments\templates\task-intake-example.csv
```

owner 请求和反馈进展记录：

```text
.\samples\owner-response-tracker.csv
```

查看 owner 收集缺口摘要：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\report-owner-intake-status.ps1"
```

如果需要给 owner 一个独立交付包，先运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\export-owner-package.ps1"
```

脚本会把收集说明、候选表、示例和跟踪表导出到 `.\agent-artifacts\akh-owner-package-<timestamp>\`。

发送给 owner 前，先检查目录或 zip 包是否完整：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-owner-package-readiness.ps1" -PackagePath "C:\path\to\owner-package.zip" -Strict
```

只有输出 `OWNER_PACKAGE_READY`，才发送给 owner。若输出 `OWNER_PACKAGE_INCOMPLETE`，先补齐缺失文件或重新导出。

owner 返回填好的目录或 zip 后，先 dry run 导入：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip"
```

确认导入计划后再写入正式 intake 表：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip" -Apply
```

如果希望把“导入 owner 返回包、检查 readiness、准备实验 run”串成一个入口，先 dry run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip" -RunId "run-001"
```

确认 dry run 通过后再写入正式 intake 并创建 run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip" -RunId "run-001" -Apply
```

### 1.1 真实样本文档

把 10 份左右真实文档放入：

```text
.\samples\raw\
```

然后更新：

```text
.\samples\sample-manifest.csv
.\samples\README.md
```

最低要求：

- 至少 1 份高通、博世或其他供应商工程文档。
- 至少 1 份内部 SPEC/需求文档。
- 至少 1 份内部架构或详细设计文档。
- 至少 1 份测试设计或问题复盘文档。
- 至少 1 份含表格文档。
- 至少 1 份多栏文档。
- 至少 1 份扫描件或 OCR 风险文档。

### 1.2 真实 Agent 任务

填写：

```text
.\experiments\templates\agent-task-cards.md
.\experiments\templates\agent-task-cases.csv
.\experiments\templates\scenario-selection-matrix.csv
```

最低要求：

- 3 个真实任务。
- 每个任务有标准答案要点。
- 每个任务有评分人或 owner。
- 每个任务至少有一个预期证据来源。
- `scenario-selection-matrix.csv` 中至少 3 个任务标记为已选。

## 2. 文档到位后的执行顺序

1. 更新样本文档 manifest。
2. 用样本文档接入脚本生成 manifest 草稿，人工确认后应用。
3. 更新任务卡。
4. 运行预检脚本，确认真实文档、任务卡和模板没有阻塞问题。
5. 创建独立实验 run 目录，不直接改模板。
6. 在 run 目录里填写 3 个以上完整任务用例和场景选择表。
7. 根据已选任务初始化 baseline/context_pack 对照结果表。
8. 对 run 目录执行严格预检。
9. 跑“直接给 Agent 文件”的基线组。
10. 用 Docling / MinerU / Unstructured 解析同一批文档。
11. 填写解析器评分表。
12. 生成第一版 Context Pack。
13. 跑 Context Pack 实验组。
14. 填写对照结果表。
15. 运行结果判定脚本。
16. 填写实验结论汇总。
17. 决定是否进入阶段 2：知识图谱、人工审核、版本失效。

预检命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs
```

统一状态报告命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\report-experiment-status.ps1"
```

如果已经创建 run 目录，使用 run 级预检：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

结果判定命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1"
```

解析器评分判定命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

创建 run 目录命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\new-experiment-run.ps1" -RunId "run-001"
```

真实 run 填表说明：

```text
.\docs\17-真实实验填表指南.md
```

生成样本文档 manifest 草稿命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-sample-docs.ps1" -WriteDraft
```

检查 owner 候选输入是否足够创建实验 run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1"
```

候选文档和候选任务都 ready 后，一步准备实验 run。该脚本会复制文档、创建 run、写任务、初始化 baseline/context_pack 结果占位行，并生成成对 prompt：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-intake.ps1" -RunId "run-001" -Apply
```

如果是手工创建 run，可以单独根据已选任务初始化 baseline/context_pack 对照结果表：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\initialize-results-from-tasks.ps1" -RunId "run-001" -Apply
```

验证完整准备链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-prepare-experiment-run-smoke.ps1"
```

验证对照结果表初始化链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-result-initialization-smoke.ps1"
```

验证 owner 收集包导出链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-smoke.ps1"
```

验证 owner 收集包发送前校验链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-readiness-smoke.ps1"
```

验证 owner intake 状态报告链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-intake-status-smoke.ps1"
```

验证 owner 返回包导入链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-import-smoke.ps1"
```

验证 owner 返回包到实验 run 准备的一键链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-owner-package-to-run-smoke.ps1"
```

把 owner 候选文档接入样本目录和 manifest：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-document-intake-to-samples.ps1" -Apply
```

验证 owner 候选输入检查的绿灯路径：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-intake-readiness-smoke.ps1"
```

验证候选文档到样本文档 manifest 的桥接路径：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-document-intake-to-samples-smoke.ps1"
```

真实输入收集入口：

```text
.\docs\19-模块Owner真实输入收集说明.md
.\docs\20-owner收集执行包.md
.\docs\21-owner响应跟踪说明.md
.\samples\document-intake-template.csv
.\samples\owner-response-tracker.csv
.\experiments\templates\task-intake-template.csv
```

## 3. 当前不应启动的工作

在真实文档和真实任务未补齐前，不建议启动：

- Neo4j 图谱建模。
- 人工审核台开发。
- 版本失效推理。
- 正式影响分析。
- IDE 插件。

这些都依赖阶段 1 的实验结论。
