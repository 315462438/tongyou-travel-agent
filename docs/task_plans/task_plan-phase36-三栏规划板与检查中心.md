# Task Plan — Phase 36：三栏规划板 + 地图 + 检查中心 + 对话联动

## 目标（路线图 Phase 36 + 用户补充）

1. 规划板三栏化：左 Timeline ｜ 中 每日路线地图 ｜ 右 AI 面板（预算/检查/点评）——
   消灭「右侧空白」的 Demo 感；
2. 条目字段扩展：时间/停留/交通/门票/标签（PRD 卡片样式）；
3. **AI 检查中心**：结构化 issues（可点击定位），算法即时计算不花 LLM；
4. **对话联动（用户特别要求）**：从对话导入的行程双向打通——板上可跳回来源攻略对话；
   原攻略消息标记「已导入」，按钮变为直接打开对应规划板。

## 方案

### A. 数据模型（迁移加列）

- `travel_trip` + `budget FLOAT` / `start_date VARCHAR(10)` /
  `source_conversation_id VARCHAR(32)` / `source_message_id VARCHAR(32)`
- `travel_trip_stop` + `start_time VARCHAR(5)`（HH:MM）/ `stay_min INTEGER` /
  `transport VARCHAR(16)` / `ticket_price FLOAT` / `tags VARCHAR(128)`（逗号分隔）

### B. 后端

1. `PATCH /api/trips/{id}`：title/destination/days/budget/start_date（成员可改）；
2. Stop 创建/PATCH/详情支持新字段；
3. **`GET /api/trips/{id}/issues`**（同步，纯算法+一次高德天气）：
   - 步行过长：某天 route_km > 8（且交通方式多为步行/空）→ warn；
   - 可优化：`order_stops` 后节省 > max(2km, 20%) → info「点一键串路线」；
   - 时间冲突：同天相邻条目 start_time + stay_min 与下一条 start_time 重叠 → warn；
   - 无坐标条目 → info（点名）；
   - 预算超标：Σticket_price > trip.budget → warn（设了预算才查）；
   - 天气：设了 start_date → 高德 4 日预报映射到 Day，雨/雪 → warn（新增
     `amap.weather_forecast()` 结构化helper；拿不到静默跳过）。
   返回 `[{level: warn|info, kind, day?, stop_id?, text}]`；
4. **联动**：import 时写 `source_conversation_id/message_id` 进 trip，并把来源消息的
   meta_json 合并 `imported_trip_id`（对话侧据此换按钮）；trip 详情返回 source 信息。

### C. 前端（TripBoard 重构为三栏）

- **左栏 Timeline**：按天分节的纵向卡片流（时间 → 地点 → 停留/交通/门票/标签徽章 →
  备注），保留 ↑↓/换天/删除；✎ 打开**编辑弹窗**（时间 time input、停留 number、
  交通 select、门票 number、标签、备注）；每天尾部快速加点；
- **中栏地图**：Day 标签页 + 该天静态路线图（复用 `/api/staticmap`，pts=该天有坐标
  条目、labels=天内序号、days=d 统一色）；点左栏卡片切到对应天并高亮；无坐标天显示
  占位提示；
- **右栏 AI 面板**：预算统计（Σ门票，可编辑 trip.budget/start_date，超标红）+
  检查中心（issues 列表，点击 → 左栏对应卡片滚动+闪烁）+ AI 按钮组（起草/串路线/检查）
  + AI 点评正文（原 ai_review）；
- **联动**：板头「📄 来源对话」按钮（有 source 时显示）→ 关闭板并打开该会话
  （Home 传 onOpenConversation）；对话里攻略消息若 meta.imported_trip_id 存在 →
  按钮变「🗺️ 打开协同行程」。

## 验收标准

- 新字段落库/展示/编辑全通；issues 六类规则单测覆盖（构造样例各触发一次）；
- 导入的行程：板头能跳回来源对话；来源消息刷新后按钮变「打开协同行程」（单测：
  import 后消息 meta 含 imported_trip_id）；
- 三栏布局桌面可用、窄屏纵向堆叠；地图按天出图、颜色与卡片序号一致；
- 全部单测通过；构建/部署成功；双账号手工回归。

## 风险

- 静态图 marker 上限 ≈10/天（Phase 13 已知），单天条目 >10 截断出图并提示；
- 时间字段全为选填，issues 的时间冲突检查只在双方都填了时间时生效。
