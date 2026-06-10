# 27 成品形态：群机器人与 Agent 本地入口

## 1. 最新产品定位

本项目的成品不是把当前工程脚手架交给使用者，也不是只做 PDF 问答或知识图谱大屏。

最新定位是：

```text
工程知识助手双入口产品

工程文档 / 供应商资料 / 内部 SPEC / 架构设计
  -> 文档解析
  -> 统一知识模型
  -> 检索索引 / 知识图谱 / Context Pack
  -> 群机器人入口
  -> Agent 本地入口
```

核心目标：

让人和 Agent 都能稳定查询工程文档知识，并拿到可追溯证据。

## 2. 两个成品入口

### 2.1 群机器人入口

群机器人服务团队成员的日常提问。

典型问题：

- 高通某接口在哪个文档定义？
- 博世某约束对我们内部 SPEC 有什么影响？
- GB/T 44464 里重要数据出境有什么限制？
- 某个测试项依据来自哪一页？
- 某个模块改动可能影响哪些文档？

推荐链路：

```text
企业微信 / 飞书 / 钉钉 群消息
  -> Bot 服务
  -> Knowledge Hub Core
  -> 检索 / 图谱 / Context Pack
  -> 回答 + 证据来源
```

返回格式要适合人在群里阅读：

```text
结论
关键依据
证据来源：文档 / 版本 / 页码 / 章节
可能影响范围
下一步建议
```

### 2.2 Agent 本地入口

Agent 本地入口服务 Codex、Cursor、Copilot、自研 Agent 或其他本地工作流。

这里不走 MCP。第一版推荐：

```text
本地 CLI
本地 HTTP 服务
本地 SDK
本地只读知识包
```

典型调用：

```text
agent-knowledge query --module 诊断 --question "这个 DTC 状态同步有什么约束？"
agent-knowledge context-pack --task "review diff" --files changed-files.txt
agent-knowledge trace --evidence-id evidence-001
```

推荐链路：

```text
Agent
  -> 本地 CLI / 本地 HTTP / SDK
  -> 本地知识索引或同步下来的只读知识包
  -> Context Pack / evidence trace / checklist
  -> Agent 编码、分析、review 时使用
```

Agent 入口返回格式要适合机器消费：

```json
{
  "answer": "...",
  "context_pack": "...",
  "evidence": [],
  "warnings": [],
  "quality": {},
  "suggested_checks": []
}
```

## 3. Knowledge Hub Core

两个入口共享同一个核心能力：

```text
文档接入
  -> 文档解析
  -> Canonical Document Model
  -> chunks / sections / metadata
  -> 检索索引
  -> 知识图谱
  -> Context Pack
  -> 证据追溯
```

核心能力包括：

- 多格式文档接入：PDF、Word、Markdown、HTML、TXT。
- 解析质量 gate：低质量文档不能和高质量正文证据同等使用。
- 混合检索：全文、结构、规则、后续可加 embedding。
- 知识图谱：表达文档、章节、模块、接口、需求、约束、测试项之间的关系。
- Context Pack：把任务相关证据压缩成 Agent 可消费上下文。
- 证据追溯：回答能回到文档、版本、页码、章节和原文片段。

## 4. 和直接把文件给 Agent 的区别

直接给文件的问题：

- 每次都重新读 PDF/Word，成本和耗时不可控。
- 大文档、扫描件、表格、多栏文本容易让 Agent 混乱。
- 多文档时容易混淆版本、供应商、项目和适用范围。
- 输出结论后很难稳定追溯到页码、章节、原文。
- 人和 Agent 不能共享同一套工程知识结果。

本产品的区别：

- 文档先被结构化和质量评估。
- 查询只返回任务相关证据，不是整份文件。
- 群机器人和 Agent 本地入口共享同一个知识底座。
- 每条结论带证据来源。
- 可以逐步沉淀知识图谱、checklist、影响分析和历史经验。

## 5. 不走 MCP 的原因

MCP 不进入当前成品路线。

当前定位收敛为：

```text
CLI / 本地 HTTP / SDK = 第一版 Agent 本地入口
Bot API = 群机器人入口
```

原因：

- 群机器人不需要 MCP。
- 很多 Agent 可以稳定调用本地命令或 HTTP。
- 本地 CLI/HTTP 更容易和当前文件、diff、编译错误、分支信息组合。
- 不围绕 MCP 设计，可以降低本地配置、协议适配和推广成本。
- 已有 MCP 代码只作为早期实验遗留，不作为成品入口。

## 6. 第一版成品建议

第一版不要先做完整知识图谱大系统。

建议先做：

```text
10-30 份真实工程文档
  -> 文档解析
  -> 质量报告
  -> 检索索引
  -> Context Pack
  -> 群机器人问答 demo
  -> 本地 CLI 查询 demo
```

第一版必须回答三个问题：

1. 人在群里问工程文档问题，是否比翻文档更快、更可信？
2. Agent 通过本地入口拿 Context Pack，是否比直接读文件更稳定？
3. 每个答案是否能追溯到文档、版本、页码和章节？

## 7. 第一版不做什么

第一版不承诺：

- 完整知识图谱已经成熟。
- 所有供应商文档都能自动理解。
- 任何 MCP 接入能力。
- 群机器人能替代专家判断。
- Context Pack 已经证明优于直接给文件。

这些都要通过真实文档、真实问题、真实 Agent 输出和人工复核逐步证明。

## 8. 推荐落地顺序

```text
Step 1：固定知识核心
  文档解析、质量 gate、检索、Context Pack、证据追溯

Step 2：做本地 Agent CLI
  query / context-pack / trace / status

Step 3：做群机器人 demo
  接入企业微信、飞书或钉钉其中一个

Step 4：跑真实问题集
  人工问题 + Agent 任务双评测

Step 5：再扩知识图谱
  模块、接口、需求、约束、测试项、版本关系
```

## 9. 当前工程和成品的关系

当前工程已经做出的解析、Context Pack、证据追溯、A/B eval、readiness gate，属于 Knowledge Hub Core 的验证和工具链。

但使用者最终不应该直接面对这些工程脚本。

成品应该让使用者面对：

```text
群机器人
本地 CLI / HTTP / SDK
```

而不是：

```text
pytest
eval-run CSV
artifact 目录
工程脚本参数
```
