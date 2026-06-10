# 18 方向冻结与阶段门

本文用于冻结当前方向，避免第一阶段在“PDF 问答、知识图谱大屏、Agent Memory、IDE 插件、MCP 接入”之间摇摆。

## 1. 冻结结论

当前方向冻结为：

```text
工程知识助手双入口产品：
把工程文档加工成可追溯知识底座，通过群机器人给人用，通过 Agent 本地入口给 Agent 用。
```

第一版只验证：

```text
结构化文档 + 混合检索 + Context Pack + 群机器人 demo + Agent 本地 CLI/HTTP demo
```

第一版的核心问题有两个：

```text
人通过群机器人问工程文档，是否比翻文档更快、更可信？
Agent 通过本地入口拿 Context Pack，是否比直接读文件更稳定？
```

## 2. 第一阶段范围

必须做：

- 10 份真实样本文档登记。
- 3 个以上真实人工问题。
- 3 个以上真实 Agent 任务。
- 直接给 Agent 文件的 baseline。
- PDF/Word/HTML 解析质量对比。
- 全文检索和向量检索。
- Context Pack 组装。
- 群机器人问答 demo。
- Agent 本地 CLI 或本地 HTTP 调用契约。
- baseline vs Context Pack 结果判定。

暂不做：

- 完整知识图谱。
- 图谱大屏。
- 实体审核台。
- 版本失效推理。
- 正式影响分析。
- IDE 插件。
- Agent 自我记忆或 skill 沉淀。
- MCP 接入。
- 完整生产级群机器人权限和审计。

## 3. 阶段门

### 3.1 进入实验执行门

只有满足以下条件，才开始真实 baseline 和 Context Pack 对照实验：

- `samples/raw/` 中至少有 10 份真实 PDF/Word/HTML/Markdown/TXT 文档。
- `samples/sample-manifest.csv` 中 10 份文档路径真实存在。
- `experiments/runs/<run-id>/agent-task-cases.csv` 至少有 3 个完整任务。
- `experiments/runs/<run-id>/scenario-selection-matrix.csv` 至少选出 3 个真实任务。
- 已选任务有 owner、真实来源、标准答案和证据要求。
- `agent-task-cards.md` 不含占位符。
- 至少准备 3 个群机器人问答场景，且每个场景有期望证据来源。

验证命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\preflight.ps1" -StrictRealInputs -ExperimentDir ".\experiments\runs\run-001"
```

### 3.2 进入阶段 2 评审门

真实实验完成后，只有满足以下条件，才讨论知识图谱、人工审核、版本失效和更深 Agent 集成：

- baseline/context_pack 至少有 3 个完整任务对。
- Context Pack 证据正确率 >= 90%。
- 准确率、遗漏率、token、耗时 4 个维度中至少 2 个明显优于 baseline。
- 实验总结能说明直接给文件的失败模式。
- 实验总结能说明单纯检索是否已经足够，还是确实需要跨文档关系。
- 群机器人问答至少能稳定返回结论和可追溯证据。
- Agent 本地入口至少能返回 Context Pack 和 evidence trace。

验证命令：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1" -ResultsPath ".\experiments\runs\run-001\baseline-vs-contextpack-results.csv"
```

输出 `READY_FOR_PHASE_2_REVIEW` 只代表可以进入人工评审，不代表自动启动阶段 2。

## 4. 停止条件

如果出现以下结果，应停止扩建平台，回到更简单方案：

- Agent 直接读文件已经足够稳定。
- Context Pack 只降低 token，但准确率和遗漏率没有改善。
- 证据正确率低于 90%。
- 真实任务里没有跨文档、多版本或多约束需求。
- 维护文档解析和 Context Pack 的成本高于收益。
- 群机器人问答不能比人工翻文档更快或更可信。
- Agent 本地入口不能比直接给文件更稳定。

可替代方案：

- PDF 转 Markdown 后放入 Git 仓库。
- 内部 Wiki + 简单 RAG。
- 只做文档转换和搜索，不做 Knowledge Hub。

## 5. 当前方向确认

截至当前阶段：

- 第一批样本范围为混合工程文档样本，覆盖供应商资料和内部工程文档。
- 系统定位是 Agent Knowledge Hub，不是 PDF 问答。
- 成品定位是工程知识助手双入口，不是当前工程脚手架。
- 人的入口是群机器人。
- Agent 的入口第一版优先本地 CLI / 本地 HTTP / SDK / 只读知识包。
- 当前成品路线不走 MCP。
- 核心输出仍是 Context Pack 和 evidence trace，不是原始 chunk。
- 知识图谱、人工审核、版本失效是后续增强，不是第一版前置依赖。

当前不能宣称：

- 已完成真实文档验证。
- 已证明 Context Pack 优于直接给文件。
- 已需要知识图谱。
- 已需要审核台。
- 已需要版本失效系统。
- 已完成群机器人成品。
- 已完成 Agent 本地调用成品。
- 需要 MCP。
