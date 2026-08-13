# Task Plan：Phase 1 — 最小可用版本（MVP）

> 创建日期：2026-07-03
> 状态：待开发
> 依据：`docs/dev_docs/PRD.md` 第 15.1 节、`docs/dev_docs/开发文档.md`、`docs/dev_docs/评审意见-PRD与开发文档.md`
> 本计划已吸收评审意见中全部 🔴 修正项。

---

## 1. 目标

用户输入一个网页 URL 或简单旅行需求，系统能通过 Chrome DevTools MCP 打开真实 Chrome、读取页面内容，并产出结构化总结（酒店信息 / 攻略信息）。

**Phase 1 验收标准（对应 PRD 15.1，按评审意见调整）**：

```text
1. 输入一个公开网页 URL，系统能打开并总结页面内容
2. 酒店页面 → 输出结构化 HotelInfo JSON
3. 攻略页面 → 输出结构化 TravelNote JSON
4. 验收用保底路径（公开博客 / Google Maps / Booking 英文页），
   不依赖小红书/携程登录态
5. 导航落在登录墙/验证码页时能正确识别并返回 need_user_handoff
   （前端弹窗在 Phase 3，本阶段仅要求后端状态正确）
```

---

## 2. 范围

### 做

```text
后端 FastAPI 骨架（plan / agent / task 三组 API 的最小集）
LLMClient 统一封装（默认 Claude，结构化输出）
MCP Client + BrowserTool 封装（基于真实 chrome-devtools-mcp 工具集）
Action Guard v1（三层判定：动作分层 → 元素判定 → 页面状态检测）
页面读取（take_snapshot → 文本提取 → token 截断）
酒店页面抽取（HotelInfo schema）
攻略页面抽取（TravelNote schema）
travel_task 表 + SQLite 落库
React 前端最小页面（输入框 + 结果展示 + 任务状态轮询）
```

### 不做（后续 Phase）

```text
LangGraph 完整图编排（Phase 2；本阶段用简单顺序调用）
多页面收集 / 行程生成 / 预算（Phase 2）
用户接管弹窗 + continue 恢复（Phase 3；本阶段只返回状态）
酒店对比 / 评分模型（Phase 4）
偏好记忆（Phase 5）
```

---

## 3. 技术方案要点

### 3.1 BrowserTool（吸收评审 🔴1）

基于 chrome-devtools-mcp **真实工具集**封装，两步交互模式：

```text
业务方法                      底层 MCP 工具
open_page(url)          →    new_page / navigate_page + wait_for
read_page()             →    take_snapshot（uid 可访问性树）→ 提取正文文本
find_and_click(desc)    →    take_snapshot → LLM 定位 uid → click(uid)
screenshot()            →    take_screenshot
scroll_and_read()       →    evaluate_script(scroll) + take_snapshot 分批
detect_page_type()      →    URL pattern + Haiku 判断 snapshot 页面类型
```

所有 click/fill 类方法执行前必须过 Action Guard。

### 3.2 Chrome 启动方式（吸收评审 🔴2）

```bash
# 独立 profile，只登录旅行平台，不用个人主 profile
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/chrome-agent-profile"

# MCP 连接该实例
npx -y chrome-devtools-mcp@latest --browser-url http://127.0.0.1:9222
```

写一个 `scripts/start_chrome.sh` 一键启动。

### 3.3 Action Guard v1（吸收评审 🔴4）

```text
第一层（动作分层）：
  navigate / snapshot / screenshot / scroll → ALLOW，直接放行
  click / fill → 进入第二层

第二层（元素判定）：
  目标元素文字或 href 命中高危词/URL（支付、checkout、提交订单）→ BLOCK
  命中中危词/URL（登录、验证码、身份证、/login）→ REQUIRE_HANDOFF
  其余 → ALLOW

第三层（页面状态检测，导航后独立执行）：
  URL pattern（/login、/passport、/verify）→ need_user_handoff
  Haiku 判断 snapshot 页面类型 ∈ {content, login_wall, captcha, payment}
  login_wall / captcha → need_user_handoff；payment → 终止任务
```

### 3.4 LLMClient（吸收评审 🔴5）

```python
# 统一封装，默认 anthropic SDK；不透传 temperature/top_p（Opus 4.8 会 400）
class LLMClient:
    def parse(self, prompt: str, schema: type[BaseModel],
              model: str = "claude-sonnet-4-6") -> BaseModel:
        """结构化输出：client.messages.parse + output_format=schema"""

    def generate(self, prompt: str,
                 model: str = "claude-opus-4-8") -> str:
        """自由文本：行程生成等，adaptive thinking + streaming"""
```

