# 16 样本文档接入说明

本文说明真实 PDF/Word/HTML 文档到位后，如何快速生成 `sample-manifest.csv` 草稿。

如果文档 owner、领域确认人或任务评分人已经填写 `samples/document-intake-template.csv`，优先使用第 3 节的候选文档接入脚本。它会按 owner 填好的 `source_location` 复制文档并更新 manifest，比手工复制后再扫描更稳。

## 1. 放置真实文档

把第一批真实文档放到：

```text
.\samples\raw\
```

支持格式：

- `.pdf`
- `.docx`
- `.doc`
- `.html`
- `.htm`

## 2. 预览扫描结果

先 dry run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-sample-docs.ps1"
```

脚本会输出：

- 找到多少支持格式文档。
- 有多少新文档可填入 manifest。
- 有多少文档超出 10 个样本槽位。

## 3. 生成 manifest 草稿

### 3.1 从 owner 候选文档表接入

先 dry run：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-document-intake-to-samples.ps1"
```

确认计划无误后应用：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\apply-document-intake-to-samples.ps1" -Apply
```

脚本会：

- 从 `samples/document-intake-template.csv` 读取 ready 文档候选。
- 检查 `source_location` 是本地或共享文件，且路径存在。
- 要求至少 10 份 ready 文档。
- 要求样本文档覆盖表格、多栏、扫描件或 OCR 风险。
- 把文档复制到 `samples/raw/`。
- 备份并更新 `samples/sample-manifest.csv`。

如果 manifest 已经是非占位内容，脚本会拒绝覆盖；确认要重建时再加 `-Force`。

验证桥接脚本本身：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\test-document-intake-to-samples-smoke.ps1"
```

### 3.2 从 raw 目录扫描生成草稿

生成草稿，不覆盖正式 manifest：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-sample-docs.ps1" -WriteDraft
```

输出：

```text
.\samples\sample-manifest.draft.csv
```

草稿会自动填：

- `file_path`
- `document_title`
- `status = candidate`
- `notes = auto-discovered...`

但以下字段仍必须人工确认：

- `slot_type`
- `document_version`
- `owner`
- `is_scanned`
- `has_tables`
- `has_multicolumn`
- `confidentiality`

## 4. 应用到正式 manifest

确认草稿无误后，可以更新正式 manifest：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-sample-docs.ps1" -Apply
```

脚本会先备份原文件：

```text
sample-manifest.backup-yyyyMMdd-HHmmss.csv
```

然后写入：

```text
.\samples\sample-manifest.csv
```

## 5. 严格检查

至少需要 10 份支持格式文档：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\import-sample-docs.ps1" -Strict
```

如果不足 10 份，严格模式会失败。

## 6. 注意事项

脚本只负责发现文件并生成登记草稿，不判断文档内容是否真的匹配槽位。

例如：一个文件名包含 supplier，不代表它一定适合 `供应商接口/机制文档` 槽位。最终是否满足样本选择要求，仍需要人工确认。
