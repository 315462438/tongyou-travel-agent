# 17同游 · 旅行智能体（Travel Browser Agent）

个人旅行规划平台：用户用自然语言提需求，Agent 驱动真实 Chrome 浏览器
（Chrome DevTools MCP）浏览小红书/携程/地图等页面，抽取结构化信息，
生成带预算的完整攻略，并支持多人协同编辑行程。

线上：<https://17tongyou.com>

主要复杂度不在「调一次 LLM」，而在**编排、上下文治理、可观测与安全边界**。

---

## 快速开始

需要 Python 3.12 / Node 23 / Chrome / PostgreSQL 16。

```bash
cp backend/.env.example backend/.env      # 填 DEEPSEEK_API_KEY / AMAP_KEY / DATABASE_URL，找管理员要
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../frontend && npm install

backend/scripts/dev.sh                    # 一键：隧道 + 调试 Chrome + uvicorn
cd frontend && npm run dev                # → http://localhost:5173
```

> **`.env` 不进版本库**，任何密钥都不要写进代码或文档。

分步启动、断点调试（不能用 `dev.sh`，shell 套子进程挂不上断点）见 `CLAUDE.md`。

```bash
cd backend && .venv/bin/python -m pytest tests/ -q      # 970+ 全离线单测
```

> 本地无外网 DNS 时 `test_research_context.py` / `test_context_security.py` 有几个失败——
> 那是沙箱把 `example.com` 解析到保留地址触发了 SSRF 防护，不是代码问题。

---

## 技术亮点

### 1. 三路路由分流（`agent/deep_research.py: resolve_route / decide_route`）

一条用户消息进来先分流，不同问题走完全不同的成本曲线：

| 路 | 判定 | 链路 | 线上耗时 |
| --- | --- | --- | --- |
| **direct** | 常识/建议/追问/闲聊 | 无浏览器无搜索，三元组记忆 + 近 5 轮历史 → 单次流式生成 | 首字 6s / 全程 17s |
| **guide** | 规划/攻略/查酒店 | LangGraph 采集→生成→反思流水线 | ~130s |
| **research** | 多城对比/预算测算/签证/帮我选 | deepagents 自主研究 | 4-6min |

分类用快模型单次调用（~1s），**失败/未知/空消息一律回落 guide**——宁慢勿错。
改造前同类问题一律走完整流水线，要 2-4 分钟。有专门的评估集守着（见 §6）。

### 2. 深度研究模式（`agent/deep_research.py` + `research_tools.py`）

开放式问题主流水线接不住（单目的地 `Preference`、产出模子固定），路由到自主 agent：

- **资源分工**：浏览器工具只在主 agent；subagent `api-researcher` 只有纯 API 工具
- **actor 模式的浏览器会话**：专职 worker task 独占 `ChromeMCP` 生命周期，工具经队列提交
  —— MCP 的 `stdio_client` 是 task-affine 的，跨 task 进出会炸 cancel scope 并泄漏池槽位
- **工具硬配额**：prompt 写的纪律在长上下文会漂移（实测一轮搜 5 次、读 18 个来源把 600s
  烧光），所以在**工具层**强制封顶，超限返回引导文案让 agent 转入产出
- **重复调用守卫**（`agent/repeat_guard.py`）：配额治「总量超标」，这个治「同一查询反复调」
  —— 连续 3/6/10 次注入升级式提醒，**不阻断**（阻断会让 agent 卡死在无路可走的状态）

### 3. 上下文治理

长任务最大的敌人是上下文膨胀。五层机制：

- **留存换引用**（`research_tools.py`）：抓来的长正文全文存 `source_store`，工具只回
  ~1500 字预览 + 一个 `source_id`；模型要细节时调 `read_source(id, offset)` 分页取
- **microcompaction**（`deep_research.py: _context_trim_middleware`）：上下文超阈值时把
  **最旧的工具结果**替换成占位摘要，保留最近 N 个完整结果——压缩历史而不打断当前推理
- **surface 投影**（`orchestrator.py: derive_surface`，借鉴 DeepSeek Harness）：
  历史压缩从「就地覆盖摘要字段」改成**往只追加日志里追加一条 `replace` 消息**遮蔽旧区间。

  ```
  travel_message 表（日志，只增不减）── derive_surface() 投影 ──> 进模型的 messages
  ```

  **压缩因此不删除任何东西**：原文一条不少地留在表里可完整回放，而投影出来的上下文是短的。
  「追加」是往日志追加，不是往上下文追加——这两件事不矛盾（账本 vs 余额）。
