# 评审意见：PRD 与开发文档

> 评审日期：2026-07-03
> 评审对象：`docs/dev_docs/PRD.md`、`docs/dev_docs/开发文档.md`
> 结论：**整体方向可行，可以开工**。但存在 5 个必须在 Phase 1 前修正的技术硬伤，以及 5 个建议补充的风险项。

---

## 总体评价

两份文档质量不错：

- **亮点**：产品边界（PRD 5.1/5.2/5.3）和 Action Guard 三级风险模型清晰；安全验收标准明确；MVP 范围克制；里程碑拆分合理。
- **主要问题**：Chrome DevTools MCP 的接入细节与真实 API 不符；LangGraph 图设计过于线性；Action Guard 判定逻辑会大量误报；LLM 抽取缺结构化输出保证。

---

## 🔴 必须修正（Phase 1 开工前）

### 1. Chrome DevTools MCP 的工具名是虚构的（开发文档第 11 节）

伪代码中的 `open_page`、`read_page_text`、`screenshot`、按文字 `click(target)` 都不是 chrome-devtools-mcp 的真实工具。实际工具集：

| 类别 | 真实工具 |
|---|---|
| 导航 | `new_page`、`navigate_page`、`list_pages`、`select_page`、`close_page` |
| 读取页面 | `take_snapshot`（返回带 **uid** 的可访问性树，这是读页面文本的主要方式） |
| 交互 | `click`、`fill`、`hover`、`press_key` —— **基于 snapshot 里的 uid 操作**，不是按文字描述点击 |
| 辅助 | `take_screenshot`、`evaluate_script`、`wait_for`、`list_network_requests`、`list_console_messages` |

**修正方案**：`BrowserTool` 封装层改为两步交互模式：

```text
1. take_snapshot → 得到带 uid 的页面结构
2. LLM 从快照中定位目标元素 uid
3. click(uid) / fill(uid, text)
```

第 11 节「不让 Agent 裸调原子工具」的封装思路保留，但接口签名按真实工具重写。

### 2. 「连接正在运行的 Chrome」缺关键操作步骤（开发文档 5.2 节）

要连接用户已登录的 Chrome，必须：

```bash
# Chrome 需以调试端口启动（正常双击打开的 Chrome 连不上）
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir="$HOME/chrome-agent-profile"

# MCP 配置加 --browser-url 参数
npx -y chrome-devtools-mcp@latest --browser-url http://127.0.0.1:9222
```

**安全要求**：必须用 `--user-data-dir` 指定**独立 Chrome profile**（只登录携程/小红书等旅行平台），不要把个人主 profile 的全部登录态（网银、邮箱、密码管理器）暴露给 Agent。MCP 官方明确警告浏览器内容会全部暴露给模型。

### 3. LangGraph 纯线性管道跑不了真实浏览任务（开发文档第 9 节）

`BrowserNode → ExtractNode` 画成单向直线，但实际是「N 个搜索任务 × 每个任务多次浏览」的循环。需要：

1. **循环边**：`BrowserNode ↔ ExtractNode` 之间加条件边，直到 `state.tasks` 队列耗尽再进入 `CompareNode`。
2. **中断-恢复机制**：`need_user_handoff` 时用 LangGraph 的 **checkpointer（SqliteSaver）+ `interrupt()`** 保存状态；`POST /tasks/{id}/continue` 从 checkpoint 恢复执行。没有这个机制，continue 接口无法实现。
3. **异步任务模型**：`/api/agent/run` 返回 task_id 意味着后台异步执行。MVP 用 FastAPI `BackgroundTasks` 起步；进度展示 MVP 用轮询 `GET /tasks/{id}`，后续升级 SSE。

### 4. Action Guard 关键词全文匹配会大量误报（开发文档 10.3 节）

把 `page_text` 全文拿来匹配「登录/订单/收藏」——几乎每个酒店页面都含这些词（页头登录按钮、"收藏酒店"、"支付方式"说明），按此逻辑所有页面都会触发接管，产品不可用。

**修正方案**（三层判定）：

| 层 | 判定对象 | 逻辑 |
|---|---|---|
| 动作分层 | 动作类型本身 | `navigate`/`snapshot`/`screenshot`/`scroll` 永远 low，不看 page_text；只有 `click`/`fill` 才进入下一层检查 |
| 元素判定 | 目标元素自身的文字 + href/URL | 点击目标含「登录/支付/提交订单」或 URL 命中 `/login`、`/checkout`、`/pay` → medium/high |
| 页面状态检测 | 导航完成后的落地页 | 独立于动作守卫：URL pattern + LLM 从 snapshot 判断页面类型（正常内容页 / 登录墙 / 验证码页 / 支付页），落在登录墙 → 触发 handoff |

