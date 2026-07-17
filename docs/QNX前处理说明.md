# QNX 知识库前处理说明

> 适用范围：`qnx-knowledge/` 目录下的入库产物，以及 ClusterHMI 工程中 `tools/qnx_kb_*.py`、`qnx_kb/` 所定义的前处理流程。
> 目标读者：需要理解、维护或扩展「QNX 文档 + 工程源码 → 可检索知识库」这一流水线的工程师。

---

## 一、背景

### 1.1 问题来源

ClusterHMI 项目在 QNX 7.1 Neutrino RTOS 上开发车载仪表盘 HMI，工程师在日常开发中面临两类信息获取瓶颈：

- **QNX 官方文档体量大、分散**：QNX SDP 7.1 共有 58 份 PDF，覆盖 RTOS 内核、资源管理器（Resource Manager）、IPC、自适应分区调度、Hypervisor 等模块。单份 PDF 可达数十 MB，全文检索困难，API 细节难以快速定位。
- **工程代码与文档脱节**：`ClusterFunctionService`、`HUD`、`ClusterHMIFramework` 等模块的业务逻辑（如 Alert 管理、DMS 集成、SOME/IP 通信）散落在近 2000 份 C/C++ 源码和配置文件中，新成员或跨模块协作时上手成本极高。

直接把原始文件交给 Agent 或大模型，会遇到如下问题：
- 每次会话重复解析相同文档，消耗大量上下文窗口。
- 关键 API 约束、平台条件编译宏（如 `EE_ARCH_GB_FAMILY`、`PLATFORM_8255`）容易被遗漏。
- 来源不可追溯，难以区分"哪个平台版本"下的行为。

### 1.2 目标与定位

本前处理流程的目标是将**两类异构原始资料**统一加工成一个**本地、可离线、零外部服务**的 SQLite 知识库，再供下游混合检索与 RAG 问答调用：

1. **QNX 官方 PDF**：以摘要形式入库，保留章节目录与官方链接，降低体积与检索噪声。
2. **工程自有源码**：按语言、模块、符号完整入库，支持代码级精确检索。

这套流水线与 `AI-knowledge-foundation` 主项目的设计理念一致：**结构化处理 → 分块 → 可溯源索引**；不同之处在于它针对 QNX/嵌入式场景做了轻量化裁剪（无 OCR、无契约校验），以便在车载开发机上快速部署。

---

## 二、技术

### 2.1 端到端数据流

```
QNX PDF（58 份，/qnx-sdp/doc/*.pdf）     工程源码（~1865 份文件）
         │                                         │
         │ pdftotext -layout -nopgbrk             │ rglob 遍历 + 白名单过滤
         ▼                                         │
  全文提取 + clean_pdf_text                         │
         │                                         │
         │ ★ replace_qnx_docs.py                   │
         │   全文 → 精简摘要（≈1 KB）                │
         │   原文另存为 *.txt.bak                    │
         ▼                                         ▼
  extracted/docs/*.txt（摘要）            safe_read_text 读取源码
         │                                         │
         └──────────────────┬──────────────────────┘
                            ▼
                  qnx_kb_ingest.py（核心前处理）
                            │
         ┌──────────────────┼────────────────────────────┐
         ▼                  ▼               ▼             ▼
     文本分块           代码分块         元数据抽取     token 估算
  （按字符滑窗）       （按行滑窗）   （标题/版本/语言/符号）  (len//4)
         └──────────────────┴───────────────┴─────────────┘
                            │
                            ▼
              SQLite: documents + chunks
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    chunks_fts       doc_chunks_fts      code_chunks_fts  ← 三套 FTS5 全文索引
                            │
                            ▼
             exports/*.jsonl  +  stats.json
                            │
                            ▼
     下游：search / hybrid_search / ask / web / MCP
```

---

### 2.2 原始资料的两条加工线

#### 2.2.1 QNX PDF 线