- **幂等中段截断**（`agent/truncate.py`）：`head + marker + tail <= threshold` 在**配置期**
  就用数学约束保证，从根上杜绝「截过的再截一次又短一截」
- **边界只由日志推动**（2026-08-22）：装配期那个「超限就取近 N 轮」的滑动窗口已删除。
  它与 surface 投影是两套互不知情的压缩，而且它砍掉的消息**没有摘要覆盖、无任何记录、
  边界还每轮左移一格**（前缀缓存随之作废）。现在唯一能改变模型可见边界的动作是折叠，
  而折叠一定在日志里留下一条 `replace`。超限时就地补一次折叠，而不是静默丢。

配套 **上下文清单**（`agent/context_manifest.py`）：每条终稿记下「这轮由什么装配而成」
（历史用了全文还是摘要+近窗、记忆几条、来源几篇），事后能回答「那轮到底喂了什么进模型」。

**记忆变更三态通知**（`agent/memory.py`，移植自 Codex 的 `PreviousSectionState`）：
投影架构让记忆永远只有当前值、历史里没有陈旧副本——但**对话历史本身承载旧状态**。
用户第 3 轮因「忌口=素食」拿到一堆素食推荐，第 8 轮说「不忌口了」把记忆删掉，
第 8 轮的历史里那些推荐仍逐字躺着，模型却收不到任何「约束解除了」的信号。
所以对「上一轮实际注入了什么」建三态：

| 态 | 含义 | 动作 |
| --- | --- | --- |
| Absent | 本会话还没有过终稿回复 | 静默 |
| Unknown | 有过回复，但没记下注入了什么 | 发一句整体重申「以当前这份为准」 |
| Known | 有精确快照 | 精确 diff，只报**更新**与**删除** |

四条硬约束：

1. **新增不通知**。新增的记忆不与历史里任何表述矛盾，说了纯是噪声。会发出文字的只有
   **更新**和**删除**——因为只有它们让历史里那些基于旧值写下的回复变成了错的。
2. **快照跨全会话聚合，通知恰好出现一次**。陈旧状态是逐轮累积的（第 1 轮展示的偏好，
   模型据此写下的内容会一直留在历史里），所以比对的是**全会话展示过的每个 (key, value)**，
   不是只跟上一轮比——只比上一轮的话，中间任何一轮因相关性筛选"没提"这条，就会静默漏发。
   代价是 diff 不会自然消失，于是**通知这个动作本身也记账**（`meta.memories_changed`），
   下一轮据此跳过。账本记的是「上次通知的新值」而非「这个 key 说过了」，所以**再次变更
   仍会再通知**。
3. **「本轮没被相关性筛中」绝不能报成删除**。`select_relevant_memories` 会按相关性筛掉
   一部分记忆，判据必须取**筛选前**的全量 key。写错的话一次筛选就让模型以为用户撤回了
   偏好——那是**主动误导，比不通知更糟**。
4. **Unknown 往「通知」这边倒**。代价不对称：多说一句几十 token，漏说则模型继续按
   已被推翻的约束作答，而用户看不出它为什么固执。

### 4. 本体层：一份攻略只解析一次（`app/ontology/`）

改造前海报、预算、行程导入**各用一次 LLM 重新解析同一份 Markdown**，三份结果互相对不上，
而且都截断丢数据。现在：

```
Markdown ──LLM 只解析一次──> TripObject 对象图 ──纯函数投影──> 海报 / 预算 / 行程板
```

- **Object + Link**：稳定 id（内容派生哈希，重复抽取自动去重）+ 显式声明的关系，可枚举
- **Store**：抽一次落库，按 `source_hash` / `schema_version` 失效；第二个消费者 0 成本
- **Projection**：纯函数，零 LLM
- **Action + Validation**：AI 改状态必须提交带校验的动作，不能直接写库

### 5. 可中断、可续跑、可自证

- **反思循环**（`agent/graph.py` + `nodes.py`）：parse → collect → generate → critique →
  （finalize / 补搜后重新生成 / 按问题重排）。自检用快模型 + 务实提示，默认放行只挑硬伤
- **协作式取消**（`agent/cancel.py`）：搜索/抓取/流式生成/排队等浏览器各处埋检查点
- **三层超时防线**（`tools/xhs_mcp.py`）：单次超时挡「单篇卡住」、连续失败熔断挡「服务垮掉」、
  **整轮总预算挡「半死状态」**——失败成功交替、每次都卡在超时边缘时，前两层单独看都正常
