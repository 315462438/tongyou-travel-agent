# 踩坑：snap chromium 多实例拉起 + 小内存服务器

Phase 19 每用户浏览器池，后端要按需拉起多个独立 Chrome（每用户一个 profile）。踩到几点。

## 1. snap chromium **能**多实例，但冷启动慢 + 需要给足就绪超时

- snap chromium 用不同 `--user-data-dir` + `--remote-debugging-port` **可以并存多实例**（实测
  9301/9302 同时跑）。
- 但**首次冷启动**（snap 解压/挂载 namespace）可能 10s+，`/json/version` 迟迟不 200。
  第一次探针只等 4s 判失败，其实是没等够。→ `browser_pool._cdp_ready` 就绪超时设 **22s**。
- 判就绪：轮询 `http://127.0.0.1:{port}/json/version`（本机直连，`ProxyHandler({})` 绕开
  HTTP_PROXY，否则 127.0.0.1 被送进代理 502）。

## 2. AppArmor / DBus 报错是**噪声**，不影响 CDP

日志里会刷：
```
ERROR ...dbus... AppArmor policy prevents this sender... (snap.chromium.chromium (enforce))
update.go: cannot change mount namespace ... /var/lib/snapd/hostfs/...
ld.so: object '/$LIB/libonion.so' from /etc/ld.so.preload cannot be preloaded
```
这些都是 snap 受限环境的正常告警，DevTools 照常 `listening on ws://127.0.0.1:{port}/...`，
CDP 可用。别被吓到去换浏览器。

## 3. 小内存服务器：一个 Chrome 能吃 ~1.5G

服务器仅 3.6G 内存。**长跑**的常驻 Chrome（开着页面累积）实测占 ~1.5G RSS；fresh 实例
用完即杀则轻得多（~0.5G）。对策：
- 池上限 `browser_pool_max=2`；**按需拉起 + 空闲回收**（`idle_timeout_s`，reaper 线程），
  不让实例长跑膨胀。
- 停用原单浏览器 `travel-chrome.service`（回收其 ~1.5G）：
  `sudo systemctl disable --now travel-chrome`。
- 实测：3 并发（上限 2）时 2 个 fresh Chrome，available 内存最低 ~1.2G，未 OOM（还有 9.9G swap 兜底）。

## 4. 后端拉起的 Chrome 是 systemd 服务的子进程

`travel-backend.service` 用 subprocess.Popen 拉起的 chromium 在同一 cgroup。后端重启
（KillMode 默认 control-group）会**连带杀掉所有池内 Chrome**——这正合意（无孤儿）。
启动再跑 `cleanup_orphans()`（pkill 端口段内残留）兜底，profile 在磁盘不丢、按需重拉。
