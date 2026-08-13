# 17同游 · 旅行智能体（Travel Browser Agent）

个人旅行规划平台：用户用自然语言提需求，Agent 驱动真实 Chrome 浏览器
（Chrome DevTools MCP）浏览小红书/携程/地图等页面，抽取结构化信息，
生成带预算的完整攻略，并支持多人协同编辑行程。

线上：<https://17tongyou.com>

---

## 快速开始

### 环境要求

- Python 3.12（后端）
- Node 23（前端）
- Chrome / Chromium（Agent 需要驱动真实浏览器）
- 可访问的 PostgreSQL 16

### 1. 配置密钥

```bash
cp backend/.env.example backend/.env
# 填入 DEEPSEEK_API_KEY / AMAP_KEY / DATABASE_URL 等，找项目管理员索取
```

> **`.env` 不进版本库**。任何密钥都不要写进代码或文档。

### 2. 装依赖

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../frontend && npm install
```

### 3. 启动

```bash
# 一键（隧道 + 调试 Chrome + uvicorn，前台运行）
backend/scripts/dev.sh

# 前端另开一个终端
cd frontend && npm run dev     # → http://localhost:5173
```

分步等价于：

```bash
backend/scripts/db_tunnel.sh                  # 1. 数据库 SSH 隧道（必须，公网直连会被重置）
backend/scripts/start_chrome.sh               # 2. Agent 专用调试 Chrome（端口 9223 + 独立 profile）
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

**断点调试**不要用 `dev.sh`（shell 套子进程挂不上断点）：先跑隧道和 Chrome，
再在 IDE 里 Debug `backend/debug_server.py`。

