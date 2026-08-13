# Phase 26 — deepagents 技能体系（主/子 agent Skills，progressive disclosure）

## 背景 / 目标

Phase 21 的深度研究模式（`app/agent/deep_research.py`）把「怎么做研究」全部焊死在
`RESEARCH_SYSTEM`/`API_RESEARCHER_PROMPT` 两段静态 system prompt 里：对比类问题怎么
列表格、预算怎么测算、签证类问题怎么求证、高德工具怎么组合用、网页读不到正文时怎么
决策——都是长期有效的方法论，但混在系统提示里只会让提示越堆越长、且不可按需关闭/单独维护。

deepagents 0.6 提供官方 **Skills** 体系（`SkillsMiddleware`，遵循
[Agent Skills 规范](https://agentskills.io/specification) 与
[LangChain 文档](https://docs.langchain.com/oss/python/deepagents/skills#statebackend)）：
把这类方法论拆成独立 `SKILL.md`，agent 启动时只加载「名字+一句话描述」（progressive
disclosure），需要时自己 `read_file` 读全文，避免系统提示常驻膨胀，也让方法论可以独立于
代码增删/迭代。

目标：给 Phase 21 的主 agent + `api-researcher` subagent 各自接入一套技能库。

## 技术选型：StateBackend + 文件种子（不用 FilesystemBackend）

`create_deep_agent` 的 `backend` 参数不传时默认 `StateBackend()`（文件活在 LangGraph
图状态里，ephemeral，per-invoke）。Phase 21 目前正是这个默认值，且没有传 `checkpointer`
——每轮 `run_deep_research` 都是一次全新的 `agent.ainvoke`，天然不跨轮持久化、不跨用户共享。

**踩坑排查发现**：`FilesystemBackend(root_dir=...)` 默认 `virtual_mode=False`——绝对路径
会**绕过 `root_dir` 直接落到真实文件系统**（详见 `docs/pitfalls/`）。如果为了「技能文件
放磁盘更好维护」就把 backend 换成 `FilesystemBackend`，会带来两个真实回归：
1. 主 agent 自带的 `ls/read_file/write_file/edit_file/glob/grep` 工具从「图状态内」
   变成「能碰真实磁盘」，攻击面骤增；
2. 就算显式加 `virtual_mode=True` 把工具限制在 `root_dir` 内，这个 `root_dir` 也是**所有
   并发用户共享的同一个磁盘目录**——多用户并发 deep research 时任何一次 `write_file`
   都会互相污染、且重启不丢失（不是我们想要的 ephemeral 语义）。

结论：**继续用默认 `StateBackend()`**，技能正文仍然以 `.md` 文件形式存在仓库里（方便
版本管理/人工维护），但**运行时由 Python 读盘一次、转成 `create_file_data()` 的
`FileData`，通过 `agent.ainvoke(..., files=seed)` 在每轮调用时注入 ephemeral 状态**——
这正是 LangChain 文档 StateBackend 一节给出的用法。子 agent 与主 agent 共享同一个
`backend`/`files` 状态通道（`graph.py` 内验证过：subagent 中间件复用同一个 `backend`
变量），所以一次性把两套技能文件都种进 `files` 即可，主 agent 和 `api-researcher` 分别
用不同的 `skills=[...]` 路径前缀各取各的。

## 技能库设计

仓库里的真实目录（开发者维护，Git 版本化）：

```
backend/app/agent/skills/
├── main/                          # 主 agent（浏览器 + 决策）
│   ├── trip-comparison/SKILL.md       # 多目的地对比方法论
│   ├── budget-estimation/SKILL.md     # 预算测算方法论
│   └── visa-policy-research/SKILL.md  # 签证/政策类问题求证方法论
└── researcher/                    # api-researcher subagent（纯 API）
    ├── amap-data-lookup/SKILL.md      # 高德工具组合使用技巧
    └── web-source-triage/SKILL.md     # fetch_url 抓取正文的取舍/降级判断
```

运行时虚拟路径：磁盘 `skills/main/...` → 状态内 `/skills/main/...`；
`skills/researcher/...` → `/skills/researcher/...`。
`create_deep_agent(..., skills=["/skills/main/"], subagents=[{..., "skills":
["/skills/researcher/"]}])`。

技能内容边界：**只放「怎么做得更好」的方法论/技巧，不重复系统提示里的硬约束**
（浏览器只在主 agent、web_search ≤3 次这类资源纪律必须常驻可见，不能变成「翻到才
看到」的选读内容，继续留在 `RESEARCH_SYSTEM`/`API_RESEARCHER_PROMPT` 里）。

## 涉及模块

- 新增 `backend/app/agent/skills/` 五个 `SKILL.md`（纯文档，无需 Python 逻辑）
- 新增 `backend/app/agent/skills_loader.py`：`load_skill_files() -> dict[str, FileData]`
  按 `functools.lru_cache` 缓存一次，扫描磁盘技能目录，读不到/解析失败只记 warning
  并跳过，不影响其余技能加载或整轮研究失败
- `backend/app/agent/deep_research.py`：
  - `_build_agent` 的 `create_deep_agent(...)` 加 `skills=["/skills/main/"]`；
    subagent 配置字典加 `"skills": ["/skills/researcher/"]`
  - `_invoke_with_cancel` 的 `agent.ainvoke({...})` 加 `"files": load_skill_files()`
  - `RESEARCH_SYSTEM`/`API_RESEARCHER_PROMPT` 瘦身：移出已被技能覆盖的方法论细节，
    保留资源纪律硬约束
- `docs/pitfalls/`：记录 FilesystemBackend virtual_mode 默认值踩坑
- `backend/tests/test_deep_research_skills.py`：离线单测

## 验收标准

1. 五个 `SKILL.md` 都能通过 deepagents 自带的 frontmatter 解析（`name` 匹配目录名、
   `description` 非空）——用 deepagents 的 `_parse_skill_metadata`（或等价逻辑）离线验证。
2. `load_skill_files()` 返回的 dict key 是 `/skills/main/...`/`/skills/researcher/...`
   虚拟路径，value 是合法 `FileData`（含 `content`/`encoding`）。
3. `_build_agent` 装配出的 `create_deep_agent` 调用里能看到 `skills=["/skills/main/"]`
   与 subagent 的 `skills=["/skills/researcher/"]`（mock `create_deep_agent` 断言调用参数）。
4. 磁盘技能目录被删空/不存在时 `load_skill_files()` 不抛异常、返回空 dict（优雅降级）。
5. 现有 `test_deep_research.py` 全量回归通过（路由判定、SSRF、正文抽取等不受影响）。
6. 全量 `pytest` 通过。
