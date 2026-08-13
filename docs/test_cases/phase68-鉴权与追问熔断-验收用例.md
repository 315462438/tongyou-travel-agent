# Phase 68 接口鉴权 + 追问熔断 + 小红书白名单 — 验收用例

自动化测试（31 例新增，全部离线）：

```bash
cd backend && .venv/bin/python -m pytest \
  tests/test_agent_api_auth.py tests/test_clarify_guard.py tests/test_xhs_whitelist.py -q
```

全量回归：`507 passed`。

## 一、接口鉴权（`tests/test_agent_api_auth.py`，7 例）

| 用例 | 断言 |
| --- | --- |
| `test_run_records_owner` | `/run` 落库写入 `user_id`，后台任务已排队 |
| `test_owner_can_read_own_task` | 本人可读自己的任务 |
| `test_other_user_cannot_read_task` | 他人读 → **404**（非 403，不泄露存在性） |
| `test_missing_task_is_404` | 不存在的 task → 404 |
| `test_orphan_task_not_readable` | `user_id` 为空的历史任务不可被任意登录用户读到 |
| **`test_no_unguarded_routes`** | **AST 扫全部 `*_api.py`：任何路由缺 `get_current_user` 即失败**，除非登记进 `PUBLIC_ROUTES` |
| `test_public_route_registry_has_no_stale_entries` | 公开路由登记表不许留过期条目（防登记表变摆设） |

> `test_no_unguarded_routes` 是本期最重要的产出：它把「不能有绕过登录的接口」变成
> **CI 强制约束**，而不是靠人记得。

### 线上实测（已执行）

| 端点 | 修复前 | 修复后 |
| --- | --- | --- |
| `POST /travel/api/agent/run` | **422**（已进参数校验＝无鉴权） | **401** ✅ |
| `GET /travel/api/agent/tasks/{id}` | 200 | **401** ✅ |

迁移验证：`travel_task.user_id` 列已建，13 条存量任务 **0 条无主**（全部归 admin）。

## 二、追问熔断（`tests/test_clarify_guard.py`，13 例）

| 用例 | 断言 |
| --- | --- |
| `test_is_clarify_text`（5 参数） | ≤60 字问号结尾＝追问；正文/空串不是 |
| `test_counts_consecutive_clarifies` | 末尾连续追问计数正确，遇正文即停 |
| `test_zero_when_last_is_normal_reply` | 最后一条是正文 → 0 |
| `test_placeholder_and_panel_messages_are_skipped` | 流式占位/海报/预算面板不打断计数 |
| `test_count_failure_returns_zero` | 查库异常 → 0（**宁可不熔断，不误熔断成乱代选**） |
| `test_decide_destination_returns_pick` | 代选返回具体地名 |
| `test_decide_destination_rejects_placeholder` | 代选也不许返回占位词（防 Phase 59.2 那个坑复发） |
| `test_decide_destination_survives_llm_failure` | LLM 挂了返回空 → 回落反问 |
| `test_normalize_destination_placeholders` | 占位词归一为空 |

## 三、小红书白名单（`tests/test_xhs_whitelist.py`，11 例）

| 用例 | 断言 |
| --- | --- |
| `test_write_tools_rejected`（7 参数） | publish_content / publish_with_video / post_comment_to_feed / reply_comment_in_feed / like_feed / favorite_feed / delete_cookies 一律拒绝 |
| `test_unknown_tool_rejected` | 未知工具名拒绝（MCP 将来新增写工具默认不放行） |
| `test_whitelist_is_exactly_readonly_pair` | 白名单保持最小：只有 search_feeds / get_feed_detail |
| `test_rejection_happens_before_network` | **拒绝发生在建连之前**，不发出任何请求 |
| `test_production_call_sites_use_whitelisted_tools_only` | 源码级：`_call_tool` 调用点只出现白名单字面量 |

## 四、手工验收清单（线上）

1. **追问熔断**：新开会话说「我想出去玩」→ 反问；答「其他」→ 第二次反问（文案应带
   「也可以直接说『你定』」）；再答「你安排一个热门的」→ **必须直接出方案，不得再问**，
   且攻略开头应说明「先按 X 安排，不合适随时换」。
2. **授权代选（快路径）**：直接说「你帮我挑个地方，随便」→ 一次到位不反问。
3. **鉴权**：退出登录后直接访问 `/travel/api/agent/tasks/任意id` → 401。
4. **小红书功能未受影响**：正常生成一份带图攻略，图片仍能出（白名单不影响读路径）。
5. **停用旁路后功能正常**：`travel-chrome` 已 stop+disable，:9222 关闭；
   携程扫码链路（走每用户池）仍正常。

## 五、已知边界

- 代选依赖历史里有候选或用户给了约束；两者皆无时仍会反问（此时反问是正确行为）。
- 小红书仍为**全平台共享单账号**（本期只加只读白名单，不做租户隔离，理由见 task plan）。
- `<img>` 类端点（img/staticmap/handoff-screenshot）与分享短链保持公开，
  依赖「cid/token 不可猜」，已在 `PUBLIC_ROUTES` 显式登记。
