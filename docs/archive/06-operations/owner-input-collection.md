# 19 Owner 真实输入收集说明

本文用于向文档 owner、领域确认人或任务评分人收集第一阶段实验需要的真实文档和真实 Agent 任务。目的不是收集越多越好，而是拿到能验证 Context Pack 价值的最小闭环输入。

如果要直接转发给 owner，优先使用：

```text
.\docs\20-owner收集执行包.md
```

填表示例：

```text
.\samples\document-intake-example.csv
.\experiments\templates\task-intake-example.csv
```

## 1. 需要 owner 提供什么

每个 owner 至少提供：

- 2-3 份真实工程文档。
- 1-2 个真实 Agent 任务。
- 每个任务的标准答案要点。
- 每个任务必须引用的证据来源。
- 文档是否允许进入实验环境的确认。

第一轮总目标：

```text
10 份真实文档 + 3 个以上真实 Agent 任务
```

## 2. 文档候选表

填写：

```text
.\samples\document-intake-template.csv
```

字段含义：

- `slot_type`：文档属于哪个样本槽位。
- `source_location`：原始文档路径或可访问位置；本地盘符路径和共享盘路径会被脚本检查是否存在，HTTP/HTTPS 链接会被标记为外部来源，需要人工确认。
- `document_title`：文档标题。
- `document_version`：版本号、发布日期或基线版本。
- `owner`：能确认文档有效性的人。
- `is_scanned`：是否扫描件。
- `has_tables`：是否包含重要表格。
- `has_multicolumn`：是否多栏排版。
- `confidentiality`：密级或传播范围。
- `allowed_for_experiment`：是否允许用于本实验。
- `candidate_reason`：为什么这份文档适合作为样本。

入选后再复制真实文件到：

```text
.\samples\raw\
```

然后用 `import-sample-docs.ps1` 生成 manifest 草稿。

## 3. 任务候选表

填写：

```text
.\experiments\templates\task-intake-template.csv
```

字段含义：

- `task_type`：查约束、查接口/机制、生成测试关注点等。
- `real_source`：这个任务来自哪里，例如缺陷、评审、设计修改、测试补充。
- `monthly_frequency`：类似任务每月大概出现几次。
- `task_description`：给 Agent 的真实任务描述。
- `allowed_documents`：任务允许使用哪些文档。
- `gold_answer_points`：人工认可的标准答案要点。
- `required_constraints`：必须覆盖的关键约束。
- `expected_evidence`：预期引用的文档、章节、页码或原文位置。
- `owner`：任务业务 owner、文档 owner 或领域确认人。
- `scorer`：实验评分人。
- `needs_evidence`：是否必须带证据。
- `selected`：是否入选第一轮实验。

入选任务需要同步写入真实 run 目录中的：

```text
experiments\runs\<run-id>\agent-task-cases.csv
experiments\runs\<run-id>\scenario-selection-matrix.csv
experiments\runs\<run-id>\agent-task-cards.md
```

## 4. 发送给 owner 的请求模板

可以直接发送：

```text
我们在做 Agent Knowledge Hub 的两周轻量实验，目标是验证“结构化 PDF + 检索 + Context Pack”是否比直接把文档给 Agent 更稳定。

这轮不做知识图谱大屏，也不做审核台，只需要真实输入来跑对照实验。

请帮忙提供：
1. 2-3 份你认为 Agent 经常需要查的真实工程文档，优先覆盖高通、博世等供应商资料，或内部 SPEC、技术架构、详细设计、测试资料。
2. 1-2 个真实 Agent 任务，例如查约束、查接口机制、生成测试关注点、一致性检查。
3. 每个任务的标准答案要点，以及答案应该引用哪份文档、哪个章节或页码。
4. 文档是否允许进入本次实验环境。

我们会用这些输入对比两种方式：
- baseline：Agent 直接读原始文件。
- Context Pack：Agent 通过知识服务拿到整理后的上下文。

如果 Context Pack 在准确率、遗漏率、token、耗时、证据正确率上没有明显优势，就不会继续扩建知识图谱和审核台。
```

## 5. 入选标准

优先选择：

- Agent 使用频率高的任务。
- 直接读文档容易漏约束的任务。
- 有明确标准答案的任务。
- 有明确证据位置的任务。
- 涉及版本、平台、接口、测试约束的文档。

暂不选择：

- 只有泛泛总结的问题。
- 没有 owner、确认人或评分人能确认答案的问题。
- 文档不能进入实验环境的问题。
- 没有证据来源的问题。

## 6. 收集完成后的动作

1. 运行 intake readiness 检查，确认候选输入是否够开实验。
2. 运行 `apply-document-intake-to-samples.ps1 -Apply`，把入选文档复制到 `samples/raw/` 并更新正式 manifest。
3. 如未使用候选文档表，也可以手工复制文档后运行 `import-sample-docs.ps1 -WriteDraft`。
4. 人工确认样本文档 manifest。
5. 创建实验 run。
6. 用 `apply-task-intake-to-run.ps1` 把已选候选任务写入 run 目录。
7. 运行 run 级严格预检。

如果候选文档和候选任务都已填写完整，也可以用编排脚本执行上述主路径：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-intake.ps1" -RunId "run-001" -Apply
```

不带 `-Apply` 时只做严格 readiness 检查，不复制文档、不创建 run、不写 manifest。

验证这条完整准备链路：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-prepare-experiment-run-smoke.ps1"
```

命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1"
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-document-intake-to-samples.ps1" -Apply
powershell -ExecutionPolicy Bypass -File ".\scripts\new-experiment-run.ps1" -RunId "run-001"
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-task-intake-to-run.ps1" -RunId "run-001"
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

如果要把候选输入不足也视为失败，使用：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict
```

`check-intake-readiness.ps1` 会额外检查：

- 候选文档 `source_location` 是否已填写。
- 本地或共享路径是否真实存在。
- HTTP/HTTPS 来源是否需要人工确认。
- 是否至少有 10 份 ready 文档。
- 是否覆盖表格、多栏、扫描件或 OCR 风险文档。
- 是否至少有 3 个已选且完整的真实 Agent 任务。