- **崩溃续跑**：LangGraph checkpoint 存 PG（`AsyncPostgresSaver`），进程被杀后启动时续跑

### 6. 可观测与评估

**看得见**（`app/observability.py` + Langfuse 自托管）：turn / LLM / 工具三层 trace，
平台内直接看，无 key 时全 no-op。三个面板：

| 面板 | 回答什么 |
| --- | --- |
| **子代理面板** | 深度研究并发派的 N 个子任务：谁在跑、查什么、多久、多少 token |
| **会话轨迹** | 整个会话的时间线，Input/Model/Tools 三泳道密度条 + 点开看 Raw |
| **日志 vs 投影** | 日志 47 条 → 进上下文 31 条 → 被摘要遮蔽 16 条，压缩成效可见 |

**量得出**（`backend/evals/`，真实 LLM 调用，不进 CI，定位是大改动前后的手动对照）：

| 评估集 | 测什么 | 成本 |
| --- | --- | --- |
| `routes.yaml` | 路由三分类 35 条 | ~1 分钟 |
| `extract.yaml` | 本体抽取，5 篇**固定**真实攻略（天数 3/3/5/7/10） | 分钟级 |
| `queries.yaml` | 端到端输出质量，跑真实流水线 | ~1 小时 |

几条刻意的设计：

- **三层验证**：结果（环境真值）→ 过程（业务规则）→ 质量（Rubric 维度化，**不折成单一总分**
  ——分数掉 0.1 没人知道该改哪）。过程层的证据源是 **Langfuse 轨迹的 span 名**，
  不是进度气泡文案（那是 UI 字符串，改一句就静默失效）
- **硬错 / 软错分级**：`ROUTE_SYSTEM` 自己写着「拿不准一律选 guide」，这类保守降级算软错，
  闸门只看硬错——否则会逼着你去「优化」一个本来就正确的行为
- **跑挂 ≠ 判错**：生产的 `decide_route` 把 API 异常兜底成 `guide`，评估若直接复用它，
  **一次断网会长得和「模型判成 guide」一模一样**。立集当天就踩到，报出一个完全由连接失败
  构成、却非常像真结论的「准确率 42.9%」。现在跑挂单独一档，准确率的分母只算跑成的条数，
  退出码 2≠1。一般化：**凡生产有「失败静默降级」的地方，评估都不能复用那条路径**
- **规则判定，不做 LLM 打分**：打分会漂移，当闸门用时分不清是模型抖动还是真退化
- **元规则**：工具序列两个证据源都还原不出来时，这一层**判自己失效并报红**，而不是静默放行

评估集第一轮就抓到一个线上缺陷：itinerary 路天数多会分块，**cost 路从来不分块**，
7 天海外攻略的逐项开销在 8000 token 处 JSON 截断 → 预算面板全空。

### 7. 安全边界（多次红队后的产物）

- **Action Guard**（`tools/action_guard.py`）：所有 `click`/`fill` 过三层判定；
  `navigate`/`snapshot` 等只读动作永远放行
- **URL Guard**（`tools/url_guard.py`）：scheme 白名单 + 内网/回环/云元数据地址拦截 +
  **DNS 解析后复验**（防域名解析到内网）。这类问题必须在工具层堵，prompt 写规矩没用
- **注入防线**（`agent/context_security.py`）：外部内容包 `<external_content>` 标签、
  以 tool 角色注入、属性转义防标签逃逸。**刻意不做**「忽略之前的指令」这类措辞过滤
- **数据外带**：CSP（`img-src 'self'`）+ 后端剥离非白名单域的 markdown 图片
- **沙箱执行**（`tools/docker_sandbox.py`）：`--network none` + `cap-drop ALL` + 只读根 fs +
  非 root + 内存/CPU/PID 限额；产物拷贝防软链外泄
- **鉴权护栏**：`tests/test_agent_api_auth.py` 用 AST 全量扫描路由——新增路由默认必须带鉴权，
  有意公开的须登记，且登记表不许留过期条目

### 8. 其他机制

