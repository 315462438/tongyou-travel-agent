# Phase 67 — 预算明细面板 + 预约提醒

> 灵感来源：调研 TripStar（github.com/1sdv/TripStar）后确认的两个可移植亮点。
> 其小红书签名方案已评估并**明确弃用**（只解决鉴权不解决 IP 信誉，静态设备指纹全球同质，
> 搬到云服务器比现有真 Chrome MCP 更易被封；我们的 xhs_mcp 已可连通）。

## 目标

攻略正文里的预算和「需提前预约」信息现在是**散文**，用户没法一眼看清钱花在哪、
哪些票要提前抢。本期把它们抽成结构化数据并给出面板：

1. **预算明细面板**：分类汇总（住宿/交通/餐饮/门票/大交通/其他）+ 逐项明细 + 总计/人均。
2. **预约提醒**：识别攻略里需提前预约的景点（渠道、提前天数），在同一面板顶部醒目展示，
   避免白跑一趟（故宫、陕历博这类）。

## 方案

沿用 **Phase 13 手账海报的成熟模式**（按钮触发 → 后台 LLM 抽取 → 写 meta 消息 → 前端渲染），
不改主攻略链路、不给每轮生成增加延迟（Phase 11 提速成果不能回退）。

链路：

```
攻略消息「💰 预算明细」按钮
  → POST /api/chat/{cid}/budget {message_id}
  → BackgroundTasks → app/agent/budget.py generate_budget()
  → _add_streaming 占位（前端保持轮询）
  → llm.parse(攻略正文[:6000], BudgetData, model=v4-flash)
  → 服务端归一分类 + 重算汇总
  → _finalize 写 meta.budget → 前端 BudgetView 渲染
```

### 关键设计决策

| 决策 | 理由 |
| --- | --- |
| **按钮触发，不自动生成** | 每轮攻略多一次 LLM 调用会拖慢首屏（Phase 11 把总时长压到 ~130s，不能回退） |
| **服务端重算汇总，不信任 LLM 的 total** | TripStar 让 LLM 自己算总额，导致输出 `"total": 30+54+120=324` 这种非法 JSON，被迫写正则去 eval 修复。我们只让模型给**单项金额**，分类汇总/总计/人均全部服务端算 |
| **复用 `trip_planner.BUDGET_CATEGORIES`** | 协同行程导入已有同一套分类和 `normalize_budget_category()` 同义词归并，不重造第二套口径 |
| **预约提醒并入同一面板** | 一次 LLM 调用出两份产物；且「钱」和「要抢的票」同属行前准备，用户心智一致 |
| **金额一律按「人均」口径** | 攻略正文多数按人均写；混用会导致汇总失真。schema 里显式说明，`headcount` 仅用于展示总价换算 |
| **抽不到就留空，不估算** | 沿用 `IMPORT_SUMMARY_SYSTEM` 里「攻略没写预算就留空数组，不要估算编造」的既有约束 |

### 涉及模块

**新增**
- `backend/app/schemas/budget_schema.py` — `BudgetLine` / `ReservationItem` / `BudgetData`
- `backend/app/agent/budget.py` — 抽取、归一、汇总、写回
- `backend/tests/test_budget.py` — 纯离线单测（不打 LLM/网络）

**修改**
- `backend/app/api/chat_api.py` — 新增 `POST /{cid}/budget`（照 poster 路由）
- `backend/app/agent/memory.py` — 记忆判定排除 `meta.budget`（同 poster，避免被当成攻略）
- `frontend/src/pages/Home.tsx` — `Msg.meta.budget` 类型、`BudgetButton`、`BudgetView`
- `frontend/src/App.css` — `.budget-*` 样式

### 数据结构

```python
BudgetLine   { category, name, day, amount, note }   # amount = 人均金额(元)
ReservationItem { name, channel, advance, note }
BudgetData   { currency, headcount, items[], reservations[], notes[] }
```

服务端组装出的 `meta.budget` payload（前端直接消费）：

```json
{
  "currency": "CNY", "headcount": 1, "total": 1234.0,
  "by_category": [{"category":"住宿","amount":800.0,"pct":64.8}],
  "by_day":      [{"day":1,"amount":500.0}],
  "items":       [...], "reservations": [...], "notes": [...]
}
```

## 验收标准

1. 攻略消息上出现「💰 预算明细」按钮，点击后面板在同一会话内生成。
2. 面板含：分类汇总（带占比条）、逐项明细（可按分类筛选）、总计与人均。
3. 攻略里提到需预约的景点，面板顶部出现「📋 需提前预约」区块（含渠道/提前天数）；
   没有则该区块整体隐藏。
4. **汇总数字由服务端算出，与逐项明细自洽**（不采信模型给的总额）。
5. 分类归一正确：机票/高铁→大交通，地铁/打车→交通，未知→其他。
6. 攻略没写预算时，面板给出友好提示而非空白或编造数字。
7. 失败路径都会终稿占位消息（不留 streaming，前端不会无限等待）。
8. `backend/tests/test_budget.py` 全部通过。

## 不做（本期范围外）

- 知识图谱可视化（ECharts force graph）——已有手账海报承担视觉招牌，另行评估。
- i18n 多语言。
- 预算的多币种换算（仅保留 currency 字段占位）。
