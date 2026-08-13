# Phase 66：17同游品牌统一验收用例

## 自动化用例

1. HTML title 为 `17同游 · 一起规划，一起出发`。
2. favicon 使用带版本号的 `/favicon.svg?v=2`。
3. HTML 包含 `application-name`、Apple Web App title 和 Open Graph 品牌信息。
4. favicon SVG 包含蓝紫品牌渐变、白色路线和方向箭头。
5. `BrandWordmark` 固定输出“17同游”。
6. 登录页显示 `17tongyou · 一起规划，一起出发`。
7. 侧栏、移动顶部栏和路线图页脚显示新品牌。
8. 用户界面的 HTML、Home 和 Auth 源文件不再包含 `travelX`。

## 手工验收

1. 微信中关闭旧页面后重新进入，顶部标题应显示“17同游”。
2. 浏览器标签页图标应为蓝紫圆角路线箭头，不再是紫色闪电。
3. 退出登录后检查登录页主标题和登机牌票根均为“17同游”。
4. 登录后检查桌面侧栏与移动顶部栏品牌一致。
5. 生成路线手账，底部显示“17同游 · 为你手绘”。
6. 在 16px、28px、48px 三种尺寸检查图标，路线起点和方向箭头仍可辨认。

## 本地执行结果

- 前端 Node 测试：21 passed。
- 前端 lint：通过。
- TypeScript + production build：通过。
- 后端全量测试：461 passed（1 条 TestClient 弃用告警）。
- macOS Quick Look 已将 favicon 渲染为 512px PNG，圆角、渐变、路线和箭头显示正常。
- 已部署；线上 HTML title、application-name、Apple Web App title 与 Open Graph 均为“17同游”。
- 线上 favicon SHA-256 为
  `e715e459ccd5435ead68d3a2856e5e8717e8cd0e52d5b10ff5568375a47e70fc`，与本地一致；
  服务状态 active，`/api/health` 返回 `{"status":"ok"}`。