| 机制 | 一句话 |
| --- | --- |
| **每用户浏览器池**（`tools/browser_pool.py`） | 每 user_id 一个独立 Chrome + 持久 profile，各自扫码互不覆盖、跨重启保留 |
| **三元组归槽记忆**（`agent/memory.py`） | 每条记忆挂规范 `key`，**同一 `(user_id, key)` 只留一条**，避免越滚越多又互相矛盾 |
| **流式生成 + 自动续写** | 触到 `max_tokens` 自动接着写，而不是给用户一句「已截断」 |
| **快答先行** | 深度任务先用快模型给 150 字初步判断，再出完整版——长任务流失的原因是「不知道还要多久」 |
| **用户技能**（`agent/skills_loader.py`） | 用户上传私有 skill 包，仅本人深度研究会话生效 |

---

## 项目结构

```
backend/app/
  agent/
    graph.py / nodes.py        LangGraph 攻略图：采集→生成→自检→(补搜/重排)
    orchestrator.py            主流水线：需求解析、来源采集、流式生成、surface 投影
    deep_research.py           三路路由分流 + deepagents 深度研究 + microcompaction
    research_tools.py          研究工具（留存换引用、read_source 分页、工具配额）
    repeat_guard.py            重复调用守卫       truncate.py       幂等中段截断
    context_manifest.py        上下文清单         subagent_trace.py 子代理追踪
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
    xhs_mcp.py                 小红书 MCP（只读白名单 + 三层超时防线）
  api/                         FastAPI 路由（含 AST 鉴权扫描护栏）
  observability.py             Langfuse 埋点（turn / LLM / 工具三层）
evals/                         评估集：路由 / 本体抽取 / 端到端质量 + 三层验证
tests/                         全离线（sqlite + fake LLM），无需真实 API key

frontend/src/pages/
  Home.tsx                     对话 / 轨迹双标签、思考工作台、子代理面板、海报、预算
  Trips.tsx                    协同行程板（三栏、地图、记账、行李、群聊）

docs/
  dev_docs/                    架构说明（**先读 系统架构总览.md**）
  task_plans/ pitfalls/ test_cases/    方案 / 62 篇踩坑 / 验收用例
```

---

## 上手顺序

1. **`docs/dev_docs/系统架构总览.md`** — 全系统拓扑与链路，了解现状先读它
2. **`CLAUDE.md`** — 各 Phase 的架构决策与关键不变式（最全，但很长）
3. **`docs/pitfalls/`** — 挑与你要改的模块相关的看

## 开发流程规范（必须遵守）

1. **开发前**：在 `docs/task_plans/` 写 task plan（目标、方案、涉及模块、验收标准）
2. **踩坑时**：在 `docs/pitfalls/` 记录（现象、原因、解决办法）
3. **完成后**：在 `docs/test_cases/` 写验收用例，并落地为可运行的自动化测试。
   **测试全绿才算完成。**

## 几条关键不变式（改代码前务必知道）

- 所有 `click` / `fill` 必须过 Action Guard；`navigate` / `snapshot` 等只读动作永远放行
- MCP 工具返回 `isError` 必须抛异常，不能当正常结果
- LLM 封装不透传 `temperature` 等采样参数；结构化输出必须走 `parse()` 而非裸 prompt
- 预算金额一律**人均**口径；总额由逐项求和得出，**绝不采信模型给的总额**
- 结构化抽取的硬约束是**输出 token**，不是输入长度；要拆按**消费者**拆，不按概念拆
- 压缩只能往日志追加遮蔽事件，**不许删除或就地覆盖原文**；模型可见的历史边界**只由
  日志里的 `replace` 事件推动**，装配期不许再自行截窗
- 记忆的「删除/更新」必须显式通知模型——历史里还留着基于旧偏好写下的回复；
  但「本轮没被相关性筛中」不是删除，**不能**报成删除
- 给已存在的表**加列**必须在 `app/db/migrate.py` 写 `ADD COLUMN IF NOT EXISTS`
  —— `create_all` 只建缺失的**表**，不加列（sqlite 单测发现不了，见 pitfalls）

---

## 部署

```bash
cd frontend && npm run build && cp -r dist/. ../backend/static/   # 末尾 /. 不能省
bash backend/deploy/deploy.sh                                     # rsync + 装依赖 + 重启
```

部署后**必须去线上核对**（曾连踩三次「部署成功但没生效」）：

```bash
curl -s https://17tongyou.com/travel/ | grep -o 'assets/index-[^"]*\.js'   # 比对 chunk hash
ssh <server> "sudo -u postgres psql -d travel_agent -c '\d 表名'"          # 加过列的话
```
