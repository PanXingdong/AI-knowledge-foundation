# 知识质量 Phase 1：自动检测与发布门禁设计

日期：2026-07-17

状态：待用户审阅

适用仓库：AI Knowledge Foundation

## 1. 背景

Phase 0 已建立不可变知识 release 控制平面：

- 文档处理记录和基础质量记录。
- candidate、ready、active release 生命周期。
- canonical、chunks、质量记录和索引的哈希绑定。
- FTS、本地向量、BGE 与检索缓存的 release 身份绑定。
- 确定性质量 baseline。
- 原子激活与回滚基础。

Phase 0 解决了“主数据、索引、证据和处理版本是否属于同一个可信 release”的问题，但尚未解决“内容本身是否达到发布质量”的问题。

当前质量门仍有以下缺口：

- 质量判断主要停留在文档级 `status` 和单一分数。
- page、block、chunk 缺少统一质量信号和决策契约。
- FTS 或向量索引命中后，可以重新加入原本被质量门挡下的 chunk。
- 当所有 chunk 被拦截时，检索会回退到全部 chunk。
- 质量原因、阈值、执行动作和 policy 版本没有统一管理。
- 无法在不重新解析文档的情况下，用新规则重新评估历史产物。
- 没有正式的隔离清单和发布集合，无法证明索引只包含已放行知识。

Phase 1 的目标是在不更换解析器的前提下，建立确定性质量检测、版本化 policy、隔离集合和分阶段强制门禁。

## 2. 目标

Phase 1 必须实现：

- 对 document、page、block、chunk 四层产物生成结构化质量信号。
- 将检测事实与发布决策分离。
- 使用版本化 Quality Policy 统一决定放行、警告、隔离和阻断。
- 支持 observe、candidate enforce、production enforce 三种模式。
- 生成可审计的 quality report、publication set 和 quarantine manifest。
- 让 candidate 索引只包含 publication set 允许的 chunk。
- 让 production 检索无法绕过 publication set。
- 支持用新 policy 重新评估历史 Phase 0 产物，不重新解析原始文档。
- 保持既有 v1 release 可读，禁止原地修改历史 release。

## 3. 非目标

Phase 1 不包括：

- 更换 PDF 解析器。
- 逐页解析路由。
- OCR 自动重试。
- 表格结构恢复。
- 多栏阅读顺序修复。
- 对 chunk 内容做自动文本修补。
- 按 QNX、Qualcomm 或文件名编写专用清洗规则。
- 使用 LLM 决定内容是否发布。
- 建设质量管理后台。
- 远端 release 搬迁和跨机器路径重定位。
- 解决所有回答生成层幻觉。

版面、表格、目录噪声和标题碎片可以在 Phase 1 产生 soft signal，但不得直接成为未经校准的硬阻断规则。

## 4. 已确认决策

### 4.1 使用独立 Quality Policy Engine

检测器只产出事实信号，不决定发布动作。Policy Engine 根据版本化 policy 把信号转换成统一 decision。

不在 pipeline、release 和 retrieval 中分别复制阈值和判断逻辑。

### 4.2 分阶段上线

执行顺序固定为：

```text
observe
  -> candidate_enforce
  -> production_enforce
```

不得直接从当前软门禁跳到 production 强制。

### 4.3 硬门禁只处理高置信完整性缺陷

Phase 1 允许硬阻断的规则必须满足：

- 完全由确定性数据验证。
- 可以稳定复现。
- 不依赖厂商、文档标题或人工关键词特例。
- 有明确对象定位和 reason code。
- 健康 Golden 样本硬误报为零。

启发式内容质量问题只产生 warning。

### 4.4 原始产物不可变

`canonical-document.json`、原始 `chunks.jsonl` 和 Phase 0 sidecar 不被修改。Phase 1 只生成新的质量和发布派生产物。

### 4.5 不对 chunk 做文本手术

若 chunk 引用了被隔离 evidence，则整个 chunk 隔离。Phase 1 不删除 chunk 中的部分文本，也不重新计算原文位置。

## 5. 总体架构

