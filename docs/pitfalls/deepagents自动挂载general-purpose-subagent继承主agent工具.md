# 踩坑：deepagents 自动挂的 general-purpose subagent 会继承主 agent 的工具/技能，但不带资源纪律

排查"主子 agent 怎么分管 skill"时发现的一个默认行为，容易被忽略。

## 现象

`create_deep_agent(tools=main_tools, skills=[...], subagents=[api_researcher_spec])`
只显式声明了一个 subagent（`api-researcher`），但读 `deepagents/graph.py` 源码发现：
**只要 `subagents` 列表里没有名字恰好叫 `"general-purpose"` 的项，框架就会自动再插入
一个内置的 `general-purpose` subagent**，且：

```python
general_purpose_spec: SubAgent = {
    **GENERAL_PURPOSE_SUBAGENT,
    "model": model,
    "tools": _tools or [],          # ← 主 agent 自己的 tools 参数
    "middleware": gp_middleware,     # 内部会挂 SkillsMiddleware(sources=skills)
}
```

即这个自动挂载的 subagent **拿到跟主 agent 一模一样的工具（含浏览器）和技能列表**，
用的却是框架自带的通用 prompt，不包含项目自己写在主 agent 系统提示里的"资源纪律"
（本项目里是 `RESEARCH_SYSTEM` 那段"浏览器极贵，web_search 全程最多 3 次"的约束）。
也就是说：即使精心把"浏览器只在主 agent 谨慎用、其余数据收集走纯 API 子任务"这个分工
写清楚了，LLM 只要调用 `task(subagent_type="general-purpose", ...)`，这个子任务就能
直接摸浏览器，完全绕开了那条约束——不是"这个自动 subagent 有 bug"，是它默认不知道
你的项目定了这条纪律。

## 原因
`general-purpose` 是 deepagents 为了"给用户一个开箱即用的通用子任务能力"设计的默认值，
框架不可能替调用方猜出项目自己的资源使用规则，所以它的默认 prompt 只是通用的
"如何委派任务"指导，不含任何领域纪律。

## 解法
在 `subagents=[...]` 里**显式声明一个同名（`"general-purpose"`）的条目**，覆盖掉自动
挂载的默认版本（`graph.py` 的判断逻辑是 `not any(spec["name"] == "general-purpose"
for spec in inline_subagents)`，同名即视为"调用方已提供，不再自动加"）。这样可以精确
控制它的 `system_prompt`（把资源纪律也写进去）、`tools`、`skills`，而不是任其使用框架
默认值。详见 `app/agent/deep_research.py` 的 `GENERAL_PURPOSE_PROMPT` 和
`_build_agent` 里 `subagents` 列表第二项。

## 推广
用任何"框架会自动补一个默认 subagent/默认角色"的 agent 编排库时，先假设这个默认角色
**会继承你给主 agent 配的能力（工具/技能/权限），但不会继承你写在主 agent 提示词里的
业务纪律**——业务纪律是文本，只存在于你写的那段 prompt 里，不会随着工具继承自动传播。
凡是有能力继承但没有提示词继承的框架默认值，都值得显式声明一遍、把纪律写全，而不是
假设"反正它权限比我给的小"。
