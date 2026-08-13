# Phase 27/27b 用户上传技能 / 技能发现追踪 / Docker 沙箱 — 验收用例

> Cube Sandbox 执行这块经服务器硬件排查（内存/CPU/无 KVM/磁盘文件系统均不满足官方最低
> 要求，且安装需要换内核重启生产机）后由用户拍板**移除**，详见
> `docs/task_plans/task_plan-phase27-用户技能上传与cube沙箱执行.md` 开头的更新说明。
> 后续加了 zip 多文件技能包上传 + 基于已装 Docker 的轻量沙箱替代方案（Phase 27b，
> 见 `task_plan-phase27b-zip技能包与docker沙箱.md`）。

自动化：`backend/tests/test_skill_api.py`、`backend/tests/test_deep_research_skills.py`、
`backend/tests/test_docker_sandbox.py`（全离线）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_skill_api.py tests/test_deep_research_skills.py tests/test_docker_sandbox.py -q`

## 用户上传技能

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 合法 SKILL.md 解析 | 正确取出 name/description | `test_parse_and_validate_ok` |
| 2 | 缺 frontmatter | 拒绝，报错提示 | `test_parse_and_validate_missing_frontmatter` |
| 3 | name 不合规范（大写/下划线） | 拒绝 | `test_parse_and_validate_bad_name` |
| 4 | 缺 description | 拒绝 | `test_parse_and_validate_missing_description` |
| 5 | 正文超过大小上限 | 拒绝 | `test_parse_and_validate_too_large` |
| 6 | 上传后能列出 | content/description 原样返回 | `test_upload_then_list` |
| 7 | 同名再次上传 | 覆盖更新而不是新增一条 | `test_upload_same_name_upserts` |
| 8 | 上传非法内容 | 400，不落库 | `test_upload_invalid_content_rejected` |
| 9 | 功能开关关闭 | 403 | `test_upload_disabled_by_settings` |
| 10 | **按用户隔离**（核心） | 别的用户看不到你的技能 | `test_list_is_scoped_to_owner` |
| 11 | 删除自己的 | 成功 | `test_delete_own_skill` |
| 12 | **越权删除别人的** | 404，且对方数据不受影响 | `test_delete_others_skill_404` |
| 13 | 删除不存在的 id | 404 | `test_delete_nonexistent_404` |
| 14 | `skills_loader` 查库转虚拟路径 | `/user/{name}/SKILL.md` | `test_load_user_skill_files_from_db` |
| 15 | DB 查询异常 | 优雅降级返回空，不炸整轮 | `test_load_user_skill_files_db_error_returns_empty` |

## 技能发现追踪（meta.skills_used）

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 16 | 从 read_file 工具调用提炼技能名 | 按虚拟路径前缀识别、去重、保序 | `test_extract_skills_used_from_tool_calls` |
| 17 | 没有工具调用/空结果 | 返回空列表，不报错 | `test_extract_skills_used_empty_when_no_tool_calls` |

## zip 多文件技能包（Phase 27b）

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 18 | 合法多文件 zip 解析 | 正确取出 name/description，files 含 SKILL.md+附带文件 | `test_parse_and_validate_zip_ok` |
| 19 | 压缩了外层文件夹 | 自动剥掉这层前缀 | `test_parse_and_validate_zip_strips_wrapping_folder` |
| 20 | 不是合法 zip | 拒绝 | `test_parse_and_validate_zip_not_a_zip` |
| 21 | 缺 SKILL.md | 拒绝 | `test_parse_and_validate_zip_missing_skill_md` |
| 22 | **zip-slip 路径逃逸**（核心） | `../` 相对路径逃逸拒绝 | `test_parse_and_validate_zip_path_traversal_rejected` |
| 23 | 绝对路径 | 拒绝 | `test_parse_and_validate_zip_absolute_path_rejected` |
| 24 | 含二进制文件 | 拒绝（暂只支持文本） | `test_parse_and_validate_zip_binary_file_rejected` |
| 25 | 文件数超限 | 拒绝 | `test_parse_and_validate_zip_too_many_files` |
| 26 | 解压后总大小超限 | 拒绝 | `test_parse_and_validate_zip_too_large` |
| 27 | 空 zip | 拒绝 | `test_parse_and_validate_zip_empty` |
| 28 | zip 上传端点 + 列表 | files 字段正确 | `test_handle_zip_upload_then_list` |
| 29 | 端点：功能关闭/超限/非法 zip | 403/400/400 | `test_handle_zip_upload_disabled_by_settings` 等 |
| 30 | zip 覆盖纯文本上传（同名） | 整体替换 files，不合并 | `test_zip_upload_and_text_upload_interop_same_name` |
| 31 | 多文件技能展开成多个虚拟路径 | `/user/{name}/SKILL.md` + `/user/{name}/references/...` | `test_load_user_skill_files_multi_file_from_zip` |

## Docker 轻量沙箱（Phase 27b）

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 32 | execute 成功 | 正确返回 output/exit_code | `test_execute_success` |
| 33 | **容器加固参数齐全**（核心） | `--network=none`/`--read-only`/`--cap-drop=ALL`/`--user nobody`/`no-new-privileges` 都在 | `test_execute_hardens_container` |
| 34 | execute 非零退出码 | 不抛异常 | `test_execute_nonzero_exit_does_not_raise` |
| 35 | **超时杀容器**（核心） | 显式调用 docker kill，不只是杀客户端进程 | `test_execute_timeout_kills_container` |
| 36 | docker 未安装 | 优雅降级为 ExecuteResponse，不崩 | `test_execute_docker_not_installed` |
| 37 | **文件操作限定在临时目录**（核心） | virtual_mode=True 拒绝路径逃逸 | `test_file_ops_confined_to_root_dir` |
| 38 | `docker_sandbox_enabled=False`（默认） | backend=None，行为同之前 | `test_build_backend_none_when_disabled` |
| 39 | `docker_sandbox_enabled=True` | 单一 `DockerSandboxBackend`（不再包 CompositeBackend）、临时目录 0o777、技能物理写入且**无二次拼前缀**（`/main/main/` 不存在，线上实测踩过这个坑） | `test_build_backend_writes_skill_files_when_enabled` |
| 39b | 用户技能也物理写入沙箱临时目录 | `/user/{name}/SKILL.md` 存在 | `test_build_backend_includes_user_skill` |
| 40 | 轮末清理 | 临时目录被删除 | `test_run_deep_research_cleans_up_sandbox_tempdir` |

## 前端
`SkillPanel`（仿 `MemoryPanel`）：列表/纯文本上传/zip 上传/删除，文件数展示；
`SkillsUsed`（仿 `MemoriesUsed`）："🧩 技能 · N" 折叠展示。`npx tsc --noEmit` +
`npm run build` 通过（无自动化 UI 测试，人工验证：本地起 `npm run dev` 登录后点
侧边栏「技能」按钮能弹出面板并上传/删除）。

## 关键不变式
- 用户上传的技能**只影响自己**：`load_skill_files(user_id=)` 只在传了 user_id 时查库，
  DB 查询按 `user_id` 过滤且有单测覆盖越权场景。
- 技能发现追踪不新增外部 vendor：详细调用链在已有的自托管 Langfuse 里（Phase 24），
  `meta.skills_used` 只是从同一轮 agent 消息里提炼出的产品可见汇总。
- zip 上传的所有文件路径最终都要落在 `/user/{name}/` 命名空间内，不能逃逸到
  `/main/`/`/researcher/` 等内置技能命名空间。
- Docker 沙箱默认关闭；开启后 `execute()` 不管成功/失败/超时都不抛异常；文件操作被
  `virtual_mode=True` 限定在 per-turn 临时目录，轮末必须清理。
- Docker 沙箱开启时**不用 `CompositeBackend` 包一层共享 `StateBackend`**——线上实测过
  这样会让 `glob`/`ls` 二次拼前缀（`/main/main/xxx/SKILL.md`），技能改成物理写进沙箱
  自己的临时目录，`backend` 是单一 `DockerSandboxBackend`。

## 回归
`cd backend && .venv/bin/python -m pytest tests/ -q` 全绿。