Phase 1 质量链路为：

```text
Phase 0 immutable artifacts
  -> Quality Evaluators
  -> Quality Signals
  -> Quality Policy Engine
  -> Quality Decisions
  -> Quality Report
  -> Publication Set + Quarantine Manifest
  -> Release / Index / Retrieval Enforcers
```

### 5.1 Quality Evaluators

职责：

- 读取 canonical、chunks、processing record、quality record。
- 分别评估 document、page、block 和 chunk。
- 输出原始指标、reason code、置信度和对象引用。
- 不读取当前 rollout mode。
- 不决定实际执行动作。

### 5.2 Quality Policy

职责：

- 定义 reason code 对应严重度。
- 定义指标阈值。
- 定义允许的执行动作。
- 定义不同 rollout mode 下的 effective action。
- 提供稳定 policy ID 和版本。

Policy 内容必须进入 release 身份和审计报告。

### 5.3 Quality Decision Engine

职责：

- 将 signals 映射为 decisions。
- 聚合 page、block、evidence 和 chunk 关系。
- 计算建议动作和实际动作。
- 产生 publication set 与 quarantine manifest。
- 不修改原始文档或 chunk。

### 5.4 Quality Enforcers

Enforcer 分布在 release、index 和 retrieval 边界，但只消费统一 decision，不重新实现质量规则。

职责：

- release ready 前校验质量派生产物。
- 索引时过滤未发布 chunk。
- production 检索只加载 publication set。
- 拒绝索引、report、policy 和 publication set 的哈希或版本错配。

## 6. 数据契约

### 6.1 QualitySignal

每条 signal 至少包含：

- `signal_id`
- `reason_code`
- `scope`
- `object_id`
- `detector`
- `detector_version`
- `metric_name`
- `actual_value`
- `threshold`
- `confidence`
- `severity`
- `document_version_id`
- page、block、chunk、evidence 引用
- 可读诊断消息

`scope` 只允许：

- `document`
- `page`
- `block`
- `chunk`
- `release`

### 6.2 QualityDecision

每条 decision 至少包含：

- `decision_id`
- `signal_ids`
- `policy_id`
- `policy_version`
- `mode`
- `recommended_action`
- `effective_action`
- `scope`
- `object_id`
- `reason_codes`
- `created_from_artifact_hashes`

动作集合固定为：

- `allow`
- `warn`
- `quarantine`
- `block_document`
- `block_release`

Observe 模式下，`recommended_action` 可以是 quarantine 或 block，但 `effective_action` 必须保持 allow 或 warn。

### 6.3 QualityReport

Quality report 包含：

- 输入 artifact 身份和哈希。
- policy 身份和哈希。
- evaluator 版本。
- 全部 signals。
- 全部 decisions。
- document/page/block/chunk 汇总。
- allow、warn、quarantine、block 数量。
- hard rule 与 soft rule 命中统计。
- determinism fingerprint。

### 6.4 PublicationSet

Publication set 包含：

- release ID。
- policy ID 和 mode。
- 允许发布的 document version。
- 允许发布的 chunk ID。
- 每个 document 的已发布 chunk 数量。
- 被排除对象对应的 decision ID。
- 原始 chunks 文件哈希。

### 6.5 QuarantineManifest

Quarantine manifest 包含：

- 被隔离的 document、page、block、evidence 和 chunk。
- 隔离来源 decision。
- reason code。
- 原始对象位置。
- 是否可通过 policy 变化重新评估。
- 是否需要 Phase 2 重新解析。

## 7. Reason Code 设计

Reason code 使用：

```text
<scope>.<category>.<condition>
```

例如：

- `document.integrity.no_chunks`
- `page.integrity.reference_out_of_range`
- `block.evidence.hash_mismatch`
- `chunk.evidence.reference_missing`
- `chunk.content.too_short`

Reason code 必须：

- 稳定、可版本化。
- 与展示文案分离。
- 不包含厂商或项目名。
- 在注册表中声明允许的 scope、severity 和 action。
- 未注册 reason code 在 enforce 模式下视为 policy 错误。

