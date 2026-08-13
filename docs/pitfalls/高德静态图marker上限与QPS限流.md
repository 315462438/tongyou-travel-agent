# 踩坑：高德静态地图 marker 上限 + POI 搜索 QPS 限流

Phase 18 手账路线图海报踩到高德两个限制。

## 1. 静态地图 marker 数量上限 ≈ 10

`/v3/staticmap` 一次请求 marker/点位太多会直接 502（上游返回非图片）。实测：
- ≤10 个点位 → 200
- ≥11 个点位 → 502（与 size 无关，750*450 / 560*620 都一样）

**现象**：全程图把整趟 14 个点位塞一张图 → 502，前端地图裂图。旧版「全程图」其实一直
在多点位时静默失败，只是以前海报以逐天卡片为主没暴露。

**解决**：改为**逐天出小图**（每天 ≤7 个点位，天然在上限内），中栏纵向堆叠；
「全程图」仅在总点位 ≤10 时才出，否则留空由逐天图兜底。见
`poster._build_poster_payload`（每天 `map`）+ `staticmap_api` 尺寸白名单加 `500*400`。

## 2. POI 搜索 QPS 限流：CUQPS_HAS_EXCEEDED_THE_LIMIT

海报要给景点/餐馆/酒店并发补坐标+实景图。一次并发 20+ 个 `/v3/place/text`，key
（与铺探项目共用配额）立刻 `CUQPS_HAS_EXCEEDED_THE_LIMIT`，大量请求失败 →
**点位查不到坐标被丢弃**（14 个点位只剩 1 个），海报几乎空。

**解决**（两层）：
- `amap._call` 命中 `CUQPS` 时**退避重试**（0.4s×(n+1)，最多 4 次）。
- `poster._enrich` / `_enrich_photos` 用 `asyncio.Semaphore(4)` **限制并发**。
  注意：Semaphore 必须在 async 函数内创建（绑定当前事件循环）——海报走
  `asyncio.run` 每次新循环，模块级全局 Semaphore 会在第二次调用时报
  "bound to a different event loop"。

修复后 14/14 点位定位成功，酒店/美食实景图 4/4、6/6。
