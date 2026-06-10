# 20 Owner 收集执行包

本文用于直接发给文档 owner、领域确认人或任务评分人，收集第一轮 Agent Knowledge Hub 轻量实验所需真实输入。

目标不是收集完整知识库，而是拿到能开跑对照实验的最小闭环：

```text
10 份真实工程文档
3 个真实 Agent 任务
每个任务有标准答案要点和证据来源
```

## 1. 可直接发送的消息

```text
我们准备做 Agent Knowledge Hub 的两周轻量实验，第一轮样本范围是“混合工程文档样本”。

这轮目标不是建设知识图谱大屏，也不是做长期审核平台，而是验证：

结构化 PDF/Word/HTML + 检索 + Context Pack
是否比“直接把文件给 Agent”更稳定、更少遗漏、更可追溯。

需要你帮忙提供两类真实输入：

1. 真实工程文档
   - 2-3 份你认为 Agent 经常需要查的文档。
   - 优先选择高通、博世等供应商资料，或内部 SPEC、技术架构、详细设计、测试资料。
   - 最好包含版本、表格、接口限制、平台约束、配置项、测试要求或问题复盘。
   - 需要确认文档是否允许进入本次实验环境。

2. 真实 Agent 任务
   - 1-2 个过去真实发生过的问题，例如查约束、查接口/机制、生成测试关注点、一致性检查。
   - 每个任务要有标准答案要点。
   - 每个任务要说明答案应该引用哪份文档、哪个章节/页码/原文位置。

我们会对比两种方式：

- baseline：Agent 直接读取原始文件。
- Context Pack：Agent 调用知识服务拿到整理后的上下文。

如果 Context Pack 在准确率、遗漏率、token、耗时、证据正确率上没有明显优势，就不会进入知识图谱、人工审核台和版本失效建设。

请填写这两张表：

- .\samples\document-intake-template.csv
- .\experiments\templates\task-intake-template.csv

项目侧会用这张表跟踪请求和回收状态：

- .\samples\owner-response-tracker.csv

可参考示例：

- .\samples\document-intake-example.csv
- .\experiments\templates\task-intake-example.csv
```

也可以先导出一个独立交付包再发送：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\export-owner-package.ps1"
```

默认输出目录：

```text
.\agent-artifacts\akh-owner-package-<timestamp>\
```

生成可发送 zip，并把请求记录到 tracker：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\export-owner-package.ps1" -CreateZip -UpdateTracker -Owner "owner-name"
```

发送前校验目录或 zip：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-owner-package-readiness.ps1" -PackagePath "C:\path\to\owner-package.zip" -Strict
```

输出 `OWNER_PACKAGE_READY` 才发送。输出 `OWNER_PACKAGE_INCOMPLETE` 时，说明包内缺少说明、表格、示例、manifest 或 readiness 命令，需要重新导出或补齐后再发。

## 2. Owner 交付清单

每个 owner 最好提供：

| 类型 | 数量 | 必填信息 |
|---|---:|---|
| 文档 | 2-3 份 | 路径、标题、版本、owner、密级、是否允许实验、是否扫描件/表格/多栏 |
| 任务 | 1-2 个 | 真实来源、任务描述、允许文档、标准答案要点、必须覆盖约束、预期证据 |

第一轮总目标：

| 项 | 最低要求 |
|---|---:|
| ready 文档 | 10 份 |
| ready 任务 | 3 个 |
| 任务类型 | 至少 3 类 |
| 供应商文档 | 至少 1 份 |
| 内部 SPEC/需求文档 | 至少 1 份 |
| 内部设计或架构文档 | 至少 1 份 |
| 测试或问题复盘文档 | 至少 1 份 |
| 表格文档 | 至少 1 份 |
| 多栏文档 | 至少 1 份 |
| 扫描件/OCR 风险文档 | 至少 1 份 |

## 3. 合格文档样例

合格文档不是“随便一个 PDF”，而是能帮助验证 Agent 是否减少遗漏的文档。

合格样例：

```text
slot_type: 高通平台/BSP/接口约束文档
source_location: \\share\project\supplier\qualcomm\bsp_interface_constraints_v2.3.pdf
document_title: Qualcomm BSP Interface Constraints
document_version: v2.3
owner: 张三
is_scanned: no
has_tables: yes
has_multicolumn: no
confidentiality: internal
allowed_for_experiment: yes
candidate_reason: 包含接口限制、版本约束、配置要求和异常处理说明。
```

不合格样例：

```text
source_location: 待提供
document_title: 供应商文档
document_version: 待确认
owner: 待确认
allowed_for_experiment: 待确认
candidate_reason: 可能有用
```

问题：

- 路径不可验证。
- 版本不明确。
- 没有 owner。
- 没确认是否能进实验。
- 不知道这份文档能验证什么。

## 4. 合格任务样例

合格任务必须能被评分。不能只是“让 Agent 总结一下文档”。

合格样例：

```text
task_type: 查约束
domain: 混合工程文档样本
real_source: 某次接口改动评审中发现供应商限制和内部 SPEC 对齐关系遗漏
monthly_frequency: 4
task_description: 修改某供应商接口调用逻辑前，需要确认哪些接口限制、版本约束、配置项和测试要求？
allowed_documents: doc-candidate-001;doc-candidate-004;doc-candidate-008
gold_answer_points: 必须说明供应商接口限制；必须说明内部 SPEC 对应约束；必须说明配置项；必须提示相关测试点
required_constraints: 接口限制；版本约束；配置项；异常处理；测试覆盖
expected_evidence: 高通接口文档第 X 章；内部 SPEC 第 Y 节；测试设计第 Z 节
owner: 张三
scorer: 李四
needs_evidence: yes
selected: yes
```

不合格样例：

```text
task_description: 帮我看看这个文档有什么注意事项
gold_answer_points: 待填写
expected_evidence: 待填写
selected: 待定
```

问题：

- 任务太泛，无法评分。
- 没有标准答案。
- 没有证据来源。
- 不能判断 Context Pack 是否比直接读文件更好。

## 5. 填完后的验收命令

填写完成后，先运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict
```

如果输出：

```text
Recommendation: READY_TO_CREATE_EXPERIMENT_RUN
```

再运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-intake.ps1" -RunId "run-001" -Apply
```

如果仍然是：

```text
Recommendation: INTAKE_INCOMPLETE
```

看输出里的失败项，优先补：

1. `source_location`
2. `allowed_for_experiment`
3. `document_version`
4. `owner`
5. `gold_answer_points`
6. `expected_evidence`
7. `selected`

## 6. 当前不要让 owner 做的事

不要要求 owner：

- 设计知识图谱 schema。
- 标实体/关系。
- 设计审核台流程。
- 判断版本失效策略。
- 搭 MCP 或 API。

这轮只要真实文档、真实任务、标准答案和证据来源。
