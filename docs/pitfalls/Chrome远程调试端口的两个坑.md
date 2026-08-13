# 踩坑：Chrome 远程调试端口的两个坑

> 日期：2026-07-03　|　阶段：Phase 1 MCP 接入

## 坑 1：新版 Chrome 在默认 profile 下禁用远程调试端点

### 现象

- `lsof -i :9222` 显示 Chrome 进程在监听
- 但 `curl http://127.0.0.1:9222/json/version` 返回 404/空
- chrome-devtools-mcp 报错：`Failed to fetch browser webSocket URL from http://127.0.0.1:9222/json/version: HTTP Not Found`

### 原因

Chrome 136+ 出于安全考虑（防止恶意程序偷默认 profile 的登录态），**在默认用户数据目录下静默忽略 `--remote-debugging-port`**，端口可能被占用但调试端点不生效。必须显式指定独立的 `--user-data-dir` 才会开启调试端点。

### 解决

`scripts/start_chrome.sh` 使用独立 profile + 端口 9223（避开主 Chrome 可能占用的 9222）：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9223 \
    --user-data-dir="$HOME/chrome-agent-profile"
```

验证方法：`curl http://127.0.0.1:9223/json/version` 应返回 Browser 版本 JSON。

## 坑 2：MCP 工具错误被当成正常结果

### 现象

任务状态 done，但入库的 `raw_text` 是一段 MCP 错误消息（93 字符），抽取结果全空。

### 原因

MCP 协议中工具执行失败不抛协议异常，而是返回 `result.isError=true` + 错误文本。
`mcp_client.call()` 初版只拼接了文本内容，没检查 `isError`，错误文本被当页面内容
一路传到抽取环节。

### 解决

`ChromeMCP.call()` 检查 `result.isError`，为真时抛 `MCPConnectionError`，
任务正确进入 failed 状态而不是产出垃圾数据。

### 经验

**凡是「任务成功但产物异常小/异常空」，先怀疑上游错误被静默吞掉。**
