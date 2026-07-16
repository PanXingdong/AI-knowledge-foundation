# knowledge-release.v1

该目录定义阶段 0 的处理记录、质量记录和候选 release manifest 契约。

- `processing-record.schema.json` 绑定一次处理运行与 canonical/chunks 哈希。
- `quality-record.schema.json` 保存显式的质量观测值和不可用指标。
- `release-manifest.schema.json` 固化候选 release 选择的文档版本、相对产物路径和三类 SHA-256。

候选 manifest 只选择每份文档的一个明确版本。历史
`layer1.processed.v1` 目录保持只读；缺失的质量记录派生到候选 release 的
`derived-quality/` 目录。
