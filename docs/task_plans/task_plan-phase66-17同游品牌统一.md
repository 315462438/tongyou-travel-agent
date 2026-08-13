# Phase 66：17同游品牌统一

## 目标

1. 将面向用户的 `travelX / 旅行智能体` 品牌统一为与未来域名 `17tongyou` 对应的“17同游”。
2. 替换当前紫色闪电 favicon，使用更符合“结伴旅行、共同规划”的路线图标。
3. 浏览器/微信标题、登录页、侧栏、移动顶部栏和路线海报不再出现旧品牌。
4. 不修改 API 路径、数据库字段或历史业务数据，避免品牌更新影响功能。

## 设计方案

- 中文主品牌：`17同游`
- 英文/域名标识：`17tongyou`
- 品牌短句：`一起规划，一起出发`
- 图标：蓝紫渐变圆角底 + 两个旅伴节点 + 弧形路线与方向箭头。
- favicon 使用独立 SVG；站内图标封装成可复用 React 组件，避免多个页面继续复制旧纸飞机。

## 涉及模块

- `frontend/public/favicon.svg`
- `frontend/index.html`
- `frontend/src/components/Brand.tsx`
- `frontend/src/Auth.tsx`
- `frontend/src/pages/Home.tsx`
- `frontend/src/index.css`
- `frontend/tests/visual-regressions.test.mjs`
- 当前架构文档与 Agent 项目说明

## 验收标准

1. 微信/浏览器标题显示“17同游”，favicon 不再是紫色闪电。
2. 登录页、登录票根、侧栏、移动顶部栏与路线图页脚均显示新品牌。
3. 用户界面源文件不再残留 `travelX`。
4. 新图标在 16px、28px、48px 下仍可辨认。
5. 前端 Node 测试、lint、TypeScript 与 production build 全部通过。

## 实施结果

- 已完成新 favicon 和共用 `BrandIcon / BrandWordmark` 组件。
- 已同步 HTML/微信元信息、登录页、侧栏、移动顶部栏、路线图页脚和助手系统身份。
- 用户界面活动代码已无 `travelX` 残留。
- 前端 21 项测试、lint、TypeScript 与 production build 全部通过。
- 后端 461 项测试通过；已部署至线上，服务健康检查正常。
