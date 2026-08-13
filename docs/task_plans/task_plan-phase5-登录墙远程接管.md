# Task Plan — Phase 5：登录墙远程接管（扫码登录 + 截图直播）

> 创建：2026-07-06　状态：已完成并上线（自动化 59 passed；线上冒烟见
> `docs/test_cases/phase5-验收用例.md`。已知：小红书风控封锁云 IP，
> 见 `docs/pitfalls/小红书风控封锁云服务器IP.md`）

## 背景 / 需求

用户要求：遇到登录墙时 Agent 暂停，用户手动完成登录，然后 Agent 用**登录后的会话**
继续在该站点搜索和整合资源，再继续生成回复。

本地开发环境已天然支持（Agent 连的就是用户可见的调试 Chrome，用户直接在窗口里登录）。
难点在服务器部署：Agent 用的是服务器上的 headless Chrome，**登录态必须产生在这个
浏览器里** —— 用户在自己电脑浏览器上登录是无效的（cookie 不互通）。

## 方案：截图直播 + 手机扫码

携程/小红书等国内站点均以「App 扫码登录」为主流方式，这使得**不需要远程键鼠转发**
就能完成登录：

1. 服务器 Chrome 命中登录墙 → Agent 暂停（复用现有 `_wait_for_login` 轮询）。
2. 暂停期间每次轮询用 `take_screenshot(filePath=...)` 把当前登录页截到
   `{tmp}/travel_handoff/{cid}.jpg`。
3. 新端点 `GET /api/chat/{cid}/handoff-screenshot` 返回该图（no-store）。
4. 前端 handoff 卡片（mode=remote）内嵌该截图并每 4s 刷新 —— 登录页上的二维码
   实时可见，用户用携程/小红书 App 扫码。
5. 登录完成 → `check_page` 检测到页面可读 → 重开目标搜索页继续抓取 → 正常生成。
   超时（默认 180s）→ 回退必应搜索（现有行为）。
6. **持久登录**：服务器模式去掉 chrome-devtools-mcp 的 `--isolated=true`，
   使用持久 profile，扫码一次后续任务直接带登录态，不再反复弹卡。
7. 等待结束（成功/超时）删除截图文件。

本地模式（mode=local）保持现状：提示在调试 Chrome 窗口里登录，不截图。

## 已知限制（写进验收）

- 若站点登录页默认是短信验证码表单且无二维码入口，远程无法输入（无键鼠转发），
  等待超时后回退搜索 —— 不阻塞主流程。键鼠转发/验证码中继留待后续版本。
- 用户在**自己浏览器**打开同一站点登录对 Agent 无效，卡片文案要说清「用 App 扫码」。

## 涉及模块

- `app/tools/mcp_client.py`：headless 模式去掉 `--isolated`（持久 profile）。
- `app/tools/browser_tool.py`：新增 `screenshot_to_file(path)`。
- `app/agent/site_router.py`：remote 模式也进入等待；等待循环内刷新截图；
  meta.handoff 增加 `mode` / `screenshot` 字段；结束后清理截图。
- `app/api/chat_api.py`：`GET /api/chat/{cid}/handoff-screenshot`。
- `app/agent/orchestrator.py`：传入 per-cid 截图路径。
- 前端 `HandoffCard`：remote 模式内嵌截图（4s 轮询刷新）+ 扫码引导文案。

## 验收标准

1. 服务器版输入酒店/路线请求 → 命中登录墙 → 聊天界面出现带**实时登录页截图**的卡片
   → 手机扫码登录 → Agent 自动继续抓取并生成（进度气泡「登录成功，继续抓取」）。
2. 超时不登录 → 回退必应搜索，正常出结果。
3. 登录一次后，后续任务不再弹登录卡（持久 profile 生效）。
4. 本地开发流程不回归（mode=local 行为不变）。
5. 单测覆盖：remote 等待+截图刷新、登录成功续抓、超时回退、截图清理。