| 步骤 | 实现 | 说明 |
|------|------|------|
| 文本提取 | `pdf_to_text()` → 系统 `pdftotext -layout -nopgbrk` | `-layout` 保版式，`-nopgbrk` 去分页符 |
| 清洗 | `clean_pdf_text()` | 去 `\r`、行尾留白，连续空行压成一行 |
| 缓存 | `extracted/docs/<stem>.txt` | 已存在则复用，避免重复调用 `pdftotext` |
| 标题/版本推断 | `infer_pdf_title()` | 正则提取版本号 `\d+\.\d+`、产品系列（SDP / Neutrino RTOS / Hypervisor）、去日期后缀 |
| **摘要化** | `replace_qnx_docs.py --mode summary` | 见 §2.4，是本流程最关键的取舍 |
| 分块 | `chunk_plain_text(target=1800, overlap=200)` | 按字符滑窗，边界回退到最近换行符 |

**为什么选 `pdftotext` 而非 MarkItDown**：实测同一份 QNX PDF，MarkItDown 0.1.6 断词错误（丢词间空格）是 `pdftotext 22.02` 的近 6 倍（1048 vs 182 处），且会把代码示例的 `#include` / `#define` 误当 Markdown 标题，表格渲染错乱。`pdftotext -layout` 对纯 PDF 更可靠；若需版面级结构化（表格/标题语义还原），应上 Docling / Marker，但代价是重模型依赖与更长处理时间。

#### 2.2.2 工程代码线

| 步骤 | 实现 | 说明 |
|------|------|------|
| 文件遍历 | `code_file_iter()` | `rglob("*")` + 排除目录 + 扩展名/文件名白名单 |
| 安全读取 | `safe_read_text()` | 含 `\x00` 视为二进制跳过；按 utf-8 / utf-8-sig / latin-1 依次尝试 |
| 语言识别 | `detect_language()` | 后缀/文件名 → 语言标签（`Makefile→make`、`CMakeLists.txt→cmake` 等）|
| 模块归属 | `rel.parts[0]` | 相对路径第一段作 module（`ClusterFunctionService`、`HUD`、`someip`…）|
| 符号抽取 | `extract_code_symbols()` | 正则取标识符，去 C/C++ 关键字停用词，按词频取 Top 24 作 keywords |
| 分块 | `chunk_code_text(max_lines=120, overlap=20)` | 按行数滑窗 |

**过滤规则**（只收工程自有代码，排除预编译/第三方）：

```python
EXCLUDED_DIRS = {
    ".git", "build_qnx", "build_windows", "coverage",
    "ClusterHMIPrebuilts", "KanziEngine", "externallib",
    "prebuilts", "external", "node_modules", "qnx_kb", "__pycache__",
}
CODE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".sh", ".cmake",
    ".proto", ".json", ".yaml", ".xml", ".java", ".ts", ...
}
```

---

### 2.3 分块策略对比

分块粒度直接决定检索召回的精度。两类资料采用不同策略：

| 维度 | PDF/文本：`chunk_plain_text` | 代码：`chunk_code_text` |
|------|------------------------------|--------------------------|
| 切分单位 | 字符 | 行 |
| 目标大小 | 1800 字符 | 120 行 |
| 重叠 | 200 字符 | 20 行 |
| 边界优化 | 回退到最近换行符（需过半位置） | 直接按行窗口滑动 |
| 位置引用 | `start_ref=char:<n>`，`end_ref=char:<n>` | `start_ref=line:<n>`，`end_ref=line:<n>` |

**重叠（overlap）的意义**：相邻块共享一段内容，避免关键信息落在切割边缘被两块分别召回一半。`start_ref/end_ref` 让每个 chunk 可以回溯到源文件的精确位置，支持证据引用。

---

### 2.4 ★ PDF 摘要化（replace_qnx_docs.py）

这是本流程**最易被误解、最影响检索质量**的设计点。

`replace_qnx_docs.py --mode summary` 默认将 `extracted/docs/*.txt` 的**全文替换为约 1 KB 的摘要**，原始全文另存为同名 `.bak`。摘要结构：

