# 阶段 0 任务 2 实施报告

## 状态

PASS。已实现候选 release manifest、精确产物迭代、路径边界与三类产物哈希校验，以及 `knowledge-release.v1` 严格 schema。未修改索引、检索、CLI 或激活逻辑。

任务基线：`2a1961bb1793ba313e085af12fe7fbe200efca59`

## 实现摘要

- 新增 `ReleaseDocument`、`ReleaseManifest` 和 `RELEASE_MANIFEST_SCHEMA_VERSION`。
- `create_candidate_release()` 仅在创建阶段按既有 latest-version 排序选择一次版本，并将排序后的文档版本、canonical/chunks/quality 哈希和规则版本绑定进稳定 release ID。
- release ID 不包含创建时间、release 目录或机器绝对路径。
- manifest 固化相对 canonical、chunks、processing record 与 quality record 路径。
- `iter_release_documents()` 不重新扫描 latest 版本；它先验证 manifest 固定产物，再只返回所选 chunks 路径和 canonical payload。
- canonical、chunks、processing record 与 quality record 路径均拒绝绝对路径、`..` 穿越及解析后越界。
- canonical、chunks、quality record 三类 SHA-256 均在迭代前验证，错误码稳定并包含 `document_version_id`。
- 新入库目录直接绑定已有 `quality-record.json`；legacy 缺失 sidecar 时只读推断 processing record，并将质量记录写入候选 release 的 `derived-quality/<document_version_id>.json`，不修改历史版本目录。
- 未增加运行时依赖。

## TDD 证据

### RED 1：模块尚不存在

命令：

```powershell
python -m pytest tests/test_release_manifest.py -q
```

结果：exit 2；收集阶段按预期失败：

```text
ModuleNotFoundError: No module named 'agent_knowledge_hub.release_manifest'
1 error in 0.18s
```

### GREEN 1：首批候选创建与 chunks 篡改检测

同一命令结果：

```text
2 passed in 0.18s
```

### RED 2：严格路径与 legacy 派生哈希

命令：

```powershell
python -m pytest tests/test_release_manifest.py -q
```

结果：exit 1；两个预期行为尚未满足：

```text
FAILED test_release_rejects_processing_record_path_traversal
FAILED test_legacy_release_derives_quality_without_mutating_version_dir
2 failed, 8 passed in 0.51s
```

首个失败证明 processing sidecar 路径尚未校验；第二个失败证明 Windows 文本换行使预计算的派生 quality 哈希与落盘字节不一致。

### GREEN 2：路径与派生哈希修复

同一命令结果：

```text
10 passed in 0.42s
```

### RED 3：schema 契约尚缺

命令：

```powershell
python -m pytest tests/test_schema_contracts.py -q
```

结果：exit 1：

```text
FAILED test_knowledge_release_schema_files_exist
FAILED test_knowledge_release_schemas_match_supported_versions
2 failed, 4 passed in 0.15s
```

### GREEN 3：指定 manifest 与 schema 测试

命令：

```powershell
python -m pytest tests/test_release_manifest.py tests/test_schema_contracts.py -q
```

结果：

```text
16 passed in 0.42s
```

### RED 4：quality 路径命名空间碰撞

自查新增文档标题为 `derived-quality` 的回归用例。命令：

```powershell
python -m pytest tests/test_release_manifest.py -q
```

结果：exit 1：

```text
FAILED test_processed_quality_path_named_derived_quality_stays_under_processed_root
1 failed, 10 passed in 0.52s
```

该失败证明仅按首段判断派生路径会误判 processed 目录；实现随后改为严格匹配 `derived-quality/<document_version_id>.json`。

### GREEN 4

同一命令结果：

```text
11 passed in 0.46s
```

## 最终测试与检查

指定测试：

```powershell
python -m pytest tests/test_release_manifest.py tests/test_schema_contracts.py -q
```

结果：`16 passed in 0.42s`。

相关回归：

```powershell
python -m pytest tests/test_release_manifest.py tests/test_schema_contracts.py tests/test_processing_record.py tests/test_quality_contracts.py tests/test_document_ingest_pipeline.py tests/test_runtime_dependencies.py -q
```

结果：`35 passed in 0.75s`。

语法与差异检查：

```powershell
python -m compileall -q src/agent_knowledge_hub
git diff --check
```

结果：exit 0，无输出。

## 修改文件

- 新增 `src/agent_knowledge_hub/release_manifest.py`
- 新增 `schemas/knowledge-release.v1/release-manifest.schema.json`
- 新增 `schemas/knowledge-release.v1/README.md`
- 新增 `tests/test_release_manifest.py`
- 修改 `tests/test_schema_contracts.py`
- 新增 `.superpowers/sdd/task-2-report.md`

## 自查