### 4. 跑测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -q          # 全部
cd backend && .venv/bin/python -m pytest tests/test_ontology.py -q   # 单个文件
```

> 本地若无外网 DNS，`test_research_context.py` / `test_context_security.py` 会有几个
> 失败——那是沙箱把 `example.com` 解析到保留地址触发了 SSRF 防护，不是代码问题。

---

## 技术亮点

这个项目不是「调一次 LLM 返回文本」，主要复杂度在**编排、上下文治理和安全边界**上。

### 1. 三路路由分流（`agent/deep_research.py: resolve_route / decide_route`）

一条用户消息进来先分流，不同问题走完全不同的成本曲线：

| 路 | 判定 | 链路 | 线上耗时 |
| --- | --- | --- | --- |
| **direct** | 常识/建议/追问/闲聊 | 无浏览器、无搜索，三元组记忆 + 近 5 轮历史 → 单次流式生成 | 首字 6s / 全程 17s |
| **guide** | 规划/攻略/查酒店 | LangGraph 采集→生成→反思流水线 | ~130s |
| **research** | 多城对比/预算测算/签证/帮我选 | deepagents 自主研究 | 4-6min |

分类用快模型单次调用（~1s）。**失败/未知/空消息一律回落 guide**——宁慢勿错。
同类问题改造前一律走完整流水线，要 2-4 分钟。

### 2. 深度研究模式（`agent/deep_research.py` + `research_tools.py`）

开放式问题主流水线接不住（单目的地 `Preference`、产出模子固定），路由到自主 agent：

- **资源分工**：浏览器工具只在主 agent；subagent `api-researcher` 只有纯 API 工具
- **actor 模式的浏览器会话**：专职 worker task 独占 `ChromeMCP` 生命周期，工具经队列提交
  —— MCP 的 `stdio_client` 是 task-affine 的，跨 task 进出会炸 cancel scope 并泄漏池槽位
- **工具硬配额**：prompt 里写的纪律在长上下文会漂移（实测一轮搜 5 次、读 18 个来源把
  600s 烧光），所以在**工具层**强制封顶，超限返回引导文案让 agent 转入产出

### 3. 上下文治理：留存换引用 + microcompaction

长任务最大的敌人是上下文膨胀。两层机制（借鉴 Claude Code 的做法）：

- **留存换引用**（`research_tools.py`）：抓来的长正文全文存 `source_store`，
  工具只回 ~1500 字预览 + 一个 `source_id`；模型真需要细节时调 `read_source(id, offset)`
  分页取。避免一次把十几篇正文灌进上下文。
- **microcompaction**（`deep_research.py: _context_trim_middleware`）：上下文超过阈值时
  把**最旧的工具结果**替换成占位摘要，保留最近 N 个完整结果——压缩历史而不打断当前推理。
- **历史分层压缩**（`orchestrator.py: update_history_summary`）：近 N 轮保留全文，
  更早的轮次在轮末旁路折叠成结构化摘要。

### 4. 本体层：一份攻略只解析一次（`app/ontology/`）

改造前海报、预算、行程导入**各用一次 LLM 重新解析同一份 Markdown**，三份结果互相对不上，
而且都截断丢数据。现在：

```
Markdown ──LLM 只解析一次──> TripObject 对象图 ──纯函数投影──> 海报 / 预算 / 行程板
```

- **Object + Link**：稳定 id（内容派生哈希）+ 显式声明的关系，可枚举
- **Store**：抽一次落库，按 `source_hash` / `schema_version` 失效；第二个消费者 0 成本
- **Projection**：纯函数，零 LLM
- **Action + Validation**：AI 改状态必须提交带校验的动作，不能直接写库

### 5. LangGraph 反思循环 + 可中断可续跑

- **反思**（`agent/graph.py` + `nodes.py`）：parse → collect → generate → critique →
  （finalize / 补搜后重新生成 / 按问题重排）。自检用快模型 + 务实提示，默认放行只挑硬伤
- **协作式取消**（`agent/cancel.py`）：搜索/抓取/流式生成各处埋检查点，用户点停止立即生效
- **崩溃续跑**：LangGraph checkpoint 存 PG（`AsyncPostgresSaver`），进程被杀后启动时
  从断点续跑在途任务

### 6. 安全边界（多次红队后的产物）

- **Action Guard**（`tools/action_guard.py`）：所有 `click`/`fill` 过三层判定；
  `navigate`/`snapshot` 等只读动作永远放行
- **URL Guard**（`tools/url_guard.py`）：scheme 白名单 + 内网/回环/云元数据地址拦截 +
  **DNS 解析后复验**（防域名解析到内网）。这类问题必须在工具层堵，prompt 写规矩没用
- **注入防线**（`agent/context_security.py`）：外部内容包 `<external_content>` 标签、
  以 tool 角色注入、属性转义防标签逃逸。**刻意不做**「忽略之前的指令」这类措辞过滤
- **数据外带**：CSP（`img-src 'self'`）+ 后端剥离非白名单域的 markdown 图片
- **沙箱执行**（`tools/docker_sandbox.py`）：`--network none` + `cap-drop ALL` +
  只读根 fs + 非 root + 内存/CPU/PID 限额；产物拷贝防软链外泄

### 7. 每用户浏览器池（`tools/browser_pool.py`）

每个 user_id 一个独立 Chrome + 持久 profile——各自扫码登录、互不覆盖、跨重启保留。
按需拉起 / 复用 / 满池驱逐 LRU 空闲 / 都忙则排队（写「排队中」进度）。

### 8. 记忆：三元组归槽而非无限追加（`agent/memory.py`）

每条记忆挂一个规范 `key`（口味/兴趣/节奏/预算/住宿/出行/常驻城市…），
**同一 `(user_id, key)` 只留一条**。四条策略无向量落地：相同 key 覆盖、相似合并、
时间更新优先、明确表达优先。避免记忆越滚越多又互相矛盾。

### 9. 其他

- **流式生成 + 自动续写**：触到 `max_tokens` 自动接着写，而不是给用户一句「已截断」
- **可观测**（`app/observability.py`）：Langfuse 埋点，turn / LLM / 工具三层 trace，
  平台内可看调用链。无 key 时全 no-op
- **用户技能**（`agent/skills_loader.py`）：用户上传私有 skill 包，仅本人深度研究会话生效

---

## 项目结构

```
backend/app/
  agent/
    graph.py / nodes.py        LangGraph 攻略图：采集→生成→自检→(补搜/重排)
    orchestrator.py            主流水线：需求解析、来源采集、流式生成、历史压缩
    deep_research.py           三路路由分流 + deepagents 深度研究 + microcompaction
    research_tools.py          研究工具（留存换引用、read_source 分页、工具配额）
    memory.py                  三元组归槽记忆、跨会话召回、睡眠整合
    site_router.py             意图 → 站点路由（携程/小红书），登录墙接管
    context_security.py        注入防护：外部内容标记 + 防标签逃逸
    cancel.py                  协作式取消（停止按钮）
    poster.py / budget.py      手账海报 / 预算面板
    trip_planner.py            行程几何：串路线、分段耗时、结算、检查项
  ontology/                    本体层：Object / Link / Store / Projection / Action
  tools/
    browser_pool.py            每用户浏览器池
    browser_tool.py / cdp.py   浏览器操作 + Chrome DevTools 协议
    action_guard.py            动作分层判定（写操作必须过）
    url_guard.py               SSRF 防护（scheme + 内网 + DNS 复验）
    docker_sandbox.py          代码执行沙箱
    amap.py / geocode.py       高德（天气/POI/静态图）+ 国内外分流地理编码
    xhs_mcp.py                 小红书 MCP（只读白名单）
  api/                         FastAPI 路由（含 AST 鉴权扫描护栏）
  db/                          SQLAlchemy 模型 + 幂等迁移
  llm/client.py                DeepSeek 封装（结构化 parse / 流式 / reasoning）
