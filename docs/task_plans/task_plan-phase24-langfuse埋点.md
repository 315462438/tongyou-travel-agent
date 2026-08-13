# Phase 24 — Langfuse 可观测埋点（每轮 prompt 传入 + 工具调用追踪）

## 目标

在 Langfuse 里能看到：
1. **每轮对话一条 trace**（按会话分组）：路由结果、用户输入、耗时；
2. **每次 LLM 调用的完整 prompt 传入/输出**（parse/classify/直答/攻略流式/研究循环）；
3. **工具调用情况**（研究模式：write_todos/web_search/task 子 agent/amap/fetch_url 的
   入参与返回；guide 流水线：搜索/读页步骤）。

## 方案（三层埋点，全部「无 key 即无操作」）

| 层 | 手段 | 覆盖 |
| --- | --- | --- |
| Turn 级 | `run_conversation_turn` 包 `turn_trace` span：session_id=cid（Langfuse 会话分组）、user_id、route、deep_reasoning | 每轮一条 trace |
| LLM 级 | `LLMClient` 条件用 `langfuse.openai.OpenAI` drop-in 包装（自动记 prompt/补全/用量，含流式） | 全部 DeepSeek 调用 |
| 工具级 | 研究模式：`agent.ainvoke(config.callbacks=[langfuse.langchain.CallbackHandler])`——LangGraph 全图（每轮模型请求 messages、每个工具调用、子 agent）自动成 trace 树；guide 流水线：`obs.span()` 手动包 search/fetch | 工具入参/返回 |

新模块 `app/observability.py`：`enabled()`（有开关且 key 齐才 True）、`turn_trace()`、
`span()`、`langchain_handler()`、`flush()`——**任何失败只 warn 不影响业务**。

配置：`langfuse_enabled`(False) / `langfuse_public_key` / `langfuse_secret_key` /
`langfuse_host`(https://cloud.langfuse.com)。key 由用户在 Langfuse（云版免费额度或
self-host）创建后填 .env。

## 验收
1. 默认（无 key）：行为零变化，全量单测通过；
2. 离线单测：enabled 判定、无 key 时 turn_trace/span/handler 全 no-op、LLMClient 回退裸 OpenAI；
3. 填 key 后（用户侧验证）：Langfuse 界面能看到 会话分组的 turn trace → 嵌套 LLM
   generation（含完整 messages）→ 研究模式的工具调用树。

## 风险
- langfuse SDK 与 langchain-core 1.x 兼容性 → 安装后跑全量单测验证；
- flush 时网络阻塞 → 只在 turn 结束 finally 里 flush（后台线程内，不挡请求）。
