# knowledge-quality.v1

该目录定义 Phase 1 Observe 的质量策略、观测报告和预览产物契约：

- `quality-policy.schema.json`：仅描述 Observe 策略及原因码到建议动作的映射。
- `quality-report.schema.json`：保存观测信号、建议决策与实际决策。
- `publication-preview.schema.json`：展示若启用策略时可能排除的文档版本和分块。
- `quarantine-preview.schema.json`：展示若启用策略时可能隔离的对象。

四个契约均使用 JSON Schema 2020-12，拒绝未声明字段，并要求模型定义的全部字段。
Phase 1 的 `ObservedQualitySignal` 与 Phase 0 的基础指标 `QualitySignal` 是独立类型；
本契约不改变 `knowledge-quality-record.v1` 或其 API。

本阶段所有产物的 `mode` 固定为 `observe`。`recommended_action` 仅表达策略建议，
`effective_action` 表达实际动作；Observe 模式不会据此执行隔离、阻断发布或其他门禁。

所有 ID、原因码和证据 ID 数组由生产者按字符串升序输出。Schema 使用
`uniqueItems` 拒绝重复值；JSON Schema 2020-12 没有通用数组排序关键字，因此排序
由模型工厂和生产者契约保证。