高风险拦截保持关键词 + URL pattern 双重判断。

### 5. LLM 抽取靠 prompt 要求「输出 JSON」不可靠（开发文档第 12 节）

网页噪声文本下纯 prompt 约束的 JSON 解析失败率高。应使用**结构化输出**。统一封装 LLMClient 时默认走 Claude（Python 后端用官方 `anthropic` SDK）：

```python
# 抽取节点：schema 保证返回合法 JSON，直接得到 Pydantic 对象
response = client.messages.parse(
    model="claude-opus-4-8",
    max_tokens=16000,
    messages=[{"role": "user", "content": extract_prompt}],
    output_format=HotelInfo,  # Pydantic model
)
hotel = response.parsed_output
```

**模型选型**（价格为 $/1M tokens 输入/输出，2026-06 数据）：

| 节点 | 模型 | 价格 | 理由 |
|---|---|---|---|
| 行程生成、酒店对比、任务规划 | `claude-opus-4-8` | $5/$25 | 需要推理质量，配 `thinking={"type": "adaptive"}` |
| 酒店/攻略页面抽取（高频调用） | `claude-sonnet-4-6` | $3/$15 | 抽取任务量大，性价比优先 |
| 偏好解析、页面类型分类 | `claude-haiku-4-5` | $1/$5 | 简单分类，追求快和便宜 |

**注意事项**：

- Opus 4.8 **不接受 `temperature`/`top_p`/`top_k`**（传了直接 400），统一封装层不要硬编码这些参数。
- 系统提示词固定不变的抽取节点加 `cache_control: {"type": "ephemeral"}` 提示词缓存，重复输入费用可省约 90%。
- 大输出（行程生成）用 streaming 避免 HTTP 超时。

---

## 🟡 建议补充的风险项

### 1. 小红书/携程的现实阻力（最大的产品风险）

小红书未登录几乎看不到正文；携程反爬激进。「用户预先登录共享 Chrome」方案正确，但要写明**降级策略**：

```text
小红书被风控 / 内容不可见时：
→ 退回 Google/Bing 搜索博客游记
→ Google Maps 评论与评分
→ 马蜂窝 / 穷游等替代攻略源

建议 Phase 1 验收就用保底路径（公开博客 + Google Maps）打通，
小红书/携程作为增强源而非唯一依赖。
```

### 2. 页面文本的 token 控制

一个酒店列表页 snapshot 可能几万 token。抽取前需要截断/分块策略：按可视区域滚动分批读取；或先用 Haiku 粗筛相关区块再交给 Sonnet 精抽。

### 3. 缺 `travel_task` 表

Agent 任务状态（running / need_handoff / done、当前 URL、错误信息、checkpoint 引用）要落库，否则进程重启后 API 6.3/6.4 无从查询。同时建议加 `revision_history` 表记录多轮修改。

```sql
CREATE TABLE travel_task (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    status TEXT,          -- running / need_user_handoff / done / failed
    current_url TEXT,
    handoff_reason TEXT,
    checkpoint_id TEXT,   -- LangGraph checkpointer 引用
    error TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

### 4. 礼貌性限速

PRD 5.3 已禁止高频抓取，落实到代码：页面间隔随机 2–5s 延迟；同域名串行访问；单任务页面总数上限（如 20 页）。

### 5. 小问题

- PRD 6.2 示例把「新宿」硬编码进搜索词，但住哪个区应该先读攻略才知道 → 任务拆解应两阶段：先攻略定区域 → 再搜该区域酒店。
- `ReviewNode` 出现在第 9 节节点图里，但没进任何 Phase 的任务清单，需归入 Phase 2 或 Phase 4。

---

## 评审结论

| 项 | 结论 |
|---|---|
| 产品定位与边界 | ✅ 通过 |
| 安全设计（Action Guard 概念） | ✅ 通过，实现逻辑需按 🔴4 修正 |
| MCP 接入设计 | ❌ 需按 🔴1/🔴2 重写第 5、11 节 |
| Agent 架构 | ⚠️ 需按 🔴3 补充循环边 + checkpointer + 异步任务模型 |
| LLM 设计 | ⚠️ 需按 🔴5 引入结构化输出与模型分层 |
| 数据库设计 | ⚠️ 建议补 `travel_task` 表 |
| 里程碑 | ✅ 通过，Phase 1 验收建议改为保底路径 |

修正项已吸收进 `docs/task_plans/task_plan-phase1-最小可用版本.md`。
