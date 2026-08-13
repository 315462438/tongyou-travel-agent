# Task Plan — Phase 46：协同板酒店推荐（高德为主 + 携程实价按需）

## 目标（用户选定方案）

协同行程板上加目的地酒店推荐。**高德 POI 为主**（秒级、无登录墙、有评分/地址/坐标、
可上地图、可一键加进行程）；**携程实价按需**（不把慢的浏览器抓取塞进 2.5s 轮询的实时板，
改为「跳转到对话」触发现成的携程流水线，慢工作回归它该在的地方）。

## 方案

### 后端

- `amap.search_hotels(city, limit)`：`/v3/place/text keywords=酒店 city=X` →
  `[{name, rating, address, location}]`（复用现成签名/限流，无浏览器）；
- `GET /api/trips/{id}/hotels?city=X`（成员校验）：默认 city=trip.destination，
  返回高德酒店列表。

### 前端（TripBoard 右栏新增「🏨 酒店」面板）

- 城市输入框（默认 trip.destination，可改成 成都/康定 等任意城市）→ 拉高德酒店；
- 每条：名称 + ⭐评分 + 地址 + 「加入行程」（作为带「住宿」标签的 stop 落到选中天，
  有坐标 → 自动上地图 marker）；
- 「💰 查携程实价」：调 `onAskInChat("查一下{city}的酒店，要携程实时价格和房态")`
  **强制 deep_reasoning=true**（Phase 44 后 guide/携程只在慢思考开启时跑）→ 新建对话、
  发消息、关板打开对话视图。复用全部携程机器，零新增抓取代码。

### 联动管线

Home 加 `onAskInChat(text)`：建会话 → 发消息（deep_reasoning=true）→ 打开对话；
经 TripsOverlay → TripBoard → 酒店面板透传。

## 验收

- `search_hotels` 解析高德 place/text 返回名称/评分/地址/坐标（fake httpx 自动化）；
- `GET /hotels` 成员校验 + 默认目的地 + city 覆盖（自动化）；
- 线上：板上出目的地酒店、可加进行程上地图；「查携程实价」跳到对话跑出携程卡片。

## 明确取舍

- 携程实价**不在板内内联**——多人实时板 + 30-60s 浏览器抓取 + 登录墙 = 卡顿源，
  跳转对话是架构上正确的「按需」；
- 高德酒店无实时价格，面板注明「价格/房态请点携程实价」。
