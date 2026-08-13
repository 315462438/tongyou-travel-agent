# Phase 21 深度研究模式（deepagents）— 验收用例

自动化：`backend/tests/test_deep_research.py`（20 例，全离线）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_deep_research.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 开关关闭 | 不路由、不调分类 LLM | `test_decide_research_disabled` |
| 2 | 无关键词命中 | 零成本门直接走普通流水线 | `test_decide_research_keyword_gate` |
| 3 | 关键词命中 + LLM 确认 | research→走研究模式；normal→回落 | `test_decide_research_classify_confirms` |
| 4 | 分类 LLM 挂了 | 回落普通流水线（不影响主链路） | `..._classify_failure_falls_back` |
| 5 | fetch_url SSRF | localhost/内网 IP 拒绝，公网/域名放行 | `test_private_host_guard` |
| 6 | HTML 正文抽取 | 去 script/style/标签、截断 | `test_html_to_text_*` |
| 7 | 答案提取 | 取最后一条 ai 消息，支持分段 content | `test_extract_answer_*` |
| 8 | 来源去重 | 按 URL 去重、截 10 | `test_dedupe_sources` |
| 9 | **MCP 同 task 生命周期**（线上踩坑回归） | enter/call/exit 全在 worker 一个 task | `test_browser_session_single_task_lifecycle` |
| 10 | 浏览器启动失败 | 调用方拿到异常不挂死、close 幂等 | `test_browser_session_startup_failure_propagates` |

## Spike（成败点验证 ✅）
DeepSeek(v4-pro) 驱动 deepagents 最小任务：4 次工具调用全部正确（2 城 × 天气/酒店），
8s 完成并产出对比表。deepagents 0.6.12 安装未动 langgraph 1.2.8 / checkpoint-postgres，
现有 166 单测全绿。

## 本地 E2E（✅）
「厦门 vs 青岛 3天亲子游对比」：路由进研究模式（progress 可见 🧭/🔎），
第一版 prompt 超时（见 pitfalls 资源纪律），修正后产出 3292 字结构化报告
（一句话结论 + 天气/景点/花费对比表 + 10 来源，天气来自高德=subagent 生效）。

## 线上 E2E（✅）
「预算5000 国庆3天 成都 vs 西安哪个划算」：2827 字报告、对比表带真实门票价格、
10 来源；且正确标注「高德返回的是7月实时天气，国庆会转凉」（不瞎编）。
第一次线上跑触发 MCP task-affinity 崩溃 + 池槽位泄漏 → actor 模式修复后通过
（见 docs/pitfalls/deepagents工具任务亲和与资源纪律.md）。

## 关键不变式
- 浏览器只在**主 agent**（BrowserSession actor，池语义不破坏）；subagent 只有纯 API 工具。
- 普通攻略请求零影响：关键词门不命中不调分类；分类失败回落主流水线；全量 186 单测通过。
- 停止按钮：工具内 cancel.check + `_invoke_with_cancel` 看护双保险；整轮 600s 超时兜底。
