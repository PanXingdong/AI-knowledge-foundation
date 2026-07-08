# Knowledge Hub VS Code 扩展

这是用于远程 Knowledge Hub 服务的 VS Code 扩展。它把工程知识库检索能力接入 VS Code，让开发者可以在 IDE 内通过 `Ask Knowledge Hub` 命令提问，并由 GitHub Copilot 基于远程 Context Pack 生成回答。

这个扩展不在本地保存完整知识库，也不自己实现检索逻辑。知识库、索引、检索排序和证据追踪都由远程 Knowledge Hub 服务负责；VS Code 扩展只负责 IDE 交互、调用远程 Context Pack API、把检索上下文交给 Copilot 生成回答，并展示精简后的证据摘要。

## 适用场景

- 团队希望把工程文档、规范、供应商资料、测试材料等集中部署在远程 Knowledge Hub 服务上。
- 开发者希望在 VS Code 中直接提问，而不是手动打开文档或复制 Context Pack。
- 希望回答可追溯到证据片段，通过 `evidence_id` 回查来源文档、章节、页码和原文。
- 不希望使用 MCP server，而是通过普通 HTTP API 对接 VS Code 扩展。

运行流程：

```text
调用 Ask Knowledge Hub 命令
  -> POST /api/knowledge-bases/{knowledge_base_id}/context-pack
  -> 将问题 + 远程服务返回的 formatted_context / Context Pack + 回答规则发送给 VS Code 中的 Copilot
  -> 在 Knowledge Hub 输出通道中渲染回答和证据摘要
  -> 可选：调用 Knowledge Hub: Trace Evidence 查看证据详情
```

## 功能

- `Ask Knowledge Hub`：输入问题，调用远程知识库获取 Context Pack，再交给 Copilot 生成回答。
- `Knowledge Hub: Trace Evidence`：输入 evidence id，调用远程 evidence trace API 查看证据来源。
- `Knowledge Hub: Select Copilot Model`：读取当前 VS Code / Copilot 可用模型列表，手动固定一个模型供后续回答持续使用，直到下次手动修改。
- 支持远程 `knowledge_base_id`，例如 `qnx-main`，避免在 IDE 侧暴露服务器文件路径。
- 支持 Bearer Token 鉴权。
- 支持配置 `task_type`、`topK`、`perDocumentLimit`。
- 默认输出精简回答、问题、知识库 ID 和最多 3 条证据摘要；调试模式下可额外显示模型元数据、prompt 预览和完整请求诊断。

## 前置条件

使用扩展前需要准备：

- VS Code `1.93.0` 或更高版本。
- 已登录并启用 GitHub Copilot / Copilot Chat。
- 可访问的远程 Knowledge Hub 服务。
- 服务端已配置至少一个 `knowledge_base_id`。
- 如果服务端启用了 `KNOWLEDGE_HUB_API_TOKEN`，需要拿到对应 token。

## 服务端准备

在本仓库中，可以使用一键脚本把当前机器启动为远程 Knowledge Hub 服务：

```bash
./scripts/start-knowledge-hub-remote.sh
```

脚本会优先复用与飞书机器人一致的环境变量：

```text
PROCESSED_DIR
FTS_INDEX_PATH
VECTOR_INDEX_PATH
DEFAULT_TOP_K
DEFAULT_PER_DOCUMENT_LIMIT
DEFAULT_TASK_TYPE
```

如果这些环境变量未设置，脚本默认配置为：

```text
host = 0.0.0.0
port = 8787
knowledge_base_id = qnx-main
processed_dir = samples/golden
token = local-dev-token
```

如果你已经有别人打包好的知识库目录，推荐直接在 `.env` 中配置：

```text
PROCESSED_DIR=/path/to/all_knowledge_processed
FTS_INDEX_PATH=/path/to/all_knowledge_fts_index.db
DEFAULT_TOP_K=8
DEFAULT_PER_DOCUMENT_LIMIT=2
KNOWLEDGE_HUB_SKIP_PREWARM=1
```

