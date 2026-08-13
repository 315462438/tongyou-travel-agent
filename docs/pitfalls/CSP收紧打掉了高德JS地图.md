# CSP 收紧打掉了高德 JS 互动地图（2026-08-01）

## 现象

协同行程板的地图上「只有编号点位、没有路线连线」，用户明确指出「以前是动态地图」。
排查一圈：坐标是对的、`TripMap` 的 polyline 逻辑是对的（`path.length >= 2` 就画）、
静态图接口也确实构造了 `path` 参数——**每一处看起来都没问题**。

## 根因

那张图根本不是互动地图，是**静态图兜底**。

`TripMap` 初始化时 `AMapLoader.load()` 失败 → `.catch(() => onFail())` → 父组件
`mapFailed=true` → 渲染 `/api/staticmap` 的图片。而静态图的 `path` 参数在高德侧
表现与互动地图不同，观感上就是「一堆点没有线」。

`AMapLoader` 失败的原因是 **Phase 69 安全加固时收紧的 CSP**：

```
script-src 'self' 'unsafe-inline' 'unsafe-eval'
```

SDK 是通过注入 `<script src="https://webapi.amap.com/maps?...">` 加载的，
`'self'` 直接把它拦死。浏览器控制台里有明确证据：

```
Loading the script 'https://webapi.amap.com/maps?v=2.0&key=...' violates the following
Content Security Policy directive: "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
```

## 解决

只对高德自己的域名开口子，其余保持收紧：

```
script-src ... https://webapi.amap.com https://vdata.amap.com
img-src    ... https://*.amap.com https://*.autonavi.com https://*.is.autonavi.com
connect-src 'self'        ← 不放宽
```

`connect-src` 之所以不用动：JS SDK 的服务型接口（样式、矢量瓦片）已经通过
`_AMapSecurityConfig.serviceHost = origin + '/_AMapService'` 走 nginx 同源反代
（官方推荐模式，密钥不进前端）。这部分设计本来就是对的，只是被 script-src 卡在了前一步。

回归测试 `test_csp_allows_amap_js_map_but_keeps_connect_locked` 锁住：
白名单域名必须在、`connect-src` 必须仍是 `'self'`、不许用裸通配。

## 教训

**静默降级会把根因藏起来。** `catch(() => onFail())` 让一个「外部资源被策略拦截」的
硬错误，表现成了「地图样式不太一样」。排查时我沿着"线为什么不画"查了坐标、查了
polyline 条件、查了静态图 path 构造，全都是对的——因为问的问题本身就错了。

两条改进方向（本次未做，记下来）：
1. 降级必须**可见**：回退静态图时在图上标明「互动地图加载失败，已降级」，
   而不是无声无息换一张图；
2. 收紧 CSP 这类**全局策略**变更，必须把「依赖外部资源的功能」列一遍逐个验证
   （本项目就是高德 JS 地图这一个），否则会在几周后以完全不相干的现象暴露出来。
