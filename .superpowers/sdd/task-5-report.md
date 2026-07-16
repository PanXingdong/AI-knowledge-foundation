# 阶段 0 任务 5 实施报告

## 状态

PASS。已实现可重复质量基线、release 完成验证、原子 manifest 切换与 ready release 原子激活；未实现 CLI 或一键 pipeline。

任务基线：`2998e0839269f2aeafc7e04ccfc0321e65acf87a`

## 实现摘要

- 新增 `QualityBaseline` 与纯读取 `build_quality_baseline()`，从 manifest 固定的 canonical/chunks 汇总文档、chunk、evidence、可追溯率、质量状态、parser、格式和 warning 计数。
- baseline 不写文件；`to_dict()` 不含时间戳、绝对路径或机器相关字段，计数字典排序后输出。
- chunk 仅在至少包含一个 evidence 引用且所有引用均存在于对应 canonical `evidence_spans` 时计为可追溯。
- `finalize_release()` 校验 canonical/chunks/quality 三类源制品、FTS/vector/baseline release ID，并绑定三个 release 内相对路径及 SHA-256。
- manifest 通过同目录 `.tmp` 文件写入后原子替换；成功或异常都会清理临时文件。
- `activate_release()` 只接受 `ready`，重新校验三类源制品、三个绑定文件哈希及 release ID 后原子写 active pointer，并安全创建父目录。
- `load_active_release()` 校验 pointer 与 manifest 的 release ID 一致性。
- 既有 candidate 重复创建幂等、ready manifest 保留及 legacy API 测试保持通过。

## TDD 证据

### RED 1：任务 5 API 不存在

先新增 baseline、finalize 与 activation 行为及错误路径测试，然后运行：

```powershell
python -m pytest tests/test_quality_baseline.py tests/test_release_manifest.py -q
```

结果：测试收集失败，符合预期缺失能力：

```text
ModuleNotFoundError: No module named 'agent_knowledge_hub.quality_baseline'
2 errors in 0.20s
```

### GREEN 1：最小 baseline/finalize/activation 实现

实现后同一命令首次得到 `36 passed, 1 failed`；唯一失败是短测试文档按既有规则被正确标记为 `low_quality`，测试夹具错误预期为 `ok`。修正夹具断言后：

```text
37 passed in 2.83s
```

### RED 2：质量状态仍读取 manifest 冗余字段

自查补充 canonical 来源测试：

```powershell
python -m pytest tests/test_quality_baseline.py::test_baseline_quality_status_comes_from_pinned_canonical -q
```

结果：

```text
FAILED: {'manifest_override': 2} != {'low_quality': 2}
1 failed in 0.18s
```

### GREEN 2：质量状态改从固定 canonical 汇总

最小修正后：

```text
1 passed in 0.15s
38 passed in 3.10s
```

## 错误路径覆盖

- candidate release 激活拒绝且不创建 pointer。
- FTS、vector、baseline 任一 release ID 错配均阻止 finalize，manifest 保持 candidate。
- canonical、chunks、quality 任一源制品篡改均阻止 finalize。
- ready 后 canonical、chunks、quality、FTS、vector、baseline 任一制品篡改均阻止激活。
- finalize 写入相对 release 目录路径，并绑定 FTS/vector/baseline 三个 SHA-256。
- manifest 和 active pointer 的 `.tmp` 文件在成功及校验失败路径均不残留。
- pointer 多层父目录不存在时可安全创建。

## 最终测试与检查

任务 5 测试：

```powershell
python -m pytest tests/test_quality_baseline.py tests/test_release_manifest.py -q
```

结果：`38 passed in 3.10s`。

release/index/retrieval 相关回归：

```powershell
python -m pytest tests/test_quality_baseline.py tests/test_release_manifest.py tests/test_release_bound_indexes.py tests/test_release_retrieval.py tests/test_fts_index.py tests/test_vector_index.py -q
```

结果：`62 passed in 4.23s`。

完整回归：

```powershell
python -m pytest -q
```

结果：`378 passed, 6 skipped, 29 warnings in 13.03s`。

语法与差异检查：

```powershell
python -m compileall -q src/agent_knowledge_hub
git diff --check
```

结果：exit 0，无错误。

## 修改文件

- 新增 `src/agent_knowledge_hub/quality_baseline.py`
- 修改 `src/agent_knowledge_hub/release_manifest.py`
- 新增 `tests/test_quality_baseline.py`
- 修改 `tests/test_release_manifest.py`
- 新增 `.superpowers/sdd/task-5-report.md`

## 自查

- baseline 所有聚合值均来自 release 固定 canonical/chunks，不读取扫描到的更新版本。
- finalize 在任何 manifest 写入前完成源制品、路径边界、文件存在、release ID 和 baseline ID 校验。
- 激活在 pointer 写入前重新执行源制品哈希、绑定文件哈希和 release ID 校验。
- 原子写 helper 使用 `finally` 清理临时文件，避免替换异常留下 `.tmp`。
- index/baseline 路径必须位于 release 目录内，并以 POSIX 风格相对路径写入 manifest。
- 工作区原有未跟踪 `.agent-artifacts/` 与 `docs/feishu-bot-optimization-plan.md` 未修改且不纳入提交。

## 顾虑

- 完整测试仍报告 29 条既有 FastAPI/Starlette 弃用警告，与本任务无关。
