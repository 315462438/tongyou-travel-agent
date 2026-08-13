# Task Plan — Phase 27d：沙箱 /workspace 路径别名（修死循环 bug）

## 背景 / 现象

线上（2026-07-14 16:27 那轮，cid `c1269d20…`）用户绑定 pptx-generator 技能 + 打开沙箱执行，
问「商丘有什么好玩的地方，生成一个 ppt 文件给我」。agent 正常读了技能、查了高德、搜了网页，
然后在「写代码 → 执行」阶段陷入死循环，烧光 80 步撞 `GraphRecursionError`，前端表现为
「卡住」约 7 分钟后收到步数超限的降级回复。

Langfuse trace（191 条 observation）还原的循环：

1. `write_file("/workspace/slides/generate_ppt.py", …)` —— 文件工具写入成功；
2. `execute("cd /workspace && python3 slides/generate_ppt.py")` —— 报「文件不存在」；
3. `glob` / `read_file` 排查 —— 文件又「明明存在」；
4. 回到 1，换着花样重写重跑，直到 recursion limit。

## 根因

`DockerSandboxBackend` 里两套坐标系差了一层前缀：

- 文件工具走 `FilesystemBackend(root_dir=tmp_dir, virtual_mode=True)`：虚拟路径 `/` ↔ host
  `tmp_dir`。所以 `write_file("/workspace/slides/x")` 实际落在 host
  `tmp_dir/workspace/slides/x`。
- `execute()` 把 `tmp_dir` 挂载到容器的 `/workspace`（`-v tmp_dir:/workspace -w /workspace`）。
  于是那个文件在容器里位于 `/workspace/workspace/slides/x`，agent 在 `/workspace/slides/`
  下找不到。

而模型必然用 `/workspace/...` 写文件——因为 `execute` 的输出（`pwd` = `/workspace`）教会了它
容器里的路径长这样。文件工具和 shell 给出互相矛盾的反馈，模型没有任何办法从工具结果里
推断出真相，死循环是必然的。

（旁证：agent 一开始试过 `mkdir /slides`——虚拟根一致的路径——但容器根文件系统是
`--read-only`，在容器视角 `/slides` 不在挂载点内，同样失败。两条路都被堵死。）

## 方案

1. **路径别名（核心）**：`DockerSandboxBackend` 覆写 `_resolve_path`，把开头的
   `/workspace`（当作挂载点别名）剥掉再交给父类解析。这样 `/workspace/x` 与 `/x`
   在文件工具里指向同一个 host 文件，且都对应容器里的 `/workspace/x`——两套坐标系收敛。
   - 只剥**一层**前缀（`/workspace/workspace/x` → `/x` 是错的，应 → `/workspace/x` →
     host `tmp_dir/workspace/x`）。
   - 输出侧（`_to_virtual_path`，ls/glob 返回值）不动：改它会影响 deepagents
     SkillsMiddleware 对 `/main/`、`/user/` 前缀的解析，风险大于收益；输入侧别名
     已足以打破死循环（写进去的文件 execute 一定能看到）。
2. **system prompt 说明（双保险）**：沙箱开启时给主 agent 和 general-purpose subagent 的
   prompt 追加一段：文件工具根目录 `/` 即 execute 里的 `/workspace`，两种写法等价；
   容器其余路径只读、无网络。
3. **顺手修**：用户没有上传过技能时不再把 `/user/` 传进 `skills`，消除每轮
   `Cannot load skills from '/user/': path_not_found` 告警。`run_deep_research` 里
   把技能文件加载提前到一次，`_build_agent` 按有无 `/user/` 文件决定 skills 列表，
   `_invoke_with_cancel` 复用已加载的 dict（少一次 DB 查询）。

## 涉及模块

- `backend/app/tools/docker_sandbox.py` —— `_resolve_path` 别名
- `backend/app/agent/deep_research.py` —— SANDBOX_NOTE、`_build_agent(user_skills=…)`、
  `run_deep_research` / `_invoke_with_cancel` 装配
- `backend/tests/test_docker_sandbox.py`、`backend/tests/test_deep_research_skills.py`

## 验收标准

- `write("/workspace/x")` 与 `read("/x")` 指向同一文件（反之亦然）；`ls`/`glob` 能看到；
- `/workspace` 本身（如 `ls /workspace`）解析为根；嵌套 `workspace` 目录名不受影响；
- 路径穿越（`/workspace/../…`）仍被拒绝；
- 沙箱开启时主 agent / general-purpose 的 system prompt 含路径说明，未开启时不含；
- 无用户技能 → `skills` 不含 `/user/`；有 → 含；
- 全部单测通过（`pytest tests/ -q`）。
