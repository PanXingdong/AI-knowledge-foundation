# 21 Owner 响应跟踪说明

本文用于跟踪文档 owner、领域确认人或任务评分人是否已经提供第一轮实验需要的真实文档和真实 Agent 任务。

它不替代正式输入表：

```text
.\samples\document-intake-template.csv
.\experiments\templates\task-intake-template.csv
```

它只回答一个问题：

```text
现在卡在哪个 owner、哪类输入、哪个阻塞点？
```

## 1. 跟踪表位置

```text
.\samples\owner-response-tracker.csv
```

## 2. 字段说明

| 字段 | 说明 |
|---|---|
| `owner` | 文档 owner、领域确认人或任务评分人 |
| `module` | 模块、领域或样本范围，第一轮默认 `混合工程文档样本` |
| `request_sent_date` | 收集请求发出日期 |
| `due_date` | 期望反馈日期 |
| `requested_documents` | 请求 owner 提供的文档数量或范围 |
| `provided_documents` | owner 已提供的文档数量 |
| `requested_tasks` | 请求 owner 提供的任务数量或范围 |
| `provided_tasks` | owner 已提供的任务数量 |
| `document_intake_updated` | 是否已写入 `document-intake-template.csv` |
| `task_intake_updated` | 是否已写入 `task-intake-template.csv` |
| `current_status` | `not_sent` / `sent` / `partial` / `ready` / `blocked` |
| `blocker` | 当前阻塞原因 |
| `next_follow_up` | 下一次跟进动作 |
| `notes` | 备注 |

## 3. 状态口径

| current_status | 含义 |
|---|---|
| `not_sent` | 还没发 owner 收集请求 |
| `sent` | 已发请求，等待反馈 |
| `partial` | 已收到部分文档或任务，但还不够 readiness |
| `ready` | 已补入正式 intake 表，可跑 `check-intake-readiness.ps1 -Strict` |
| `blocked` | owner 明确无法提供，或有合规/权限/路径问题 |

## 4. 推荐跟进节奏

1. 发送 [20-owner收集执行包.md](20-owner收集执行包.md)，或先运行 `scripts/export-owner-package.ps1` 导出独立交付包。
2. 要求 owner 按导出包里的 `OWNER_CHECKLIST.md` 自检后再返回。
3. 在 `owner-response-tracker.csv` 中新增或更新 owner 行。
4. owner 返回文档/任务后，先更新 tracker。
5. 确认字段完整后，再写入正式 intake 表。
6. 每次更新后运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\report-experiment-status.ps1"
```

7. 正式 intake 表补齐后运行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\check-intake-readiness.ps1" -Strict
```

也可以在导出收集包时同步追加 tracker 记录：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\export-owner-package.ps1" -CreateZip -UpdateTracker -Owner "owner-name"
```

这个动作只记录“已发请求”，不会让实验 readiness 通过。正式实验仍只认 `document-intake-template.csv` 和 `task-intake-template.csv` 中的真实输入。

owner 返回填好的目录或 zip 后，先导入到正式 intake 表：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip"
powershell -ExecutionPolicy Bypass -File ".\scripts\import-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip" -Apply
```

导入脚本会把返回包里的 `candidate_id` 重新编号，并同步更新任务里的 `allowed_documents` 引用，避免多个 owner 都从同一份模板填写造成 ID 冲突。

如果返回包已经完整，可以用一键入口先 dry run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip" -RunId "run-001"
```

dry run 通过后再显式写入正式 intake、复制文档、创建 run 并生成成对 prompt：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\prepare-experiment-run-from-owner-package.ps1" -PackagePath "C:\path\to\returned-package.zip" -RunId "run-001" -Apply
```

查看当前 owner 收集缺口摘要：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\report-owner-intake-status.ps1"
```

这个报告会把 tracker、候选文档表和候选任务表合并成一个状态：是否已经发出 owner 请求、ready 文档还差几份、ready 任务还差几个、表格/多栏/OCR 风险样本是否覆盖。

## 5. 不要把 tracker 当作实验输入

`owner-response-tracker.csv` 只是项目推进表。

实验脚本只认：

```text
samples\document-intake-template.csv
experiments\templates\task-intake-template.csv
samples\sample-manifest.csv
experiments\runs\<run-id>\*
```

所以 tracker 里写了“已提供 3 份文档”，不代表实验已经 ready。必须把真实路径、版本、owner、证据和任务答案写入正式 intake 表，才能通过 readiness 检查。
