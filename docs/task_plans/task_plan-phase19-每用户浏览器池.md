# Phase 19 — 每用户浏览器 profile 池（登录隔离 + 有限并发）

## 背景 / 目标

现状：线上只有**一个**常驻 headless Chrome（`travel-chrome.service` :9223，单 profile），
后端只连不启，`_MCP_GLOBAL_LOCK`（进程级 threading.Lock）把**所有用户的浏览器操作全局串行**。
多用户「登录」靠**切换用户时清 cookie**（`_expire_stale_logins`→`clear_browser_cookies`）伪装，
导致两个用户无法同时保持各自登录态。

目标（用户诉求「每个账户各自扫码登录」）：
1. **每用户独立 profile**：各自扫码，登录态持久化在磁盘、互不覆盖。
2. **有限并发**：不同用户可并行浏览（受服务器内存限制，池上限≈2），同一用户的并发轮次仍串行。

## 硬约束：服务器内存

服务器仅 **3.6G 内存**，单个 Chrome 进程树已占 **~1.5G**，空闲仅 ~1.7G。
→ 不能无限并发浏览器。策略：**按需拉起 + 用完/空闲即回收**（fresh 实例占用远低于 1.5G），
池上限 `browser_pool_max`（默认 2，可配），超出的排队。登录态在磁盘 profile，回收进程不丢登录。

## 设计

### 新模块 `app/tools/browser_pool.py`
线程安全（多后台线程各自事件循环）的键控资源池：
- 每 `user_id` 一个 `_Instance{port, profile_dir, proc, busy, last_used}`，profile =
  `{browser_profile_base}/{user_id}`（持久）。
- `acquire(user_id) -> browser_url`（`threading.Condition` 保护）：
  - 该用户已有存活实例且空闲 → 标记 busy 返回。
  - 该用户实例 busy（同用户另一轮次在跑）→ 等待。
  - 需新建：存活数 ≥ max → 杀一个**空闲** LRU 实例腾内存（都 busy 则等待）；再 spawn。
  - 超 `browser_acquire_timeout_s` 抛异常（上层降级）。
- `release(user_id)`：清 busy、更新 last_used、notify。
- **排队提示**：`acquire(user_id, on_wait)` 在需要等待（池满且都 busy）时回调一次
  `on_wait(position)`，上层据此写一条 progress 消息「前面还有 N 个任务在用浏览器，排队中…」。
- 空闲回收线程：每 ~60s 杀 `last_used` 超 `browser_idle_timeout_s` 且非 busy 的实例（释放内存，
  profile 保留）。
- `restart(user_id)`：杀该用户实例（自愈 tier-3 用），下次 acquire 重拉。
- 端口从 `browser_pool_port_start`(9300) 起取空闲端口；spawn 后轮询 `/json/version` 就绪。
- spawn 参数加 `--disable-dev-shm-usage --no-sandbox --headless=new`（内存/稳定）。

### `app/tools/mcp_client.py`
- `ChromeMCP(user_id=..., browser_url=...)`：`browser_pool_enabled` 时 `__aenter__` 走
  `pool.acquire(user_id)` 拿 url（替代全局锁，池的 busy 即每用户串行）、`__aexit__` `release`；
  未启用时保留原全局锁 + 固定 `chrome_debug_url`（本地开发不变）。
- 自愈 tier-3：pool 模式下 `pool.restart(user_id)` 重拉该用户 Chrome（替代杀常驻 + 等 systemd）。

### `app/agent/orchestrator.py`
- 两处 `async with ChromeMCP()` → 传 `user_id`。
- `_expire_stale_logins`：pool 模式下不再清 cookie（每用户 profile 天然隔离，登录应持久）；
  仍保留 `TravelSiteLogin` 标记供「是否尝试该站点」判定。登录失效走登录墙 handoff 重扫。

### 配置 `app/config.py`
`browser_pool_enabled`(False) / `browser_pool_max`(2) / `browser_profile_base` /
`chromium_path`(/snap/bin/chromium) / `browser_pool_port_start`(9300) /
`browser_idle_timeout_s`(600) / `browser_acquire_timeout_s`(120)。

### 启动 & 部署（`app/main.py` / deploy）
- 启动清理：杀端口段内的孤儿 chromium（上次崩溃残留，profile 会被锁）→ 按需重拉。
- 线上 `.env` 设 `BROWSER_POOL_ENABLED=true`；**停用** `travel-chrome.service`（回收其 ~1.5G）。
- 建 `browser_profile_base` 目录。

## 验收标准
1. 两个不同用户各自扫码登录携程，登录态各自持久（互不覆盖）；重启后端后仍在。
2. 两用户可并行浏览（池上限内），同一用户并发轮次串行、不撞 CDP。
3. 池达上限时第三个用户排队而非 OOM；空闲实例被回收释放内存。
4. `browser_pool.py` 单测（mock spawn）：acquire/release/同用户复用/超限驱逐/超时。
5. 本地开发（pool 关）行为不变、全量单测通过。
6. 线上双用户 E2E 验证登录隔离 + 并发。

## 风险
- 内存：cap=2、fresh 实例 + 空闲回收控制；swap 9.9G 兜底。
- 孤儿进程/端口：启动清理 + 就绪探测 + 端口探测规避。
- 大改动，先本地实现+单测，再灰度上线（保留 pool 关的回退路径）。
