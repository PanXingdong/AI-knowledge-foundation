# 05 数据模型与图谱 Schema

## 1. 设计原则

1. 原始证据不可变。
2. 第一阶段只实现 Agent Context Pack 需要的最小数据模型。
3. 图谱实体、关系、审核状态和版本失效是第二阶段能力。
4. 任何关键结论都必须保留文档来源、页码、章节和 span。
5. 数据模型服务 Agent 消费，不服务炫酷展示。

## 2. 阶段边界

第一阶段落地：

```text
Document
DocumentVersion
Section
Block
EvidenceSpan
Chunk
ContextPack
```

第二阶段再落地：

```text
工程实体
实体关系
人工审核状态
版本失效
影响分析路径
```

## 3. 第一阶段最小数据模型

### 3.1 Document

```json
{
  "document_id": "doc_001",
  "title": "QNX Platform Guide",
  "source_type": "supplier_pdf",
  "owner": "platform_team",
  "project": "ProjectA",
  "supplier": "QNX",
  "created_at": "2026-05-31T00:00:00Z"
}
```

### 3.2 DocumentVersion

```json
{
  "document_version_id": "docver_001",
  "document_id": "doc_001",
  "version": "unknown",
  "file_path": "samples/raw/example.pdf",
  "file_hash": "sha256...",
  "created_at": "2026-05-31T00:00:00Z"
}
```

### 3.3 Section

```json
{
  "section_id": "sec_001",
  "document_version_id": "docver_001",
  "section_path": ["3", "3.2"],
  "title": "Service Startup Constraints",
  "page_start": 18,
  "page_end": 20
}
```

### 3.4 EvidenceSpan

```json
{
  "evidence_id": "span_001",
  "document_version_id": "docver_001",
  "page": 18,
  "section_path": ["3", "3.2"],
  "block_id": "blk_123",
  "bbox": [72, 120, 520, 188],
  "text": "原文片段...",
  "text_hash": "sha256..."
}
```

### 3.5 Chunk

```json
{
  "chunk_id": "chunk_001",
  "document_version_id": "docver_001",
  "section_path": ["3", "3.2"],
  "page_start": 18,
  "page_end": 19,
  "text": "用于检索和 Context Pack 组装的文本...",
  "evidence_ids": ["span_001", "span_002"],
  "embedding_id": "emb_001"
}
```

### 3.6 ContextPack

```json
{
  "context_pack_id": "ctx_001",
  "query": "QNX 适配改动需要注意什么约束？",
  "summary": "...",
  "constraints": [],
  "relevant_sections": [],
  "evidence_ids": ["span_001"],
  "token_count": 1800,
  "created_at": "2026-05-31T00:00:00Z"
}
```

## 4. 第一阶段 Context Pack 组装规则

进入 Context Pack 的优先级：

1. 当前领域和任务类型强匹配的文档块。
2. 关键词、接口名、章节名精确命中的文档块。
3. 向量相似度高的文档块。
4. 有页码、章节、span_id 的证据片段。
5. 可选的 LLM 摘要和约束提炼。

必须排除：

- 无文档来源的片段。
- 无页码或无法定位来源的关键结论。
- 明显不属于当前领域的片段。
- 与任务无关的长篇背景材料。

## 5. 第二阶段实体类型

阶段 2 可引入：

```text
Module
Interface
API
Service
Signal
Configuration
ErrorCode
Requirement
Constraint
Platform
Chipset
OS
Supplier
Version
TestItem
DesignDecision
Defect
```

## 6. 第二阶段关系类型

阶段 2 可引入：

```text
PART_OF
DEFINED_IN
MENTIONED_IN
IMPLEMENTS
DEPENDS_ON
CALLS
PROVIDES
CONSTRAINS
AFFECTS
VERIFIES
REPLACES
CONFLICTS_WITH
VALID_FOR_VERSION
INVALIDATED_BY
SUPPORTED_BY_EVIDENCE
```

## 7. 第二阶段图谱结构

### 7.1 Lexical Graph

```text
(Document)-[:HAS_VERSION]->(DocumentVersion)
(DocumentVersion)-[:HAS_SECTION]->(Section)
(Section)-[:HAS_BLOCK]->(Block)
(Block)-[:HAS_EVIDENCE]->(EvidenceSpan)
```

### 7.2 Domain Graph

```text
(Module)-[:DEPENDS_ON]->(Interface)
(Interface)-[:DEFINED_IN]->(EvidenceSpan)
(Constraint)-[:CONSTRAINS]->(Module)
(Requirement)-[:IMPLEMENTS]->(DesignDecision)
(TestItem)-[:VERIFIES]->(Requirement)
(DocumentVersion)-[:REPLACES]->(DocumentVersion)
```

## 8. 第二阶段审核和版本属性

关系状态：

```text
candidate
pending_review
approved
rejected
corrected
superseded
invalidated
```

版本字段：

```json
{
  "valid_from": "2026-01-01",
  "valid_until": null,
  "applies_to": {
    "project": "ProjectA",
    "platform": "QNX",
    "bsp_version": ">=1.2,<1.5"
  },
  "evidence_ids": ["span_001", "span_002"]
}
```