## 8. 四层质量信号

### 8.1 Document 层

允许硬阻断：

- 解析失败。
- 文件格式不支持。
- canonical、chunks、processing record 或 quality record 缺失。
- 文档不存在可发布 chunk。
- document version 关系不一致。
- 文档证据关系整体无法建立。

只软报告：

- OCR fallback 使用异常。
- warning 数量偏高。
- 文本总量异常偏少。
- 目录或附录占比疑似过高。
- 文档整体乱码率接近阈值。

### 8.2 Page 层

允许硬隔离：

- page 引用超出声明页数。
- 页面对象绑定错误 document version。
- 页面存在非空 block，但这些 block 既没有合法 page range，也没有可解析 evidence 关联。

只软报告：

- 疑似空页。
- 页面文本过短。
- 页面乱码率偏高。
- 多栏阅读顺序异常。
- 表格结构疑似破坏。
- 页眉页脚重复度过高。

### 8.3 Block 层

允许硬隔离：

- block 为空。
- block 类型非法。
- page 范围非法。
- evidence 缺失。
- evidence text hash 不匹配。
- block 绑定错误 document version。

只软报告：

- 标题碎片。
- 页眉页脚污染。
- 乱码或异常字符比例偏高。
- 段落异常长。
- 表格行列疑似粘连。
- 重复 block。

### 8.4 Chunk 层

允许硬隔离：

- chunk 为空。
- chunk 没有 evidence ID。
- evidence ID 不存在。
- chunk 和 evidence 属于不同 document version。
- chunk 全部来源 block 已隔离。

只软报告：

- chunk 过短或过长。
- 标题上下文不足。
- 重复率过高。
- 目录型内容比例过高。
- 表格或代码块疑似切碎。
- overlap 重复比例过高。

## 9. Decision 聚合与隔离传播

### 9.1 传播规则

- document 硬失败：整个 document version 不发布。
- page 硬失败：隔离该页 blocks 及其 evidence。
- block 硬失败：隔离该 block 和对应 evidence。
- chunk 硬失败：隔离该 chunk。
- chunk 引用任意隔离 evidence：整个 chunk 隔离。
- document 隔离后没有剩余 chunk：升级为 `block_document`。
- release 没有任何可发布文档：升级为 `block_release`。

### 9.2 Release 级错误

以下问题阻止整个 release：

- quality report 哈希不匹配。
- policy 哈希或版本不匹配。
- publication set 引用不存在对象。
- quarantine manifest 引用不存在对象。
- 索引包含 publication set 之外的 chunk。
- release 最终没有任何可发布内容。

单个文档或 chunk 的质量失败不得阻止其他健康文档发布。

### 9.3 邻接合并

publication set 必须在运行时邻接合并之前应用。

被隔离 chunk 将原始序列切成多个允许片段。邻接窗口只能在同一允许片段内生成，不得删除隔离 chunk 后把原本不相邻的两侧重新拼接。

## 10. Release Schema 演进

Phase 1 引入 `knowledge-release.v2`。

v2 在 Phase 0 release 绑定基础上增加：

- quality report 路径与哈希。
- publication set 路径与哈希。
- quarantine manifest 路径与哈希。
- policy ID、版本、哈希和执行模式。
- 原始 chunk 数量。
- published chunk 数量。
- quarantined chunk 数量。
- 索引 publication fingerprint。

### 10.1 v1 兼容

- v1 release 继续可读。
- v1 解释为全部 chunk 发布、无 publication set。
- Observe 阶段允许当前 v1 active release 继续服务。
- Candidate enforce 开始生成 v2。
- Production enforce 要求新激活 release 必须为 v2。
- 不原地修改或升级任何 v1 release。

### 10.2 Phase 1 派生产物

每个 v2 candidate 至少包含：

```text
release-manifest.json
quality-report.json
publication-set.json
quarantine-manifest.json
indexes/
quality-baseline.json
```

所有派生产物必须在 ready 前绑定哈希。

## 11. 执行模式

### 11.1 Observe

