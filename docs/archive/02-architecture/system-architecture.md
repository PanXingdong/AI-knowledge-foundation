# 02 系统架构

## 1. 架构分层

本文描述目标架构。第一阶段只实现其中的轻量实验链路，不直接建设完整知识图谱。

### 1.1 目标架构

```text
文档源
  -> 文档接入层
  -> 文档解析层
  -> Canonical Document Model
  -> 知识抽取层
  -> 人工审核层
  -> 图谱与检索层
  -> Context Pack 组装层
  -> 群机器人入口 / Agent 本地入口
  -> 研发团队 / 各类研发 Agent
```

### 1.2 第一阶段实验链路

```text
10 份混合工程样本文档
  -> Docling / MinerU / Unstructured 解析对比
  -> Canonical Document Blocks
  -> 全文索引 + 向量索引
  -> Context Pack 组装
  -> 群机器人 demo / Agent 本地 CLI 或 HTTP demo
  -> 人工问答与 Agent 基线对比测试
```

第一阶段暂不建设：

- Domain Graph
- 完整人工审核台
- 复杂版本失效推理
- 影响分析产品化

## 2. 分层说明

### 2.1 文档源

第一版支持：

- PDF
- Word
- Markdown
- HTML
- 内部 SPEC
- 架构设计
- 详细设计
- 测试文档
- 供应商文档

后续可接：

- 缺陷单
- PR / review 记录
- 代码仓库
- Wiki
- CI 日志

### 2.2 文档接入层

职责：

- 上传或同步文档
- 记录来源、版本、owner、项目、模块、供应商
- 计算文件 hash
- 判断是否已有版本
- 触发解析任务

核心对象：

```text
DocumentSource
DocumentVersion
IngestionJob
```

### 2.3 文档解析层

职责：

- PDF 版面识别
- OCR
- 表格抽取
- 图片和图注抽取
- 章节层级识别
- 页码和坐标保留
- 输出统一中间格式

候选工具：

- Docling
- MinerU
- Unstructured

### 2.4 Canonical Document Model

这是系统的关键中间层。

不要直接把 Markdown chunk 写入向量库。必须先形成统一文档模型：

```text
Document
Page
Section
Block
Table
Figure
EvidenceSpan
```

该模型承担：

- 证据回溯
- chunk 生成
- 实体抽取输入
- 人工审核定位
- 版本 diff

### 2.5 知识抽取层

职责：

- 抽取工程实体
- 抽取实体关系
- 抽取约束和规则
- 抽取版本适用范围
- 抽取需求、设计、测试之间的链路
- 生成置信度和证据引用

原则：

- schema-guided，不做完全自由抽取
- 规则和 LLM 结合
- 接口名、错误码、版本号优先用规则抽取
- 复杂约束和影响关系用 LLM 抽取

### 2.6 人工审核层

职责：

- 审核候选实体
- 审核候选关系
- 合并重复实体
- 标记冲突
- 标记版本适用范围
- 驳回低质量抽取

状态流：

```text
extracted -> pending_review -> approved
                       |-> rejected
                       |-> corrected
                       |-> superseded
                       |-> invalidated
```

### 2.7 图谱与检索层

需要同时维护三类索引：

```text
全文索引：精确查接口名、错误码、章节名
向量索引：语义召回相近说明
图谱索引：实体关系、依赖、影响、追溯
```

图谱分两层：

```text
Lexical Graph:
Document -> Section -> Block -> EvidenceSpan

Domain Graph:
Module -> Interface -> Constraint -> Requirement -> TestItem
```

### 2.8 Context Pack 组装层

这是 Agent 真正消费的输出。

输入：

```text
project
module
task_type
files
query
version constraints
```

输出：

```text
任务摘要
相关实体
相关关系
必须阅读的证据
约束和风险
建议测试项
开放问题
证据来源
```

### 2.9 产品入口层

第一版成品入口分两类：

```text
群机器人入口：服务团队成员的日常问答。
Agent 本地入口：服务 Codex、Cursor、Copilot、自研 Agent 等本地工作流。
```

群机器人入口：

```text
企业微信 / 飞书 / 钉钉
  -> Bot 服务
  -> Knowledge Hub Core
  -> 回答 + 证据
```

Agent 本地入口优先：

```text
本地 CLI
本地 HTTP
SDK
只读知识包
```

当前成品路线不走 MCP；已有 MCP adapter 只作为早期实验遗留，不作为产品入口。

## 3. 推荐部署形态

第一阶段建议轻量单体部署：

```text
FastAPI backend
Docling / MinerU parser adapter
PostgreSQL 或 SQLite metadata
Qdrant 或 pgvector vector index
PostgreSQL full-text 或轻量 BM25
Bot adapter
Local CLI / local HTTP adapter
```

目标架构可演进为：

```text
FastAPI backend
PostgreSQL metadata
Neo4j graph
Qdrant vector index
OpenSearch / PostgreSQL full-text
Object storage for original files
Worker queue for parsing/extraction
Bot gateway
Local knowledge package sync
Simple web review console
```

后续再拆服务，不要第一版就微服务化。

## 4. 核心设计原则

### 4.1 阶段 1 原则

1. 证据优先：Context Pack 中的关键结论必须能回到原文。
2. 双入口优先：输出既要服务群机器人可读回答，也要服务 Agent 可消费 Context Pack。
3. 实验优先：先证明比直接给文件更好，再扩展平台能力。
4. 混合检索优先：阶段 1 使用全文检索 + 向量检索。
5. 核心中心化：文档接入、解析、索引和治理集中管理；Agent 本地入口可以同步只读知识包或调用本地 HTTP。

### 4.2 阶段 2 原则

1. 审核优先：未审核关系不能作为强事实使用。
2. 版本优先：文档和关系必须有适用范围。
3. 图谱优先处理关系问题：只有出现跨文档、多跳依赖、影响路径需求时再引入 Domain Graph。
4. 治理优先：进入团队知识库的实体、关系和规则必须可追溯、可撤回、可失效。
