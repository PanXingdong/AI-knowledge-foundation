# 03 技术栈选型

## 1. 选型原则

第一阶段技术栈要满足：

- 能在内网部署
- 能处理真实 PDF
- 能保留证据链
- 能通过群机器人和 Agent 本地入口调用
- 能快速做两周实验
- 后续可替换局部组件

不追求一开始就最复杂，优先做可验证闭环。

## 2. 两周实验推荐栈

```text
Backend: Python + FastAPI
Document parsing: Docling + MinerU + Unstructured 对比
Metadata: SQLite 或 PostgreSQL
Vector: Qdrant 或 pgvector
Full-text: PostgreSQL full-text 或轻量 BM25
LLM: 可切换 provider；如涉密则先用内网模型或只做检索不做总结
Bot: 企业微信 / 飞书 / 钉钉机器人 adapter
Agent local: CLI + local HTTP
UI: 暂不做完整 UI，用 API + Markdown 报告 + 简单查看页即可
Storage: 本地目录或 NAS
```

第一阶段不引入 Neo4j、完整审核台和复杂版本管理，避免把实验做成平台建设。

## 3. 文档解析

### 推荐组合

```text
Docling + MinerU A/B 测试
Unstructured 作为通用备用
```

### Docling

适合：

- 多格式文档解析
- 统一文档表示
- 导出 Markdown/JSON/HTML
- 保留 pages、tables、images、structure、metadata

风险：

- 中文复杂版面和工程表格需要真实样本验证。

### MinerU

适合：

- 中文 PDF
- 复杂版面
- 表格、公式、图片
- layout/span 可视化质检
- CPU/GPU 部署

风险：

- 许可证和企业内网部署需要单独确认。
- 解析速度和资源占用需要压测。

### Unstructured

适合：

- 通用文档 ETL
- element 类型划分
- PDF/Word/HTML/邮件等多格式处理

风险：

- 对复杂工程 PDF 的结构保真需要验证。

## 4. 后端服务

推荐：

```text
Python + FastAPI
```

原因：

- 文档解析、LLM、RAG、图谱生态主要在 Python。
- FastAPI 适合快速做 REST API 和内部服务。
- 后续可接异步 worker。

备选：

- Node.js：适合部分机器人 SDK 和前端生态，但文档 AI 生态不如 Python 直接。
- Java/Spring Boot：适合企业系统治理，但 MVP 成本高。

## 5. 后台任务

推荐：

```text
Celery / RQ / Dramatiq + Redis
```

第一阶段任务类型：

- 文档解析
- OCR
- chunk 生成
- embedding 生成

二阶段再加入：

- 实体抽取
- 关系抽取
- 版本 diff
- 图谱写入

## 6. 元数据存储

推荐：

```text
PostgreSQL
```

存储：

- 文档 registry
- 解析任务
- 审核状态
- 用户和权限
- 版本记录
- 调用日志

如果团队已经有 MySQL，也可先用 MySQL，但 PostgreSQL 对 JSONB、全文和扩展更友好。

## 7. 图数据库（二阶段）

图数据库不进入两周实验的核心路径。只有当实验证明需要跨文档多跳关系、影响分析和实体卡片时，再引入图数据库。

第一推荐：

```text
Neo4j
```

原因：

- 社区成熟。
- Cypher 易读。
- GraphRAG 生态较完整。
- 适合做实体关系、影响路径、证据追溯。

备选：

- NebulaGraph：国产化和大规模图谱可考虑。
- TigerGraph：企业级能力强，但引入成本高。
- PostgreSQL + Apache AGE：可做轻量方案，但生态弱。

## 8. 向量库

推荐：

```text
Qdrant
```

原因：

- 自托管方便。
- API 简单。
- 元数据过滤能力较好。
- 适合按项目、模块、版本过滤。

备选：

- Milvus：大规模向量更强，但运维复杂。
- pgvector：阶段 1 最简单，但大规模和检索能力有限。
- Elasticsearch/OpenSearch vector：如果已有 ES/OS，可以复用。

## 9. 全文检索

第一阶段可选：

```text
PostgreSQL full-text / OpenSearch
```

选择建议：

- 文档量小：PostgreSQL full-text 足够。
- 文档量大、需要中文分词和复杂检索：OpenSearch。

## 10. LLM 和 Embedding

第一阶段 LLM 用途：

- Context Pack 汇总
- 查询改写
- 可选的约束摘要

二阶段 LLM 用途：

- 实体抽取
- 关系抽取
- 约束总结
- 问答生成

Embedding 用途：

- 文档块语义检索
- 实体描述检索
- 关系说明检索

部署建议：

- 如果资料涉密，优先内网模型或企业合规 API。
- 抽取任务需要结构化输出能力强的模型。
- 不要把 LLM 作为唯一判断来源，必须绑定证据和审核状态。

## 11. 群机器人和 Agent 本地入口

推荐：

```text
群机器人 adapter + 本地 CLI + 本地 HTTP
```

原因：

- 群机器人服务团队日常问答，适合中心化部署。
- 本地 CLI 方便 Agent 通过 shell 调用。
- 本地 HTTP 适合需要持续会话或本地工具编排的 Agent。
- 不走 MCP 可以降低协议适配和本地配置成本。

已有 MCP adapter 只作为早期实验遗留，不进入当前成品路线。

## 12. Web UI（二阶段）

第一阶段不做完整 Web UI。二阶段 UI 只做管理台：

- 文档上传
- 解析状态
- 查看文档结构
- 审核实体/关系
- 查看实体卡片
- 查询 Context Pack
- 调用日志

推荐：

```text
React / Next.js + 简单组件库
```

如果只做内网后台，也可以先用：

```text
FastAPI templates / Streamlit / Gradio
```

但长期看，审核台需要更强交互，建议最终用 React。

## 13. 目标架构推荐栈

```text
Backend: Python + FastAPI
Worker: Celery/RQ + Redis
Document parsing: Docling + MinerU A/B
Metadata: PostgreSQL
Graph: Neo4j
Vector: Qdrant 或 pgvector
Full-text: PostgreSQL full-text first
LLM: 可切换 provider
Bot: 企业微信 / 飞书 / 钉钉 adapter
Agent local: CLI + local HTTP
UI: React 或轻量 FastAPI admin
Storage: 本地/NAS/MinIO
```
