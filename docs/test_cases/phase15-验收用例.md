# Phase 15 验收用例 — 登录/注册 + 按用户隔离

> 自动化：`tests/test_auth.py`（8 例：密码哈希、注册/登录、坏 token、会话/记忆隔离、
> admin 权限与用户列表）；存量各 test 已改带 user_id。合计 140 passed 无回归。

## A. 自动化 ✅

| # | 覆盖 |
| --- | --- |
| A1 | pbkdf2 密码哈希 roundtrip / 错密码不通过 |
| A2 | 注册→拿 token→/me 解析用户；登录；重名/短密码/错密码拒绝；坏 token 401 |
| A3 | 两用户会话、记忆互不可见（list_conversations / list_memories 按 user_id 过滤） |
| A4 | require_admin：非管理员 403；admin 用户列表带会话/记忆计数 |
| A5 | 站点登录记录按 (user_id, site) 隔离；记忆 apply_ops 只改本人记忆 |

## B. 端到端（线上）

| # | 场景 | 结果 |
| --- | --- | --- |
| B1 | 迁移+引导 | ✅ 启动自动加 user_id 列、建 user/session 表、引导 admin、旧数据（50 会话/20 记忆）归 admin |
| B2 | 登录界面 | ✅ 登机牌造型：sky 渐变背景 + 航线飞机 + 撕裂票根（航班/日期/目的地）+ 登录/注册 tab + 「登机」CTA（响应式，reduced-motion 友好） |
| B3 | admin 登录 | ✅ 看到旧数据；「用户管理」面板列出注册用户 + 计数 |
| B4 | 新用户隔离 | ✅ alice 注册后会话/记忆为空，看不到 admin 的 |
| B5 | 鉴权 | ✅ 无 token 401；非 admin 访问 /admin 403；退出回登录页 |

## 隔离范围

- 会话/消息（经会话归属）、记忆、站点扫码登录记录 → 按 user_id。
- 携程 cookie 共享浏览器：切用户时清 cookie（_expire_stale_logins 检测归属变化），
  避免跨用户复用登录态；同一时段仅一人保持站点登录。
- travel_ctrip_city（城市 ID）保持全局（无隐私）。

## 备注

- admin 账号：用户名/密码见 `.env` 的 ADMIN_USERNAME/ADMIN_PASSWORD（默认 admin/admin123，
  建议线上改后重启）。
