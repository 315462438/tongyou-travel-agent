# Docker 沙箱 /workspace 路径错位把 agent 逼进死循环

## 现象

线上（2026-07-14 16:27，Phase 27c 沙箱执行 + 用户 pptx-generator 技能）：用户问
「商丘有什么好玩的地方，生成一个 ppt 文件给我」。agent 前半程一切正常（读技能、
高德查数据、必应搜索），进入写代码阶段后开始「卡住」，约 7 分钟后撞
`GraphRecursionError`（80 步上限），前端收到步数超限的降级回复。

Langfuse trace（191 条 observation）里是一个完美的死循环：

1. `write_file("/workspace/slides/generate_ppt.py", …)` → 成功；
2. `execute("cd /workspace && python3 slides/generate_ppt.py")` → 文件不存在；
3. `glob("**/generate_ppt.py")` / `read_file` → 文件明明存在；
4. 回到 1，换姿势重写重跑（find / ls / pwd 各种排查），直到步数烧光。

日志侧没有任何报错——每一次工具调用都是「成功」的，只是彼此矛盾。

## 原因

`DockerSandboxBackend` 的两套坐标系差了一层前缀：

- **文件工具**（ls/read/write/glob/grep）走 `FilesystemBackend(root_dir=tmp_dir,
  virtual_mode=True)`：虚拟路径 `/` ↔ host `tmp_dir`。
  `write_file("/workspace/slides/x")` → host `tmp_dir/workspace/slides/x`。
- **execute()** 把同一个 `tmp_dir` 挂载到容器 `/workspace`（`-v tmp_dir:/workspace
  -w /workspace`）。上面那个文件在容器里位于 `/workspace/workspace/slides/x`。

而模型**必然**用 `/workspace/...` 当文件路径——execute 的输出（`pwd` = `/workspace`）
教会了它容器路径长这样。它没有任何手段从工具反馈里发现「文件工具的 / 才是容器的
/workspace」：shell 说不存在、文件工具说存在，两边都"对"。

旁证：agent 一开始试过 `mkdir /slides`（虚拟根一致的路径），但容器根文件系统
`--read-only`，容器视角 `/slides` 不在挂载点内 → Read-only file system。两条路都死。

## 解决

Phase 27d，两层修复：

1. **backend 侧别名（根治）**：`DockerSandboxBackend._resolve_path` 把开头整段
   `/workspace` 前缀当根目录别名剥掉再交给父类。`/workspace/x` ≡ `/x`，两套坐标系
   收敛到容器视角。注意只剥一层（`/workspace/workspace/x` → host `tmp_dir/workspace/x`，
   与容器一致），且只匹配整段路径段（`/workspace2` 不受影响）。
   输出侧 `_to_virtual_path` 不动——改它会影响 deepagents SkillsMiddleware 对
   `/main/`、`/user/` 前缀的解析。
2. **prompt 侧说明（双保险）**：沙箱开启时给主 agent / general-purpose 追加
   `SANDBOX_NOTE`：文件工具根 `/` 即 execute 的 `/workspace`、容器其余路径只读、
   无网络（装不了依赖）。

## 教训

- 给 agent 同一份数据挂两个入口（文件工具 + shell）时，**路径坐标系必须完全一致**，
  否则模型会被互相矛盾的"成功"反馈锁死——这类死循环没有报错，比崩溃难定位得多。
- recursion limit 撞线时优先怀疑「工具反馈自相矛盾」，去 trace 里找同一个资源在
  不同工具下的不同答案，而不是先调大步数上限。

相关：`docs/pitfalls/CompositeBackend共享StateBackend多路由二次拼前缀.md`（同一批
路径拼接坑）、`docs/task_plans/task_plan-phase27d-沙箱workspace路径别名.md`。
