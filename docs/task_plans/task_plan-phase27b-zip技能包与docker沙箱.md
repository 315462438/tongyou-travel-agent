# Phase 27b — zip 多文件技能包 / Docker 轻量沙箱

> **上线实测更新**：临时打开 `DOCKER_SANDBOX_ENABLED` 在生产环境跑了一轮真实深度研究
> 请求验证 general-purpose subagent 是否被调用、沙箱是否启动，过程中发现最初的
> `CompositeBackend(default=沙箱, routes={"/main/": state, ...})` 装配方式（三个路由
> 共享同一个 `StateBackend` 实例）会导致 agent 的 `glob`/`ls` 返回二次拼前缀的错乱路径
> （如 `/main/main/xxx/SKILL.md`），污染了 `meta.skills_used`。已改成沙箱开启时完全不用
> `CompositeBackend`——技能文件轮初直接物理写进沙箱自己的 per-turn 临时目录，`backend`
> 是单一的 `DockerSandboxBackend`。详见
> `docs/pitfalls/CompositeBackend共享StateBackend多路由二次拼前缀.md`。下面第 2 节
> "Docker 轻量沙箱"里的 `CompositeBackend` 描述是**最初方案**，当前实现已按上述方式修正。

## 背景 / 目标

Phase 27 的 Cube Sandbox 因服务器硬件不达标被移除（见
`task_plan-phase27-用户技能上传与cube沙箱执行.md` 开头的更新说明）。用户后续追问两点：

1. 技能上传当时只支持单文本框粘贴，能不能像官方 Skills 规范那样支持
   `SKILL.md + 参考文件/脚本` 的多文件打包上传？
2. 有没有小一点、这台机器扛得住的沙箱可以给 agent 真正的代码执行能力？

## 结论（已跟用户逐条确认）

| 问题 | 结论 |
| --- | --- |
| zip 多文件上传 | **加**——存储/读取多文件本来就不需要沙箱（`StateBackend` 直接能存），只有"执行"才需要 |
| 轻量沙箱 | **Docker**（服务器已装，同机 Langfuse 也用它，无需新守护进程/内核/重启）；明确告知用户这是共享宿主内核的隔离（namespace/cgroup），不是 Cube Sandbox 那种 VM 级边界 |

## 方案

### 1. zip 多文件技能包
- `travel_user_skill` 加 `files_json` 列（JSON `{相对路径: 文本内容}`，含 `SKILL.md` 自身；
  旧的纯文本单文件行留空，读取时回退成 `{"SKILL.md": content}`）。
- `app/agent/skill_validation.py::parse_and_validate_zip`：解析 zip、校验：
  - 文件数/解压后总大小上限（`user_skill_max_zip_files`/`user_skill_max_zip_bytes`）；
  - **zip-slip 防护**：拒绝绝对路径和 `..` 逃逸——所有用户技能文件最终会拼成
    `/user/{name}/{相对路径}` 虚拟路径跟内置技能共用同一个 `files` 种子 dict，
    路径逃逸能拼出 `/main/xxx/SKILL.md` 这样的虚拟路径，冒充/篡改内置技能；
  - 只收 UTF-8 文本（暂不支持二进制，脚本文件能被读但不会被执行，没有存二进制的必要）；
  - 兼容"压缩了外层文件夹"的常见习惯：根目录没有 SKILL.md 但唯一顶层目录里有就剥掉前缀；
  - 复用已有的 `parse_and_validate()` 校验 SKILL.md 本身。
- `POST /api/skills/upload`（multipart 文件上传）+ 保留原 `POST /api/skills`（纯文本），
  两条路径共享 `_upsert_skill()`，统一写 `content`（SKILL.md 正文，向后兼容）+ `files_json`。
- `skills_loader._load_user_skill_files` 按 `files_json` 展开成多个虚拟路径。
- 前端 `SkillPanel` 加"📦 上传 zip"按钮（文件选择 + FormData 上传），列表显示文件数。

### 2. Docker 轻量沙箱
- `app/tools/docker_sandbox.py::DockerSandboxBackend(FilesystemBackend, SandboxBackendProtocol)`：
  - 文件操作（ls/read/write/grep/glob）由 `FilesystemBackend` 直接在一个 per-turn 的 host
    临时目录上做（`virtual_mode=True` 限定，不逃逸真实文件系统——同一个 Phase 26 就踩过的坑）；
  - `execute()` 才真正起一个一次性、高度限制的容器：`--rm --network=none --read-only
    --cap-drop=ALL --security-opt=no-new-privileges --user nobody --pids-limit=64
    --memory=256m --memory-swap=256m --cpus=0.5`，把临时目录挂进去当 `/workspace`；
  - 超时（`subprocess.TimeoutExpired`）显式 `docker kill`，不能只杀本地 CLI 客户端进程
    （否则容器在后台继续跑，见踩坑文档）；
  - 非 root 容器用户要能写挂载目录，临时目录创建后 `chmod 0o777`（per-turn 短生命周期，
    可以接受这个放宽）。
- `_build_backend()` 沿用 Phase 27 的 `CompositeBackend` 思路：`default` 挂
  `DockerSandboxBackend`（execute 不可路径路由，永远走 default），`/main/｜/researcher/｜/user/`
  路由回同一个 `StateBackend()`（技能读取继续免费走图状态，不因为装了沙箱就搭上容器开销）。
- 轮末（`run_deep_research` 的 `finally`）删掉这个临时目录。
- 默认 `docker_sandbox_enabled=False`——这依然是共享内核隔离，安全边界弱于最初设想的
  Cube Sandbox，开不开是用户的选择，不能默认打开。

## 涉及模块
`app/db/models.py`（`files_json` 列）、`app/db/migrate.py`（ALTER 迁移）、
`app/agent/skill_validation.py`（zip 解析）、`app/api/skill_api.py`（`/upload` 端点）、
`app/agent/skills_loader.py`（多文件展开）、`app/tools/docker_sandbox.py`（新文件）、
`app/agent/deep_research.py`（`_build_backend`/`_build_agent` 恢复 backend 参数）、
`requirements.txt`（加 `python-multipart`，`UploadFile` 需要）、前端 `SkillPanel`。

## 验收标准
1. zip 上传：合法包成功、缺 SKILL.md/路径逃逸/非 UTF-8/超限都被拒绝并有清晰错误。
2. 同名覆盖时整体替换 `files`（不是合并），纯文本上传和 zip 上传互相覆盖行为一致。
3. `skills_loader` 正确把多文件技能展开成多个 `/user/{name}/{relpath}` 虚拟路径。
4. `docker_sandbox_enabled=False`（默认）时行为与之前完全一致。
5. `docker_sandbox_enabled=True`：`execute()` 成功/失败/超时三条路径都正确映射、不抛异常；
   超时场景真的调用了 `docker kill`；文件操作确认被 `virtual_mode=True` 限定在临时目录内；
   轮末临时目录被删除。
6. 全量 `pytest` 通过；前端 `tsc --noEmit` + `npm run build` 通过。
