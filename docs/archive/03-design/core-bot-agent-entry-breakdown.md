# 28 Core / Bot / CLI 成品拆解

## 1. 一句话关系

```text
Knowledge Hub Core 是大脑。
群机器人 adapter 是给人用的入口。
agent-knowledge CLI 是给 Agent 用的本地入口。
```

三者关系：

```text
群用户
  -> 群机器人 adapter
  -> Knowledge Hub Core
  -> 群回复

Agent
  -> agent-knowledge CLI
  -> Knowledge Hub Core
  -> Context Pack / evidence
```

群机器人和 CLI 不能各查各的。它们必须共用同一个 Core，否则知识、证据和规则会分裂。

## 2. Knowledge Hub Core 是什么

Knowledge Hub Core 是真正干活的核心。

它负责：

- 管理文档解析产物。
- 读取统一文档模型。
- 做全文/结构/后续向量检索。
- 按任务组装 Context Pack。
- 返回证据来源。
- 标记质量 warning。
- 后续接知识图谱、版本失效、审核状态。

第一版 Core 不一定是一个复杂服务。它可以先是一个 Python 包加本地 HTTP 包装。

第一版最小能力：

```text
query(question, filters) -> answer + evidence
context_pack(task, query, files) -> context_pack + evidence
search(query, filters) -> chunks
trace(evidence_id) -> source document / page / section / text
status() -> document count / quality summary / index status
```

## 3. Core 查询接口

第一版 Core 对外统一输入：

```json
{
  "question": "重要数据出境有什么限制？",
  "task_type": "question_answer",
  "project": "",
  "module": "",
  "files": [],
  "filters": {
    "supplier": "",
    "document_version": ""
  }
}
```

第一版 Core 对外统一输出：

```json
{
  "answer": "车辆不应直接向境外传输重要数据；用户自主访问境外网站等行为不受该条限制。",
  "summary": "找到 2 条关键约束和 2 条试验方法证据。",
  "context_pack": "...",
  "evidence": [
    {
      "evidence_id": "evidence-001",
      "document": "GBT 44464-2024 汽车数据通用要求.pdf",
      "version": "2024",
      "page": 7,
      "section": "6.7 重要数据出境",
      "text": "..."
    }
  ],
  "warnings": [],
  "suggested_checks": []
}
```

注意：

- `answer` 给人读。
- `context_pack` 给 Agent 用。
- `evidence` 给人和 Agent 共同追溯。
- `warnings` 用来提示解析质量、版本不确定、证据不足。

## 4. 群机器人 adapter 是什么

adapter 是外部系统和 Core 之间的接头。

群机器人 adapter 做三件事：

1. 接收群平台消息。
2. 转成 Core 统一查询请求。
3. 把 Core 输出转成群里可读的回复。

例如飞书/企微原始消息可能很复杂，但 adapter 转给 Core 的只应该是：

```json
{
  "user": "user-001",
  "group": "diagnostics-group",
  "question": "GB/T 44464 里重要数据出境有什么限制？",
  "source": "feishu"
}
```

Core 返回后，adapter 负责组织群回复：

```text
结论：
车辆不应直接向境外传输重要数据。

关键依据：
1. 6.7 重要数据出境
2. D.8 出境试验方法

证据：
- GB/T 44464-2024，第 7 页，6.7
- GB/T 44464-2024，第 13 页，D.8

注意：
用户自主访问境外网站、通信软件传递消息或安装第三方应用不受该条限制。
```

第一版群机器人 adapter 只需要支持一个平台，建议先选团队真实会用的平台。

## 5. agent-knowledge CLI 是什么

`agent-knowledge` 是给 Agent 调用的本地命令行工具。

它不是给人日常手敲命令用的主产品，而是让 Agent 在任务中可以稳定调用知识底座。

第一版命令建议：

```powershell
agent-knowledge query "重要数据出境有什么限制？"
agent-knowledge search "D.8 出境试验方法"
agent-knowledge context-pack --task "code_review" --query "诊断模块修改需要注意什么"
agent-knowledge trace --evidence-id "evidence-001"
agent-knowledge status
```

CLI 输出默认用 JSON，方便 Agent 解析：

```powershell
agent-knowledge query "重要数据出境有什么限制？" --json
```

输出：

```json
{
  "answer": "...",
  "evidence": [],
  "warnings": []
}
```

也可以支持 markdown，方便人调试：

```powershell
agent-knowledge query "重要数据出境有什么限制？" --format markdown
```

## 6. 本地 HTTP 是什么

本地 HTTP 是给需要持续调用的 Agent 或脚本用的本地服务。

第一版可以和 CLI 共用同一套 Core：

```text
agent-knowledge serve --port 8765
```

本地 HTTP 接口：

```text
POST /query
POST /context-pack
POST /search
GET  /trace/{evidence_id}
GET  /status
```

CLI 和本地 HTTP 不应该各实现一套逻辑。它们都只是 Core 的外壳。

## 7. 第一版模块边界

推荐代码边界：

```text
knowledge_core/
  document_store
  retriever
  context_pack_builder
  evidence_tracer
  answer_formatter

agent_knowledge_cli/
  command parser
  local config
  output formatter

bot_adapter/
  platform message parser
  permission check
  reply formatter
```

边界原则：

- Core 不知道消息来自飞书、企微还是钉钉。
- Core 不知道调用者是 Codex、Cursor 还是人。
- Bot adapter 不直接读文档。
- CLI 不直接实现检索算法。
- 所有证据都从 Core 返回。

## 8. 第一版最小闭环

最小闭环不是完整知识图谱，而是：

```text
10-30 份真实文档
  -> 解析和质量 gate
  -> Core query/context_pack/trace/status
  -> agent-knowledge CLI
  -> 一个群机器人 adapter
  -> 真实问题验证
```

验收标准：

1. 群里问 3 个真实问题，能返回结论和证据。
2. Agent 用 CLI 查 3 个真实任务，能拿到 Context Pack。
3. 每条关键回答能追溯到文档、页码、章节。
4. 低质量文档证据会有 warning。
5. 同一个问题从群机器人和 CLI 得到的核心证据一致。

## 9. 不做什么

第一版不做：

- MCP。
- 完整 Web 门户。
- 图谱大屏。
- 自动学习所有经验。
- 无审核自动把抽取内容变成强事实。
- 多平台机器人同时接入。

## 10. 推荐开发顺序

```text
1. 抽出 Core 查询接口
2. 做 agent-knowledge CLI
3. 用现有 GB/T 文档跑通 CLI query/context-pack/trace
4. 做一个群机器人 adapter
5. 群机器人和 CLI 共用同一批 Core 输出
6. 再考虑知识图谱和版本治理
```
