# Phase 30 验收用例 — 记忆升级 + 历史压缩 + 前端停滞提示

对应自动化测试：`backend/tests/test_memory_upgrade.py`（12 例，sqlite 内存库全离线）。
设计见 `docs/task_plans/task_plan-phase30-记忆升级与历史压缩.md`。

## A. 记忆选择器

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A1 | 挑子集 + 保底 | 5 条记忆（含 trip_state、explicit），fake llm 选 1 条 | 注入 = trip_state + explicit + 选中的（保底不过选择器） |
| A2 | 失败回退 | fake llm 抛异常 | 回退全量注入（选择器只能锦上添花） |
| A3 | 空选合法 | fake llm 返回空列表 | 注入空（宁缺毋滥） |
| A4 | 阈值门 | gather_context：记忆 ≤12 条 | 不调选择器，全量注入（现行为） |

## B. 新鲜度标注

| # | 用例 | 预期 |
| --- | --- | --- |
| B1 | 年龄标签 | 今天/昨天/「47 天前」；无 updated_at 不标 |
| B2 | 行程过期提醒 | trip_state 超 30 天：追加「⚠️ …先与用户确认」；新鲜的不加 |

## C. 提炼 prompt

| # | 用例 | 预期 |
| --- | --- | --- |
| C1 | 纪律齐全 | EXTRACT_SYSTEM 含「绝对日期」「正面确认」「原因」 |
| C2 | 注入今天日期 | plan_memory_ops 的 prompt 含「今天是 YYYY-MM-DD」 |

## D. 历史压缩

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| D1 | 折叠早期轮次 | 8 轮对话后跑 update_history_summary | 摘要只含前 3 轮内容（近 5 轮不进摘要）；history_summary_count=16 |
| D2 | 短会话跳过 | 3 轮对话 | 不调 LLM、不写摘要 |
| D3 | 注入顺序 | 会话带摘要时取 _history_text | 「【早前对话要点（已折叠）】」在前、近窗原文在后 |

## E. 前端停滞提示（手工验收，部署后）

1. 发起一轮深度研究，在模型长推理阶段（无新进度气泡）等 30 秒以上：
   消息流底部出现「已约 N 秒没有新进度——模型可能在长推理或写产物，仍在运行中…」，
   秒数随轮询递增；
2. 新的 progress/流式内容到达后提示立即消失；
3. 发送新消息时不会因上一轮的空闲立刻误报（计时已重置）。

## F. 线上手工回归

1. 老会话（>5 轮）发新消息：轮末 `travel_conversation.history_summary` 被写入/更新；
   下一轮 Langfuse trace 里 prompt 含「早前对话要点」；
2. 记忆面板攒到 >12 条后发消息：`memories_used` 只剩相关子集 + 行程/明确记忆；
3. 注入块每条带「（N 天前）」。

## 运行

```bash
cd backend && .venv/bin/python -m pytest tests/test_memory_upgrade.py -q
```
