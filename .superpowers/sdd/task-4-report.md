# 阶段 0 任务 4 实施报告

## 状态

PASS。已实现 release-aware Context Pack 检索、证据回溯和索引 release mismatch 阻断；未传 manifest 的 legacy 行为保持不变。

任务基线：`df9cb4e8a22f19a605b731f1631f850c6bab99bd`

## 实现摘要

- `build_context_pack_for_processed_dir()` 和 `trace_evidence_in_processed_dir()` 新增可选 `release_manifest_path`。
- release-aware Context Pack 在加载语料前校验 manifest 的 `processed_dir`，并校验每个已提供 FTS/vector 索引的 `release_id`。
- release-aware 调用允许不提供索引；提供无 release metadata 的 legacy 索引会以 `actual=None` 被稳定 mismatch 错误阻断。
- release-aware 检索与证据回溯均只使用 `iter_release_documents()` 返回的 manifest 固定版本，不扫描后续入库版本。
- chunk 与 BM25 缓存均使用 `processed_dir|release_id` 隔离；legacy 使用 `processed_dir|legacy-latest`。
- `ContextPackResult.release_id` 为可选字段；JSON、summary 和 bundle 反序列化路径均保留该值。legacy 结果为 `None`。
- 未实现或修改 baseline、finalize、activation、CLI，也未重构既有评分逻辑。

## TDD 证据

### RED：release-aware 接口、字段和隔离尚不存在

新增真实 ingest/release/index 行为测试后运行：

```powershell
python -m pytest tests/test_release_retrieval.py -q
```

结果：`9 failed in 0.70s`。失败均来自需求能力缺失：

```text
TypeError: build_context_pack_for_processed_dir() got an unexpected keyword argument 'release_manifest_path'
TypeError: trace_evidence_in_processed_dir() got an unexpected keyword argument 'release_manifest_path'
AttributeError: 'ContextPackResult' object has no attribute 'release_id'
```

测试覆盖：

- release 后新增文档不进入旧 release 检索；
- FTS/vector 不同 release 索引被拒绝；
- FTS/vector legacy `release_id=None` 索引被拒绝；
- manifest 与调用 `processed_dir` 不匹配被拒绝；
- 同一 `processed_dir` 的两个 release 不复用 chunk 缓存；
- 旧 release 的证据回溯不扫描 release 后文档；
- JSON/summary 输出 release ID，legacy 结果保持 `None`。

### GREEN：最小 release-aware 实现

同一命令重跑：

```text
9 passed in 0.66s
```

## 最终测试与检查

任务 4、Context Pack 与 Layer1 contract：

```powershell
python -m pytest tests/test_release_retrieval.py tests/test_context_pack_retrieval.py tests/test_layer1_contract.py -q
```

结果：`67 passed in 3.30s`。

扩展 release、manifest 与索引回归：

```powershell
python -m pytest tests/test_release_retrieval.py tests/test_context_pack_retrieval.py tests/test_layer1_contract.py tests/test_release_bound_indexes.py tests/test_release_manifest.py tests/test_fts_index.py tests/test_vector_index.py -q
```

结果：`103 passed in 4.71s`。

完整回归：

```powershell
python -m pytest -q
```

结果：`361 passed, 6 skipped, 29 warnings in 9.64s`。

语法与差异检查：

```powershell
python -m compileall -q src/agent_knowledge_hub/retrieval.py tests/test_release_retrieval.py
git -c core.whitespace=cr-at-eol diff --check
```

结果：exit 0，无输出。

## 修改文件

- 修改 `src/agent_knowledge_hub/retrieval.py`
- 新增 `tests/test_release_retrieval.py`
- 新增 `.superpowers/sdd/task-4-report.md`

## 自查

- mismatch 校验发生在 `_load_processed_chunks()`、FTS 查询和 vector 查询之前。
- 同时提供两个索引时会逐一读取并校验 release ID；任一缺失或不匹配即阻断。
- release-aware 无索引路径正常工作，且结果只包含 manifest 固定版本。
- chunk 与 BM25 两类 corpus 级缓存都绑定 release ID，避免评分上下文跨 release 污染。
- 证据回溯使用与 Context Pack 相同的 manifest 版本集合。
- legacy 入口不加载 manifest、不校验索引 release ID，继续扫描 latest 版本。
- 工作区原有未跟踪 `.agent-artifacts/` 与 `docs/feishu-bot-optimization-plan.md` 未修改且不纳入提交。

## 顾虑

- 完整测试仍报告 29 条既有 FastAPI/Starlette 弃用警告，与本任务无关。
