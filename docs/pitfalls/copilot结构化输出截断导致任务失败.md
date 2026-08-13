# 踩坑：协同板 AI Copilot「上次 AI 任务失败」——结构化输出被截断

## 现象
协同行程板右侧 AI Copilot 输入大改需求（如在 7 天拉萨行程里发「15天，从武汉出发一个来回，
规划一下」），板头出现「⚠️ 上次 AI 任务失败」，且无任何可操作提示。

## 定位（服务器日志）
```
copilot failed for 1fcb3db393ef452298d3a1c71a75b6db
Traceback ... _run_copilot_task -> run_copilot -> llm.parse
ValueError: LLM 结构化输出解析失败（重试后仍不合法）: 1 validation error for CopilotResult
  ... v/json_invalid
```
`json_invalid` = 返回内容整段不是合法 JSON（不是字段级 schema 不符）。

## 原因
- `run_copilot` 用 `llm.parse(..., CopilotResult)`，parse 走 `response_format=json_object`，
  默认 `max_tokens=8000`，模型是 `deepseek-v4-pro`（带 reasoning_content 的推理模型）。
- Copilot 本是**增量编辑器**（COPILOT_SYSTEM 明确「一次提案不超过 8 条改动」），
  用户却发了一个**15 天整体重规划**请求。模型的思考链 + 大量改动输出一起吃掉
  8000 token 预算 → JSON 在中途被截断 → 不合法 → 重试一次仍失败 → 抛 ValueError。
- `_run_copilot_task` 的兜底只把 `ai_status="failed"`，前端显示「上次 AI 任务失败」，
  既不解释也不给出路。

## 解决（演进：从「劝退」改为「让它真能做」）

第一版曾让 copilot「大改就 changes 留空、劝用户回主对话」——回避了截断，但用户体验差
（缩短天数这种正常需求也被拒）。改为让它**尽力完成复杂请求**：

1. **两级模型策略**（`run_copilot`，主修复）：
   - ① 规划模型（v4-pro，质量好）+ 大 `max_tokens=16000` → 让思考链 + 结构化输出都放得下；
   - ② 仍抛异常（截断/超限/非法 JSON）→ 回退**快模型**（v4-flash，几乎不烧 reasoning 预算，
     8000 token 足以输出完整 JSON）。复杂请求成功率大幅提升。
2. **放开自我设限**：COPILOT_SYSTEM 改为「复杂/结构性请求也要尽力完成，列出必要增删改，
   reason≤20 字、保持 JSON 紧凑」；后台改动硬上限 8 → **40**（缩短天数本就需要多条增删）。
3. **优雅降级兜底**：两级都失败时，`_run_copilot_task` 才写一条 answered 建议（拆小指令 /
   回主对话重规划），`ai_status` 清空绝不留「失败」死状态；连降级消息都写不进才回落 failed。
4. **前端解锁**：failed 是终态，输入框只被「进行中」状态（seeding/copilot/reviewing）锁，
   不再被 failed 锁死——否则用户无法重发自愈（见 Trips.tsx `aiBusy`）。

## 经验
- 结构化 parse 用在**推理模型 + json 模式**时，reasoning 挤占 max_tokens，大输出易被截断。
  对策：给足 token 预算 + 回退不烧 reasoning 的快模型，而不是限制用户能问什么。
- 面向用户的后台任务失败必须**降级成可操作反馈**，且**不能把 UI 锁死在失败态**。
