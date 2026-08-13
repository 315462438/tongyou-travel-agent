# Task Plan — Phase 7：登录来源确认弹窗（用户选「否」才跳过）

> 创建：2026-07-06　状态：已完成并上线（验收见 docs/test_cases/phase7-验收用例.md）
> 同批：服务器浏览器架构迁移为常驻 travel-chrome.service（修 profile 锁冲突）、
> ChromeMCP.call 兜底超时（修 mcp 僵死挂起）、360 搜索兜底（修必应间歇限流）。

## 需求（用户原话）

搜索抓取阶段遇到「需登录的来源」（知乎等）时，不要直接静默跳过——
应弹出确认卡片让用户决定是否登录；用户选「跳过」或超时未响应才跳过；
选「登录」则走扫码/本地登录接管，登录后读取该来源继续。

## 方案

### 交互协议（复用消息轮询通道，无需 WebSocket）

1. 后台任务遇到需登录来源 → 写一条 progress 消息，meta 带
   `confirm: {id, question, source: {title, url}}` → 前端渲染确认卡片
   （「登录读取」/「跳过」两个按钮 + 倒计时提示）。
2. 用户点击 → `POST /api/chat/{cid}/confirm {confirm_id, choice}` →
   落一条 role=`action` 的隐藏消息（meta `confirm_reply`，前端不渲染）。
3. 后台 `wait_confirm()` 轮询消息表等待回复；超时（默认 60s）视为跳过。
4. choice=login → 复用 Phase 5/6 的登录接管：切扫码 tab → 截图直播 →
   `_wait_for_login` → 登录成功重开该来源页继续读取。

### 防打扰

- 同一域名每轮只问一次；选「跳过」后同域来源本轮静默跳过。
- 每轮最多弹 2 次确认（超出的直接跳过，保持旧行为）。

### 涉及模块

- `config.py`：`confirm_wait_s = 60`。
- `app/agent/confirm.py`（新）：`ask_confirm` / `find_confirm_reply` / `wait_confirm`。
- `orchestrator._search_and_collect`：need_user_handoff 分支改为确认流程。
- `chat_api`：`POST /{cid}/confirm`；`_is_running` 与启动修复兼容 role=action。
- 前端：ConfirmCard（按钮 + 已选状态）、过滤 role=action、POST confirm。

## 验收标准

1. 抓到需登录来源时对话流出现确认卡片；点「跳过」→ 立即跳过该来源并继续；
   超时 60s 未点 → 自动跳过。
2. 点「登录读取」→ 出现扫码卡（服务器）/窗口登录提示（本地）→ 登录后
   该来源被读取进 sources。
3. 同域名本轮只问一次；每轮最多问 2 次。
4. 单测：确认回复查找、超时默认、同域去重、次数上限、running 判定兼容 action。
