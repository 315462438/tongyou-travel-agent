# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

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

**线上体验地址**：http://42.194.202.233/travel/

服务器部署架构：
- **nginx**（:80）反代 `/travel/` → 后端 :8080（配置在 `/etc/nginx/sites-enabled/default`）
  - ⚠️ 只有 80 端口外网可达；8080/443 被云安全组/中间网络重置（同 PG 那个坑），
    所以必须走 nginx 80 反代，不能直接暴露 8080
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
  （`systemctl disable --now travel-chrome`，回收 ~1.5G）。本地开发 `BROWSER_POOL_ENABLED` 不设
  → 回退单调试 Chrome（`CHROME_DEBUG_URL` + start_chrome.sh）+ 全局串行。
  见 docs/pitfalls/snap-chromium多实例与小内存.md。

**重新部署**：本地 `frontend` 改动后 `npm run build && cp -r dist ../backend/static`，
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
消息，每 ~1.2s 增量更新，终稿去标记；`_is_running` 视 streaming 为运行中，
启动修复会就地终稿被打断的流式消息）。一轮共享一个浏览器会话（勿在会话内
调 `_expire_stale_logins`，它可能重启 Chrome）。抓取来源 summary 用
`_excerpt` 清洗摘录（无 LLM 摘要调用）；页面分类长正文规则快判。
线上实测：总时长 3-6min → ~130s，首段回复 82s 可见。

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

**Phase 77 — 旅行预演与灵感入口**：登录后新会话首屏改为**单入口自动分流**，不再把相近能力
包装成三个 tab。主输入有公开 HTTP(S) 链接→提取最多 5 条并走收藏整理；主输入为空但有出发地+
预算→反推 3 个目的地；纯短地名→旅行预演（逐日时间轴/体力/预算/风险备选）；其他自然语言问题
原样交给后端路由。前两类通过发送级
覆盖强制 `deep_reasoning=true`，不能只先改 React 开关状态（异步 state 会让当前请求仍走普通
模式）。纯函数在 `frontend/src/interaction.ts`，视图在 `Home.tsx`。当前上传接口不等于视觉理解，
本阶段明确不宣称支持截图识别。

**Phase 78 — 热门目的地图片卡片与单入口回归**：空状态彻底移除第二 Composer，只保留上述统一
输入。`/api/onboarding` 继续按近 30 天真实会话次数返回热门地名（排除内部账号）；新增
`/api/onboarding/covers` 最多为前 4 名异步补高德景点封面，成功/空结果分别做 TTL 缓存，异常不
阻塞首屏。前端在主输入下展示四张图片卡，外图经 `/api/img` 同源代理，失败回退品牌渐变；点击
只回填唯一输入供用户补约束。桌面四列、移动横向 snap，reduced-motion 关闭位移。坑见
`docs/pitfalls/单入口残留第二个输入框与同步取封面.md`。

**Phase 79 — 第一视角旅行实境预演**：首页单入口下新增“天堂寨 · 身临其境”横幅，进入懒加载
全屏 `ImmersivePreview`。后端 `GET /api/immersive/preview?destination=` 返回 6 幕场景包；天堂寨
使用人工校准的山门/白马大峡谷/瀑布群/哲人峰/天堂顶/吊锅剧情，高德 POI 补真实图片，成功缓存
6h、无图缓存 1h、并发≤2、单图失败不阻塞。前端有峡谷慢行/主峰挑战分支、时间/环境/体力/花费
HUD、结算和“一键转真实行程”；模拟值明确不冒充实时数据。外图只走 `/api/img`，移动端与
`prefers-reduced-motion` 有独立降级。不做 WebGL/3D 自由行走。

**Phase 80 — 互动旅行电影样片**：Phase 79 的全屏图片 + 常驻 HUD 改为环境延展与中央电影取景框，
低分辨率 POI 图不再过度铺满 2K 屏；天堂寨首幕使用项目内高质量 WebP 氛围主视觉并明确标注
“氛围演绎”，后续图片标注“真实地点参考”。鼠标/触控驱动轻量 2.5D 视差，普通场景需持续按住
900ms（或空格键）推进，短按取消；体力/花费收进按需展开的“行程感受”，路线分支、结算和转真实
行程继续复用原逻辑。reduced-motion 会关闭视差、呼吸、光斑与颗粒动画。

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
