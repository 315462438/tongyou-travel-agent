# Task Plan — Phase 14：迁移 LangGraph + 反思循环（自主优化 agent）

> 创建：2026-07-07　状态：已完成并上线（验收见 docs/test_cases/phase14-验收用例.md）

## 需求

从固定编排升级为带自我反思的自主 agent：攻略生成后 agent 自检
（细节是否缺失、路线是否合理、是否覆盖用户全部要求），不满意就循环优化；
手账海报同理（点位是否详细/够多、吃住行打卡是否齐全）。

## 决策（用户确认）

- 循环深度：**最多 2 轮**（攻略）/ 1-2 轮（海报），上限可配。
- 不满意策略：**智能区分**——「缺具体细节」→ 针对性补搜一轮；
  「路线不合理/结构问题」→ 用现有资料重写，不白搜。

## 方案：包裹现有逻辑，不重写

现有采集/生成/海报逻辑（踩坑踩出来的）全保留，用 LangGraph 包成节点，
上面加 critique/research 反思节点。流式与消息表进度机制不变（节点内部照旧写库）。

### 攻略图（`app/agent/graph.py` + `nodes.py` + `graph_state.py`）

```
START → parse
parse → 条件路由：chat / clarify / apologize / plan
  chat|clarify|apologize → END（短路，与现状一致）
plan → collect（复用 _collect_amap/_collect_from_routed_site/_search_and_collect）
collect → 有来源? generate : apologize
generate（复用流式生成，msg_id 首次建、循环复用同一条消息）→ critique
critique（LLM 判定，rounds++）→ 条件：
  ok 或 rounds≥max → finalize
  action=research → research（针对 critique.search_queries 补搜）→ generate
  action=rewrite  → generate（把 critique.issues 作为反馈注入 prompt）
finalize（记忆提炼 + 终稿 meta）→ END
```

- `GuideCritique`（schema）：`ok / action(research|rewrite|none) / issues[] / search_queries[]`
- critique 系统提示：查细节充分度、路线地理就近/时间合理/合节奏、覆盖用户全部要求。

### 海报图（`app/agent/poster.py` 扩展）

```
extract → enrich → critique_poster → 条件：ok 或 rounds≥max → build : extract_more → enrich
```
- `PosterCritique`：够不够（每天≥3 点、含餐馆+打卡）、每点有无 note；不足给
  `add_hints`（要补的点/类型），extract_more 据此再抽。

### 配置

`reflection_enabled=True`、`graph_max_guide_rounds=2`、`graph_max_poster_rounds=2`。
关掉 reflection 时退化为「生成一次即终稿」（等价现状）。

### 兼容

- `run_conversation_turn` 入口不变（chat_api 无需改）；内部改为构建 state → `graph.ainvoke`。
- 流式：generate 节点内部照旧流式写库；循环时复用同一 streaming 消息、progress 叙述
  「正在自检…」「发现可优化：X，正在重排…」。
- 依赖：+ `langgraph`（纯编排层，LLM 仍走 DeepSeek `get_llm()`，不引 LangChain）。

## 涉及模块

新增：`schemas/critique_schema.py`、`agent/graph_state.py`、`agent/nodes.py`、
`agent/graph.py`。改：`orchestrator.py`（抽出 `_generate_once` 供节点复用、
`run_conversation_turn` 改为跑图）、`poster.py`（加 critique 循环）、
`config.py`、`requirements.txt`。

## 验收标准

1. 普通查询走完整图，结果与现状相当（无回归）；日志/进度可见 critique 环节。
2. 造一个「细节不足」的场景 → 触发 research 补搜再生成；「路线绕路」→ 触发 rewrite。
3. 循环不超过上限；reflection_enabled=False 时退化为单次生成。
4. 海报点位过少时触发 extract_more 补点。
5. 流式、记忆、配图、海报等既有功能不回归；存量测试全过 + 新增图/critique 单测。
