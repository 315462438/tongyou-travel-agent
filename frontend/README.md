# 17同游 Web 与 Android 共享界面

React + TypeScript + Vite，部署基路径 `/travel/`，后端 API 为 `/travel/api`。截至 2026-10-20：旅行 / 记账 / 我的三入口、独立问 AI；协同行程地图与行程同屏、景点图文详情、紧凑卡片；修复我的页面工具弹层遮挡。Android 0.8.2 (13) 打包此界面快照，iOS 为独立 SwiftUI 实现。

## 本地开发

以下命令在 `frontend/` 执行；Node 23，依赖版本以 package-lock.json 为准。

```bash
npm ci
cp .env.example .env.local
npm run dev
```

默认 http://localhost:5173/travel/。开发服务器将 `/travel/api` 转发到本地后端 8000；后端启动见[根 README](../README.md)。
高德 JS key 与安全密钥读取 `.env.local`，勿提交。JS key 会发送到浏览器，靠域名白名单限制使用；生产安全密钥由 `/_AMapService` 服务端代理注入。localhost 被白名单拒绝时不能仅根据 SDK 已加载判断底图可用。

## 主要模块

| 模块 | 文件 |
| --- | --- |
| 三入口导航、AI 与工具弹层 | src/pages/Home.tsx、JourneyShell.css |
| 旅行册首页 | src/pages/TravelHome.tsx |
| 地图与逐日行程 | src/pages/Trips.tsx、AndroidTripWorkspace.tsx、TripRouteLayout.css |
| 地点图片与详情 | src/pages/TripStopThumbnail.tsx、PlaceDetails.tsx |
| 高德地图、编号与定位 | src/components/TripMap.tsx |
| 独立记账与协作 | src/pages/Ledger.tsx |
| Android 桥接与返回 | src/nativeAndroid.ts |

## 验证

```bash
npm test
npm run build
npm run lint
```

浏览器专项使用 Playwright，需要 Chrome 和 Playwright 模块。可设置 `PLAYWRIGHT_MODULE` 为已有模块的绝对路径。另开终端启动 `npm run dev -- --host 127.0.0.1 --port 4185`，再运行：

```bash
npm run test:journey
npm run test:trip-route
npm run test:account
```

以上测试拦截业务 API 使用 fixture，不修改生产数据。`REAL_MAP=1 QA_CASE=web-mobile` 可验证真实高德 SDK；正式域名测试见[地图验收](../docs/test_cases/行程卡片密度与安卓地图比例-2026-10-20.md)。本轮 99 单测、主流程 6 组、地图 7 组、账户工具 6 组通过，结果见 `../docs/test_cases/`；lint 为额外检查入口，不等于本轮所有规则均无历史告警。

## 构建与发布边界

`npm run build` 生成 dist。Web 将 dist 内容部署到后端静态目录；先发布资源，再切换入口，保留旧哈希资源供已打开页面使用。部署后校验线上资源与健康状态。
Android 由 `../android/scripts/bundle-web.py` 生成独立固定快照，不覆盖 dist/backend/static；修改共享 UI 后需要另发 APK。iOS 构建不使用这份 UI。签名、APK、环境文件与构建输出均不提交 Git。
