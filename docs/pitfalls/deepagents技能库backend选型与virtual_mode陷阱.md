# 踩坑：deepagents Skills 该配哪个 backend——FilesystemBackend 的 virtual_mode 默认值陷阱

Phase 26 给深度研究 agent（`app/agent/deep_research.py`）接技能库
（[deepagents Skills 文档](https://docs.langchain.com/oss/python/deepagents/skills#statebackend)）
时，第一反应是「技能文件本来就在磁盘上，直接用 `FilesystemBackend(root_dir=skills目录)`
不是更省事，还不用手写种子代码」。排查后发现这个直觉是错的，记录下来避免以后重蹈。

## 现象/风险

`FilesystemBackend.__init__` 的 `virtual_mode` 参数**默认是 `False`**：

```python
def __init__(self, root_dir=None, virtual_mode: bool | None = None, ...):
    ...
    # virtual_mode=False（默认）时：
    # - 绝对路径按原样使用，直接绕过 root_dir
    # - 带 ".." 的相对路径可以逃出 root_dir
```

`create_deep_agent` 默认会给主 agent（以及每个 subagent）挂上 `FilesystemMiddleware`，
自带 `ls/read_file/write_file/edit_file/glob/grep` 工具。deepagents 官方 skills 例子里
用的虚拟路径都是 `/skills/xxx/...`（绝对路径），如果这时 backend 是
`virtual_mode=False`（默认）的 `FilesystemBackend`，这些**绝对路径会直接命中真实文件系统
根目录**，而不是 `root_dir` 里——不仅技能读不到（`/skills/main/` 在真实系统上通常不存在），
还意味着 agent 的 `write_file`/`edit_file` 工具此时对**真实磁盘**有效，攻击面从「只能碰
LangGraph 图状态」骤然放大到「LLM 能读写宿主机文件系统」。

即使显式补上 `virtual_mode=True` 把工具限制在 `root_dir` 内，还有第二个问题：deep research
的每一轮都是全新 `agent.ainvoke`（无 `checkpointer`），但如果 backend 换成
`FilesystemBackend`，`root_dir` 就是**磁盘上一个真实存在、所有并发用户共享的目录**——
agent 在这个目录里 `write_file` 的任何草稿/中间文件都会跨用户、跨重启持久化，
和"ephemeral、per-invoke、多用户互不干扰"的设计初衷正相反。

## 正确做法

**继续用 `create_deep_agent` 不传 `backend` 时的默认值 `StateBackend()`**（Phase 21
本来就是这样，未受影响）。技能正文依然以 `.md` 文件存在仓库里方便维护
（`backend/app/agent/skills/`），但由 `app/agent/skills_loader.py` 在每轮调用时读盘一次、
用 `deepagents.backends.utils.create_file_data()` 转成 `FileData`，通过
`agent.ainvoke({..., "files": load_skill_files()})` 当种子注入 ephemeral 状态——
这正是 LangChain 文档 StateBackend 一节给出的用法，不是退而求其次。

`skills=[...]` 参数本身和 backend 是哪种实现无关，只要 backend 里能 `ls`/`download_files`
到对应虚拟路径下的 `SKILL.md` 即可；`StateBackend` 天然满足（无 root_dir 概念、
无跨请求共享磁盘的问题）。

## 推广

给 deepagents（或任何基于虚拟文件系统抽象的 agent 框架）接文件型能力时，先确认：
1. 这批文件是「每次调用都该重新种、互不干扰」还是「本来就该多次调用间持久化/共享」——
   决定该用 ephemeral 状态型 backend 还是磁盘型 backend；
2. 如果确实要用磁盘型 backend，**默认参数是否已经把危险面圈住了**（这里是
   `virtual_mode` 默认 `False`），不要假设"传了 `root_dir` 就等于沙箱化"。
