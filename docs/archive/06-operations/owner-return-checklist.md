# 23 Owner 回填自检清单

返回 owner 收集包前，请逐项确认。没有通过自检的输入，很可能无法创建真实实验 run。

## 1. 文档表自检

文件：

```text
samples/document-intake-template.csv
```

- 至少填写 2-3 份真实工程文档。
- `source_location` 是可访问路径、共享盘路径，或已说明需要人工确认的 URL。
- `document_title` 能让评分人识别文档。
- `document_version` 已填写版本号、发布日期或项目基线。
- `owner` 是能确认文档有效性的人。
- `allowed_for_experiment` 已明确填写 `yes` 或 `no`。
- `candidate_reason` 说明了这份文档能验证什么，例如约束、接口、表格、多栏或 OCR 风险。
- 已标出是否扫描件、是否含表格、是否多栏。

## 2. 任务表自检

文件：

```text
experiments/templates/task-intake-template.csv
```

- 至少填写 1-2 个真实发生过的 Agent 任务。
- `task_description` 是可以直接交给 Agent 执行的问题。
- `real_source` 说明任务来自缺陷、评审、设计修改、测试补充或真实咨询。
- `allowed_documents` 指向文档表中的 `candidate_id`。
- `gold_answer_points` 写清楚标准答案要点。
- `required_constraints` 写清楚必须覆盖的关键约束。
- `expected_evidence` 写清楚预期文档、章节、页码或原文位置。
- `scorer` 是能判断答案是否正确的人。
- 入选任务的 `needs_evidence` 和 `selected` 填写 `yes`。

## 3. 不合格输入

以下情况会导致实验无法开跑：

- 文档路径写 `待提供`。
- 文档版本写 `待确认`。
- 任务是“总结一下这个文档”这类泛化问题。
- 没有标准答案要点。
- 没有预期证据位置。
- 文档不能进入实验环境，但没有标明替代方案。

## 4. 返回后项目侧检查

项目侧会运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict
```

只有看到下面这个推荐结论，才说明 owner 输入足够创建真实实验 run：

```text
Recommendation: READY_TO_CREATE_EXPERIMENT_RUN
```

检查项包括：

- ready 文档是否达到 10 份。
- ready 任务是否达到 3 个。
- 是否覆盖 3 类任务类型。
- 是否至少有 1 份表格文档、1 份多栏文档、1 份扫描/OCR 风险文档。
- 本地或共享路径是否真实存在。
- 入选任务是否有标准答案、关键约束、证据位置、owner 和 scorer。
