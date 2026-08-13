# Task Plan — Phase 9：站点登录态过期机制（扫码登录 1 小时后需重扫）

> 创建：2026-07-06　状态：开发中

## 需求（用户原话）

扫码登录（如携程）后设置过期时间，例如 1 小时后需要重新扫码。
动机：服务器 headless Chrome 的持久 profile 会无限期保留登录态，存在安全隐患。

## 方案

1. **记录**：`travel_site_login` 表（site 主键 + logged_in_at）。
   `_wait_for_login` 成功（用户完成登录）且为服务器模式时落一条记录。
2. **过期检查**：站点路由入口 `_collect_from_routed_site` 开头调
   `_expire_stale_logins`：任一记录超过 `site_login_ttl_min`（默认 60，0=永不过期）
   → 通过 CDP `Storage.clearCookies` 清空常驻浏览器全部 cookie（单用途浏览器，
   全清最可靠；按域清理受 cookie domain 归属影响不可靠）→ 删全部登录记录 →
   progress 提示「登录已过期，需要时会重新引导扫码」。
3. **重新引导**：cookie 清掉后，后续流程命中登录墙/无价场景，自然复用
   Phase 5/6 的扫码卡片，无需新 UI。
4. **本地模式不启用**：本地连的是用户自己的 Chrome，绝不清用户个人 cookie。

## 涉及模块

- `config.py`：`site_login_ttl_min: int = 60`
- `db/models.py`：`TravelSiteLogin`
- `app/tools/cdp.py`（新）：`clear_browser_cookies(debug_url)`（websockets 直连 CDP）
- `site_router._wait_for_login`：成功时记录；新增 mark/expired 查询函数
- `orchestrator._collect_from_routed_site`：入口过期检查
- `requirements.txt`：+websockets

## 验收标准

1. 扫码登录后 `travel_site_login` 出现记录；TTL 内再次查询不重新扫码（实价直出）。
2. 把记录时间改老（模拟超时）后再查询：progress 出现「登录已过期」，
   携程价格变回「登录后可见」并弹出扫码卡。
3. `SITE_LOGIN_TTL_MIN=0` 时永不过期。
4. 单测：记录/过期判定（含 0=禁用、未登录无记录不触发）；cookie 清除函数联通性服务器实测。
