# 小红书MCP故障触发LangGraph重试与停止失效

- 日期：2026-08-14
- 现象：小红书 MCP 服务 500/超时后，一轮攻略「无限死循环」无终止；期间停止按钮无反应
- 涉及：`app/agent/orchestrator.py`（collect_sources/_collect_xhs/_ensure_stopped_message）、
  `app/tools/xhs_mcp.py`（熔断）、`app/tools/browser_pool.py`（cancel_check）、
  `app/tools/mcp_client.py`（透传）

## 现象（线上日志实证）

```
app.tools.browser_pool.BrowserAcquireTimeout: 排队等待浏览器超时     ← collect 节点抛异常
xhs note_detail failed ... HTTPStatusError: 500 ... 127.0.0.1:18060  ← xhs MCP 垮
conversation 3dcb2d78... failed: ... langgraph/pregel/_retry.py, arun_with_retry  ← 图在重试
```

用户侧表现：一直转圈 10+ 分钟（看起来"无限死循环"），点停止没反应，最后才看到"处理出错"。

## 根因（四层叠加）

1. **collect 节点异常冒进 LangGraph 默认重试**：LangGraph `compile()` 默认对节点异常
   `arun_with_retry` 重试 3 次（带退避）。collect 里 `BrowserAcquireTimeout`（排队 120s 超时）
   只被 `except MCPConnectionError` 捕获——不匹配 → 异常冒出节点 → 图重试 collect →
   每次重试再经历 120s 排队 / 40s×N xhs 超时。**外部依赖故障被放大成 10 分钟级**。
2. **quick_take 提前建的 streaming 占位在异常路径无人终稿**：快答先行把占位创建提前了
   ~2 分钟（quick_take 节点），collect 异常重试/最终 failed 时 generate 没跑、占位空着且
   `streaming=true` → `_is_running` 永远判运行中 → **前端无限转圈、停止按钮形同虚设**。
   此前只修了 apologize 与停止路径的占位终稿，漏了异常失败路径。
3. **采集期间无取消检查点**：`await xhs_task`（并行采集新增）、xhs 详情逐篇、浏览器
   acquire 排队——用户点停止后要干等这几处自然结束（最长 2-5 分钟）。
4. **xhs MCP 故障时不快速失败**：`collect_xhs_sources` 每篇详情失败都继续下一篇，
   每次等 `xhs_mcp_timeout_s`(40s) 超时，n+2=7 次尝试 ≈ 5 分钟纯等待。

## 修复

| # | 改动 |
| --- | --- |
| ① | `collect_sources` 浏览器块全程 try：**除 TurnCancelled 外所有异常就地消化**（progress 说明后继续用已有 amap/xhs 来源，或走 apologize 正常终止）——**绝不冒进 LangGraph 重试**；入口加 `_cancel_check` |
| ② | `_ensure_stopped_message(cid, text)` 参数化；`run_conversation_turn` 的 `except Exception` 分支也调它（文案「抱歉，处理过程中出错了」）——**异常失败同样终稿残留占位** |
| ③ | `await xhs_task` → 既有 `cancel.wait_cancellable(cid, task)`（等结果期间每 1s 响应停止）；`_collect_xhs` 每查询前加 `_cancel_check` |
| ④ | `xhs_mcp.collect_xhs_sources` 熔断：**连续 2 次详情失败（None，MCP 故障）→ break**；短笔记不算故障 |
| ⑤ | `BrowserPool.acquire(user_id, on_wait, cancel_check=None)`：排队等待循环内周期调用 cancel_check（抛异常随锁释放传播）；`ChromeMCP` 透传——**排队 120s 期间停止也立即生效** |

## 教训

- **LangGraph 默认节点重试对"外部依赖故障"是灾难**：LLM 抖动重试合理，MCP/浏览器/排队
  这类分钟级外部故障必须由节点自身消化，否则 3 次重试 = 10 分钟用户不可控。
- **凡是把"占位消息创建"提前的改动，必须排查全部收尾路径**（apologize/停止/异常失败/
  崩溃续跑）都能终稿占位，否则 `_is_running` 永远 true = 前端假死。
- **MCP 故障要快速失败（熔断），不是逐篇等超时**——超时是给"正常慢"的兜底，不是给
  "服务已死"的循环。
- 并行改造引入新等待点时，每个 `await` 都要问一遍：停止按钮在这里要不要生效。

## 回归测试

`test_xhs_mcp.py::test_collect_circuit_breaker_on_consecutive_failures`（熔断只读 2 篇）、
`test_browser_pool.py::test_acquire_cancel_check_aborts_queueing`（排队立即中止且池状态不坏）、
`test_guide_quick_take.py`（`_ensure_stopped_message` 自定义文案全分支）。

---

## 追加（2026-08-14）：整轮总预算

熔断只覆盖「连续失败」，挡不住 MCP **半死**（失败-成功交替 / 每篇卡在 40s 超时边缘）：
最坏 2×40s 搜索 + 7×40s 详情 ≈ 5 分钟。新增 `xhs_collect_timeout_s=150`：
`collect_xhs_sources` 整轮包 `asyncio.wait_for`（搜索+全部详情合计 ≤150s），超预算整轮
放弃返回 []，必应兜底；`CancelledError` 放行（停止优先）。测试：
`test_collect_total_budget_exceeded`（预算 0.05s + 慢详情 → []）、
`test_collect_total_budget_sufficient_for_normal`（正常不受影响）。

---

## 追加（2026-08-14）：熔断的「连续」语义名实修复

`consecutive_failures` 初版漏了成功时重置——名字/注释写「连续」，行为却是**累计 2 次失败**。
健康 MCP 下 `note_detail` 返回 None 的正常情况（笔记被删/登录墙/解析失败）零星撞上 2 次
就会误熔断丢料。修复：只要 MCP 有响应（含短笔记）即重置为 0，恢复真正的「连续」语义；
总预算（`xhs_collect_timeout_s`）仍兜底，熔断晚一两个回合安全。回归测试
`test_collect_breaker_is_consecutive_not_cumulative`：失败→成功→失败→失败 只在第二次
连续失败时熔断，且中间的成功来源被保留。
**教训：熔断/限流类计数器的语义（连续 vs 累计）必须在代码里写死并配测试，注释不算数。**