- 范围：未修改索引、检索、CLI、激活逻辑或依赖声明。
- 兼容性：保留 `layer1.processed.v1` 读取方式；legacy 测试逐文件比较前后哈希，确认历史目录只读。
- 确定性：release ID 输入仅为 schema/规则版本与排序后的版本 ID、canonical/chunks/quality 哈希；时间和路径仅写入 manifest 元数据。
- 精确迭代：创建 release 后再入库更高版本，迭代仍返回 manifest 固定的旧版本。
- 安全性：覆盖 processing/canonical 路径穿越、三类哈希篡改及 derived-quality 命名碰撞。
- 依赖：运行时依赖回归通过，新增模块仅使用标准库和项目现有模块。

## 顾虑

- `load_release_manifest()` 按 dataclass 字段加载 manifest，但不会在运行时执行 JSON Schema 校验；简报要求提供严格 schema 且禁止增加运行时依赖，因此本任务未引入 `jsonschema`。
- latest-version 排序逻辑按现有实现局部复用，以避免提前改动索引/检索模块；未来若统一该排序规则，应将各处重复实现收敛到共享模块。

## 审查修复：manifest 完整性加固

### 修复内容

- `ReleaseManifest.resolve_artifact()` 拒绝绝对路径，以及解析后逃逸
  `manifest_path.parent` 的相对路径，稳定错误为
  `release_artifact_path_escape:<name>`。
- 候选创建以 canonical 的 `document_version_id` 为权威值，要求 processing
  record 与 quality record 的版本 ID 相同。
- `validate_release_artifacts()` 在路径、存在性和对应哈希通过后，继续验证
  canonical、processing record、quality record 的版本 ID 与 manifest item 一致。
- 同 release ID 的 manifest 已存在时，在任何写入前核对 release ID、完整文档
  条目与实际产物；一致则直接返回已有 manifest，不改变
  `created_at/status/indexes/baseline` 或文件字节，不一致则抛出
  `existing_release_manifest_mismatch:<release_id>`。
- 未增加索引、检索、finalize API 或运行时依赖。

### TDD 证据

#### RED 5：release artifact 路径逃逸

```powershell
python -m pytest tests/test_release_manifest.py -q -k "resolve_artifact"
```

结果：exit 1；绝对路径与 `../../outside.db` 均未抛错：

```text
2 failed, 11 deselected in 0.19s
```

#### GREEN 5

同一命令结果：

```text
2 passed, 11 deselected in 0.11s
```

#### RED 6：跨产物版本一致性

```powershell
python -m pytest tests/test_release_manifest.py -q -k "other_version"
```

结果：exit 1；创建阶段的 quality/processing 错配，以及落盘后重算哈希的
canonical/quality 错配和 processing 错配均未被阻断：

```text
5 failed, 13 deselected in 0.35s
```

#### GREEN 6

同一命令结果：

```text
5 passed, 13 deselected in 0.25s
```

#### RED 7：同 release ID 重复创建

```powershell
python -m pytest tests/test_release_manifest.py -q -k "repeated"
```

结果：exit 1；重复调用刷新 `created_at`、覆盖 ready 状态，且未拒绝不一致的
已有 manifest：

```text
3 failed, 18 deselected in 0.26s
```

#### GREEN 7

同一命令结果：

```text
3 passed, 18 deselected in 0.20s
```

### 审查修复测试

任务 2 测试：

```powershell
python -m pytest tests/test_release_manifest.py tests/test_schema_contracts.py -q
```

结果：`27 passed in 0.88s`。

相关回归：

```powershell
python -m pytest tests/test_release_manifest.py tests/test_schema_contracts.py tests/test_processing_record.py tests/test_quality_contracts.py tests/test_document_ingest_pipeline.py tests/test_runtime_dependencies.py -q
```

结果：`45 passed in 1.10s`。

语法与差异检查：

```powershell
python -m compileall -q src/agent_knowledge_hub
git diff --check
```

结果：exit 0，无输出。

### 审查修复修改文件

- 修改 `src/agent_knowledge_hub/release_manifest.py`
- 修改 `tests/test_release_manifest.py`
- 追加 `.superpowers/sdd/task-2-report.md`

### 审查修复自查

- 路径：覆盖 Windows 绝对路径和父目录逃逸；解析后仍以 release 根目录为边界。
- 版本：普通内容篡改仍优先保持既有 hash mismatch；只有哈希有效时追加版本一致性检查。
- 幂等：已有 ready manifest 的状态、索引、基线和原始字节均被测试锁定。
- 范围：未触及索引、检索、CLI、激活或正式 finalize API。
- 依赖：未引入 JSON Schema 运行时库或其他依赖。

### 审查修复顾虑

- 无新增顾虑；原报告中关于运行时 schema 校验和 latest 排序局部复用的说明仍适用。