```
Document: <标题>
Summary generated from the original QNX document.

<正文首个有效段落（≤6 句 / ≤180 词）>

Official online reference: https://www.qnx.com/developers/docs/7.1/...
Original content is preserved as <file>.txt.bak

Main sections:
- <章节标题 1..5>
```

**取舍分析**：

| 视角 | 摘要化（默认） | 全文入库（restore 后重 ingest） |
|------|---------------|--------------------------------|
| 体积 | 轻量，doc 侧只占 58 个 chunk | 单 PDF 全文可达 7.7 MB，58 份合计极大，FTS 噪声高 |
| 检索 | 只能命中文档级主题/目录/官方链接 | 可检索 API 参数级细节 |
| 可逆性 | `--mode restore` 一键还原；`--dry-run` 预览 | N/A |
| 推荐场景 | **快速问"这份文档讲什么 / 从哪里找"** | 正文级问答（如"`MsgSend()` 的 `rcvid` 参数含义"） |

> 维护提示：若需正文级问答，先 `python3 tools/replace_qnx_docs.py --mode restore`，再重跑 `qnx_kb_ingest.py`。注意库体积会从 ~500 MB 膨胀至数 GB。

---

### 2.5 数据库模型（SQLite）

`qnx_knowledge.db` 含两张主表 + 三张 FTS5 虚表：

**`documents`（文档级）**

| 字段 | 说明 |
|------|------|
| `id` | 主键：`pdf::<stem>` 或 `code::<rel_path>` |
| `source_type` | `qnx_pdf` / `project_code` |
| `title` / `path` / `relative_path` | 文档标识与路径 |
| `product` / `version` / `module` / `language` | 元数据（PDF 有 product/version；代码有 module/language）|
| `checksum` | SHA-1，用于未来增量更新判断 |
| `char_count` / `line_count` | 体积信息 |
| `metadata_json` | 扩展字段（JSON）|

**`chunks`（切片级）**

| 字段 | 说明 |
|------|------|
| `id` | `<doc_id>::chunk::<idx>` |
| `document_id` | 外键 → documents |
| `source_type` / `path` / `content` | 内容与来源 |
| `start_ref` / `end_ref` | 精确位置（`char:<n>` 或 `line:<n>`）|
| `token_estimate` | 粗略 token 估算（`len//4`）|
| `metadata_json` | keywords、module、language 等 |

**三套 FTS5 索引**

| 索引表 | 覆盖范围 | 用途 |
|--------|----------|------|
| `chunks_fts` | 全部 chunk | 全局兜底检索 |
| `doc_chunks_fts` | 仅 `qnx_pdf` | 文档侧检索（含 keywords 列）|
| `code_chunks_fts` | 仅 `project_code` | 代码侧检索（含 keywords 列）|

按 `source_type` 分流让下游可以**按"查文档 / 查代码"分别打分**，而不是混在一个索引里相互干扰。

---

### 2.6 下游检索衔接（qnx_kb_lib.py 边界）

前处理产出的 `documents / chunks / *_fts` 是下游的契约。`qnx_kb_lib.py` 在此之上实现**混合检索**：

1. **查询扩展**：`expand_query()` 用 `SYNONYMS`（如 `rm → resource manager`、`ipc → message passing / channel`）扩展同义词，提升召回率。
2. **意图分类**：`classify_query()` 按命中 `CODE_HINTS` / `DOC_HINTS` 判定 `code / doc / hybrid`。
3. **召回**：`doc_chunks_fts` + `code_chunks_fts` 的 BM25 + `LIKE` 兜底候选。
4. **打分**：BM25 RRF（权重 0.65）+ 三元组模糊相似度/词重叠（权重 0.35），再乘 `source_boost`（按意图偏置 doc 或 code）。
5. **Context Pack 产出**：`exports/last_query_context.md`，可直接作为大模型 RAG 上下文；附 Top hits 列表与原文位置。

