# Phase 21 — 深度研究模式（deepagents 试点，主 agent 持浏览器 / subagent 纯 API）

## 背景 / 目标

现有 LangGraph 流水线（parse→collect→generate→critique）是「单目的地→固定产出」形态，
接不住开放式需求：
- 解析丢信息：`Preference.destination` 单值，多城市对比一进 parse 就被压扁；
- 产出焊死：只有 ITINERARY/HOTEL 两个模子，吐不出对比矩阵/成本测算/签证材料清单；
- 搜索深度固定：一轮查询 + critique ≤2 轮补搜，不能按中间发现自适应下钻；
- 无跨来源计算步骤（多来源数字聚合算账）。

目标：用 LangChain **deepagents**（LangGraph 之上的 agent harness：write_todos 规划 +
虚拟文件系统 + subagents）加一个**深度研究模式**，处理对比/决策/政策类开放问题。
**风险隔离**：独立入口，不碰主攻略链路。

## 资源分配原则（用户拍板）

| 资源 | 归属 | 原因 |
| --- | --- | --- |
| 浏览器（必应搜索/开页面） | **主 agent** | 串行有状态昂贵（池 busy=每用户串行、登录态） |
| 高德 API（天气/POI/地理编码） | **subagent** | httpx 无状态，可并行 |
| fetch_url（纯 HTTP 抓页面） | **subagent** | 主 agent 搜到 URL → 派 subagent 纯 HTTP 读；JS 重/登录墙失败再由主 agent 浏览器兜底 |

## 方案

### 成败点前置验证（先做）
DeepSeek 在 deepagents ReAct 循环里的 tool-calling 质量 + deepagents 与现有
langgraph/checkpoint-postgres 版本兼容性。本地最小 demo 通过才继续；不通过则记录并止损。

### 新模块
- `app/agent/research_tools.py`：工具集
  - 主 agent：`web_search(query)`（复用 BrowserTool 必应，整轮共享一个 ChromeMCP 会话）、
    `open_page(url)`（浏览器兜底读页）
  - subagent：`amap_weather(city)` `amap_poi(keyword, city)` `fetch_url(url)`
    （httpx，SSRF 防护：仅 http/https、禁内网 IP、超时+大小上限、HTML→正文摘录）
  - 所有工具内打 `cancel.check(cid)`（停止按钮可用）+ 写 progress（前端可见进度）
- `app/agent/deep_research.py`：`run_deep_research(cid, user_text, user_id)`
  - `create_deep_agent(model=DeepSeek, tools=[主agent工具], subagents=[api-researcher])`
  - system_prompt：旅行研究员人设 + 资源分工说明 + 输出带来源引用的 Markdown 报告
  - `recursion_limit` 封顶 + 总时长 `asyncio.wait_for`（8min）兜底
  - 终稿写 `travel_message`（assistant，meta.sources 尽量回填）
- 路由：意图判定加 `research`（LLM 分类 + 关键词兜底：对比/比较/哪个更/帮我选/签证/预算够不够…），
  命中且 `deep_research_enabled` 时走 `run_deep_research`，否则回落原流水线。

### 配置
`deep_research_enabled: bool = False`（默认关，服务器 .env 开）、
`deep_research_timeout_s: int = 480`、`deep_research_recursion: int = 40`。

## 验收标准
1. 本地 spike：DeepSeek 驱动 deepagents 完成一次带工具调用的最小任务。
2. 对比类问题（如「厦门 vs 青岛 3 天哪个更适合亲子」）走研究模式，产出对比结构报告，
   过程中 progress 可见、停止按钮生效。
3. subagent 只用纯 API 工具（日志可证），浏览器操作全部在主 agent（池语义不破坏）。
4. 普通攻略请求不受影响（回归：现有全量单测通过）。
5. 离线单测：research 意图判定、fetch_url SSRF 防护/正文抽取、工具注册装配（mock）。
6. 服务器部署 + 线上 E2E 一次。

## 风险
- deepagents 依赖可能升级 langgraph → 跑全量单测验证现有图不受影响；冲突则钉版本或止损。
- DeepSeek tool-calling 循环质量未知 → spike 先行。
- 研究模式耗时长 → 明确 progress 反馈 + 超时兜底 + 可停止。
