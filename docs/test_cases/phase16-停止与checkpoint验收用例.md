# Phase 16 停止按钮 + PostgreSQL checkpoint — 验收用例

自动化测试：`backend/tests/test_cancel.py`（3 例）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_cancel.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | request_cancel → check → clear 生命周期 | check 抛 TurnCancelled；clear 后不再抛 | `test_cancel_lifecycle` |
| 2 | 两个 cid 独立取消 | 取消 a 不影响 b | `test_cancel_isolated_per_cid` |
| 3 | 近 N 轮历史 = limit N×2 | history_rounds=5 → limit 10 | `test_history_rounds_limit` |

## 线上/本地 E2E（已执行 ✅）

**停止按钮**：发起一轮 → 3s 后点停止（`POST /api/chat/{cid}/stop`）：
```
{"status":"stopping"} → running 变 False → 末条 assistant「已停止本轮。」
checkpoint 表该 thread 有记录（7 条）
```

**崩溃续跑（resume-on-restart）**：发起「厦门2天海鲜」→ 采集中强杀 uvicorn（SIGKILL）→ 重启：
```
启动时 resume_inflight_turns() 从 travel_inflight_turn 发现在途 turn
→ 后台线程 asyncio.run(resume_turn(turn_id)) 从 checkpoint 续跑
→ 最终产出完整攻略（2149 字，含「## Day 1」）→ inflight 登记清空（0）
```

## 关键不变式

- checkpointer 用 `AsyncPostgresSaver`（复用现有 PG，非 MongoDB），thread_id = 用户消息 id（每轮唯一）。
- 停止是**协作式**：`cancel.check(cid)` 在搜索循环、抓取、流式生成各 checkpoint 处抛 `TurnCancelled`。
- 续跑只处理 10 分钟内的在途 turn；孤儿 streaming 消息先删再续。
- 近 5 轮对话（`history_rounds`）经 state 传入图节点。

## 已知非阻塞项

启动日志有 msgpack 反序列化告警（`Preference` 未注册），当前可正常读写 checkpoint，
未来 langgraph 版本可能收紧 → 见 `docs/pitfalls/checkpoint-msgpack未注册类型告警.md`。
