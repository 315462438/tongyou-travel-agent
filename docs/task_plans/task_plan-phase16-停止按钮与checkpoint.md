# Task Plan — Phase 16：停止按钮 + Postgres checkpoint + 5 轮历史

> 创建：2026-07-07　状态：开发中

## 需求

1. 停止按钮：生成中可终止本轮对话。
2. 图级 checkpoint：LangGraph 每步 state 持久化到**现有 PostgreSQL**
   （用户确认复用 PG，不部署 MongoDB），支持服务器重启后续跑。
3. 对话历史取近 5 轮，放进 graph state 节点传递。

## 方案

### 停止按钮（协作式取消）

- `app/agent/cancel.py`：进程内线程安全的「取消 cid 集合」+ `request/is/clear`。
- 生成流式循环每块 check、采集阶段每次搜索/抓取前 check → 命中则抛 `TurnCancelled`。
- `generate_guide_streaming` 命中取消：把已生成部分 + 「（已停止）」终稿该消息后抛出。
- `run_conversation_turn` 捕获 `TurnCancelled`：确保有终稿消息、`clear_cancel`。
- `POST /api/chat/{cid}/stop`（需登录+归属）→ `request_cancel`。
- 前端：running 时发送键变■停止键 → 调 /stop；轮询到 running=false 收尾。

### Postgres checkpointer + 重启续跑

- `langgraph-checkpoint-postgres`（AsyncPostgresSaver，conn 用 PG，去掉 `+psycopg`）。
- `graph.py`：`_build_graph()`（拓扑）；`_compiled()` 保留无 checkpointer 供离线测试；
  `run_guide_graph(cid, user_text, user_id, turn_id)` 用 `async with AsyncPostgresSaver`
  编译带 checkpointer，`thread_id = turn_id`（= 用户消息 id，每轮唯一，天然 fresh）。
- startup：`saver.setup()` 一次建 checkpoint 表。
- **在途登记** `TravelInflightTurn(cid, turn_id, started_at)`：`run_conversation_turn`
  开始插、正常/取消结束删；进程被杀则残留 → startup 扫描并 `resume_turn`
  （删掉上一轮的未终稿流式消息避免重复 → `ainvoke(None, thread_id)` 从 checkpoint 续跑）。
  resume 失败回退现有 repair（提示重发）。
- config：`checkpointer_enabled=True`。

### 5 轮历史进 state

- `_history_text` 取近 5 轮（user+assistant 各 5 ≈ 10 条）；`AgentState.history` 由
  parse 节点写入、parse_request 使用。

## 涉及模块

后端：`cancel.py`（新）、`graph.py`、`orchestrator.py`（run_conversation_turn/生成循环/
采集 check、_history_text）、`nodes.py`/`graph_state.py`（history）、`chat_api.py`
（stop 路由 + send 传 turn_id）、`db/models.py`（TravelInflightTurn）、`db/migrate.py`
（setup + resume 扫描）、`main.py`、`config.py`、`requirements.txt`。
前端：`Home.tsx`（停止键）。

## 验收标准

1. 生成中点停止 → 立即停、保留已生成部分标「已停止」、running 回落、输入框解锁。
2. checkpoint 表有数据；每轮 thread_id 唯一、不串。
3. 模拟生成中重启 → 该轮从 checkpoint 续跑出稿（或安全回退提示重发）。
4. 历史注入为近 5 轮。
5. 存量测试全过 + 新增（取消判定、history 轮数、in-flight 登记）。
