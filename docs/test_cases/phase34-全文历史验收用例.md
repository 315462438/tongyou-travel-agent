# Phase 34 验收用例 — direct/guide 全文历史

对应自动化测试：`backend/tests/test_full_history.py`（4 例，全离线）。
设计与机制映射见 `docs/task_plans/task_plan-phase34-全链路全文历史.md`。

## A. 装配（自动化）

| # | 用例 | 预期 |
| --- | --- | --- |
| A1 | 全文逐字 | 未超 60k：长攻略全文进历史（无 500 字截断）、与本轮重复的用户消息去重、无摘要 |
| A2 | 超限回退 | 近 history_rounds 轮**仍逐字**保留 + conversation_summary（分段压缩形态） |
| A3 | guide 轨迹 | build_guide_messages 历史为全文；本轮问题只在末条 user 出现一次 |
| A4 | 阈值独立 | direct/guide 用 history_full_max_chars；研究链路上限独立可调 |

## B. 线上手工回归（部署后）

1. **核心场景**：先要一份哈尔滨长攻略，然后问「解释一下上一轮第三天的推荐」——
   回答应能引用攻略**后半段**的具体内容（此前只能看到开头 500 字，答不准）；
2. guide 多轮修改照常（来源复用不受影响）；
3. Langfuse 看 direct 轮的 input：历史部分为完整交替消息、长回复全文在内；
4. 首字延迟观察：direct 轮带全文历史后首字时间若明显恶化（未命中缓存的长 prefill），
   调小 `HISTORY_FULL_MAX_CHARS`。
