# 09 评估指标与基线对比

## 1. 评估目标

本评估回答一个问题：

```text
Agent Knowledge Hub 的 Context Pack 是否比直接给 Agent 文件更好？
```

如果不能证明更好，就不进入完整知识图谱建设。

## 2. 基线测试：直接给 Agent 文件

### 2.1 输入

- 同一批 10 份样本文档。
- 同一批 3-5 个真实 Agent 任务。
- 同一个 Agent 或同一类 Agent。

### 2.2 执行方式

Agent 直接拿到：

```text
原始 PDF/Word/Markdown 文件
或用户手动贴入/指定文档内容
```

不提供预加工 Context Pack。

### 2.3 记录项

| 指标 | 说明 |
|---|---|
| task_id | 任务编号 |
| task_type | 查约束/查接口/生成测试点 |
| source_docs | 给 Agent 的原始文件 |
| answer_correct | 答案是否正确 |
| missed_constraints | 遗漏的关键约束数量 |
| wrong_claims | 错误结论数量 |
| citation_correct | 引用文档/页码/章节是否正确 |
| token_cost | 上下文和输出 token |
| elapsed_minutes | 完成耗时 |
| human_fix_count | 人工修正次数 |
| notes | 失败原因 |

## 3. Context Pack 实验

### 3.1 输入

与基线测试完全相同：

- 同一批文档。
- 同一批任务。
- 同一个 Agent。

差异只在于 Agent 不直接读全部文件，而是调用：

```text
get_context_pack
```

### 3.2 Context Pack 最小内容

```json
{
  "summary": "...",
  "constraints": [],
  "relevant_sections": [],
  "evidence": [
    {
      "document": "...",
      "version": "...",
      "page": 1,
      "section": "...",
      "span_id": "..."
    }
  ],
  "open_questions": []
}
```

### 3.3 记录项

记录同基线测试，额外记录：

| 指标 | 说明 |
|---|---|
| context_pack_tokens | Context Pack token 大小 |
| retrieved_span_count | 召回 span 数量 |
| useful_span_count | 实际有用 span 数量 |
| irrelevant_span_count | 无关 span 数量 |
| retrieval_failure | 是否检索失败 |

## 4. PDF 解析器对比指标

解析器候选：

```text
Docling
MinerU
Unstructured
```

解析器评分表字段映射：

| 指标 | CSV 字段 | 计算方式 |
|---|---|---|
| 页码保留率 | `page_metadata_rate` | 有正确 page metadata 的 block 数 / 总 block 数 |
| Span 可追溯率 | `span_traceability_rate` | 能回到原文位置或稳定 block/span id 的内容数 / 总内容数 |
| 表格结构准确率 | `table_accuracy` | 人工抽样中结构可用的关键表格数 / 抽样关键表格数 |
| 阅读顺序准确率 | `reading_order_accuracy` | 阅读顺序正确块数 / 抽样块数 |
| OCR 准确率 | `ocr_accuracy` | 正确识别字符数 / 抽样字符数 |

### 4.1 页码保留率

```text
有正确 page metadata 的 block 数 / 总 block 数
```

及格线：

```text
>= 95%
```

### 4.2 Span 可追溯率

```text
能回到原文位置或稳定 block/span id 的内容数 / 总内容数
```

及格线：

```text
>= 90%
```

### 4.3 表格结构准确率

人工抽样检查表格：

- 行列是否正确。
- 跨页表格是否被错误拆分。
- 表头是否保留。
- 单元格内容是否错位。

及格线：

```text
关键表格可用率 >= 80%
```

### 4.4 阅读顺序准确率

人工抽样检查多栏、页眉页脚、图注、列表：

```text
阅读顺序正确块数 / 抽样块数
```

及格线：

```text
>= 90%
```

### 4.5 OCR 准确率

针对扫描页或图片页：

```text
正确识别字符数 / 抽样字符数
```

及格线：

```text
>= 95%（关键术语、接口名、版本号不得错）
```

## 5. Agent 使用效果指标

### 5.1 答案准确率

```text
正确回答任务数 / 总任务数
```

目标：

```text
Context Pack 组比基线组提升 >= 30%
```

### 5.2 关键约束遗漏率

```text
遗漏关键约束数 / 应覆盖关键约束数
```

目标：

```text
Context Pack 组明显低于基线组
```

### 5.3 Token 成本

```text
输入 token + 输出 token
```

目标：

```text
Context Pack 组降低 >= 50%
```

### 5.4 完成耗时

```text
从开始任务到可用答案的分钟数
```

目标：

```text
Context Pack 组降低 >= 30%
```

### 5.5 证据正确率

```text
正确引用文档/页码/章节/span 的数量 / 总引用数量
```

目标：

```text
>= 90%
```

### 5.6 人工修正次数

```text
人工指出并要求修正的问题数量
```

目标：

```text
Context Pack 组低于基线组
```

## 6. 决策规则

进入阶段 2 的条件：

```text
准确率、遗漏率、token、耗时中至少 2 项明显优于基线；
且证据正确率 >= 90%。
```

如果只在 token 或耗时上变好，但准确率和遗漏率没有改善，不进入知识图谱阶段。

如果证据正确率低于 90%，先修解析和证据链，不进入知识图谱阶段。

如果出现大量跨文档多跳问题无法靠检索解决，再考虑引入 Domain Graph。

## 7. 自动判定脚本

真实对照实验完成后，用脚本读取结果表并输出阶段 2 建议：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-results.ps1"
```

脚本判定规则见：

- [15-实验结果判定说明.md](15-实验结果判定说明.md)

注意：脚本只处理已经完整填写的 baseline/context_pack 任务对。模板里的 `待填写`、`待评分` 不会被当成有效实验结果。

解析器对比完成后，用脚本读取解析器评分表并输出第一阶段默认解析器建议：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

严格模式：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\evaluate-parser-results.ps1" -Strict -ParserSheetPath ".\experiments\runs\run-001\parser-evaluation-sheet.csv"
```

脚本要求至少 3 个解析器各覆盖 10 份文档，并按页码、span、表格、阅读顺序、OCR 和 critical failures 判断是否可作为第一阶段默认解析器。