tests/                         全部离线（sqlite + fake LLM），无需真实 API key

frontend/src/
  pages/Home.tsx               对话式攻略（流式、思考工作台、海报、预算、调用链）
  pages/Trips.tsx              协同行程板（三栏、地图、记账、行李、群聊）
  components/                  通知、社交、上传、地图等

docs/
  dev_docs/                    架构说明（**先读 系统架构总览.md**）
  task_plans/                  开发前的方案文档
  pitfalls/                    60 篇踩坑记录（改动前建议扫一眼）
  test_cases/                  验收用例
```

---

## 上手顺序建议

1. **`docs/dev_docs/系统架构总览.md`** — 全系统拓扑与链路，了解现状先读它
2. **`CLAUDE.md`** — 各 Phase 的架构决策与关键不变式（最全，但很长）
3. **`docs/pitfalls/`** — 挑与你要改的模块相关的看

---

## 开发流程规范（必须遵守）

1. **开发前**：在 `docs/task_plans/` 写 task plan（目标、方案、涉及模块、验收标准）
2. **踩坑时**：在 `docs/pitfalls/` 记录（现象、原因、解决办法）
3. **完成后**：在 `docs/test_cases/` 写验收用例，并落地为可运行的自动化测试。
   **测试全绿才算完成。**

---

## 几条关键不变式（改代码前务必知道）

- 所有 `click` / `fill` 必须过 Action Guard；`navigate` / `snapshot` 等只读动作永远放行
- MCP 工具返回 `isError` 必须抛异常，不能当正常结果
- LLM 封装不透传 `temperature` 等采样参数；结构化输出必须走 `parse()` 而非裸 prompt
- 预算金额一律**人均**口径；总额由逐项求和得出，**绝不采信模型给的总额**
- 给已存在的表**加列**必须在 `app/db/migrate.py` 写 `ADD COLUMN IF NOT EXISTS`
  —— `create_all` 只建缺失的**表**，不加列（sqlite 单测发现不了，见 pitfalls）

---

## 部署

```bash
cd frontend && npm run build && cp -r dist/. ../backend/static/   # 末尾 /. 不能省
bash backend/deploy/deploy.sh                                     # rsync + 装依赖 + 重启
```

部署后**必须去线上核对**（今天连踩三次「部署成功但没生效」）：

```bash
# 前端：比对 chunk hash 与本次构建是否一致
curl -s https://17tongyou.com/travel/ | grep -o 'assets/index-[^"]*\.js'
# 加过列的话：确认列真的建上了
ssh <server> "sudo -u postgres psql -d travel_agent -c '\d 表名'"
```
