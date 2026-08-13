# Phase 5 验收用例 — 登录墙远程接管（扫码登录 + 截图直播）

> 自动化测试：`backend/tests/test_site_router.py` 新增/改写 4 例（remote 等待+截图、
> 超时清理、无截图路径仍等待、local 模式不截图），全部离线。
> 运行：`cd backend && .venv/bin/python -m pytest tests/test_site_router.py -q`

## A. 自动化 ✅

| # | 场景 | 预期 |
| --- | --- | --- |
| A1 | 服务器模式命中登录墙 | 暂停等待；handoff meta `mode=remote, screenshot=true`；文案引导扫码；首帧+每轮轮询刷新截图 |
| A2 | 扫码登录成功（check_page 变 ok） | 重开目标页继续抓取，progress「登录成功」；截图文件清理 |
| A3 | 超时未登录 | 返回空回退搜索；截图文件清理 |
| A4 | 服务器模式未传截图路径 | 照常暂停等待，卡片 `screenshot=false`，不调截图 |
| A5 | 本地模式 | 行为不变（mode=local，不截图） |

## B. 端到端手工验收（线上）

| # | 步骤 | 预期 |
| --- | --- | --- |
| B1 | 线上发酒店/路线请求命中登录墙 | 聊天界面出现「用 App 扫码登录」卡片，内嵌登录页实时截图（4s 刷新），`GET /api/chat/{cid}/handoff-screenshot` 返回 jpeg |
| B2 | 手机 App 扫码登录 | Agent 自动继续抓取站点内容并生成回复 |
| B3 | 不登录等超时 | 回退必应搜索，正常出结果 |
| B4 | 登录一次后再次发起同站点任务 | 持久 profile 带登录态，不再弹登录卡 |
| B5 | 本地开发流程 | 不回归（调试 Chrome 窗口内直接登录） |

## 已知限制

- 站点登录页若无二维码入口（纯短信表单），远程无法输入，等超时后回退——不阻塞。
- 用户在自己浏览器里登录同一站点对 Agent 无效（cookie 不互通），卡片文案已引导扫码。

## 结果记录

- 2026-07-06：A 组自动化通过 + 新增风控页相关性校验用例（合计 59 passed 无回归）。
- 2026-07-06：服务器 headless `take_screenshot(filePath)` 实测可用（10KB jpeg）。
- 2026-07-06 线上冒烟（厦门路线 → 小红书）：
  - B1 ✅ handoff 卡片出现（mode=remote, screenshot=true），
    `handoff-screenshot` 端点返回实时 jpeg；结束后文件清理（404）。
  - B3 ✅ 未登录时回退必应搜索，5 来源正常出攻略（且自动应用了口味记忆）。
  - ⚠️ 发现小红书风控封锁云服务器 IP（见 `docs/pitfalls/小红书风控封锁云服务器IP.md`），
    该服务器上小红书连登录页都不展示，扫码路径对小红书暂不可用（携程正常）；
    风控页混入来源的次级 bug 已修复（is_relevant 校验）。
  - B2/B4 扫码与持久登录：携程场景待用户真实扫码验证。