入口对应关系：
- `qnx_kb_search.py`：纯 FTS 检索
- `qnx_kb_hybrid_search.py` / `qnx_kb_ask.py`：混合检索 + 问答
- `qnx_kb_web.py`：本地 Web UI
- `qnx_kb_mcp_server.py`：MCP 工具接口（`search_qnx_kb` / `ask_qnx_kb` / `get_context_for_question`）

---

### 2.7 运行方式

**外部依赖**：仅需系统 `pdftotext`（`poppler-utils`），其余为 Python 标准库，无需安装额外包。

```bash
# （可选）摘要化 / 还原 PDF 全文
python3 tools/replace_qnx_docs.py --mode summary    # 全文→摘要（默认，原文存 .bak）
python3 tools/replace_qnx_docs.py --mode restore    # 从 .bak 还原全文
python3 tools/replace_qnx_docs.py --mode url        # 全文→仅官方链接
python3 tools/replace_qnx_docs.py --dry-run --mode summary  # 只打印不改文件

# 全量入库（核心前处理，约数分钟）
python3 tools/qnx_kb_ingest.py \
  --pdf-root     /root/qnx-sdk/qnx/qnx-sdp/doc \
  --project-root /root/qnx-sdk/qnx/vendor/patac/patac-qnx/ClusterHMI \
  --output-root  qnx_kb
```

入库完成后，`qnx_kb/stats.json` 记录本次统计（文档数、chunk 数、失败列表、库路径等），可作为入库是否正常的快速核查依据。

---

### 2.8 已知限制

| 项 | 现状 | 建议方向 |
|----|------|----------|
| PDF 正文不可检索 | 默认摘要化，doc 侧只索引摘要/目录 | `restore` 后重 ingest，或对正文单独分块入库 |
| 全量重建 | 每次 `reset_db` 清空重来，无增量 | 按 `checksum` 增量更新，跳过未变更文件 |
| token 估算粗糙 | `len//4`，不区分中英文 | 严格预算时改用真实分词估算 |
| 符号抽取靠正则 | 词频 Top-N，无语义 | 接 `tree-sitter` / `clangd` 提取真实符号与定义位置 |
| FTS 中文分词有限 | 默认 Unicode 分词 | 中文为主场景可用 trigram tokenizer 或 jieba 预切 |
| PDF 提取器 | `pdftotext`，无版面/表格语义还原 | 结构化需求高时评估 Docling / Marker（但依赖重） |

---

## 三、总结

本套 QNX 知识库前处理流程将**两类异构资料**统一加工为一个可本地运行的 SQLite 知识库：

- **QNX 官方 PDF（58 份）** 以摘要形式入库，保留文档主题、章节目录与官方参考链接，体积可控（58 个 chunk），适合回答"去哪里查"的导航类问题。
- **工程自有源码（~1865 份文件，~16753 个 chunk）** 按语言和模块完整入库，支持 API 调用、平台宏、数据结构、DMS/ADAS 告警逻辑等代码级精确检索。

**核心设计取舍**：
- PDF 全文摘要化是**有意为之的折中**——牺牲正文细节的可检索性，换取体积可控与低噪声；需要正文级问答时可一键 `restore` 还原。
- 三套 FTS5 索引按 `source_type` 分流，让"查文档"与"查代码"可以独立调权，避免互相干扰。
- 零外部服务依赖、全离线可运行，适合车载开发环境（无稳定网络、无云计算资源的场景）。

**价值验证**：该流程已在 ClusterHMI 日常开发中投入使用，覆盖从 Alert 管理、DMS 集成、ADAS 告警、SOME/IP 通信到 Kanzi 渲染流水线的多个模块。后续如需提升 PDF 正文召回深度、或引入真实 embedding 增强语义检索，可在当前基础上按需扩展，而无需重构已有管道。

---

> 维护提示：代码实现以 `tools/qnx_kb_ingest.py`、`tools/replace_qnx_docs.py`、`tools/qnx_kb_lib.py` 为权威；本文描述的行为与这三个文件保持对应。如修改了分块参数、过滤规则或索引结构，请同步更新本文相应小节。