说明：

- `PROCESSED_DIR` 是主内容源，必须包含 `chunks.jsonl` 和 `canonical-document.json`。
- `FTS_INDEX_PATH` 不是可选装饰。对于具体符号、属性、宏、命令名检索，缺少 FTS 往往会明显降低命中质量。
- `KNOWLEDGE_HUB_SKIP_PREWARM=1` 可避免大知识库在服务启动阶段长时间阻塞；首次真实查询仍可能较慢。

脚本启动后会打印可复制的 VS Code 配置，例如：

```json
{
  "knowledgeHub.baseUrl": "http://10.49.98.224:8787",
  "knowledgeHub.token": "local-dev-token",
  "knowledgeHub.defaultKnowledgeBaseId": "qnx-main"
}
```

也可以指定真实知识库目录和端口：

```bash
./scripts/start-knowledge-hub-remote.sh \
  --host 0.0.0.0 \
  --port 8787 \
  --knowledge-base-id qnx-main \
  --processed-dir /srv/knowledge/qnx/processed \
  --fts-index-path /srv/knowledge/qnx/index/chunks.db \
  --vector-index-path /srv/knowledge/qnx/index/chunks.vector.json \
  --token your-token
```

也可以直接通过环境变量启动服务：

```bash
export PYTHONPATH="$PWD/src"
export KNOWLEDGE_HUB_API_TOKEN='your-token-if-needed'
export KNOWLEDGE_BASES_JSON='{
  "knowledge_bases": {
    "qnx-main": {
      "processed_dir": "/path/to/processed",
      "fts_index_path": "/path/to/chunks.db",
      "vector_index_path": "/path/to/chunks.vector.json",
      "default_task_type": "general_query",
      "default_top_k": 8,
      "default_per_document_limit": 2
    }
  }
}'

python3 -m uvicorn agent_knowledge_hub.service:create_app --factory --host 0.0.0.0 --port 8787
```

验证服务是否可用：

```bash
curl -sS http://127.0.0.1:8787/health
```

验证远程 Context Pack 接口：

```bash
curl -sS "http://127.0.0.1:8787/api/knowledge-bases/qnx-main/context-pack" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer local-dev-token" \
  -d '{"query":"What constraints should the agent use?","task_type":"code_review","top_k":3,"per_document_limit":2}'
```

## 配置项

- `knowledgeHub.baseUrl`：远程 Knowledge Hub 服务地址。
- `knowledgeHub.token`：可选的 Bearer Token（用于鉴权）。
- `knowledgeHub.defaultKnowledgeBaseId`：默认知识库 ID，例如 `qnx-main`。
- `knowledgeHub.defaultTaskType`：Context Pack 任务类型。
- `knowledgeHub.topK`：请求的 chunk 数量。
- `knowledgeHub.perDocumentLimit`：每篇文档的 chunk 数量上限。
- `knowledgeHub.showDebugInfo`：是否在输出中显示远程 API、模型元数据、上下文来源、token 统计等调试信息。
- `knowledgeHub.showPromptPreview`：是否在开启 `showDebugInfo` 时显示发送给 Copilot 的 prompt 预览。

推荐工作区配置：

```json
{
  "knowledgeHub.baseUrl": "http://127.0.0.1:8787",
  "knowledgeHub.token": "local-dev-token",
  "knowledgeHub.defaultKnowledgeBaseId": "qnx-main",
  "knowledgeHub.defaultTaskType": "code_review",
  "knowledgeHub.topK": 3,
  "knowledgeHub.perDocumentLimit": 2,
  "knowledgeHub.showDebugInfo": false,
  "knowledgeHub.showPromptPreview": false
}
```

如果要给其他同事使用，把 `knowledgeHub.baseUrl` 改为服务端机器的局域网或内网地址，例如：

```json
{
  "knowledgeHub.baseUrl": "http://10.49.98.224:8787",
  "knowledgeHub.token": "local-dev-token",
  "knowledgeHub.defaultKnowledgeBaseId": "qnx-main"
}
```

