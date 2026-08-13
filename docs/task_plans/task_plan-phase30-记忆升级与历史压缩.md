# Task Plan — Phase 30：记忆升级 + 历史压缩 + 前端停滞提示（P1 批次）

## 背景

Phase 29 落完 P0 后，继续落 Claude Code 源码调研的 P1 批次（来源同
`task_plan-phase29-上下文与预算治理.md` 的调研）：

| 项 | 借鉴机制 | 来源 |
| --- | --- | --- |
| 记忆检索选择器 | 小模型按清单挑 ≤5 条、宁缺毋滥、空选合法 | `src/memdir/findRelevantMemories.ts` |
| 记忆新鲜度 | 「N 天前」人类可读年龄 +过期提醒（模型不擅长日期算术） | `src/memdir/memoryAge.ts` |
| 提炼 prompt 升级 | 相对日期转绝对；正面确认也要记；附原因 | `src/memdir/memoryTypes.ts` |
| 历史压缩 | 近 N 轮逐字保留 + 更早轮次结构化摘要（固定小节） | `src/services/compact/prompt.ts` 分段压缩 |
| 前端停滞提示 | 「X 秒无新 token」显式提示而非静默转圈 | `src/components/Spinner/useStalledAnimation.ts` |

## 方案

### A. 记忆检索选择器（`memory.py`）

- 现状：全量注入（`memory_max_inject` 截断）。个人量级可用，但条数多后稀释注意力。
- 改造：`gather_context` 增加 `user_text` 参数（各调用点透传本轮消息）。当记忆条数 >
  `memory_select_threshold`(12) 时，用 v4-flash 按「id+key+content」清单挑与本轮
  **明确相关**的 ≤`memory_select_top`(5) 条；prompt 强调宁缺毋滥、空选合法。
  少于阈值 / LLM 失败 → 回退全量注入（现行为），选择器只能锦上添花不能致损。
- `trip_state`（当前行程）与 explicit 记忆**始终注入**不过选择器（是用户明确说的/
  正在进行的，漏掉代价高）。

### B. 记忆新鲜度标注（`memory.py`）

- `format_memories_block` 每条后缀「（今天/昨天/N 天前）」——借鉴「模型不擅长日期
  算术，给人类可读年龄」。
- 「当前行程」槽超过 `memory_trip_stale_days`(30) 天：追加
  「⚠️ 这条行程记录已 N 天未更新，可能已结束，规划前先与用户确认」。

### C. 提炼 prompt 升级（`memory.py::EXTRACT_SYSTEM` / `plan_memory_ops`）

- prompt 注入「今天是 YYYY-MM-DD」，要求内容里的相对日期（下周五/五一）一律换算成
  绝对日期再存；
- 明确「正面确认也值得记」：用户对某方案表示满意/采纳（如「就按这个来」），提炼成
  可复用的偏好；只记纠正会让画像越来越保守；
- 偏好尽量附简短原因（「爱吃辣——川渝人」），便于后续判断边界情况。

### D. 历史压缩（`orchestrator.py` + `models.py` + `migrate.py`）

- 现状：`_history_text` 只取近 5 轮，更早的直接丢。
- 改造：`travel_conversation` 加列 `history_summary TEXT`、`history_summary_count INT`
  （幂等迁移）。**轮末旁路**（与记忆提炼同一后台时机，不加轮内延迟）调用
  `update_history_summary(db, cid, llm)`：当消息总数超过近窗（`history_rounds*2`）且
  比上次折叠时有新增，用 v4-flash 把**除最近 5 轮外**的全部对话重写成固定小节摘要
  （用户约束[预算/日期/人数/偏好] / 已确认的决定 / 已排除的选项 / 待跟进事项），整体覆盖。
- `_history_text` 若会话有摘要则前置注入「【早前对话要点】…」+ 近 5 轮原文。
- 失败只记日志（摘要是增强，不能影响主链路）。

### E. 前端停滞提示（`frontend/src/pages/Home.tsx`）

- 轮询里对消息列表做签名比对，记录「最后一次有变化」的时刻；
- `running` 且超过 30s 无变化 → 消息流末尾渲染提示行
  「⏳ 已约 N 秒没有新进度——模型可能在长推理或写产物，仍在运行中…」（复用
  `.progress-line` 样式，含 spinner）；有新消息即消失。
- 与后端 60s 心跳互补：心跳是服务端兜底，这个是纯前端即时反馈（15-60s 的空窗）。

## 配置新增（`config.py`）

```
memory_select_threshold: int = 12
memory_select_top: int = 5
memory_trip_stale_days: int = 30
```

## 涉及模块

- `backend/app/agent/memory.py` —— A/B/C
- `backend/app/agent/orchestrator.py` —— D + gather_context 调用点传 user_text
- `backend/app/db/models.py`、`backend/app/db/migrate.py` —— D 的两列
- `backend/app/config.py` —— 配置
- `frontend/src/pages/Home.tsx` —— E
- `backend/tests/test_memory_upgrade.py`（新增）

## 验收标准

- 记忆 >12 条时走选择器（fake llm 验证只注入选中的 + trip_state/explicit 保底）；
  ≤12 条或 LLM 失败回退全量；
- 注入块每条带年龄标注；30 天前的「当前行程」带过期提醒；
- EXTRACT_SYSTEM 含「今天是」「绝对日期」「正面确认」表述；
- 长会话轮末生成/更新 history_summary；`_history_text` 前置摘要块；短会话不生成；
- 前端 running 且 30s 无消息变化出现停滞提示（手工验收）；
- 全部单测通过；前端 build 成功并部署。

## 风险

- 选择器误漏关键记忆 → trip_state/explicit 保底注入 + 失败回退全量；
- 摘要覆盖策略每轮全量重写（长会话一次 flash 调用），成本可接受（旁路异步）；
  会话极长时输入截断到最早 60 条消息。
