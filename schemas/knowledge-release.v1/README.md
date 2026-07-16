# knowledge-release.v1

该目录定义阶段 0 的处理记录、质量记录和候选 release manifest 契约。

- `processing-record.schema.json` 绑定一次处理运行与 canonical/chunks 哈希。
- `quality-record.schema.json` 保存显式的质量观测值和不可用指标。
- `release-manifest.schema.json` 固化 release 选择的文档版本、processing/quality
  sidecar、相对产物路径和 SHA-256。BGE `.npz` 同时绑定矩阵及其规范
  `.npz.metadata.json` sidecar。

候选 manifest 只选择每份文档的一个明确版本。历史
`layer1.processed.v1` 目录保持只读；缺失的质量记录与 processing record
分别派生到候选 release 的 `derived-quality/`、`derived-processing/` 目录。

BGE metadata 和 resumable work manifest 记录模型内容指纹：单文件按内容哈希，
目录按相对 POSIX 路径排序并绑定每个常规文件的内容哈希，不使用 mtime。模型路径
中出现 symlink 时稳定拒绝为 `model_path_symlink_unsupported`，避免跟随到目录外。

`candidate` 用于发布前验证和影子检索：可以不带索引执行 lexical 检索，也可显式
传入 release ID 匹配的临时候选索引。`ready` 用于生产检索：索引默认从 manifest
自动解析；若调用方显式提供路径，则必须与 manifest 的规范绑定路径完全相同。
每次生产检索和激活都会重新验证制品哈希及 release ID。
