# QNX 7.1 文档结构化产物

## 概述

本目录是第一段（文档结构化）的交付物。

将 58 份 QNX Neutrino RTOS 7.1 / QNX SDP 7.1 官方 PDF 文档，通过
[AI Knowledge Foundation](https://github.com/PanXingdong/AI-knowledge-foundation)
管道转换成带版本、章节、证据的 Canonical Document Model，供第二段（知识检索与组包）和第三段（产品入口与验证）直接使用。

---

## 产物说明

```
qnx-knowledge/
  qnx-doc-manifest.csv          # 58 份文档的接入清单（复现入口）
  parse-quality-summary.json    # 质量报告（JSON）
  parse-quality-summary.md      # 质量报告（可读）
  processed/                    # 结构化产物（见下）
    <document-slug>/
      <docver_xxx>/
        canonical-document.json   # Canonical Model（document / sections / blocks / evidence_spans）
        chunks.jsonl              # 检索用 chunk，每行含 evidence_ids / section_path / page
```

### 摄取统计

| 指标 | 数值 |
|---|---|
| 文档总数 | 58 |
| 解析成功 | 58 |
| Quality Gate 通过 | 58 |
| 被拦截 / 失败 | 0 |
| 质量分数 | 全部 100.0 |
| 总页数 | 15,466 |
| 总 block 数 | 15,218 |
| 总 chunk 数 | 14,601 |

---

## 直接使用 processed/ 产物（推荐）

从 GitHub Release 下载 `qnx-knowledge-processed.zip`，解压到本地：

```bash
unzip qnx-knowledge-processed.zip -d /your/local/path/
```

解压后目录结构与上述 `processed/` 完全一致，可直接传给第二段的检索接口：

```bash
# 示例：用 context-pack 查询
PYTHONPATH=src python -c "
from agent_knowledge_hub.cli import main
main([
  'context-pack',
  '--processed-dir', '/your/local/path/processed',
  '--query', 'IPC message passing',
  '--top-k', '8',
])
"
```

---

## 从头复现（有原始 PDF 时）

如果你本地有 QNX SDP 原始 PDF（路径可能不同），可按以下步骤重新生成。

### 1. 环境准备

```bash
# 需要 Python 3.11+
python3.11 -m venv qnx-env
source qnx-env/bin/activate   # Windows: qnx-env\Scripts\activate

# 安装 AI Knowledge Foundation
git clone https://github.com/PanXingdong/AI-knowledge-foundation.git
cd AI-knowledge-foundation
pip install -e .
```

### 2. 修改 manifest 中的文件路径

`qnx-doc-manifest.csv` 中 `file_path` 列写的是原始生成环境的绝对路径：

```
/root/qnx-sdk/qnx/qnx-sdp/doc/QNX_Neutrino_RTOS_7.1_*.pdf
```

如果你的 PDF 在不同路径，批量替换：

```bash
# Linux / macOS
sed -i 's|/root/qnx-sdk/qnx/qnx-sdp/doc|/你的/pdf/路径|g' qnx-doc-manifest.csv

# Windows PowerShell
(Get-Content qnx-doc-manifest.csv) -replace '/root/qnx-sdk/qnx/qnx-sdp/doc','D:\你的\pdf\路径' | Set-Content qnx-doc-manifest.csv
```

### 3. 运行摄取

```bash
PYTHONPATH=src python -c "
from agent_knowledge_hub.cli import main
main([
  'manifest',
  '--manifest', 'qnx-doc-manifest.csv',
  '--out-dir', 'processed',
  '--incremental',
])
"
```

### 4. 验证质量

```bash
PYTHONPATH=src python -c "
from agent_knowledge_hub.cli import main
main([
  'parse-quality-summary',
  '--processed-dir', 'processed',
  '--output-dir', '.',
])
"
# 查看 parse-quality-summary.md
```

预期结果：58 份文档全部 `allowed_for_context_pack: true`，quality_score 100.0。

---

## 给第二段的接口说明

第二段（知识检索与组包）消费 `processed/` 目录，核心接口：

| 功能 | CLI 命令 |
|---|---|
| 语义检索 | `context-pack --processed-dir processed --query "..."` |
| 关键词检索 | 同上（当前为 lexical retrieval） |
| 证据追溯 | `GET /api/evidence/{evidence_id}?processed_dir=...` |
| 质量过滤 | 自动：只返回 `allowed_for_context_pack=true` 的 chunk |

每个 chunk 的 `evidence_ids` 可通过 Evidence Trace 接口回溯到原文页码和章节。

---

## 给第三段的接口说明

第三段（产品入口与验证）可通过以下方式使用：

**MCP Server（Claude Code / Cursor）**：
```bash
PYTHONPATH=src python -m agent_knowledge_hub.mcp_server \
  --processed-dir /your/local/path/processed
```

**Core HTTP API**：
```bash
PYTHONPATH=src fastapi run src/agent_knowledge_hub/service.py
# POST /api/context-pack  {"processed_dir": "...", "query": "..."}
```

**Eval 基线对比**：
```bash
# 准备评测 run，baseline = 原始文件，context_pack = 本产物
PYTHONPATH=src python -c "
from agent_knowledge_hub.cli import main
main(['prepare-eval-run', ...])
"
```

---

## 原始文档来源

| 字段 | 值 |
|---|---|
| 来源 | QNX SDP 7.1 官方文档包 |
| 版本 | 7.1（20230501） |
| 格式 | PDF |
| 数量 | 58 份 |
| 覆盖范围 | Neutrino RTOS / SDP / 驱动 / 网络 / 多媒体 / 安全 / IDE |
