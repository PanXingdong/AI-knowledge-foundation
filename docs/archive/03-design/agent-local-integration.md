# 04 Agent 本地调用方式

## 1. 调用目标

Agent 调用本系统，不是为了拿到一堆原始文件，而是为了拿到当前任务需要的结构化上下文。

最新成品方向里，Agent 入口第一版不走 MCP，而是支持：

```text
本地 CLI
本地 HTTP
SDK
只读知识包
```

核心输出是：

```text
Context Pack
```

第一阶段的调用能力只依赖结构化文档块、全文检索、向量检索和最小证据链。知识图谱、人工审核和版本失效是第二阶段能力，不作为第一阶段调用前提。

## 2. 为什么不是直接返回 PDF

直接返回 PDF 的问题：

- Agent 不知道哪些页重要。
- 上下文太大。
- 每次解析成本高。
- 容易漏掉跨文档关系。
- 无法区分已确认知识和未确认候选。
- 无法处理版本适用范围。

Context Pack 的优势：

- 小而相关。
- 带证据。
- 带版本。
- 已按任务类型组织。
- 可直接放入 Agent prompt。
- 多个 Agent 调用结果一致。

## 3. Context Pack 输入

典型请求：

```json
{
  "project": "ProjectA",
  "module": "diagnostics",
  "task_type": "code_change",
  "files": [
    "src/diagnostics/dtc_manager.cpp"
  ],
  "query": "修改 DTC 状态同步逻辑需要注意什么",
  "version": {
    "platform": "QNX",
    "bsp": "1.3"
  }
}
```

## 4. Context Pack 输出

建议输出：

```json
{
  "status": "success",
  "summary": "找到 4 条约束、3 个相关接口、2 个建议测试项。",
  "task_context": {
    "project": "ProjectA",
    "module": "diagnostics",
    "task_type": "code_change"
  },
  "must_read": [
    {
      "title": "DTC 状态同步约束",
      "summary": "修改 DTC 状态时需要同步更新清除状态和持久化状态。",
      "evidence_id": "span_001"
    }
  ],
  "constraints": [],
  "interfaces": [],
  "related_sections": [],
  "risks": [],
  "tests_to_consider": [],
  "evidence": [
    {
      "evidence_id": "span_001",
      "document": "Diagnostic_SPEC_v2.1.pdf",
      "version": "2.1",
      "page": 18,
      "section": "3.2.4",
      "text": "..."
    }
  ],
  "open_questions": [],
  "confidence": 0.84
}
```

## 5. 本地 CLI / 本地 HTTP

### 5.1 第一版本地 CLI

第一版建议先做 Agent 容易调用的本地命令：

```powershell
agent-knowledge query --question "重要数据出境有什么限制？"
agent-knowledge context-pack --task "review diff" --files changed-files.txt
agent-knowledge trace --evidence-id evidence-001
agent-knowledge status
```

本地 CLI 的优势：

- 不依赖 MCP。
- 各类 Agent 都能通过 shell 调用。
- 容易和当前文件、diff、branch、编译错误组合。
- 适合作为 Agent 本地入口的最小可用版本。

### 5.2 第一版本地 HTTP

本地 HTTP 适合需要持续服务的 Agent 或脚本：

```text
POST /api/context-pack
GET  /api/evidence/{evidence_id}
POST /api/search
POST /api/documents
GET  /api/documents/{document_id}/versions
```

其中：

- `/api/context-pack`：根据任务和查询返回 Context Pack。
- `/api/evidence/{evidence_id}`：回溯文档、版本、页码、章节、span。
- `/api/search`：全文、向量、混合检索。
- `/api/documents`：登记样本文档。
- `/api/documents/{document_id}/versions`：只记录文档版本元数据，不做版本失效推理。

当前代码里已经落地的阶段 1 接口是：

```text
GET  /health
POST /api/context-pack
POST /api/search
POST /api/gap-report
GET  /api/evidence/{evidence_id}
```

说明：

- `/api/context-pack`：已实现，返回 `sections[]`、`selected_chunks[]` 和 markdown。
- `/api/search`：已实现，返回排序后的 chunk 结果。
- `/api/gap-report`：已实现，先自动生成 context pack，再与人工参考包比对。
- `/api/evidence/{evidence_id}`：已实现，返回证据原文、章节、页码和关联 chunk。
- `/api/documents`、`/api/documents/{document_id}/versions`：仍是阶段 1 规划项，尚未实现。

### 5.3 中心 REST API

中心 REST API 仍然可以保留，用于群机器人、内部系统或后续 Web 控制台调用。

### 5.4 阶段 2 API

阶段 2 进入知识图谱、审核和版本失效后，再增加：

```text
GET  /api/entities/{entity_id}
GET  /api/entities/{entity_id}/related
POST /api/impact-analysis
POST /api/review/items/{item_id}/decision
POST /api/document-version-diff
```

## 6. 历史 MCP 遗留

MCP 不进入当前成品路线。

### 6.1 已有遗留实现

早期实验中曾实现以下 MCP tools：

```text
get_context_pack
search_knowledge
trace_evidence
```

当前代码里已经落地的 MCP adapter 只作为历史验证入口：

- 启动脚本：[scripts/start-context-pack-mcp.ps1](../scripts/start-context-pack-mcp.ps1)
- Python 入口：[src/agent_knowledge_hub/mcp_server.py](../src/agent_knowledge_hub/mcp_server.py)
- transport：`streamable-http` / `stdio` / `sse`
- 默认 remote endpoint：`http://127.0.0.1:8788/mcp`
- 启动参数使用 `-BindHost`，避免和 PowerShell 内置 `$Host` 变量冲突

当前 smoke 验证脚本：

- [scripts/test-context-pack-mcp-smoke.ps1](../scripts/test-context-pack-mcp-smoke.ps1)

### 6.2 不再扩展的 MCP Tools

以下曾作为阶段 2 设想，现在不进入当前成品路线：

```text
get_entity_card
find_related_entities
impact_analysis
compare_document_versions
submit_feedback
```

## 7. Agent 使用流程

### 7.1 写代码

```text
用户让 Agent 修改代码
  -> Agent 识别项目/模块/文件
  -> 调本地 CLI/HTTP 获取 Context Pack
  -> 根据约束和证据制定方案
  -> 修改代码
  -> 调本地 CLI/HTTP 搜索遗漏
  -> 后续可基于知识图谱做正式影响分析
```

### 7.2 做 review

```text
Agent 获取 diff
  -> 调本地 CLI/HTTP 获取 code_review Context Pack
  -> 获取模块约束、接口规则、测试要求
  -> 生成 review comment
  -> 每条关键 comment 可追溯证据
```

### 7.3 做测试设计

```text
Agent 获取需求/变更说明
  -> 调本地 CLI/HTTP 获取 test_design Context Pack
  -> 获取相关文档片段、约束和轻量影响提示
  -> 生成测试点
  -> 后续可基于知识图谱找到正式影响路径
```

## 8. 权限和审计

每次调用应记录：

- caller
- agent type
- project
- query
- returned evidence
- token size
- user feedback

权限至少按：

```text
组织
项目
文档来源
密级
角色
```

控制。
