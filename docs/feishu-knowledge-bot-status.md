# Feishu Knowledge Bot Status

## Executive Summary

当前项目已经从“能检索文档并返回文本答案”的原型，推进到“飞书群内可用的工程知识助手”阶段。

核心能力已经形成闭环：

```text
工程文档知识库
  -> 混合检索 / Context Pack
  -> DeepSeek 结构化回答
  -> 飞书交互卡片
  -> 完整证据追溯
```

这意味着机器人不只是聊天入口，而是一个面向人和 Agent 的工程知识服务入口。它可以基于 QNX、Qualcomm 等技术文档回答问题，并把结论追溯回文档、章节、页码和原文证据。

## Current User Experience

飞书机器人当前支持：

- 群聊中 `@QNX知识库机器人` 提问。
- 本地知识库检索真实工程文档。
- DeepSeek 基于 Context Pack 生成结构化 JSON 回答。
- 飞书 interactive card 展示答案。
- 卡片按钮“查看完整证据”追溯原文。
- 多轮追问时按 `chat_id:user_id` 隔离上下文。

当前卡片结构：

```text
标题

结论
工具 / Demo / 其他 direct answer

关键说明 / 怎么用这些工具 / 用法说明
按 answer_type 展示 details

关键依据
最多展示 2 条核心证据

需要注意
限制、缺口、不确定性

下一步建议
可执行的后续动作

置信度
高 / 中 / 低 + 理由

[查看完整证据]
```

## Architecture

### 1. Retrieval Layer

入口：

- `src/agent_knowledge_hub/service.py`
- `src/agent_knowledge_hub/retrieval.py`

职责：

- 从 processed knowledge base 加载 chunks。
- 使用 FTS、vector、BM25、topic signals 进行混合检索。
- 生成 `context-pack.v1`。
- 支持 `/api/evidence/{evidence_id}` 证据追溯。

### 2. Candidate Facts Layer

入口：

- `MessageFormatter.extract_candidate_facts()`

职责：

- 从 Context Pack 的 selected chunks 中抽取候选事实。
- 当前支持的事实类型包括：
  - `tool`
  - `api_feature`
  - `demo`
- 每个事实保留：
  - `kind`
  - `name`
  - `purpose`
  - `source`
  - `evidence_ids`

作用：

- 减少 DeepSeek 自由发挥。
- 把“检索到了什么事实”显式告诉模型。
- 在模型回答与证据矛盾时做程序侧一致性修正。

示例：

```json
{
  "kind": "tool",
  "name": "screeninfo",
  "purpose": "查看 Screen 对象和显示状态",
  "source": "QNX Screen Graphics Subsystem Developers Guide / Debugging / page 309",
  "evidence_ids": ["span_xxx"]
}
```

### 3. LLM Answer Layer

入口：

- `src/agent_knowledge_hub/llm_agent.py`

职责：

- DeepSeek 只负责生成结构化内容，不负责决定飞书卡片 UI。
- 技术问答使用 `temperature=0`，提高稳定性。
- 闲聊和无证据回复保留较低随机性，使表达自然。

当前技术问答 schema：

```json
{
  "title": "...",
  "direct_answer": {
    "tools": "...",
    "demos": "..."
  },
  "summary": "...",
  "answer_type": "tool_lookup | demo_lookup | how_to | concept | troubleshooting | api_usage | general",
  "details": [
    {
      "name": "...",
      "purpose": "...",
      "usage": "...",
      "when_to_use": "..."
    }
  ],
  "key_points": [],
  "evidence_items": [
    {
      "name": "...",
      "source": "...",
      "why_relevant": "...",
      "evidence_ids": []
    }
  ],
  "caveats": [],
  "next_steps": [],
  "confidence": "..."
}
```

设计原则：

- LLM 负责内容理解和结构化答案。
- 程序负责卡片展示、证据按钮、截断、fallback。
- 同一个结构化答案未来可渲染到飞书、CLI、网页或 Agent SDK。

### 4. Feishu Presentation Layer

入口：

- `src/agent_knowledge_hub/feishu_bot.py`
- `src/agent_knowledge_hub/feishu_bot_sdk.py`

职责：

- 把结构化答案转换为飞书 interactive card。
- 卡片发送失败时降级：

```text
interactive card
  -> post rich text
  -> text
```

当前按钮：

- `查看完整证据`
- 携带 `evidence_refs`
- 点击后调用 `/api/evidence/{evidence_id}`
- 返回文档、章节、页码、原文片段和支撑关系。

## Completed Improvements

### Feishu Reply Format

已完成：

- 从纯文本升级为 interactive card。
- 去除普通用户不可读的 `span_xxx` 展示。
- 保留完整证据按钮用于追溯。
- 卡片内容压缩为“结论 / 细节 / 依据 / 注意 / 下一步 / 置信度”。
- 根据 `answer_type` 渲染不同细节标题：
  - `tool_lookup` / `demo_lookup`: `怎么用这些工具`
  - `api_usage`: `用法说明`
  - `concept` / `troubleshooting` / `how_to`: `关键说明`

### Answer Stability

已完成：

- 技术问答 `temperature` 默认改为 `0`。
- DeepSeek 输出改为 JSON 优先。
- JSON 解析失败时 fallback 到自然语言分节解析。
- Candidate facts 注入 LLM 上下文。
- Candidate facts 和模型输出矛盾时，程序侧做一致性修正。

