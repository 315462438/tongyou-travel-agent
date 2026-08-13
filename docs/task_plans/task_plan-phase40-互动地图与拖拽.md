# Task Plan — Phase 40：高德 JS 互动地图 + 拖拽排序

## 前置

用户已申请「Web 端(JS API)」key（js_map）：key 可进前端（域名白名单保护），
**securityJsCode 不进前端**——用高德官方「代理服务器」模式：nginx 起 `_AMapService`
反代、服务端追加 jscode（与 staticmap 后端签名同一原则）。

## 方案

1. **nginx**（服务器 /etc/nginx/sites-enabled/default 增三段 location）：
   `/_AMapService/v4/map/styles` → webapi.amap.com；`/_AMapService/v3/vectormap` →
   fmap01.amap.com；`/_AMapService/` → restapi.amap.com 并在 args 追加 jscode。
2. **前端**：`@amap/amap-jsapi-loader` 加载 SDK（key 常量进前端）；
   `window._AMapSecurityConfig = { serviceHost: origin + '/_AMapService' }`；
   本地 dev（vite）例外：DEV 模式直接内联 jscode（只在 localhost 生效，可接受）。
   新组件 `TripMap.tsx`：编号 marker（天色一致）+ 路线 polyline + fitView；
   点 marker → 左栏卡片定位闪烁；点卡片 → 地图平滑移过去；顺序变化重绘路线。
   **降级保底**：SDK 加载失败自动回退静态图（弱网/白名单未生效时不至于没地图）。
3. **拖拽排序**：原生 HTML5 DnD（零依赖，不引 dnd-kit）——卡片 draggable，
   拖到同天/跨天的目标卡片上插入；落点后调新端点
   `POST /{id}/stops/reorder {day, ordered_ids}`（服务端按序重赋 order_no，单请求
   替代 N 次 PATCH），修改记录留痕。

## 验收

- reorder 端点：重排/跨天移入顺序正确、非法 id 忽略（自动化）；
- 线上：中栏为可拖动缩放的互动地图，marker 编号/颜色与卡片一致；点卡片地图平滑
  定位、点 marker 卡片闪烁；拖拽卡片换序/跨天后地图与段间时间自动刷新；
- 无白名单/断网时回退静态图。