## 开发

```bash
cd integrations/vscode-knowledge-hub
npm install
npm run compile
```

在 VS Code 中打开此文件夹，按 `F5`，选择 `Run Knowledge Hub Extension` 启动扩展开发主机，然后运行 `Ask Knowledge Hub` 命令。仓库已提供 `.vscode/launch.json` 和 `.vscode/tasks.json`，正常情况下不会再弹出“选择调试器”。

扩展依赖 VS Code 中的 Copilot 语言模型。远程 Knowledge Hub 服务必须暴露 `../../docs/api-contract.md` 中记录的接口。

## 本机调试

1. 在仓库根目录启动本机远程服务：

```bash
./scripts/start-knowledge-hub-remote.sh
```

2. 在 VS Code 中打开 `integrations/vscode-knowledge-hub` 目录。
3. 安装依赖并编译：

```bash
npm install
npm run compile
```

4. 按 `F5`，选择 `Run Knowledge Hub Extension` 启动 Extension Development Host。
5. 在新窗口中打开命令面板，执行 `Ask Knowledge Hub`。
6. 输入问题后，扩展会调用远程 `/api/knowledge-bases/{knowledge_base_id}/context-pack`，优先使用服务端返回的 `formatted_context`，再交给 Copilot 生成回答。

如果你希望固定使用某个模型：

7. 在命令面板执行 `Knowledge Hub: Select Copilot Model`。
8. 从当前可用模型列表中选一个。扩展会持久保存该选择，后续 `Ask Knowledge Hub` 会持续使用这个模型，直到下次手动修改或重置为默认模型。

如需查看证据来源，复制输出中的 evidence id，再执行 `Knowledge Hub: Trace Evidence`。

## 对外演示流程

1. 在服务端机器运行：

```bash
./scripts/start-knowledge-hub-remote.sh
```

2. 确认服务输出中的 `LAN URL`，例如：

```text
http://10.49.98.224:8787
```

3. 在演示用 VS Code 中安装扩展，并配置：

```json
{
  "knowledgeHub.baseUrl": "http://10.49.98.224:8787",
  "knowledgeHub.token": "local-dev-token",
  "knowledgeHub.defaultKnowledgeBaseId": "qnx-main",
  "knowledgeHub.defaultTaskType": "code_review",
  "knowledgeHub.topK": 3,
  "knowledgeHub.perDocumentLimit": 2
}
```

4. 运行 `Ask Knowledge Hub`，输入问题，例如：

```text
What constraints should the agent use?
```

5. 展示输出结果：

- Copilot 生成的回答。
- Knowledge base id。
- 证据摘要（文档标题、章节/页码、少量 evidence id）。
- 使用 `Knowledge Hub: Trace Evidence` 回查证据来源。

## 打包分享

生成 `.vsix` 安装包：

```bash
cd integrations/vscode-knowledge-hub
npm install
npm run compile
npx @vscode/vsce package
```

生成后会得到类似：

```text
vscode-knowledge-hub-0.1.0.vsix
```

把这个 `.vsix` 文件发给其他人。对方可以通过命令安装：

```bash
code --install-extension vscode-knowledge-hub-0.1.0.vsix
```

也可以在 VS Code 中打开扩展视图，选择 `Install from VSIX...` 后选中该文件。

安装后，对方需要配置：

- `knowledgeHub.baseUrl`：远程 Knowledge Hub 地址。
- `knowledgeHub.token`：服务端设置了 `KNOWLEDGE_HUB_API_TOKEN` 时填写。
- `knowledgeHub.defaultKnowledgeBaseId`：例如 `qnx-main`。

对方的 VS Code 还需要已登录并启用 GitHub Copilot，否则扩展无法调用 Copilot 语言模型生成最终回答。

## 接口契约

扩展依赖以下远程接口：

```text
POST /api/knowledge-bases/{knowledge_base_id}/context-pack
GET  /api/knowledge-bases/{knowledge_base_id}/evidence/{evidence_id}
```

