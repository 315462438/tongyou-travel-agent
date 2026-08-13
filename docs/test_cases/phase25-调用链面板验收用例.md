# Phase 25 平台内调用链面板 — 验收用例

自动化：`backend/tests/test_trace_api.py`（5 例，全离线）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_trace_api.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 按 metadata.turn_id 匹配 trace | 命中该轮；匹配不到/空 turn_id 回退最新；空列表 None | `test_pick_trace_by_turn_id` |
| 2 | metadata 是 JSON 字符串 | 照样解析匹配 | `test_pick_trace_metadata_as_string` |
| 3 | 观测化简 | 按 startTime 排序、durMs 计算、父子/usage 保留 | `test_simplify_sorts_and_computes_duration` |
| 4 | 载荷截断 | >4000 字符截断加标记；非字符串 JSON 化；None→"" | `test_clip_truncates` |
| 5 | 时间缺失/非法 | durMs=None 不抛 | `test_dur_ms_handles_missing` |

## 线上 E2E（✅）

- 接口：`GET /api/chat/{cid}/trace?turn_id=`（登录+归属校验；Langfuse pk/sk 只在服务端）
  → enabled=true、trace(route=direct, latency)、4 节点（SPAN + 3×GENERATION，
  含模型/耗时/完整输入片段）。
- UI（生产实测截图）：助手消息下「🔗 调用链」按钮 → 右侧抽屉滑出：route 徽章 + 总耗时、
  节点树（类型分色徽章/模型/耗时），点节点展开完整 输入/输出/tokens；再点按钮或 ✕ 关闭。
- 降级：未启用埋点 → 抽屉提示「未启用调用链埋点」；该轮无 trace（早于上线）→ 友好提示。

## 关键设计
- turn_id = 该助手消息之前最近一条 user 消息 id，与 turn_trace 写入的 metadata.turn_id 对齐；
  匹配不到回退该会话最新 trace。
- input/output 服务端截断 ≤4000 字符防大包；节点树深度按 parentObservationId 缩进。
