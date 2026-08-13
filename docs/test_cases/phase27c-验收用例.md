# Phase 27c 页面沙箱开关 / 自定义沙箱镜像 / 产物展示 — 验收用例

自动化：`backend/tests/test_docker_sandbox.py`（含新增用例）、
`backend/tests/test_sandbox_artifacts_api.py`（全离线）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_docker_sandbox.py tests/test_sandbox_artifacts_api.py -q`

## per-message 沙箱开关

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 服务器开关关闭 | 即使本轮开关开也不生效 | `test_build_backend_none_when_server_disabled` |
| 2 | 本轮开关关闭 | 即使服务器开着也不生效 | `test_build_backend_none_when_per_message_toggle_off` |
| 3 | 两者都开 | 正常装配 `DockerSandboxBackend` | `test_build_backend_writes_skill_files_when_both_enabled` |
| 4 | `run_conversation_turn` → `run_deep_research` 穿透 | `sandbox_enabled` 原样传到底 | `test_run_conversation_turn_threads_sandbox_enabled` |

## 沙箱产物捕获 / 存储 / 清理 / 下载

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 5 | 只识别种子文件之外的新文件 | 技能文件本身不会被误当产物 | `test_collect_sandbox_artifacts_skips_seed_files` |
| 6 | 没有新文件 | 返回空列表 | `test_collect_sandbox_artifacts_empty_when_nothing_new` |
| 7 | 产物数量超上限 | 截断，不整轮失败 | `test_collect_sandbox_artifacts_caps_file_count` |
| 8 | 懒清理：过期目录 | 被删除 | `test_cleanup_expired_artifacts_removes_old_dirs` |
| 9 | 懒清理：未过期目录 | 保留 | `test_cleanup_expired_artifacts_keeps_recent_dirs` |
| 10 | 下载存在的产物 | 正确返回文件 | `test_download_existing_artifact` |
| 11 | 下载不存在/已过期的产物 | 404 | `test_download_missing_artifact_404` / `test_download_expired_artifact_removed_returns_404` |
| 12 | **路径穿越**（核心） | `batch`/`filename` 含 `/`、`..`、URL 编码穿越全部拒绝 | `test_download_path_traversal_rejected` |

## 前端
- Composer 加「🐳 沙箱执行」胶囊（仿「🧠 深度推理」），localStorage 持久化，随每条消息传
  `sandbox_enabled`。
- `SkillPanel` 提示文案更新：明确"打开沙箱执行开关后脚本才会被真实运行"。
- assistant 消息新增 `SandboxArtifacts` 组件渲染 `meta.artifacts`：图片内联预览，其余给
  文件名+大小+下载链接。
- `npx tsc --noEmit` + `npm run build` 通过。

## 自定义沙箱镜像
`backend/docker/sandbox/{Dockerfile,requirements.txt}`：预装 python-pptx/python-docx/
openpyxl/reportlab/matplotlib/Pillow/pandas/markdown。`docker_sandbox_image` 默认改成
`travel-sandbox:latest`。服务器上手动构建（不接入 `deploy.sh` 自动构建）：
```
docker build -t travel-sandbox:latest backend/docker/sandbox/
```

## 关键不变式
- 沙箱能力生效需要**服务器开关 AND 本轮开关**同时为真，任一为假都优雅降级为
  Phase 26 行为（不报错）。
- 产物下载端点沿用项目里 `/api/img`/handoff-screenshot 的信任模型（不鉴权、靠
  batch_key 不可猜测），但额外做了显式路径穿越校验（正则白名单字符 + 路径必须真的
  落在产物根目录下）。
- 产物元信息（`meta.artifacts`）跟 `meta.sources`/`meta.skills_used` 走同一套
  `meta_json` 机制，不新增表。

## 回归
`cd backend && .venv/bin/python -m pytest tests/ -q` 全绿（269 例）；
前端 `npx tsc --noEmit && npm run build` 通过。

## 线上真实端到端验证（✅ execute 机制正常，⚠️ 发现一个已知限制）

自定义镜像构建成功（`docker build` 在这台 2 核机器上跑了较长时间，`pip install`
下载慢，属正常但耗时，非死循环——期间一度误判为卡死，用 `ps` 看 `ELAPSED` 涨但
`TIME`（累计 CPU）不涨确认过是真的卡住过一次，kill 掉重跑后其实是构建已经完成、
之前看到的"卡住"进程是已断开 SSH 会话的残留），`docker run --rm --network=none
travel-sandbox:latest python3 -c "import pptx, docx, openpyxl, ..."` 验证全部库可正常
导入。

真实发一条「生成 PPT」的深度推理 + 沙箱执行请求，跑满 600s 超时：
- **`execute()` 本身很快**（trace 里 10 次调用，每次 0.4–2.4s，总计 <15s）——沙箱机制
  验证有效，不是瓶颈。
- **瓶颈是单次 DeepSeek 生成调用**：10 轮 execute 之后的最终答案生成调用单次耗时
  **393.7 秒（6.6 分钟）**，加上前面的规划/执行轮次，累计超过 600s 整轮超时上限，
  最终没能产出报告（回退到"研究超时了"提示）。
- **结论**：不是沙箱 bug，是"多轮代码执行 + 长篇最终综合写作"这类任务本身比常规
  查询更重，现有 600s 超时上限对这类任务偏紧。用户拍板暂不调整，留待以后真正用到时
  再看要不要加大超时或者拆分任务。