Context Pack 请求示例：

```json
{
  "query": "诊断模块修改需要注意什么？",
  "task_type": "code_review",
  "top_k": 8,
  "per_document_limit": 2,
  "metadata_filters": {
    "supplier": ["Bosch"],
    "document_version": ["v7.0"]
  }
}
```

响应会包含：

- `knowledge_base_id`
- `schema_version`
- `task_type`
- `markdown`
- `formatted_context`
- `selected_chunks`
- `sections`
- `evidence_ids`

扩展会优先把 `formatted_context` 与用户问题组合成 Copilot prompt；如果服务端未返回该字段，才回退到 `markdown`。证据展示默认只渲染少量来源摘要，而不是输出所有 span id。

## 安全边界

- 扩展不会读取或上传完整知识库文件。
- 扩展只把远程服务返回的 `formatted_context` / `markdown` 交给 Copilot，不直接读取知识库原始文件。
- 远程 Knowledge Hub 服务负责权限控制、知识库 ID 映射、索引路径和 evidence trace。
- 生产环境应使用 HTTPS、稳定身份认证、访问审计和最小化 Context Pack 输出。
- 如果资料不能发送给 Copilot，应改用内网模型或本地模型作为回答生成后端。

## 常见问题

### 运行 `Ask Knowledge Hub` 提示没有 Copilot 模型

确认当前 VS Code 已安装并登录 GitHub Copilot / Copilot Chat，并且组织策略允许使用 Copilot language model。

### 为什么飞书机器人回答更准，而 VS Code 扩展效果差

优先检查这几项：

- 远程服务是否同时配置了 `PROCESSED_DIR` 和 `FTS_INDEX_PATH`。
- VS Code 是否连的是你当前重启后的远程服务，而不是旧端口/旧进程。
- 知识库里是否真的包含用户询问的具体符号名；例如某些问题只有相邻概念命中，没有直接符号定义。

当前扩展已经优先使用服务端返回的 `formatted_context`，尽量复用飞书机器人的上下文整理逻辑。但如果知识库本身没有命中目标符号，回答仍然应该表现为“证据不足”，而不是强行给出文档事实。

### 返回 `401 Unauthorized`

检查 `knowledgeHub.token` 是否和服务端 `KNOWLEDGE_HUB_API_TOKEN` 一致。如果服务端用 `--no-token` 启动，可以把 `knowledgeHub.token` 留空。

### 返回 `404 Knowledge base not found`

检查 `knowledgeHub.defaultKnowledgeBaseId` 是否存在于服务端 `KNOWLEDGE_BASES_JSON` / `KNOWLEDGE_BASES_CONFIG` 中。

### 连接不上远程服务

确认：

- 服务端已启动。
- `knowledgeHub.baseUrl` 使用了正确 IP 和端口。
- 防火墙、VPN 或公司网络策略允许访问该端口。
- 服务端启动参数使用 `--host 0.0.0.0`，而不是只绑定 `127.0.0.1`。

### 端口已被占用

一键启动脚本会提示端口占用。可以停止已有 uvicorn 服务，或换端口启动：

```bash
./scripts/start-knowledge-hub-remote.sh --port 8797
```

然后把 VS Code 配置里的 `knowledgeHub.baseUrl` 改成对应端口。

## 本次集成内容

本扩展配合仓库中的远程 Knowledge Hub API 一起使用，当前 proof path 包含：

- 远程 `knowledge_base_id` Context Pack endpoint。
- 远程 evidence trace endpoint。
- Bearer Token 鉴权。
- VS Code 命令、配置项和 Output Channel 展示。
- Copilot language model 合成回答。
- `.vsix` 打包分享流程。
- `scripts/start-knowledge-hub-remote.sh` 一键启动本机远程服务。

已验证：

```text
npm run compile
POST /api/knowledge-bases/qnx-main/context-pack -> 200 OK
GET /api/knowledge-bases/qnx-main/evidence/span_demo_1 -> 200 OK
```