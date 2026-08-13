# MCP 调用无超时，子进程僵死时后台任务永久挂起

> 记录：2026-07-06（Phase 7 线上验证时，开封查询卡在搜索阶段 7+ 分钟无进展）

## 现象

进度停在「正在搜索…」不再更新；py-spy dump 显示后台任务线程 idle 在
asyncio select——在 await 一个永远不会返回的 MCP RPC。服务器上对应的
chrome-devtools-mcp node 进程活着但已僵死（连着常驻 Chrome 却不干活）。

## 原因

`ChromeMCP.call()` 直接 `await session.call_tool(...)`，**没有任何超时**。
mcp 子进程一旦僵死（stdio 还在、逻辑卡住），RPC 无响应也无异常，
调用方永远等待。navigate_page 等工具自带的页面超时参数只约束页面加载，
不约束「mcp 本身不回话」。

## 解决办法

1. `call()` 外层包 `asyncio.wait_for(timeout=120s)`，超时抛 MCPConnectionError
   —— 僵死从「永久挂起」降级为「该步骤失败、上层回退/跳过」，任务能继续走完。
2. 应急恢复：`pkill -f chrome-devtools-mcp`（杀 mcp 不影响常驻 Chrome），
   悬挂的 RPC 立即报错、任务解卡。

## 经验

- **跨进程的 await 必须有超时**，对方进程的死活不受你控制。
- 诊断利器：`py-spy dump --pid <uvicorn>` 一秒看清后台线程卡在哪一行。
