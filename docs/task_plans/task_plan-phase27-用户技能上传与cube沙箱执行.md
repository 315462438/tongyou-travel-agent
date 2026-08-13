# Phase 27 — 用户上传技能 / 技能发现追踪 / Cube Sandbox 执行

> **后续更新**：real 联调前先排查了服务器硬件（`ssh` 只读诊断），发现跟 Cube Sandbox
> 官方最低要求差距很大——7.4GB 总内存（仅 3.3GB 可用）< 官方最低 8GB；2 核 < 官方最低 4 核；
> 这台云主机没有暴露 `/dev/kvm`/`vmx` 硬件虚拟化，只能走需要装 PVM 内核模块 + **重启**
> 的路径；`/data/cubelet` 要求 XFS 且 ≥50GB，现有磁盘可用空间（37GB，ext4）也不够。
> 在这台承载线上服务的机器上装等于拿生产机赌一次换内核重启，风险和收益不成比例。
> 用户拍板**不真部署、移除 Cube Sandbox 这部分代码**（`app/tools/cube_sandbox.py`、
> config 里的 `cube_sandbox_*`、`deep_research.py` 的 `_build_backend`/`_close_backend`、
> `requirements.txt` 的 `e2b`、对应测试均已删除）。下面第 4 节的方案描述保留作为
> 「当时怎么设计的」历史记录，**当前代码库里已不存在这部分**；用户上传技能 + 技能发现追踪
> 两块不受影响，正常保留。踩坑记录见
> `docs/pitfalls/CubeSandbox-e2b-execute契约与懒加载.md`（BaseSandbox/CompositeBackend
> 的通用契约知识，对以后接别的沙箱仍有参考价值）。

## 背景 / 目标

Phase 26 给深度研究 agent 接了一套开发者维护的内置技能库（`backend/app/agent/skills/`）。
用户提出三个延伸需求（已逐一确认方案，见下）：

1. **用户自己上传技能**：让用户能补充自己的方法论/习惯（私有，只在自己的深度研究里生效）。
2. **技能发现追踪**：想知道每轮到底读了哪些技能。
3. **Cube Sandbox 执行**：给 agent 一个真正能跑代码的沙箱（用户上传的技能可能带脚本），
   而不是现在 `execute` 工具在非 sandbox backend 下的"返回错误"占位状态。

## 已确认的方案（AskUserQuestion 逐条拍板）

| 问题 | 结论 |
| --- | --- |
| 技能发现追踪用什么 | **复用现有自托管 Langfuse**（Phase 24 已给整条调用链埋点，不引入新 vendor） |
| Cube sandbox 账号 | 改用自建 **Cube Sandbox**（`https://cubesandbox.com/guide/quickstart.html`），E2B 兼容 REST API，自托管，不需要 LangSmith |
| 用户上传技能归属 | **仅本人可见**（每个用户上传的技能只在自己的深度研究会话里生效，无审核/共享） |
| 排期 | 三块一起做 |

## 方案

### 1. 虚拟路径改名（为 Cube Sandbox 铺路，向后兼容内部实现）
Phase 26 用的是 `/skills/main/`、`/skills/researcher/` 前缀。为了让"技能走 StateBackend、
`execute()` 走沙箱"可以用同一个 `backend` 参数装配（`CompositeBackend` 按前缀路由），把
虚拟路径**去掉外层 `/skills/` 包裹**，直接用 `/main/`、`/researcher/`、`/user/`：
- 不装 Cube Sandbox 时：`backend` 仍是 `create_deep_agent` 默认的 `StateBackend()`，
  这几个前缀只是普通虚拟路径，行为和 Phase 26 完全一致；
- 装了 Cube Sandbox 时：`backend=CompositeBackend(default=CubeSandboxBackend(...),
  routes={"/main/": state, "/researcher/": state, "/user/": state})`（`state` 是同一个
  `StateBackend()` 实例）——技能读取仍然免费走图状态，只有 `execute()`（"不可按路径路由，
  永远走 default"，见 `CompositeBackend.execute()` 源码）才落到真沙箱。

### 2. 用户上传技能
- **DB**：新表 `TravelUserSkill`（`app/db/models.py`）：`id, user_id, name, description,
  content, created_at, updated_at`；`(user_id, name)` 唯一索引（同名 = 覆盖更新，
  同 Phase 17 记忆表按 key upsert 的思路）。`content` 是完整 `SKILL.md` 文本
  （含 frontmatter），v1 不支持多文件技能包。`Base.metadata.create_all` 自动建表，
  不需要手工 ALTER（全新表）。
- **校验**：上传时用 deepagents 自带的 frontmatter 解析
  （`deepagents.middleware.skills._parse_skill_metadata`，Phase 26 测试里已验证过这个
  函数可离线调用）校验 `name`/`description` 合法、`name` 与用户填写的技能名一致；
  内容大小上限 8KB（个人方法论文本，不需要更大；防止滥用把整段大段材料塞进每轮
  system prompt 的 Level-1 元数据）。
- **API**（`app/api/skill_api.py`，鉴权同 `memory_api.py` 模式）：
  - `POST /api/skills` `{name, description, content}` → 校验 + upsert
  - `GET /api/skills` → 列出当前用户自己的技能
  - `DELETE /api/skills/{id}` → 删除自己的（403/404 校验 owner）
- **接入 skills_loader**：`load_skill_files(user_id=None)` 在内置技能之外，若传了
  `user_id` 就查该用户的 `TravelUserSkill` 行，各自转成 `/user/{name}/SKILL.md` 虚拟路径
  一并种进 `files`。`_build_agent`/`_invoke_with_cancel` 透传 `user_id`（`run_deep_research`
  本来就有）。主 agent `skills=["/main/", "/user/"]`（用户技能只给主 agent，不给
  api-researcher subagent）。
