# Task Plan — Phase 56：深度研究提速（流式 + 模型分层 + 并行子任务）

## 背景
深度研究（deepagents）整轮 ~6 分钟。读 ai-agent-book chapter5 后定位到三个可优化点：
1. **不流式**：`run_deep_research` 走 `ainvoke`，用户干等 6 分钟才见终稿（体感耗时大头）；
2. **整个循环跑 v4-pro（推理模型）**：每步长思考链 ×几十步（真实耗时大头）；
3. **子任务串行**：对比类问题一个个城市查（可并行）。

## 方案

### ① 终稿流式（体感提速，`deep_research_stream` 开关，出问题 .env 关即回退）
- `_invoke_streaming`：`agent.astream(stream_mode=["messages","values"])`——按 message id 跟踪
  「当前正在写的 AI 消息」，累积 token 增量写进 streaming 占位消息（≥1.2s 节流），
  `values` 事件留存最终 state。收尾用 `_extract_answer(最终 state)` 的干净终稿
  `_finalize_streaming_message` 定稿 + 挂 sources/skills/memories（与原逻辑共用）。
- 心跳改用后台协程（astream 期间模型思考/工具执行的静默期仍报「还在研究」）。
- 取消：`async for` 每次迭代查 `is_cancelled`。
- 安全阀：`deep_research_stream=False`（.env `DEEP_RESEARCH_STREAM=false`）即刻回退 `ainvoke` 老路，
  无需改代码——因为无法离线测真 astream，留这个开关兜底。

### ② 模型分层（真实提速，低风险）
- `api-researcher` 子任务（纯数据采集：高德/fetch_url，不需深推理）改用**快模型 v4-flash**
  （`SubAgent` 支持 `model` 字段）。主 agent 保持 v4-pro（规划/汇总要质量）。
- 配置 `model_research_sub`（空=回退 `model_classifier`）。

### ③ 并行子任务（对比类真实提速，prompt）
- RESEARCH_SYSTEM 子任务纪律加一条：独立子问题（多城对比等）**同一步并发派多个
  api-researcher**（LangGraph 会并行跑），而非串行等；保留「禁止为每个页面单独派」的反滥用。

## 验收
- 现有 deep_research 相关单测全过（结构未破坏）；新增装配层单测（api-researcher 带独立 model、
  stream 开关读取）。
- 全量 pytest 过 + 部署健康。
- 线上人工验证：研究报告边生成边出现（首字大幅提前）；对比题子任务并发；若流式异常，
  `DEEP_RESEARCH_STREAM=false` 重启即回退。
