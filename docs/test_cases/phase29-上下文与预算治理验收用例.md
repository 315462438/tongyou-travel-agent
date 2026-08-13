# Phase 29 验收用例 — 上下文与预算治理

对应自动化测试：`backend/tests/test_research_context.py`（11 例，全离线）。
机制来源与设计见 `docs/task_plans/task_plan-phase29-上下文与预算治理.md`。

## A. 留存换引用 + read_source

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A1 | 长正文换引用 | fetch 一个 >1500 字的页面 | 返回 `[来源 s1 …]` 预览 + `read_source("s1", offset=…)` 提示，长度 ≈ 预览上限 |
| A2 | 短正文原样返回 | fetch 一个短页面 | 不带来源编号、不带 read_source 提示 |
| A3 | 翻页 | read_source("s1") → offset 翻页 → 超末尾 | 每页带「第 X-Y 字/共 N 字」+ 下一页提示；末页标「已到末尾」；超界给明确报错 |
| A4 | 未知编号 | read_source("s99") | 报错并列出可用编号 |
| A5 | 双端可用 | 检查 main_tools/sub_tools | 两边都含 read_source |

## B. 旧工具结果清理（ContextEditingMiddleware）

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| B1 | 装配 | `_build_agent` 捕获 kwargs | 主 agent 与 general-purpose 各挂一个 ContextEditingMiddleware；api-researcher 不挂 |
| B2 | 参数来自 settings | 改 trim_tokens/keep_tools 再构建 | ClearToolUsesEdit 的 trigger/keep 跟随变化；占位符含 read_source（可行动） |
| B3 | 真实构建 | 不 mock deepagents 构建一次 | 返回 CompiledStateGraph，不报错（冒烟） |

## C. 预算 nudge

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| C1 | 早期无噪音 | 轮初调工具 | 结果不带 ⏳ |
| C2 | 60% 报用量 | 假时钟拨到 65% 预算 | 结果尾部带「⏳ 已用 X/Y 分钟（搜索/读页/抓取 用量）」，不带 ❗ |
| C3 | 80% 强收敛 | 拨到 90% | 额外带「❗预算即将耗尽：立即停止收集…」 |

## D. prompt 纪律

| # | 用例 | 预期 |
| --- | --- | --- |
| D1 | RESEARCH_SYSTEM 含「子任务纪律」段，点名禁止「根据你的发现…」句式 |
| D2 | 工具 docstring 含「不要用于」负面清单（web_search/fetch_url/open_page/read_source） |

## E. 线上手工回归（部署后）

1. 重跑「商丘 PPT」+ 一个多城对比问题，在 Langfuse 对比 Phase 28 的 trace：
   - 后程（第 5 分钟后）单次 LLM 调用耗时不应随轮次继续线性上涨（上下文被清理/预览化）；
   - 抓取类工具结果长度应明显变短（预览 1500 字 + 编号）。
2. 观察是否出现 read_source 调用——有即说明预览+翻页链路真实被模型使用。
3. 超过 6 分钟的轮次，工具结果里应能看到 ⏳ 预算报告；整轮不应再出现超时作废。

## 运行

```bash
cd backend && .venv/bin/python -m pytest tests/test_research_context.py -q
```