### Evidence Trace

已完成：

- 卡片按钮可触发“查看完整证据”。
- 完整证据会过滤低价值标题碎片。
- 证据详情会说明“这条证据支撑什么”。

### Image/OCR Foundation

图片能力已另行整理为 PR 分支：

- 支持独立图片 OCR ingest。
- OCR 结果保留 bbox、confidence、ocr_lines、media refs。
- evidence trace 可返回 OCR/image metadata。

## Real Query Regression

新增脚本：

```text
scripts/run_real_query_regression.py
```

用途：

- 固定真实工程问题。
- 跑真实 Context Pack 检索。
- 抽取 candidate facts。
- 可选调用 DeepSeek。
- 输出 JSON/Markdown 报告。

当前回归问题集包括：

- QNX 是否提供 debug 渲染显示问题的 demo 或工具。
- 高通 8397 上缓存零拷贝技术方案架构。
- `mm_dma` 和 `dma_ecc_above_4g` 的区别。
- 实际进程的显存如何分配。

当前发现：

- QNX 渲染调试工具问题已能稳定抽取 Screen 调试工具候选事实。
- 高通缓存零拷贝、`mm_dma` / `dma_ecc_above_4g`、显存分配等问题还需要扩展 candidate facts 领域覆盖。

## Known Limitations

### 1. Candidate Facts 覆盖面仍有限

当前 candidate facts 已能覆盖部分 Screen 工具 / demo / API feature。

## One-shot Chain

如果你已经把飞书机器人创建好，并且希望把“知识库预处理 -> 质量门禁 -> Layer2 冒烟 -> 飞书长连接启动”串成一条完整链路，推荐直接使用：

```bash
./scripts/run-feishu-knowledge-chain.sh \
  --processed-dir "/mnt/d/AI Knowledge/AI-knowledge-foundation/qnx-knowledge/processed" \
  --smoke-query "QNX 里有哪些可用的调试工具和 demo？"
```

这个入口会按下面顺序执行：

```text
inventory
  -> manifest ingest
  -> parse-quality-summary
  -> validate-processed
  -> layer2-run smoke check
  -> start-context-pack API
  -> start Feishu bot
```

如果不传参数，而仓库下已经存在 `qnx-knowledge/processed`，脚本会自动识别这份目录并跳过预处理。

如果现成 processed 目录里存在少量无效文档版本，例如 `chunks.jsonl` 为空，脚本会自动生成一个过滤后的运行目录，保留其余有效文档继续完成 Layer2 冒烟和飞书启动。

但还需要扩展：

- memory carveout:
  - `mm_dma`
  - `dma_ecc_above_4g`
  - `gvm_pmem`
- diagnostic command:
  - `showmem -t`
  - `pidin pmem`
  - `pidin syspage=asinfo`
- zero-copy / cache:
  - `zero-copy`
  - `DMA buffer`
  - `non-cache mapping`
  - `mmap`
- scheduling:
  - APS
  - CPU budget
  - critical budget
  - server boost

### 2. 检索结果仍可能混入噪声

典型噪声：

- IDE/GDB 通用调试文档。
- End User license/debug log 文档。
- 与查询弱相关的 demo 文档。

当前通过 prompt 和 formatter 做了部分过滤，但根本上仍需提升 retrieval/rerank 对领域意图的识别能力。

### 3. 完整证据仍是文本回复

当前证据详情是纯文本。

后续可以升级成：

- 证据详情卡片。
- 按证据类型分组。
- 支持“继续追问这条证据”。
- 支持打开本地/内部证据页面。

## Recommended Next Steps

### P0: Expand Real Query Regression

优先扩展真实问题集和 candidate facts：

- `mm_dma` vs `dma_ecc_above_4g`
- 高通 8397 DMA-BUF / zero-copy / cache
- 进程显存/PMEM 分配
- APS 防止高优线程饿死 UI
- GPU active 状态降低占用

目标：

```text
每次改检索、prompt、formatter 前后，都能跑固定问题回归，
不再依赖人工在飞书里反复试错。
```

### P1: Improve Retrieval Intent Routing

增加 query intent：

- tool lookup
- API usage
- troubleshooting
- memory / carveout
- scheduler
- graphics / display

让检索阶段根据 intent 调整 query expansion 和 rerank。

### P2: Evidence UX

改进“查看完整证据”：

- 证据详情也用卡片。
- 每条证据对应回答中的 claim。
- 支持更多/折叠/追问。

### P3: Agent Entry

把同一套 Context Pack + structured answer 输出给本地 Agent 使用：

- CLI
- HTTP API
- SDK

飞书机器人服务人，Agent entry 服务开发工具和自动化任务。

## Demo Talking Points

给老板演示时建议按这个顺序：

1. 问一个 QNX Screen 调试工具问题。
2. 展示飞书卡片：
   - 结论
   - 工具/示例说明
   - 关键依据
   - 置信度
3. 点击“查看完整证据”。
4. 展示能回到文档、章节、页码和原文。
5. 说明该系统不是普通聊天机器人，而是可追溯工程知识入口。
6. 说明下一阶段会扩展真实问题回归集，覆盖 Qualcomm / memory / GPU / scheduler 场景。

