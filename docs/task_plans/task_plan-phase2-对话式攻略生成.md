# Task Plan：Phase 2 — 对话式自主攻略生成

> 创建日期：2026-07-03
> 状态：待确认 → 待开发
> 依据：PRD 全文（回归原始愿景）、用户 2026-07-03 明确的产品方向

## 0. 产品形态转变（本阶段核心）

从「输入 URL 分析单页」升级为「**对话式旅行攻略 Agent**」：

```
用户在对话框输入「我想去成都玩3天，喜欢美食，不想太累」
  → Agent 解析需求
  → 自动拆解搜索任务（成都攻略/景点/美食/住宿/交通）
  → 用搜索引擎为主，逐个查询、打开、抓取多个来源
  → 汇总多来源信息
  → 生成图文攻略（每日行程/景点/美食/预算）在对话流中展示
  → 用户可继续追问「第二天太累了」「预算再低点」→ 重新规划
  → 可一键导出为长图
```

交互参照 GPT/Claude 网页版：单一对话框，流式进度，多轮上下文。

## 1. 用户已确认的关键决策

| 项 | 决策 |
|---|---|
| 输出形态 | **两者都要**：对话流中先出图文攻略（Markdown 渲染），再提供「导出为长图」按钮 |
| 数据源优先级 | **搜索引擎优先 + 按需深入**：必应/百度搜公开攻略博客 + 高德/Google Maps 评论为主；小红书/携程作增强，遇登录/验证码时提示用户接管 |
| 推进方式 | 先写本 task plan，确认后开发 |

## 2. 复用现有资产（Phase 1 成果）

```text
✅ ChromeMCP / BrowserTool（两步交互、限速、截断、页面类型检测）
✅ Action Guard 三层判定（登录墙/验证码/支付识别与接管）
✅ LLMClient（DeepSeek v4-pro/v4-flash，parse 结构化 + generate 文本）
✅ 抽取模块（HotelInfo / TravelNote / 页面总结）
✅ 数据库（travel_plan/task/page/hotel/note）+ 远程 PostgreSQL
✅ 部署架构（nginx /travel/ 反代 + systemd + headless Chrome）
```

## 3. 新增能力

### 3.1 对话交互层

- **前端**：聊天界面（消息气泡、输入框、流式进度、Markdown 渲染、导出按钮）
- **后端**：会话与消息持久化，多轮上下文
- **新表**：
  ```sql
  travel_conversation(id, title, created_at, updated_at)
  travel_message(id, conversation_id, role, content, reasoning, meta_json, created_at)
  -- role: user / assistant / progress（进度气泡）
  -- reasoning: 该条 assistant 消息对应的模型思考过程（可折叠展示）
  ```

### 3.1.1 思考过程展示（类 GPT/Claude 可展开）

用户明确要求：对话界面像 GPT/Claude 一样，点击可展开模型的具体思考过程。
分两层，都做成可折叠 UI：

1. **模型思考**（`reasoning_content`）——已验证 DeepSeek v4-pro/v4-flash **都返回**
   `message.reasoning_content`，质量高（能看到需求拆解、路线权衡）。
   - `LLMClient.generate_with_reasoning()` 返回 `(正文, 思考)`（已实现）
   - 关键节点（TaskPlanNode 拆解、ItineraryNode 规划）的思考存入 `travel_message.reasoning`
   - 前端每条 assistant 消息上方放「🧠 思考过程」可折叠块，默认收起
2. **Agent 执行轨迹**——`progress` 角色消息，实时展示
   「正在解析需求 → 搜索成都攻略 → 打开第3个页面 → 汇总5个来源」，
   也可折叠为一个「执行过程」时间线。

### 3.2 Agent 编排（LangGraph 真正用起来）

Phase 1 是单页顺序调用；Phase 2 用 LangGraph 图 + checkpointer：

```text
PreferenceNode   解析对话 → 结构化偏好(destination/days/budget/pace/interests)
      ↓
TaskPlanNode     偏好 → 搜索任务列表(guide/spot/food/hotel/transport)
      ↓
SearchLoop       对每个任务：搜索引擎查询 → 打开前 N 个结果 → 抓取 → 抽取
      ↓ (need_handoff 时中断，checkpointer 保存，等用户接管后 continue)
AggregateNode    多来源去重、合并、按主题归类
      ↓
ItineraryNode    生成每日行程 + 景点 + 美食 + 预算(generate 长文本)
      ↓
ReviewNode       检查是否太累/绕路/超预算
      ↓
最终 Markdown 攻略 → 存 message → 流式推给前端
```

