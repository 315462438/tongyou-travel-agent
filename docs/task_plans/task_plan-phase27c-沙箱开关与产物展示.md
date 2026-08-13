# Phase 27c — 页面沙箱开关 / 自定义沙箱镜像 / 产物展示

## 背景 / 目标

Phase 27b 的 Docker 沙箱只能改服务器 `.env` 的 `DOCKER_SANDBOX_ENABLED` + 重启才能开关，
且默认 `python:3.12-slim` 镜像配合 `--network=none` 装不上任何库。用户想要：

1. 页面上能直接开关沙箱（不用改配置重启）；
2. 技能上传界面的提示文案更新——沙箱开了之后脚本真的会被执行，不再是"只能读不能跑"；
3. 沙箱真能生成有用的产物（用户举例：PPT），且执行完之后能在页面上看到/下载。

## 已确认的方案（AskUserQuestion 逐条拍板）

| 问题 | 结论 |
| --- | --- |
| 开关范围 | **每条消息一个开关**，仿现有「🧠 深度推理」胶囊：localStorage 持久化 + 随每条消息传给后端 |
| 沙箱镜像能力 | **构建自定义镜像**（预装 python-pptx/python-docx/openpyxl/reportlab/matplotlib/Pillow/pandas/markdown），不能指望 `--network=none` 的容器运行时 pip install |
| 产物存储 | **服务器本地目录 + 到期自动清理**，到期时间 30 分钟 |

## 方案

### 1. per-message 开关穿透
仿 `deep_reasoning`（Phase 23）的路径原样再走一遍：
`SendMessageRequest.sandbox_enabled` → `send_message` 传给
`run_conversation_turn(..., sandbox_enabled)` → 在 `route == "research"` 分支调用
`run_deep_research(cid, user_text, user_id, sandbox_enabled)`。**生效条件是"服务器开关
AND 本轮开关"两者都为真**（`settings.docker_sandbox_enabled and sandbox_enabled`）——
服务器开关仍然是"这台机器到底具不具备这个能力"的运维开关，本轮开关是用户每次的选择。

### 2. 自定义沙箱镜像
`backend/docker/sandbox/{Dockerfile,requirements.txt}`：基于 `python:3.12-slim`，
build 时装好办公文档/数据/绘图相关库（无网络运行时约束下必须在构建期就装好）。
服务器上手动 `docker build -t travel-sandbox:latest backend/docker/sandbox/`
（构建是一次性/偶发操作，不接入 `deploy.sh` 自动构建——避免每次部署都重新构建镜像）。
`settings.docker_sandbox_image` 默认改成 `travel-sandbox:latest`。

### 3. 产物捕获 / 存储 / 清理 / 展示
- `_write_skill_files_to_dir` 返回它写入的相对路径集合（"种子文件"基线）。
- 轮末（成功路径）用这个基线跟临时目录当前内容做 diff，多出来的文件就是 agent 产出的
  产物，拷贝进 `{sandbox_artifacts_dir}/{message_id}/{relpath}`（先于
  `shutil.rmtree(临时目录)` 执行）。
- **懒清理**：每次要写新产物之前，先扫一遍 `sandbox_artifacts_dir`，删掉超过
  `sandbox_artifacts_ttl_min`（30 分钟）的旧 message_id 子目录——不额外起后台线程/定时器，
  个人项目量级足够。
- 产物元信息写进 assistant 消息的 `meta.artifacts: [{name, size, url}]`（跟
  `meta.sources`/`meta.skills_used` 同一套 meta_json 机制）。
- 新端点 `GET /api/chat/{cid}/artifacts/{message_id}/{filename}`：**不鉴权**（跟
  `/api/img`、handoff-screenshot 同一套信任模型——message_id 是服务端生成的 32 位
  十六进制 UUID，不可猜测；同时做路径穿越校验 + 到期检查）。
- 前端 assistant 消息里加"📎 产物"展示（仿 `Sources`/`MemoriesUsed` 折叠卡片）：
  图片类内联预览，其余给文件名+大小+下载链接。

### 4. 技能上传提示更新
`SkillPanel` 的说明文案根据"这台服务器 `docker_sandbox_enabled` 是否开启"分两种表述：
开启时告知"打开沙箱执行开关后，你上传技能里的脚本会被真实运行"；关闭时保留原有
"暂不会被执行"表述。前端目前没有直接查询服务器端 `docker_sandbox_enabled` 的接口，
借用 `deep_reasoning`/`sandbox_enabled` 一样走一个轻量配置探测（或者更简单：文案统一改成
"打开消息旁的「沙箱执行」开关后可能会被运行，取决于服务器是否配置了沙箱"，不做服务端探测，
避免新增一个只为文案服务的接口）。

## 涉及模块
`app/api/chat_api.py`（`sandbox_enabled` 字段 + 新增 artifacts 端点）、
`app/agent/orchestrator.py`（`run_conversation_turn` 穿透）、
`app/agent/deep_research.py`（`run_deep_research`/`_build_backend`/`_write_skill_files_to_dir`
签名调整 + 产物捕获逻辑）、`app/config.py`（`sandbox_artifacts_dir`/`_ttl_min`、
`docker_sandbox_image` 默认值）、`backend/docker/sandbox/`（新 Dockerfile）、
前端 `Home.tsx`（composer 开关胶囊、`SkillPanel` 文案、`SandboxArtifacts` 展示组件）。

## 验收标准
1. 关掉开关（默认）：行为与 Phase 27b 完全一致，不受影响。
2. 打开开关且服务器 `docker_sandbox_enabled=true`：`_build_backend` 生效；服务器
   `docker_sandbox_enabled=false` 时即使本轮开关开也不生效（优雅降级，不报错）。
3. 产物捕获只识别"种子文件基线之外"的新文件，不会把技能文件本身误当产物。
4. 产物元信息正确写入 `meta.artifacts`，下载端点能正确取到文件、路径穿越被拒绝、
   过期产物被清理/拒绝访问。
5. 全量 `pytest` 通过；前端 `tsc --noEmit` + `npm run build` 通过。
6. 服务器上构建自定义镜像后，实测一次"帮我生成一份行程 PPT 大纲"之类的问题，确认
   `execute()` 真的跑了 `python-pptx` 生成文件、产物出现在页面上可下载。
