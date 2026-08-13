# Phase 14 验收用例 — LangGraph 反思循环

> 自动化：`tests/test_graph.py`（路由 + 循环终止/研究分支/关闭反思，6 例）
> + `_is_running` 反思/海报回归（test_stuck_conversation.py）。131 passed 无回归。

## A. 自动化 ✅

| # | 覆盖 |
| --- | --- |
| A1 | 条件边：parse 路由、collect 有无来源、critique 三分支（finalize/research/rewrite，research 无查询词退化 rewrite） |
| A2 | 全图循环：critique 恒不满意 → 循环到 graph_max_guide_rounds 次强制终稿（初次+2轮=3次生成） |
| A3 | 反思关闭 → 单次生成即终稿 |
| A4 | research 分支：补搜再生成 |
| A5 | `_is_running`：终稿攻略后留有「补搜/重排」progress 不误判运行中；海报流式占位在终稿攻略后仍判运行中；海报终稿→完成 |

## B. 端到端（线上）

| # | 场景 | 结果 |
| --- | --- | --- |
| B1 | 普通攻略查询 | ✅ 走完整图；自检静默（快模型 v4-flash，~几秒），大多一次通过；长沙 126s / 武汉 233s（触发一轮重排） |
| B2 | running 状态 | ✅ 终稿后正确回落 false（修复反思 progress 尾随导致的永久 running bug） |
| B3 | 手账海报 | ✅ 抽取+补点均用快模型，贵阳 37s（原 60-90s）；生成中 running=true 前端实时接住，完成 false |
| B4 | 流式/记忆/配图 | 不回归 |

## 关键调优

- 自检用快模型 v4-flash + 务实提示（默认放行，只挑硬伤）→ 大多不循环，仅 +几秒。
- 海报抽取/补点改快模型；自检务实 → 37s。
- `_is_running` 改为「有流式 assistant→运行中；有终稿 assistant 且无流式→完成」，
  兼容反思尾随 progress 与海报占位。
