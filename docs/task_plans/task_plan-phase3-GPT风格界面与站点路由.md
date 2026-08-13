# Task Plan — Phase 3：GPT 风格界面 + 站点路由（携程/小红书 + 用户自行登录）

> 创建：2026-07-06　状态：已完成（自动化 15 例 + 端到端冒烟通过）

> 追加实现：助手消息下方的「🌐 参考了 N 个网站」可展开来源列表（GPT Sources 样式）。
> 开发中踩坑 3 个，见 `docs/pitfalls/db_tunnel误判隧道存活.md`、
> `docs/pitfalls/调试Chrome无标签页导致NoPageSelected.md`（含 HTTP_PROXY 连带坑）。

## 目标

1. **前端全面对齐 ChatGPT 的展现格式**（参考用户提供的 ChatGPT 截图）：
   - 左侧侧边栏：应用名、「新对话」按钮、历史会话列表（点击切换会话）。
   - 空态：主区域居中大标题（类 "Where should we begin?"）+ 居中胶囊输入框 + 建议按钮。
   - 会话态：消息流居中限宽；用户消息为右侧浅灰圆角气泡；助手消息为无气泡的全宽
     Markdown 正文（GPT 风格）；思考过程为正文上方灰色「已深度思考 ▸」可折叠块。
   - progress 消息渲染为灰色状态行（最新一条带转圈动画）。
   - 底部composer：圆角胶囊输入框 + 圆形上箭头发送按钮，下方小字提示。
2. **站点路由**：根据用户意图 / 流程所处环节，把 Agent 浏览器导航到指定站点：
   - 酒店/住宿相关 → 打开**携程**（hotels.ctrip.com 关键词搜索页）；
   - 路线/行程规划/攻略相关 → 打开**小红书**（xiaohongshu.com 搜索页）；
   - 命中登录墙时**不再跳过**，而是向对话流写入「handoff 卡片」消息，提示用户在
     Agent 调试 Chrome 窗口中自行登录；后台轮询页面状态，登录完成后自动继续抓取；
     超时则回退到必应公开搜索，不阻塞整体流程。

## 方案

### 后端

- `app/schemas/chat_schema.py`：`Preference` 增加 `intent` 字段
  （`hotel` / `route` / `general`），由 PreferenceNode 一并抽取；另提供纯规则兜底
  `detect_intent_by_rules()`（关键词：酒店/住宿/民宿… → hotel；路线/行程/规划/攻略… → route）。
- 新增 `app/agent/site_router.py`：
  - `SiteTarget`：site key（ctrip/xhs）、显示名、搜索 URL 构造。
  - `route_for_intent(intent, destination)` → `SiteTarget | None`。
  - `collect_via_site(cid, pref, target, browser_factory)`：
    打开站点搜索页 → `open_page` 三层守卫检测：
    - `ok` → `scroll_and_read` → `summarize_page` → 返回 sources；
    - `need_user_handoff` → 写入带 `meta.handoff` 的 progress 消息（前端渲染卡片），
      轮询（默认每 6s，共 `handoff_wait_s`=180s）重新检测页面；用户登录完成后继续抓取；
      超时返回空列表。
    - 服务器 headless 模式（`chrome_executable` 非空，用户看不到浏览器）→ 不等待，
      写说明性 progress 后直接返回空列表回退搜索。
- `app/config.py`：新增 `site_routing_enabled: bool = True`、`handoff_wait_s: int = 180`、
  `handoff_poll_s: float = 6.0`。
- `app/agent/orchestrator.py`：
  - 解析偏好后：`intent=hotel` → progress「打开携程…」→ 站点抓取，成功来源并入 sources；
    `intent=route` → 同样走小红书；站点来源不足时回退/补充必应搜索（现有逻辑不变）。
  - `intent=hotel` 时改用 `HOTEL_SYSTEM` 生成酒店推荐（清单式：位置/价位/优缺点/适配理由），
    其他 intent 仍用 `ITINERARY_SYSTEM`。
  - 多轮修改（复用来源）逻辑保持不变，不重复路由。
- 关键不变式保持：navigate/snapshot 只读放行；登录墙处置继续复用 Action Guard 第三层；
  MCP isError 抛异常；LLM 结构化走 `parse()`。

### 前端

- `Home.tsx` 重写为 GPT 风格布局（sidebar + main），新增：
  - 会话列表（`GET /api/chat/conversations`）、切换会话加载消息、新对话。
  - `meta.handoff` 的 progress 消息渲染为「请在浏览器中登录 携程/小红书」卡片
    （站点名、说明文案、等待动画）。
  - 思考块、progress 行、composer 均按 GPT 视觉重做（浅色主题）。
- `index.css` 全局样式配套更新；保留导出长图能力。

## 涉及模块

backend: `config.py`、`schemas/chat_schema.py`、`agent/site_router.py`（新）、
`agent/orchestrator.py`；frontend: `src/pages/Home.tsx`、`src/index.css`、`src/App.css`。

## 验收标准

1. 输入「帮我查成都的酒店」→ progress 显示「已识别酒店需求，正在打开携程」，
   本地可见 Chrome 导航到携程；命中登录墙时对话流出现登录提示卡片；
   登录后自动继续；超时回退必应搜索并最终产出酒店推荐。
2. 输入「帮我规划成都3天的路线」→ 同上，站点为小红书，最终产出攻略。
3. 界面：侧边栏会话列表可切换；空态居中标题+胶囊输入；用户右气泡/助手全宽正文；
   思考可折叠；发送后底部 composer 固定。
4. `backend/tests/` 新增 `test_site_router.py` 全部通过，存量测试不回归。

## 测试

- 单测（无网络、mock browser/LLM）：intent 规则兜底、URL 构造（URL 编码）、
  handoff 等待循环（fake browser 先返回 need_user_handoff 再返回 ok）、
  headless 模式直接跳过、超时返回空。
- 手工验收：本地起前后端跑上述两条用例。
