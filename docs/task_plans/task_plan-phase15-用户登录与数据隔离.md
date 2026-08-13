# Task Plan — Phase 15：登录/注册 + 按用户隔离数据

> 创建：2026-07-07　状态：已完成并上线（验收见 docs/test_cases/phase15-验收用例.md）

## 需求

加登录/注册界面；用户的历史会话、记忆、扫码登录凭证都按 user_id 隔离。
登录界面设计参考 skills/frontend-design（做出旅行主题的独特感，不要模板化表单）。

## 鉴权方案（零重依赖，stdlib）

- `TravelUser`（id/username/password_hash/created_at）+ `TravelSession`（token→user_id）。
- 密码：`hashlib.pbkdf2_hmac`（stdlib，加盐，无需 bcrypt 依赖）。
- 令牌：注册/登录返回随机 token，存 travel_session；前端存 localStorage，
  请求带 `Authorization: Bearer <token>`。
- 依赖 `get_current_user`（FastAPI Depends）解析当前用户；所有业务路由改为需登录。
- 端点：`POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me`、
  `POST /api/auth/logout`。

## 数据隔离

- `TravelConversation` + `user_id`（列表/取消息/删除/发消息全部按当前用户过滤，
  并校验会话归属）。消息经会话归属间接隔离。
- `TravelMemory` + `user_id`（gather_context/extract_and_save/记忆 API 全部带 user_id）。
- `TravelSiteLogin` 改为 (user_id, site) 复合主键（登录记录、过期判定按用户）。
- `TravelCtripCity` 保持全局（城市 ID 是通用缓存，无隐私）。
- 后台任务（BackgroundTasks/agent）不再能用 Depends 拿 user，需把 user_id 显式
  透传进 `run_conversation_turn(cid, user_text, user_id)` 与 poster 流程。

## 登录界面设计（参考 frontend-design）

- 主题：把认证卡做成**登机牌 / 行李牌**造型，落在柔和的天空渐变背景上
  （呼应现有 sky→indigo 品牌渐变 logo），不是居中通用表单。
- 签名元素：一条从左到右的虚线航线 + 小飞机，串起「出发地(登录)」到「目的地」。
- 排版：品牌渐变标 + 一个有个性的中文标题字重，字段做成登机牌信息栏的样式。
- 登录/注册同屏切换（tab 或链接）。空/错态文案用界面自己的口吻（不道歉、说清怎么办）。
- 避开 skill 点名的三种 AI 默认风（暖米色+衬线+赤陶 等）。

## 前端接入

- 未登录 → 显示 AuthScreen；登录后进主界面，右上/侧边栏加「退出登录」。
- 统一 `authFetch`（自动带 token；401 → 清 token 回登录页）。现有 10 处 fetch 改走它。

## 涉及模块

后端：`app/db/models.py`（+User/Session，3 表加 user_id）、`app/api/auth_api.py`（新）、
`app/api/deps.py`（get_current_user）、`chat_api.py`/`memory_api.py`（加用户过滤）、
`orchestrator.py`/`poster.py`/`site_router.py`/`memory.py`（透传 user_id）、`main.py`。
前端：`AuthScreen`（新）、`Home.tsx`（authFetch + 登录态 + 退出）、`index.css`。

## 验收标准

1. 未登录访问显示登录界面；注册后自动登录；刷新保持登录；退出回登录页。
2. 两个账号互不可见对方的历史会话、记忆。
3. 记忆提炼/注入、扫码登录记录都归属当前用户。
4. 登录界面是旅行主题的独特设计（登机牌），非通用表单。
5. 单测：注册/登录/密码校验/token 鉴权、按用户过滤会话与记忆；存量不回归。
