# Phase 19 每用户浏览器池 — 验收用例

自动化：`backend/tests/test_browser_pool.py`（10 例，mock launcher，不拉真 Chrome）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_browser_pool.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 同用户 acquire→release→acquire | 复用同实例，不二次拉起 | `test_acquire_reuses_same_user_instance` |
| 2 | 两个不同用户 | 各自独立实例、不同端口 | `test_distinct_users_distinct_instances` |
| 3 | 满池新用户 | 驱逐最久空闲 LRU 实例后拉起 | `test_evict_lru_idle_when_full` |
| 4 | 同用户并发第二轮 | 阻塞直到第一轮 release | `test_same_user_serialized` |
| 5 | 满池且都 busy | 排队 + on_wait(position) 触发一次 | `test_all_busy_queues_and_on_wait_fires` |
| 6 | 排队超时 | 抛 BrowserAcquireTimeout | `test_acquire_timeout` |
| 7 | restart | 杀实例、下次 acquire 重拉 | `test_restart_kills_and_respawns` |
| 8 | 空闲回收 | 超时且非 busy 被回收 | `test_reap_idle` |
| 9 | busy 不回收 | busy 实例不被 reaper 杀 | `test_busy_instance_not_reaped` |
| 10 | 拉起失败回滚 | 槽位释放、不残留 | `test_launch_failure_rolls_back` |

## 线上 E2E（已执行 ✅）

**单用户浏览**：admin 发「福州2天路线」→ 端口 9300 拉起一个 Chrome，profile 目录 =
admin 的 user_id（`293cbea7…`）；turn 产出 2902 字攻略 + 5 来源（经池抓取成功）。

**并发 + 排队**：3 个不同用户并发发起浏览任务（池上限 2）→ **恰好 2 个 Chrome**
（端口 9301+9302，各自 profile），第 3 个用户收到 progress「前面还有 2 个任务在用浏览器，
正在排队…」。内存 available 最低 ~1.2G，未 OOM。

**内存回收**：turn 结束后实例空闲；停用 `travel-chrome.service` 回收 ~1.5G，
部署后 available 从 ~0.35G 升到 ~2.0G。

## 关键不变式
- `browser_pool_enabled=true`（服务器 .env）才走池；本地开发（false）回退单浏览器全局串行。
- 每 user_id 一个持久 profile（磁盘），登录态互不覆盖、跨重启保留（不再切用户清 cookie）。
- 池 busy 即每用户串行（避免同一 Chrome 被两个 MCP 会话搞死 CDP）；不同用户并行（≤max）。
- 启动 `cleanup_orphans()` 杀端口段孤儿；`_cdp_ready` 就绪超时 22s 容忍 snap 冷启动。