多轮修改：用户追问 → 带上会话历史 + 已有攻略 → 重跑 ItineraryNode（不必重新搜索）。

### 3.3 搜索引擎驱动的抓取（数据源优先级落地）

```text
BrowserTool 新增 search_web(query)：
  打开 https://www.bing.com/search?q=<query>
  take_snapshot → 提取前 N 条结果的标题+链接
  过滤：优先博客/游记/地图；跳过需登录站点（除非用户已在共享 Chrome 登录）
逐个 open_page 抓取 → 页面类型检测 → 抽取
遇 login_wall/captcha → 记录该来源为「需接管」，跳过继续下一个（不阻塞整体）
  仅当用户主动要求深入某平台时才触发接管流程
```

### 3.4 攻略输出

- **图文攻略**：Markdown（每日行程表、景点/美食清单、预算表、避坑提示、来源链接）
- **对话流展示**：前端 Markdown 渲染（`react-markdown`）
- **导出长图**：前端 `html2canvas` 把攻略 DOM 截成 PNG 下载（纯前端，无需服务器渲染）

## 4. API 设计（新增/调整）

```text
POST /api/chat/conversations            创建会话
POST /api/chat/{cid}/messages           发用户消息 → 启动 agent 任务
GET  /api/chat/{cid}/messages           拉取消息（含进度、攻略）
GET  /api/chat/{cid}/stream (SSE)       流式进度与增量攻略（可选，先轮询起步）
POST /api/chat/{cid}/tasks/{tid}/continue  用户接管完成后继续
```

## 5. 开发顺序

```text
1. 数据表 travel_conversation / travel_message + 会话 API
2. 前端对话界面（消息流 + 输入框 + 轮询）—— 先能来回对话
3. PreferenceNode + TaskPlanNode（需求→搜索任务）
4. BrowserTool.search_web + 搜索结果解析
5. SearchLoop（多任务多页面抓取，含 need_handoff 跳过策略）
6. AggregateNode + ItineraryNode（汇总→图文攻略）
7. 攻略 Markdown 渲染 + 多轮修改
8. 导出长图（html2canvas）
9. LangGraph checkpointer 接入 + continue 接管恢复
10. 端到端测试 + docs/test_cases/phase2 落档
```

## 6. 验收标准

```text
1. 对话输入「我想去成都玩3天」→ 产出一份含 3 天行程的图文攻略
2. 攻略包含：每日行程、景点、美食、预算估算、来源链接
3. 追问「第二天太累」→ 重新生成更轻松的第二天，不重复全量搜索
4. 搜索过程中遇登录墙的来源被跳过，不阻塞整体产出
5. 攻略可导出为一张长图
6. 全过程无自动下单/支付/登录（安全边界不变）
```

## 7. 风险与预案

| 风险 | 预案 |
|---|---|
| 必应/百度搜索页反爬 | 多引擎轮换；抓不到时退回直接构造已知攻略站 URL |
| 单次任务耗时长（多页面抓取） | 限制每任务抓取页数（3-5）；SSE 或进度气泡让用户看到进展；DeepSeek 长任务异步 |
| 多来源信息矛盾/噪声 | AggregateNode 去重 + 让模型标注来源；攻略附来源链接供核对 |
| 抓取质量参差 | 优先高信息密度页面；页面总结兜底（Phase 1 已有） |
| token 成本上升（多页面+长攻略） | 抽取用 flash 粗筛、pro 精抽；搜索结果先筛后抓 |

## 8. 不做（留待 Phase 3+）

```text
自动下单/支付/登录（永久禁止，安全边界）
真正的用户接管弹窗完整流程（Phase 3；本阶段先做「跳过需登录来源」）
偏好长期记忆（Phase 5）
多用户系统
```

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-07-03 | 初版：产品转向对话式自主攻略生成，吸收用户三项决策 |
