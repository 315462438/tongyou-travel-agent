# Task Plan — Phase 35：多人协同行程规划（AI 起草 / 串路线 / AI 检查）

## 目标（用户原话拆解）

1. 通过账号邀请进入**多人路线协同规划界面**（参考小红书行程计划板）；
2. **AI 推荐一条初始路线**，进去在此基础上编辑；
3. 多人编辑时有 **AI 提示/润色**；
4. 「我给他想去的地点，他给我串路线」——**地点串联优化：怎么走合适、不走回头路**。

## 关键取舍（本期拍板）

| 决策点 | 选择 | 理由 |
| --- | --- | --- |
| 实时协同方式 | **轮询**（板打开时 2.5s 拉全量，带 updated_at） | 与现有聊天轮询同款栈；个人/小团体规模无需 WebSocket/CRDT |
| 冲突策略 | 条目级 last-write-wins + 轮询快速收敛 | 行程条目粒度小、冲突罕见；不做锁 |
| 邀请方式 | **按用户名邀请**（已有账号体系） | 最简；邀请链接/注册引流后续再说 |
| 串路线算法 | **确定性算法**（高德坐标 + 最近邻贪心 + 按天切段），LLM 不参与排序 | 「不走回头路」是几何问题，算法比弱模型可靠且零成本；LLM 只负责起草和点评 |
| 交通假设 | 直线距离（haversine）近似 | 与海报 Phase 13/18 同口径；接高德路径规划 API 留作后续 |

## 数据模型（新表，`Base.metadata.create_all` 幂等建表）

```
travel_trip        id / owner_id / title / destination / days / updated_at
travel_trip_member trip_id / user_id / role(owner|editor)   —— 复合主键
travel_trip_stop   id / trip_id / day / order_no / name / note / location("lng,lat")
```

不建 activity/event 表（v1 不做操作流），编辑者信息靠成员列表 + 轮询收敛。

## API（`app/api/trip_api.py`，全部需登录 + 成员校验）

- `POST /api/trips` 建行程；`GET /api/trips` 我的（owner+member）；`GET /api/trips/{id}` 详情（stops 按 day+order 排、members、updated_at）
- `POST /api/trips/{id}/invite` {username} —— 仅 owner；`DELETE /api/trips/{id}` 仅 owner
- `POST /api/trips/{id}/stops` {day,name,note?} —— 建条目时异步高德补坐标
- `PATCH /api/trips/{id}/stops/{sid}` {name?/note?/day?/order_no?}；`DELETE` 同
- **AI 三件套**（BackgroundTasks，轮询看结果，复用 progress 思路→行程表 `ai_status` 字段）：
  - `POST /api/trips/{id}/ai/seed` {prompt}：LLM 结构化起草（天数+每天地点+备注）→
    高德补坐标 → 串路线 → 写入 stops（覆盖前端二次确认）
  - `POST /api/trips/{id}/ai/order` ：对现有 stops **串路线**——高德坐标 → 按天最近邻
    贪心排序（天内不走回头路），跨天用「首尾衔接」原则（次日从前一天终点附近开始）
  - `POST /api/trips/{id}/ai/review`：LLM 点评当前路线（回头路检测结果[算法算好喂给它]、
    节奏、吃住缺口、备注润色建议），写入 `travel_trip.ai_review` 展示面板
- 串路线核心为**纯函数** `order_stops(stops) -> stops`（可离线单测：优化后总里程 ≤ 原始）

## 前端（`frontend/src/pages/Home.tsx` 内新增视图 + 样式）

- 侧边栏新入口「🗺️ 协同行程」→ 行程列表（我的/被邀请的）+ 新建（可选「AI 起草」输入框）
- 行程板：按天分列的地点卡片（名称/备注/序号），上移/下移/换天/删除/新增；
  顶部：成员头像 + 邀请输入框 + 三个 AI 按钮（AI 起草 / 一键串路线 / AI 检查）；
  AI 检查结果为右侧建议面板。打开期间 2.5s 轮询详情（updated_at 变化即刷新）。
- 不做拖拽（v1 用按钮换序/换天，避免引第三方 DnD 库）；不做地图渲染（后续可复用
  海报的 staticmap）。

## 验收标准

- 双账号：A 建行程邀 B，B 列表可见并可编辑，A 侧 ≤3s 看到 B 的改动；非成员 404；
- `order_stops`：构造回头路样例，优化后总里程严格下降且不劣于原序（单测）；
- AI 起草：给「开封两日游」生成 ≥2 天、每天 ≥3 地点、含坐标的行程；
- AI 检查：面板给出含里程/节奏/缺口的建议文本；
- 全部单测通过；线上双账号手工回归。

## 风险

- 高德 POI 限流：复用 Phase 13 的退避 + Semaphore 限并发；
- 弱模型起草的地点名高德查不到：查不到的条目无坐标也保留（串路线时跳过、面板提示）；
- 轮询覆盖不了「同条目同时编辑」：last-write-wins，可接受（v1 明确不解决）。

## v2 追加（35b，用户细化需求）

1. **邀请确认流**：邀请不再直接入伙——`travel_trip_member.status`（pending/accepted）。
   被邀请者任意界面右上角弹邀请卡（全局 30s 轮询 `GET /api/trips/invites`），
   接受 → 进入同一规划板；拒绝 → 删除邀请（可再邀）。行程可见性/编辑权限均要求
   accepted。
2. **主对话一键导入**：攻略消息按钮区（导出长图/手账海报旁）新增「🗺️ 导入协同行程」：
   `POST /api/trips/import` {conversation_id, message_id} → 校验会话归属 → 建行程
   （ai_status=seeding）→ 后台 LLM 从攻略 Markdown 提取结构化行程（不虚构、只取
   文中真实地点）→ 高德补坐标 → 串路线 → 落条目；前端直接打开该规划板。
3. **React Bits 美化**：选 Iridescence（ogl 系，与既有 Aurora 同依赖、零新增包）作
   规划界面的柔和流光背景（低速低幅、淡彩），面板半透明浮于其上——「好看、放松」。
