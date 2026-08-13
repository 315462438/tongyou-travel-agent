# Phase 68 — 接口鉴权收口 + 追问熔断 + 小红书工具白名单

> 触发：用户反馈 Agent 陷入反复追问；顺带审计站点登录隔离时，
> **发现 `/api/agent/run` 在公网完全无鉴权**（线上实测无 token 返回 422 而非 401）。
> 用户明确要求：「系统和 LLM 安全必须第一，不可能绕过登录直接访问接口这种情况」。

## 一、全量路由鉴权审计结论（AST 扫描，非正则）

| 路由 | 现状 | 处置 |
| --- | --- | --- |
| `POST /api/agent/run` | ❌ 无鉴权，可驱动服务端浏览器访问任意 URL | **P0 修复** |
| `GET /api/agent/tasks/{id}` | ❌ 无鉴权、无归属校验 | **P0 修复** |
| `POST /api/auth/register`、`/login` | 无鉴权 | ✅ 合理，必须公开 |
| `GET /api/chat/{cid}/handoff-screenshot` | 无鉴权 | ✅ 合理，`<img>` 不能带 header，cid 不可猜（Phase 15 既有决策） |
| `GET /api/img`、`GET /api/staticmap` | 无鉴权 | ✅ 合理，同上；已有 SSRF 白名单 |
| `GET /api/trips/shared/{token}`、`/t/{code}` | 无鉴权 | ✅ 合理，分享短链设计即公开，token 不可猜 |
| `GET /api/sandbox/{batch_key}/{filename}` | 无鉴权 | ✅ 已有段校验 + abspath 双重保险，无路径穿越 |

其余 60+ 路由均已带 `Depends(get_current_user)`。**真实缺口只有 agent_api 两条**（Phase 1 遗留，
Phase 15 加鉴权时漏掉）。

## 二、反复追问死循环（真实现场）

用户连续 4 轮被问同一个问题，即使明说「你安排一个比较热门的」（＝授权代选）仍被追问。

**根因三条叠加：**

1. `orchestrator.py:674-682` 确定性护栏：`destination` 为空即强制反问并 `route=clarify` → 图直接 END。
2. `_DEST_PLACEHOLDERS`（`orchestrator.py:264-271`）把「热门目的地」这类占位词清成空——
   Phase 59.2 为防必应搜出垃圾而加，但**没区分「模型幻觉占位词」和「用户主动授权代选」**，
   于是授权被转译成"信息缺失"。
3. `_is_clarify_continuation`（`:283-306`）判定「上条 assistant 是 ≤60 字问号结尾」即锁死走 guide，
   而反问自身正好满足该特征 —— **反问制造了下一轮走进反问的条件，闭环**。
4. **完全没有追问次数熔断**（`graph_max_guide_rounds` 是攻略生成后的 critique 循环，无关）。

已排除：历史是带进去的（近 5 轮逐字，`:655`），不是上下文丢失。

## 三、方案

### P0-1 接口鉴权
- `agent_api` 两条路由加 `Depends(get_current_user)`。
- `TravelTask` 加 `user_id` 列（`db/migrate.py` 幂等加列，存量置 admin），
  `/run` 落库时写入，`/tasks/{id}` 校验归属，非本人一律 404（不泄露存在性）。

### P0-2 追问熔断 + 授权代选
- `Preference` 加 `let_agent_decide: bool` —— 显式建模「你决定/随便/挑个热门的/都行」。
- `PREF_SYSTEM` 增补：识别授权表达时置 `let_agent_decide=true`，并**自己从上一轮候选里选一个**填 destination。
- `parse_request` 空目的地分支改为**三级降级**：
  1. `let_agent_decide` 为真 → 从历史候选代选；
  2. 连续 clarify 次数 ≥ `clarify_max_rounds`(2) → **强制代选**（LLM 从历史挑一个具体地名），
     并在攻略开头说明「先按 X 安排，不合适随时换」；
  3. 都不满足才反问。
- 追问计数：查库统计**本会话末尾连续的 clarify 轮数**（不引入新表；clarify 回复特征已有
  `_is_clarify_continuation` 可复用），避免加状态字段带来的 checkpoint 兼容问题。
- 反问文案兜底加一句「也可以直接说『你定』，我来挑」，给用户明确出路。

### P1 小红书工具白名单
`xhs_mcp` 是**全局共享单账号**（`/home/ubuntu/xhs-mcp-data/cookies.json`，无 user_id 维度）。
完整的按用户隔离改造大（要每用户 cookie + 扫码 API），本期先做**强制只读白名单**：
`_call_tool` 只允许 `search_feeds` / `get_feed_detail`，其余一律拒绝并告警——
防止 MCP 端将来暴露写工具（收藏/私信/发布）时任意登录用户可用运维账号身份操作。

### P2 清理与订正
- 停用线上仍 `active` 的 `travel-chrome.service`（池外旁路，`/api/agent/run` 就落在它上面）。
- 订正 CLAUDE.md：`site_login_ttl_min=60` 在池模式下是**死代码**，实际登录态寿命 ≈ 站点 cookie
  （携程约 13 个月、小红书约 1 年），profile 永不删除、跨重启保留。

## 四、验收标准

1. 无 token 请求 `/api/agent/run`、`/api/agent/tasks/{id}` 返回 **401**（当前是 422/200）。
2. 带 token 但访问他人 task 返回 404。
3. 存量 `travel_task` 迁移后归 admin，迁移可重复执行不报错。
4. 连续追问不超过 `clarify_max_rounds`(2) 次，第 3 轮必定给出具体方案。
5. 「你安排一个热门的」「随便」「你定」→ 直接代选，不再反问。
6. 小红书非白名单工具调用被拒绝并记 warning。
7. 全量 pytest 通过；新增 `tests/test_agent_api_auth.py`、`tests/test_clarify_guard.py`、
   `tests/test_xhs_whitelist.py`。

## 五、不做

- 小红书按用户隔离（需每用户 cookie 存储 + 扫码 API + MCP 改造，另开 Phase）。
- 把 `<img>` 类公开端点改成带签名 token（当前 cid/token 不可猜，风险可接受）。
