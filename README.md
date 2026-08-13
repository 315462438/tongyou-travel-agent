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

## 项目结构

```
backend/
  app/
    agent/        Agent 编排（LangGraph 图、orchestrator、记忆、海报、预算）
    ontology/     本体层：攻略 → 对象图 → 各视图投影（见下）
    api/          FastAPI 路由
    tools/        浏览器、高德、小红书 MCP 等外部能力
    db/           SQLAlchemy 模型与幂等迁移
  tests/          全部离线（sqlite + fake LLM），无需真实 API key
frontend/src/
  pages/          Home.tsx（对话）、Trips.tsx（协同行程板）
  components/
docs/
  task_plans/     开发前的方案文档
  dev_docs/       架构说明（**先读 系统架构总览.md**）
  pitfalls/       踩坑记录（很有价值，改动前建议扫一眼）
  test_cases/     验收用例
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
