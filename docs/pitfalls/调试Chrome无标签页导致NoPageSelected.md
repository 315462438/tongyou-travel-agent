# 调试 Chrome 无标签页导致 MCP "No page selected"

> 记录：2026-07-06（Phase 3 站点路由冒烟测试时发现）

## 现象

站点路由 / 必应搜索全部失败，progress 显示：

```
浏览器连接失败：MCP 工具 navigate_page 执行失败: No page selected
```

`curl http://127.0.0.1:9223/json/list` 返回空数组 —— 调试 Chrome 活着，
但一个标签页都没有（此前的标签页被手动关掉了）。

## 原因

chrome-devtools-mcp 以 `--browser-url` 连接现成 Chrome 时，会把「当前选中页」
指向连接时已存在的某个标签页；如果浏览器没有任何标签页（或选中页之后被关闭），
所有针对“当前页”的工具（navigate_page / take_snapshot / evaluate_script…）都会报
`No page selected`。服务器 headless 自启动模式没有这个问题（isolated 启动自带页面），
所以只在本地调试环境暴露。

## 解决办法

注意：浏览器完全没有标签页时，chrome-devtools-mcp 0.6.0 的**所有工具都会失败**，
连 `new_page` 也报 `No page selected` —— 无法用 MCP 自救。

`ChromeMCP.connect()` 在 initialize 之后调用 `_ensure_page()`：
`list_pages` 里没有 `[selected]` 标记（或直接报错）时，绕过 MCP 用 Chrome 调试
HTTP 接口建标签页：

```bash
curl -X PUT "http://127.0.0.1:9223/json/new?about:blank"   # 注意必须是 PUT
```

之后再 `list_pages` 触发 MCP 感知。headless 自启动模式（isolated）自带页面，跳过。

## 连带坑：HTTP_PROXY 把 127.0.0.1 也代理了

用 urllib 调 `http://127.0.0.1:9223/json/*` 时返回 502 Bad Gateway ——
shell 环境里有 `HTTP_PROXY`（无 NO_PROXY），urllib 默认读代理环境变量，
把本机 CDP 请求也送进了远端代理。curl 之所以正常，是它对 http URL 只认小写
`http_proxy`。修复：`urllib.request.build_opener(ProxyHandler({}))` 强制直连。

## 经验

- 连「用户的」浏览器时不能假设它有标签页；每次建会话都要先确保有选中页。
- MCP 层自救不了就退回协议层（CDP HTTP 接口 `/json/new`、`/json/list`）。
- 访问本机服务的代码一律显式绕开代理，别依赖环境变量恰好没设。
- `search_web`/路由里 `except Exception: return []` 会把这类环境错误吞成
  「搜索无结果」，排查时先看后端日志/progress 消息里的 MCP 原始报错。
