# Phase 26 deepagents 技能体系 — 验收用例

自动化：`backend/tests/test_deep_research_skills.py`（全离线，不调用真实 LLM/浏览器）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_deep_research_skills.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 主 agent 3 个技能的 frontmatter | 用 deepagents 自带 `_list_skills` 解析，name 集合匹配、description 非空 | `test_main_skills_parse_with_deepagents` |
| 2 | subagent 2 个技能的 frontmatter | 同上 | `test_researcher_skills_parse_with_deepagents` |
| 3 | 磁盘 → 虚拟路径种子 | key 都在 `/main/`或`/researcher/` 下（Phase 27 去掉了外层 `/skills/` 包裹）、以 `SKILL.md` 结尾、内容含 frontmatter | `test_load_skill_files_virtual_paths` |
| 4 | 种子内容与磁盘一致 | 逐字节比对一个样本文件 | `test_load_skill_files_matches_disk_content` |
| 5 | 技能目录缺失时优雅降级 | 返回空 dict，不抛异常 | `test_load_skill_files_missing_dir` |
| 6 | `_build_agent` 装配 | `create_deep_agent(skills=["/main/","/user/"])`；`api-researcher` 带 `skills=["/researcher/"]`；显式声明的 `general-purpose` 带 `skills=["/main/","/user/"]` + 主 agent 同款 `tools` + 带资源纪律的 prompt（覆盖 deepagents 默认自动挂载版本，见 Phase 27b 踩坑） | `test_build_agent_wires_skills` |
| 7 | 每轮 invoke 携带技能种子 | `agent.ainvoke` 收到的 payload 里 `files` 含主/子技能虚拟路径 | `test_invoke_with_cancel_seeds_skill_files` |

## 关键不变式
- backend 维持默认 `StateBackend()`（不是 `FilesystemBackend`）——理由见
  `docs/pitfalls/deepagents技能库backend选型与virtual_mode陷阱.md`；本组测试里唯一
  用到 `FilesystemBackend` 的地方（用例 1/2）只是借它的 `_list_skills` 做离线解析校验，
  显式传 `virtual_mode=True`，不代表运行时 agent 用这个 backend。
- 资源纪律（浏览器只在主 agent、web_search ≤3 次）继续留在
  `RESEARCH_SYSTEM`/`API_RESEARCHER_PROMPT` 里，技能库只补充方法论细节，两者不冲突、
  不重复必须常驻可见的硬约束。
- **主/子 agent 的 `skills` 各管各的，不会互相继承**（唯一例外是 deepagents 自动挂载的
  `general-purpose` subagent，会继承主 agent 的 `tools`+`skills`——本项目显式声明同名
  条目覆盖它，把资源纪律也补进它的 prompt，见
  `docs/pitfalls/deepagents自动挂载general-purpose-subagent继承主agent工具.md`）。
- 回归：`test_deep_research.py` 全量（路由判定/SSRF/正文抽取/BrowserSession actor）不受影响。

## 回归
`cd backend && .venv/bin/python -m pytest tests/ -q` 全绿。
