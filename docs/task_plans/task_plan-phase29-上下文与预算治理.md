# Task Plan — Phase 29：深度研究上下文与预算治理（借鉴 Claude Code 源码机制）

## 背景

研究了 Claude Code 还原源码（`~/Desktop/claude code/Claude-Code`，仅借鉴机制不搬代码）后，
选定 4 个直击现有痛点的 P0 机制落地：

| 痛点 | 借鉴机制 | 来源 |
| --- | --- | --- |
| 抓的网页越多，后程每次 LLM 调用越肥越慢 | microcompaction：旧工具结果正文换占位符 | `src/services/compact/microCompact.ts` |
| 长网页正文一次性灌进上下文 | 大结果留存换引用 + 分页读回 | `src/utils/toolResultStorage.ts`、`FileReadTool` 的 offset 提示 |
| 600s 硬超时 kill 掉全作废；模型对预算无感知 | 预算感知 + 收敛 nudge（注入「别再收集、立即产出」） | `src/query/tokenBudget.ts` |
| 弱模型挥霍工具/子任务 | 工具描述「When NOT to use」负面清单；子任务纪律 | `src/tools/AgentTool/prompt.ts` |

前置发现：`deepagents.create_deep_agent` 原生支持 `middleware=`，且 langchain 自带
`ContextEditingMiddleware(edits=[ClearToolUsesEdit(...)])`——对齐 Anthropic
`clear_tool_uses_20250919` 行为，即 microcompaction 的现成实现，不需要自研。

## 方案

### A. 大正文留存换引用（`research_tools.py`）

- `build_tools` 闭包新增 `source_store: dict[str, str]`（`s1`、`s2`… 编号 → 全文），
  按轮存在内存里（一轮结束随闭包释放，不引入磁盘/DB 新故障面）。
- `fetch_url` / `open_page`：正文超过 `deep_research_source_preview_chars`(1500) 时只返回
  `[来源 s3 | host | 共 N 字] 前 1500 字…`，末尾附可执行提示
  `（继续读：read_source("s3", offset=1500)）`——借鉴 FileReadTool「越界错误必须带修复
  指引」的做法，让模型自我纠偏而不是拿一坨截断垃圾。
- 新工具 `read_source(source_id, offset=0)`：按 `deep_research_read_source_chunk`(3000)
  分页返回全文切片，主 agent 和 subagent 都给。读不存在的 id 返回可用 id 列表。
- `sources`（来源引用卡）口径不变。

### B. 旧工具结果清理（`deep_research.py::_build_agent`）

- 主 agent 与 general-purpose subagent 挂
  `ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=deep_research_context_trim_tokens,
  keep=deep_research_context_keep_tools, placeholder=…)])`：
  上下文超过 trigger（默认 30k token，approximate 计数）时，把**最旧的工具结果**内容
  换成占位符，保留最近 keep(5) 个完整结果。
- 占位符文案要可行动：`[旧工具结果已清理以节省上下文；如需重看该来源请用 read_source]`。
- api-researcher 不挂（单个子任务上下文短，清理无收益）。

### C. 预算感知 + 收敛 nudge（`research_tools.py`）

- `build_tools` 记录轮开始时刻；所有工具返回统一过 `_with_budget_note`：
  - 用时 > 60% 预算：结果末尾追加
    `⏳ 已用 X/Y 分钟（搜索 a/3 · 读页 b/3 · 抓取 c/10）`——借鉴 coordinator
    「子任务结果附带 usage」的思路，把消耗显式喂回模型；
  - 用时 > 80% 预算：追加强收敛指令
    `❗预算即将耗尽：立即停止收集与子任务，基于现有资料产出最终答案（缺的标「待核实」）`。
- 阈值为模块常量（0.6 / 0.8），预算即 `deep_research_timeout_s`。
- 不改 600s 硬超时本身：nudge 生效后大多数轮次会在软阈值内主动收敛。
- 使用预算感知和收敛远胜于模型超时强行截断，用于更用户更好的等待和回复体验。

### D. 工具负面清单 + 子任务纪律（prompt 层）

- `web_search` docstring 补「何时别用」：已知确切 URL 直接 fetch_url；天气/景点走高德；
  同一信息缺口不要换词反复搜。
- `fetch_url` 补：同一 URL 不要重复抓（先 read_source）。
- `RESEARCH_SYSTEM` 补一条子任务纪律（借鉴「Never delegate understanding」）：
  派子任务的 prompt 必须自带具体信息（明确的 URL 列表/城市/要核实的事实），
  禁止「根据你的发现去…」这类甩锅式委派；子任务结果回来后由你自己综合。

## 配置新增（`config.py`）

```
deep_research_source_preview_chars: int = 1500
deep_research_read_source_chunk: int = 3000
deep_research_context_trim_tokens: int = 30000
deep_research_context_keep_tools: int = 5
```

## 涉及模块

- `backend/app/agent/research_tools.py` —— A、C、D（工具层）
- `backend/app/agent/deep_research.py` —— B、D（agent 装配 + prompt）
- `backend/app/config.py` —— 配置
- `backend/tests/test_research_context.py`（新增）

## 验收标准

- fetch_url 长正文只返回预览 + 来源编号 + read_source 提示；read_source 能按 offset 翻页、
  未知 id 报可用列表；subagent 工具列表里也有 read_source；
- `_build_agent` 装配出的 middleware 含 ContextEditingMiddleware（且 trigger/keep 取自
  settings）；api-researcher 不挂；
- 超过 60%/80% 预算后工具返回带对应后缀（可用假时钟测）；未超不带；
- 工具 docstring 含「不要用」表述；RESEARCH_SYSTEM 含子任务纪律；
- 全部单测通过；线上回归：连续跑「商丘 PPT」与一个多城对比问题，观察
  ① 后程 LLM 调用耗时不再随轮次线性上涨（Langfuse trace 对比）② 无超时作废。

## 风险

- ClearToolUsesEdit 的 approximate 计数对中文偏差较大 → trigger 取保守值 30k，
  留 settings 可调；
- 预览 1500 字符可能让模型漏掉页面后部关键信息 → read_source 补偿 + 预览长度可调；
- DeepSeek 对结果尾部追加的 nudge 依从性未知 → 若不理会，后续升级为在 60% 处直接
  把剩余搜索/读页配额降为 0（代码级强制收敛）。
