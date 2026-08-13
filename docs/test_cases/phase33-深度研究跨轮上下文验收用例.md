# Phase 33 验收用例 — 深度研究跨轮上下文（全量历史 + 分层压缩 + 记忆/轮末钩子）

对应自动化测试：`backend/tests/test_deep_research_context.py`（6 例，全离线）。
设计见 `docs/task_plans/task_plan-phase33-深度研究跨轮上下文.md`。

## A. 消息装配（自动化）

| # | 用例 | 预期 |
| --- | --- | --- |
| A1 | 全量历史 | 历史轮逐字注入（长报告不截断）、progress 排除、与本轮重复的落库用户消息去重；末条 user = <background_memory> + 本轮问题 |
| A2 | 超限回退 | 历史超 `deep_research_history_max_chars` → 回退窄窗：<conversation_summary> + 近 5 轮（每条 ≤500 字） |
| A3 | 开关关 | `deep_research_carry_history=false` → 只带本轮问题 |
| A4 | 装配失败兜底 | 记忆/历史查询异常 → 退化为裸问题，不影响整轮研究 |

## B. 轮末钩子（自动化）

| # | 用例 | 预期 |
| --- | --- | --- |
| B1 | 成功路径 | extract_and_save 与 update_history_summary 各调一次；meta 带 memories_used / memories_saved；turn_messages 透传到 ainvoke |
| B2 | 失败/超时路径 | （由 run_deep_research 既有异常分支保证）不写记忆、不折叠摘要 |

## C. 分层压缩装配（自动化）

| # | 用例 | 预期 |
| --- | --- | --- |
| C1 | 中间件顺序 | 主 agent middleware：ContextEditingMiddleware 在 SummarizationMiddleware 之前（先便宜清理后全量摘要） |

## D. 线上手工回归（部署后）

1. **追问接住**：先深度研究「哈尔滨 vs 长春」，出报告后保持深度推理开关，追问
   「按预算 3000 只对比住宿和交通」——新报告应体现上一轮结论与本轮约束（此前接不住）；
2. **记忆生效**：记忆里有「爱吃辣」时，研究报告的美食部分应有所体现；研究轮里新透露
   的偏好出现在记忆面板（轮末提炼生效）；
3. **缓存观察**（Langfuse）：连续两轮研究，第二轮首次 LLM 调用的 input 前缀应包含第一
   轮的完整问答（append-only）；
4. **压缩兜底**：极长会话（多份长报告）里再发起研究，若触发 Summarization，轨迹中
   应出现结构化摘要消息且轮次正常完成。

## 运行

```bash
cd backend && .venv/bin/python -m pytest tests/test_deep_research_context.py -q
```
