# Phase 22 — 轻量直答通道（direct，简单问题秒回）

## 背景 / 问题

普通轮次统一走全量攻略流水线，新目的地一轮 2-4 分钟，大头是浏览器采集
（搜索 ~25s + 抓 ≤8 页 50-120s）。但相当一部分用户消息**根本不需要实时网页数据**：
常识/建议/注意事项类问题（「鼓浪屿要提前订票吗」「带娃去三亚注意什么」）、
对上文的追问澄清、闲聊。这类问题被迫陪跑整条采集链，体感"问个小问题也要几分钟"。

## 方案：三路路由 + 直答通道

`run_conversation_turn` 入口改为统一 `decide_route`（v4-flash 一次分类，~1s）：

| 通道 | 判定 | 链路 | 目标时延 |
| --- | --- | --- | --- |
| direct | 无需实时数据：常识/建议/追问/闲聊 | 记忆+近5轮历史 → 单次流式生成（无浏览器无图） | 首字 ~3s，全程 20-40s |
| guide | 规划/修改行程、攻略、查酒店/价格 | 现有 LangGraph 流水线（不动） | 现状 |
| research | 多城对比/预算测算/签证/决策 | 现有 deepagents（不动） | 现状 |

原 `decide_research`（关键词门+确认）合并进 `decide_route` 单次分类；
`deep_research_enabled=false` 时 research 降级为 guide。

**保守原则**：分类拿不准/失败一律 guide（宁慢勿错）；修改行程类明确归 guide
（decide_revision 复用来源本来就快）。direct 的回答里若涉及时效信息（价格/房态），
prompt 要求注明是常识参考、可让我联网核实。

### 直答实现（`run_direct_answer`）
- 注入：三元组记忆 + 近 `history_rounds` 轮对话（不做目的地历史召回——无目的地）；
- 复用流式占位消息机制（streaming 占位 → ~1.2s 增量 → 终稿），支持停止（is_cancelled 打点）；
- 终稿 meta 带 memories_used；回复后照常旁路记忆提炼；
- 无 sources、无浏览器、无 checkpoint（单发生成，崩了重发成本低）。

### 配置
`direct_answer_enabled: bool = True`（可整体关闭退化为原两路）。

## 验收标准
1. 「鼓浪屿要提前订票吗」类问题走 direct：无浏览器进程活动，全程 <45s，首字 <8s。
2. 「帮我规划成都3天」仍走 guide；「成都 vs 西安哪个划算」仍走 research（回归）。
3. 分类失败/异常 → 回落 guide（离线单测）。
4. direct 流式可停止；记忆照常提炼与注入。
5. 全量单测通过；线上 E2E 计时对比。

## 风险
- 误判把该联网的问题直答 → 分类 prompt 保守 + 拿不准归 guide；direct 回答内注明时效局限。
- 每条消息 +1 次 flash 分类（~1s）→ 相对 guide 的分钟级可忽略，对 direct 是净赚。
