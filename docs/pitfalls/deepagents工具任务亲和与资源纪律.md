# 踩坑：deepagents 工具跨 task 共享 MCP 会话炸 cancel scope + agent 资源纪律

Phase 21 深度研究模式（deepagents）踩到两个坑。

## 1. MCP 会话是 task-affine 的：跨 asyncio task 进出会炸 + 泄漏池槽位

**现象**（线上）：
```
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
```
随后同一轮里 `BrowserAcquireTimeout: 排队等待浏览器超时`——池里该用户的槽位卡成 busy。

**原因**：mcp 的 `stdio_client` 基于 anyio cancel scope，**必须在同一个 asyncio task 里
进入和退出**。deepagents/langgraph 的每次工具调用跑在**不同的 task** 里（ToolNode 的
TaskGroup）。最初的 `BrowserSession` 在第一个工具调用的 task 里 `__aenter__`、在轮末
finally（又一个 task）里 `__aexit__` → anyio 崩溃 → `ChromeMCP.__aexit__` 没走完 →
`browser_pool` 的 busy 标记没释放 → 同用户下次 acquire 排队 120s 超时。

**解法：actor 模式**（`research_tools.BrowserSession`）：
- 专职 worker task **全程独占** ChromeMCP 生命周期（enter/调用/exit 都在这一个 task）；
- 工具通过 `asyncio.Queue` 提交 `(future, method, args)`，await future 拿结果；
- 启动失败（acquire 超时）：worker 记录 `_startup_error` 并把队列中等待者全部置异常
  （`call()` 里 `asyncio.wait({fut, worker})` 双保险，worker 先死也不会挂）；
- `close()`：投毒丸（None）让 worker 自然退出；20s 不退再 `worker.cancel()`——取消发生在
  worker 自己的 task 里，anyio scope 同 task 解开，槽位一定释放。

回归测试：`test_browser_session_single_task_lifecycle`（断言 enter/call/exit 同 task）、
`test_browser_session_startup_failure_propagates`。

**推广**：任何「anyio/结构化并发的资源」要给多 task 的调用方共用，都应包成 actor，
不要裸共享 async context manager。

## 2. agent 资源纪律：不写死预算它就会挥霍浏览器

**现象**：第一版 system_prompt 只说「数据收集尽量委派 subagent」，DeepSeek 实际行为是
连发 **6 次浏览器搜索**（含 2 次查天气——高德一次 API 就能给），从不委派，480s 超时。

**解法**：prompt 里写**硬性资源纪律**而非建议：
- 天气/景点/地点核实 → **一律**派 api-researcher 用高德（禁用 web_search 查这些）；
- web_search 全程**最多 3 次**，一个 query 合并覆盖一个信息缺口（两城并进一个 query）；
- 搜到 URL 立刻整批（3-5 个）交给 subagent fetch_url，open_page 只做兜底。

改后同问题 ~4min 内完成，天气来自高德（表格里标注来源），报告带 10 个来源。
教训：**对弱一些的模型，资源预算要当规则写（最多 N 次），不要当风格建议写（尽量）**。
