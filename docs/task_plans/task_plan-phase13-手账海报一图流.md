# Task Plan — Phase 13：手账海报「一图流」

> 创建：2026-07-07　状态：已完成并上线（验收见 docs/test_cases/phase13-验收用例.md）

## 需求

把生成的攻略做成小红书手账风的「一图流」海报：整趟一张竖向长图，
顶部整体路线地图，下面按 Day 分区，每区含当天路线小图 + 景点/餐馆/打卡点
编号卡片（配实景图）。景点+餐馆+打卡都标到地图上。

## 技术验证（已通过）

- 高德静态地图 `v3/staticmap`（带签名）：真实地图 + 编号标记 + 路线连线，实测 200/PNG。
- 高德 POI 文本搜索：可按名称查餐馆/打卡点的坐标 + 实景图（Phase 10 已用）。

## 方案

### 触发（按需，非自动）

攻略消息下加「🎨 生成手账海报」按钮 → `POST /api/chat/{cid}/poster {message_id}`
→ 后台任务 → 写一条 `meta.poster` 的 assistant 消息 → 前端轮询渲染 PosterView。

### 后台流程（`app/agent/poster.py`）

1. **结构化抽取**（LLM `parse()`）：从攻略正文抽 `PosterData`：
   title/subtitle + stops[]（每个 {day, order, name, type: spot|food|checkin, note}）。
2. **坐标+实景图补全**：先匹配该会话 amap 来源已有景点；其余 stop 名称并发跑
   高德 POI 搜索（keyword=name, city=目的地）取 location + 首图。按名去重、限并发。
3. **地图 URL**：整体图（全部点，按天着色 + 连线）+ 每天小图（当天编号点 + 连线），
   走新端点 `/api/staticmap`（后台签名+代拉，key/sig 不进前端）。
4. 写 `meta.poster = {title, subtitle, destination, overall_map, days:[{day, map,
   stops:[{name,type,note,photo}]}]}`。

### 端点

- `GET /api/staticmap?pts=lng,lat;...&labels=1,2..&colors=..&size=..`：后台构造
  markers+path、签名、拉图返回 PNG（缓存 1 天）。避免高德 key 泄露到前端。
- 实景图复用 `/api/img`（高德域名已在白名单）。

### 前端 PosterView（`components/Poster`）

手账风布局：暖色纸背景、楷体手写感（系统字体 'STKaiti'/'KaiTi'/'楷体'）、
胶带/贴纸 CSS 装饰、轻微旋转的照片卡、Day 徽章、虚线路线连卡片。
顶部整体地图 → 逐 Day（当天小地图 + 编号卡片：实景图/图标/名称/note）。
「保存图片」按钮 html2canvas（同源图片，useCORS）导出单张长 PNG。

## 涉及模块

后端：`app/schemas/poster_schema.py`（新）、`app/agent/poster.py`（新）、
`app/api/chat_api.py`（+poster 触发路由、running/修复兼容）、
`app/api/staticmap_api.py`（新）+ main 注册、`app/tools/amap.py`（+poi 搜索复用）。
前端：`Home.tsx`（按钮 + poster 消息渲染）、`PosterView` 组件、`index.css`（手账样式）。

## 验收标准

1. 攻略消息点「生成手账海报」→ 出现手账海报：顶部整体路线地图，逐 Day 小地图 +
   景点/餐馆/打卡编号卡（带实景图）；「保存图片」导出单张长图。
2. 地图上景点/餐馆/打卡都有编号标记且连线。
3. 高德 key/sig 不出现在前端返回里。
4. 单测：PosterData 抽取契约、坐标补全匹配/并发、staticmap 参数与签名、
   URL 构造；存量不回归。
