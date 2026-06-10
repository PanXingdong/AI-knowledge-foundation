# Scoring Rubric

本 rubric 用于把 Agent 原始输出转成 `baseline-vs-contextpack-results.csv` 中的评分字段。评分时必须同时查看：

- `agent-task-cases.csv` 中的 `gold_answer_points`、`required_constraints`、`expected_evidence`。
- `agent-run-log.csv` 中对应任务、组别和 attempt 的执行记录。
- `raw_output_path` 指向的 Agent 原始回答。

## 1. 评分原则

- baseline 和 context_pack 使用同一个任务意图、同一个评分人、尽量同一个 Agent/model。
- 唯一应变化的是上下文来源：baseline 使用原始文件，context_pack 使用 Context Pack。
- 不从记忆或印象评分，只根据原始回答和任务标准答案评分。
- 如果 Agent 回答缺少证据，但任务要求证据，`citation_correct` 必须记为 `no`。
- 如果答案看似合理但无法由允许文档支持，计入 `wrong_claims`。

## 2. 字段口径

| 字段 | 评分口径 |
|---|---|
| `answer_correct` | 回答覆盖主要 `gold_answer_points`，且没有会误导执行的关键错误，填 `yes`；否则填 `no`。 |
| `missed_constraints` | `required_constraints` 中被遗漏的关键约束数量。只数会影响工程判断的遗漏。 |
| `wrong_claims` | 与文档冲突、无证据支撑或把版本/平台说错的结论数量。 |
| `citation_correct` | 引用的文档、版本、章节、页码或 span 能回到原文并支持结论，填 `yes`；否则填 `no`。 |
| `token_cost` | 本次任务输入 token + 输出 token。没有自动统计时记录人工估算方法。 |
| `elapsed_minutes` | 从开始执行任务到得到可评分答案的分钟数。 |
| `human_fix_count` | 评分人为了得到可用答案所需指出的问题或补问次数。 |

## 3. 证据正确率

`citation_correct = yes` 的最低要求：

1. 文档名称正确。
2. 文档版本或适用范围没有明显错误。
3. 页码、章节或 span 能定位到原文。
4. 引用内容确实支持对应结论。

只给出“来自供应商文档”“见内部 SPEC”这类泛引用，不算正确证据。

## 4. 复核要求

- 每个任务至少保留 baseline 和 context_pack 两条 `agent-run-log.csv` 记录。
- 每条结果表评分都应能追溯到一条原始输出。
- 评分争议写入 `notes`，不要改动原始输出。
- 若某任务标准答案本身不清楚，先退回任务定义，不应硬评分。
