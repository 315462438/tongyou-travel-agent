# 持久 profile + 每会话自启动 Chrome = profile 锁冲突（搜索静默变空）

> 记录：2026-07-06（用户报告：开封攻略连续两轮「没能抓到足够资料」）

## 现象

必应和 360 搜索全部静默返回空、整轮失败；服务器上手工排查时报出真正的错误：

```
The browser is already running for /home/ubuntu/.cache/chrome-devtools-mcp/chrome-profile.
Use --isolated to run multiple browser instances.
```

## 原因

Phase 5 为保留扫码登录态，把 chrome-devtools-mcp 的 `--isolated` 去掉（持久 profile）。
但架构仍是**每个 ChromeMCP 会话自启动一个 Chrome**：一次编排要开 3-4 个会话
（站点路由、每个搜索查询、抓取各一个）。只要任何一个 Chrome 进程退出不及时/残留，
下一个会话启动就撞 profile 锁直接失败；而 `search_web`/路由里的异常全被
`except: return []` 吞掉，表现为「搜索无结果」，极难定位。

## 解决办法（架构修正）

服务器改成与本地开发一致的**常驻浏览器**架构：

1. `travel-chrome.service`（systemd）：常驻 headless Chrome，
   `--remote-debugging-port=9222` + 固定 `--user-data-dir`（沿用原 profile，
   登录态无缝保留）。
2. 后端 `.env`：删 `CHROME_EXECUTABLE`，加 `CHROME_DEBUG_URL=http://127.0.0.1:9222`
   和 `REMOTE_BROWSER=true`。ChromeMCP 全部走 `--browser-url` 连接模式——
   只连接、不启动，锁冲突根除。
3. 代码里「服务器模式」判定从 `chrome_executable` 改为
   `settings.is_headless_server`（= `remote_browser or chrome_executable`），
   handoff 截图直播等行为不变。

## 经验

- 「持久 profile」和「每会话新起浏览器」天然互斥，二选一：要么 isolated 临时
  profile（无登录态），要么常驻单浏览器（都连它）。
- 底层基础设施错误绝不能吞成业务空结果——`except: return []` 至少要打日志。