- 执行全部 evaluator 和 policy。
- 生成 quality report。
- 生成 publication preview 和 quarantine preview。
- 记录 `would_warn`、`would_quarantine`、`would_block`。
- 实际 publication set 保持全部内容。
- 不改变当前 production 行为。

### 11.2 Candidate Enforce

- candidate 使用 v2。
- hard decision 实际隔离内容。
- FTS 和向量索引只索引 publication set。
- 当前 active production 不变。
- candidate 失败不得改变 active pointer。

### 11.3 Production Enforce

- active release 必须为 v2。
- 检索只加载 publication set。
- 删除外部索引命中后的 quality gate bypass。
- 删除没有 eligible chunk 时回退全部 chunk 的逻辑。
- 查询只命中隔离内容时返回无可信证据。
- 不允许临时读取原始 chunks 绕过 policy。

## 12. 模式切换验收

### 12.1 Observe 到 Candidate Enforce

必须满足：

- 相同输入和 policy 重复运行，signals、decisions 和 publication set 完全一致。
- 已知严重缺陷 fixture 全部产生预期 hard decision。
- 健康 Golden fixture 硬误报为零。
- 每个 decision 都有 reason code、原始指标和对象定位。
- QNX、Qualcomm 和正常 PDF 基准均产生完整报告。
- 人工抽样确认 hard rule 不依赖厂商名称。

### 12.2 Candidate Enforce 到 Production Enforce

必须满足：

- 已知硬缺陷隔离率为 100%。
- 健康 Golden fixture 硬误报为零。
- publication set 之外进入索引的 chunk 数量为零。
- 所有 published chunk 证据可追踪率为 100%。
- page 和 block 隔离传播符合预期。
- candidate 没有可发布内容时稳定失败。
- 核心 Golden Queries 对健康知识的 Top-K 结果不低于 Phase 0 基线。
- 完成至少一次完整 candidate 构建与检索回归。

## 13. Production 激活与回滚

Production 切换必须显式执行，不自动激活。

激活前重新验证：

- policy 哈希。
- quality report 哈希。
- publication set 哈希。
- quarantine manifest 哈希。
- FTS 和向量索引 publication fingerprint。
- release 状态和 schema version。

回滚要求：

- 保留上一份 ready v2 release。
- 回滚只切换 active pointer。
- 不重新评估、不重建索引。
- 回滚目标重新执行完整绑定校验。
- break-glass 回到 v1 必须显式记录，并恢复 observe 行为，不得伪装为 production enforce。

## 14. 错误处理

### 14.1 Observe

检测器异常：

- 记录 `detector_error`。
- 保留异常名称和对象范围。
- 不影响当前 production。
- 不把异常误记为通过。

### 14.2 Candidate Enforce

以下情况 fail closed：

- detector 异常。
- policy 无法解析。
- 未知 reason code。
- report 或 publication set 生成失败。
- 引用关系不完整。
- 派生产物哈希校验失败。

失败 candidate 不得 ready 或激活。

### 14.3 Production

新 release 加载失败时：

- 拒绝切换 active pointer。
- 当前 active release 继续服务。
- 输出明确 blocker。

已激活 release 的绑定产物损坏时：

- 拒绝继续加载损坏 release。
- 触发回滚到上一份已验证 ready v2。
- 不回退到原始 chunks。

## 15. 测试策略

### 15.1 Contract 测试

覆盖：

- signal、policy、decision、report、publication、quarantine schema。
- 未知字段、未知 reason code、错误 scope 和错误 action。
- v1 和 v2 release 兼容。
- 派生产物哈希和引用完整性。

### 15.2 Evaluator 单元测试

每个 evaluator 必须包含：

- 健康样本。
- 单一缺陷样本。
- 边界值。
- 缺少可选数据。
- 重复执行确定性。
- 不同厂商但相同缺陷产生相同 reason code。

### 15.3 传播测试

覆盖：

- page 到 block、evidence、chunk。
- block 到 evidence、chunk。
- 部分隔离后 document 保留。
- 全部 chunk 隔离后 document block。
- 全部 document block 后 release block。
- 邻接合并不跨隔离间隙。