- **前端**：仿照 `MemoryPanel`（`frontend/src/pages/Home.tsx`）加一个 `SkillPanel`
  模态框（列表 + 新增表单：技能名/描述/正文三个输入框 + 提交 + 删除），侧边栏
  加一个"技能"入口按钮（挨着"记忆"按钮）。

### 3. 技能发现追踪（复用 Langfuse，不引入新 vendor）
- 详细调用链已经在 Langfuse 里（`langchain_handler()` 全图追踪，含每次 `read_file`
  工具调用）——这块不用新写代码，本来就有。
- 补一层**产品可见的轻量汇总**：`run_deep_research` 拿到 `result` 后，扫一遍
  `result["messages"]` 里 `tool` 类型消息，挑出对应 `read_file` 调用且 `file_path`
  命中 `/main/` `/researcher/` `/user/` 前缀的，取技能目录名去重，写进最终
  `assistant` 消息的 `meta.skills_used: list[str]`（模式同 `meta.sources`/
  `meta.memories_used`）。
- 前端加 `SkillsUsed` 折叠 pill（仿 `MemoriesUsed`，"🧩 技能 · N"），渲染在
  assistant 消息里。

### 4. Cube Sandbox 执行
- 新增 `app/tools/cube_sandbox.py`：`CubeSandboxBackend(deepagents.backends.sandbox
  .BaseSandbox)`，参考 deepagents 自带 `LangSmithSandbox` 的写法（同样是包一个外部
  沙箱 SDK 对象）：
  - 懒加载：不在 `__init__` 时创建真实沙箱，第一次 `execute()`/`upload_files()`/
    `download_files()` 调用时才 `e2b.Sandbox.create(template=..., api_key=...,
    domain_or_api_url=...)`（探测确认 `e2b` SDK 支持通过 `api_url`/`api_key`/`domain`
    kwargs 指向自托管端点，对应 Cube Sandbox quickstart 的 `E2B_API_URL`/
    `E2B_API_KEY`/`CUBE_TEMPLATE_ID`）——多数深度研究问题根本不会触发 `execute`，
    懒加载让"没装 Cube Sandbox 的用户"/"没用到脚本的这一轮"零开销、零新故障面。
  - `execute()`：调 `sandbox.commands.run(cmd, timeout=...)`；`commands.run` 在非零
    退出码时抛 `e2b.CommandExitException`（本身携带 stdout/stderr/exit_code）——
    必须 catch 住转成 `ExecuteResponse`，不能让异常冒出去（`BaseSandbox`/
    `create_deep_agent` 的 `execute` 工具契约是"永远返回 ExecuteResponse，不 raise"）。
  - `upload_files`/`download_files`：调 `sandbox.files.write`/`sandbox.files.read`，
    捕获 `e2b.NotFoundException` 等映射成 `FileUploadResponse.error`/
    `FileDownloadResponse.error`（partial-success 契约）。
  - 轮末清理：`run_deep_research` 的 `finally` 里如果这轮创建过沙箱就 kill 掉
    （避免累积孤儿沙箱，同 `BrowserSession.close()` 的收尾思路）。
- **配置**（`app/config.py`，默认全关——自托管 Cube Sandbox 需要用户自己另外部署）：
  `cube_sandbox_enabled: bool = False`、`cube_sandbox_api_url`、`cube_sandbox_api_key`、
  `cube_sandbox_template_id`、`cube_sandbox_timeout_s: int = 120`。
- `_build_agent`：`cube_sandbox_enabled=True` 时用
  `CompositeBackend(default=CubeSandboxBackend(...), routes={"/main/": state, ...})`；
  否则维持现状（`backend=None` → deepagents 默认 `StateBackend()`）。

## 涉及模块
- `app/db/models.py`（新表）、`app/api/skill_api.py`（新路由）、`app/main.py`（注册路由）
- `app/agent/skills_loader.py`（加 `user_id` 参数、`/user/` 前缀、内置前缀改名）
- `app/agent/deep_research.py`（`_build_agent` 装配 Cube Sandbox / Composite；
  `run_deep_research` 提取 `skills_used`；轮末沙箱清理）
- `app/tools/cube_sandbox.py`（新文件，`CubeSandboxBackend`）
- `requirements.txt` 加 `e2b`（按需惰性 import，未装 SDK 时 `cube_sandbox_enabled` 也应
  保持可关闭不报错——`_build_agent` 里 `import e2b` 放在 `if settings.cube_sandbox_enabled`
  分支内）
- 前端 `Home.tsx`：`SkillPanel`、`SkillsUsed`、侧边栏入口按钮、`Msg.meta.skills_used` 类型
- `docs/pitfalls/`：记录 Cube/E2B SDK 的 `CommandExitException` 契约踩坑
- `backend/tests/test_skill_api.py`、`backend/tests/test_cube_sandbox.py`（离线，mock e2b）

## 验收标准
1. 用户能在前端上传/查看/删除自己的技能；上传非法 frontmatter 被拒绝并有清晰错误。
2. 别的用户看不到、用不到你上传的技能（DB 查询按 `user_id` 过滤，接口越权删除返回 404）。
3. 深度研究一轮结束后，assistant 消息 `meta.skills_used` 能看到本轮实际读过的技能名；
   前端"🧩 技能 · N"折叠展示正确。
4. `cube_sandbox_enabled=False`（默认）时行为与 Phase 26 完全一致，回归全绿。
5. `cube_sandbox_enabled=True` 且 mock 掉 e2b SDK 时：`execute()` 成功/失败两种路径都能
   正确映射出 `ExecuteResponse`，不抛异常；技能读取仍从 `StateBackend` 走（不经网络）。
6. 全量 `pytest` 通过。