模型分层（2026-07-03 变更：改用 DeepSeek，OpenAI 兼容接口）：

| 用途 | 模型 |
|---|---|
| 页面类型分类、偏好解析 | `deepseek-v4-flash` |
| 酒店/攻略抽取（高频） | `deepseek-v4-pro` |
| 总结/规划类生成 | `deepseek-v4-pro` |

结构化输出实现：`response_format={"type": "json_object"}` + schema 注入 system prompt
+ Pydantic 校验 + 失败带错误重试一次。

### 3.5 Token 控制（吸收评审 🟡2）

```text
snapshot 文本 > 30k chars 时：
  1. 先用 Haiku 粗筛与酒店/攻略相关的区块
  2. 或按滚动分批读取，每批独立抽取后合并
硬上限：单次抽取输入 ≤ 50k tokens
```

### 3.6 任务模型（吸收评审 🔴3 的 Phase 1 子集）

```text
POST /api/agent/run → 创建 travel_task 记录，FastAPI BackgroundTasks 执行
GET  /api/agent/tasks/{id} → 从 travel_task 表读状态
状态机：pending → running → (done | need_user_handoff | failed)
```

LangGraph checkpointer + interrupt 恢复留到 Phase 2/3，本阶段任务不可恢复（失败重跑）。

---

## 4. 涉及模块

```text
backend/
├── app/main.py                    FastAPI 入口
├── app/api/agent_api.py           run / task 状态查询
├── app/llm/client.py              LLMClient 统一封装
├── app/tools/mcp_client.py        MCP stdio 连接管理
├── app/tools/browser_tool.py      BrowserTool 封装
├── app/tools/action_guard.py      三层判定
├── app/agent/extract.py           酒店/攻略抽取
├── app/schemas/hotel_schema.py    HotelInfo (Pydantic)
├── app/schemas/note_schema.py     TravelNote (Pydantic)
├── app/db/models.py               travel_task / travel_page 表
└── scripts/start_chrome.sh        Chrome 独立 profile 启动脚本

frontend/
└── src/pages/Home.tsx             URL 输入 + 结果展示 + 状态轮询
```

---

## 5. 开发顺序

```text
1. LLMClient 封装 + 单测（mock API）
2. MCP Client 连接 chrome-devtools-mcp，验证 take_snapshot / navigate_page
3. BrowserTool 封装 + Action Guard v1
4. 页面读取 + token 截断
5. 酒店/攻略抽取（结构化输出）
6. FastAPI 任务 API + travel_task 表
7. React 最小前端
8. 端到端联调 + 测试用例（docs/test_cases/）
```

---

## 6. 验收测试用例（完成后落地到 docs/test_cases/）

| # | 用例 | 预期 |
|---|---|---|
| 1 | 打开 Booking 某酒店公开页 | 返回含 name/price/rating 的 HotelInfo |
| 2 | 打开一篇公开旅行博客 | 返回含 spots/tips 的 TravelNote |
| 3 | 打开需登录的小红书正文页 | detect_page_type=login_wall，任务状态 need_user_handoff |
| 4 | 构造含「立即支付」按钮的点击请求 | Action Guard 返回 BLOCK |
| 5 | 普通页面 navigate + snapshot | Action Guard 全部 ALLOW，无误报 |
| 6 | 超长页面（>30k chars） | 截断/分批逻辑生效，抽取不报错 |
| 7 | LLM 返回与 schema 校验 | messages.parse 输出通过 Pydantic 校验 |

按 CLAUDE.md 规范：**以上用例全部通过，Phase 1 才算「初步完整」**。

---

## 7. 风险与预案

| 风险 | 预案 |
|---|---|
| 小红书/携程风控 | 验收用保底路径（博客/Google Maps/Booking）；小红书作为增强源 |
| chrome-devtools-mcp 版本变动 | 锁定版本号（不用 @latest），升级前先跑用例 3/5 |
| snapshot 文本噪声大 | Haiku 粗筛 + 分批抽取；踩坑记入 docs/pitfalls/ |
| MCP stdio 连接不稳定 | mcp_client 加重连逻辑；连接失败任务标记 failed 而非挂死 |

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-07-03 | 初版，吸收评审意见全部 🔴 修正项 |
| 2026-07-03 | LLM 由 Claude 切换为 DeepSeek（v4-pro 主力 / v4-flash 分类），结构化输出改为 json_object + Pydantic 校验重试 |
| 2026-07-03 | 数据库改为 SSH 隧道连接远程 PostgreSQL（见 docs/pitfalls/远程PostgreSQL公网直连被重置.md） |