### 15.4 Index 与 Retrieval 测试

覆盖：

- publication set 外 chunk 不进入 FTS。
- publication set 外 chunk 不进入本地向量和 BGE 索引。
- 索引 publication fingerprint 错配被拒绝。
- production 不再执行两条绕过路径。
- 隔离内容查询返回无可信证据。
- 健康 Golden Queries 召回不回退。

### 15.5 端到端测试

使用：

- QNX 复杂 PDF fixture。
- Qualcomm 复杂 PDF fixture。
- 正常 PDF fixture。
- 手工构造完整性错误 fixture。
- 现有 51 题、100 题及对抗问题的相关子集。

## 16. 指标

Phase 1 至少记录：

- signal 数量及 reason code 分布。
- recommended action 和 effective action 分布。
- would block、would quarantine 数量。
- published 与 quarantined chunk 数量。
- 健康样本硬误报数量。
- 已知硬缺陷漏检数量。
- published chunk 证据追踪覆盖率。
- publication set 与索引差异数量。
- Golden Queries 健康知识 Recall@K 和正确证据 Top-K。
- detector 失败数量。

不使用单一平均总分作为发布依据。

## 17. 交付拆分

Phase 1 使用一份总体设计，但拆成三个独立 PR。

### 17.1 PR 1：Observe 基础能力

范围：

- Quality Signal、Policy、Decision 契约。
- reason code 注册表。
- 四层确定性 evaluator。
- observe policy engine。
- quality report。
- publication 和 quarantine preview。
- QNX、Qualcomm 和正常 PDF Golden fixture。
- 质量评估 CLI。

验收：

- 不改变现有发布和检索行为。
- 重复评估完全确定。
- 已知严重缺陷全部产生 `would_block`。
- 健康 Golden fixture 硬误报为零。

### 17.2 PR 2：Candidate Enforce

范围：

- `knowledge-release.v2`。
- publication set 和 quarantine manifest。
- 隔离传播。
- 按 publication set 构建索引。
- candidate ready 前一致性检查。
- v1 release 兼容读取。

验收：

- 隔离 chunk 进入索引数量为零。
- candidate 失败不影响 active。
- published chunk 证据追踪率为 100%。
- publication set 与索引内容一致。

### 17.3 PR 3：Production Enforce

范围：

- active v2 强制校验。
- retrieval publication set 过滤。
- 删除 gate bypass。
- 删除全量 fallback。
- 邻接合并隔离边界。
- 无可信证据响应。
- 回滚验证。
- 运维文档和线上质量信号。

验收：

- 隔离内容无法从任何 production 检索路径返回。
- 正常 Golden Queries 不低于批准基线。
- 无可信证据问题不生成伪证据。
- 上一 ready v2 可以原子回滚。

## 18. 实施顺序

顺序固定为：

```text
PR 1 Observe
  -> 真实基线审阅
  -> PR 2 Candidate Enforce
  -> candidate 验收
  -> PR 3 Production Enforce
```

PR 2 不得在 Observe 基线审阅前开始生产切换。

PR 3 不得在 Candidate Enforce 验收前关闭现有绕过逻辑。

每个 PR：

- 单独编写实施计划。
- 按 TDD 实现。
- 独立代码审查。
- 通过全量回归。
- 不自动合并或激活下一阶段。

设计文档通过审阅后，第一份实施计划只覆盖 PR 1 Observe。

## 19. 预期结果

Phase 1 完成后，系统将从“低质量内容可能被标记但仍可绕过”升级为：

- 新知识在发布前经过统一 policy 评估。
- 严重完整性缺陷自动隔离。
- 健康文档和健康 chunk 可以继续发布。
- 每项隔离都有稳定 reason code 和对象定位。
- 索引内容可以与 publication set 精确核对。
- production 无法通过索引命中或 fallback 绕过门禁。
- policy 升级可以重新评估历史产物。
- 出现问题可以回滚上一份 ready v2 release。

这为 Phase 2 的逐页解析路由、OCR 恢复和表格结构修复提供可量化的质量控制基础。
