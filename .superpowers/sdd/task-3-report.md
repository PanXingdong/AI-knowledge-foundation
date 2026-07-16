# 阶段 0 任务 3 实施报告

## 状态

PASS。已实现 release-bound FTS、本地向量和 BGE-M3 普通/可恢复索引，保留未传 manifest 时的 legacy latest 选择与 `release_id=None`。

任务基线：`891ad33e375f7d4ccdcb1cabfa93bb38a197091b`

## 实现摘要

- `build_fts_index()`、`build_vector_index()` 及两条 BGE-M3 构建路径接受可选 `release_manifest_path`。
- release-aware 构建先确认 manifest 的 `processed_dir` 与调用目录解析后相同，再使用 `iter_release_documents()` 固定的 canonical/chunks；后续入库文档不会进入该索引。
- FTS 在创建 FTS 表、写入 chunks 的同一 SQLite 事务中创建并写入 `release_metadata`。
- 本地 JSON、BGE 普通构建和 BGE resumable 构建均写入 `release_id`，构建 summary 也包含该字段。
- 新增 `read_fts_release_id()` 和 `read_vector_release_id()`；旧 FTS 无 metadata 表、旧 vector 无 `release_id` 均返回 `None`。
- BGE 新元数据路径按简报使用 `*.metadata.json`，读取与查询兼容历史 `*.npz.metadata.json`。
- 未修改 retrieval、CLI、finalize、activation 或依赖声明。

## TDD 证据

### RED 1：release-bound 接口和 metadata 尚不存在

首次运行：

```powershell
python -m pytest tests/test_release_bound_indexes.py -q
```

收集阶段因 `read_fts_release_id` 尚不存在而 exit 2。调整测试导入使全部行为测试可执行后重跑，得到：

```text
7 failed in 0.45s
TypeError: build_fts_index() got an unexpected keyword argument 'release_manifest_path'
TypeError: build_vector_index() got an unexpected keyword argument 'release_manifest_path'
AttributeError: 'FtsIndexBuildSummary' object has no attribute 'release_id'
AttributeError: module ... has no attribute 'read_fts_release_id'
```

失败原因均为需求能力缺失。

### GREEN 1：基础 release 绑定

同一命令：

```text
7 passed in 0.55s
```

### RED 2：BGE 元数据路径不符合简报

将测试收紧为 `.npz` 对应 `with_suffix(".metadata.json")` 后：

```text
2 failed, 5 passed in 0.57s
FileNotFoundError: ...build_bge_m3_vector_index.metadata.json
FileNotFoundError: ...build_bge_m3_vector_index_resumable.metadata.json
```

### GREEN 2：统一 BGE 元数据路径

任务 3 聚焦测试重跑：

```text
12 passed in 0.65s
```

### RED 3：历史 BGE 元数据命名兼容

```powershell
python -m pytest tests/test_release_bound_indexes.py::test_vector_release_reader_supports_legacy_bge_metadata_name -q
```

结果：exit 1，reader 查找新路径时触发 `FileNotFoundError`。

### GREEN 3：历史命名只读 fallback

同一命令：

```text
1 passed in 0.08s
```

## 最终测试与检查

任务 3 与现有索引测试：

```powershell
python -m pytest tests/test_release_bound_indexes.py tests/test_fts_index.py tests/test_vector_index.py -q
```

结果：`13 passed in 0.70s`。

完整回归：

```powershell
python -m pytest -q
```

结果：`350 passed, 6 skipped, 29 warnings in 9.42s`。警告为既有 FastAPI/Starlette 弃用警告。

语法与差异检查：

```powershell
python -m compileall -q src tests
git -c core.whitespace=cr-at-eol diff --check
```

结果：exit 0，无输出。

## 修改文件

- 修改 `src/agent_knowledge_hub/fts_index.py`
- 修改 `src/agent_knowledge_hub/vector_index.py`
- 新增 `tests/test_release_bound_indexes.py`
- 新增 `.superpowers/sdd/task-3-report.md`

## 自查

- FTS metadata 建表、release ID 写入、FTS chunks 写入仅在最终 `commit()` 时共同提交。
- manifest 目录不匹配在读取 release 文档前抛出稳定错误 `release_processed_dir_mismatch`。
- release-aware 三类 vector 构建均复用同一输入解析分支；普通与 resumable BGE 测试使用替身模型，不下载模型。
- legacy FTS/vector 构建仍走现有 latest 选择，summary 和落盘 metadata 的 `release_id` 均为 `None`。
- release 创建后新增文档的测试确认 FTS、本地 vector 和两条 BGE 构建均只索引 manifest 固定文档。
- 工作区原有未跟踪 `.agent-artifacts/` 与 `docs/feishu-bot-optimization-plan.md` 未修改且不纳入提交。

## 顾虑

- 完整测试仍报告 29 条既有 FastAPI/Starlette 弃用警告，与本任务无关。
- BGE 新构建的 metadata 文件名由历史 `*.npz.metadata.json` 统一为简报指定的 `*.metadata.json`；读取和查询已提供历史文件名 fallback，但其他直接依赖旧文件名的外部脚本需要迁移。
