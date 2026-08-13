# Task Plan — Phase 37/38/39：Copilot 提案制 + 协同深化 + 真实交通时间

## Phase 37 — AI Copilot + 提案制（AI 永不直接改）

- 新表 `travel_trip_suggestion`：id/trip_id/user_id/prompt/reply/diff_json/status
  (pending|answered|applied|rejected|reverted)/snapshot_json/created_at。
- `POST /{id}/ai/copilot` {prompt}：后台 LLM——输入行程 JSON + 指令，结构化输出
  `{reply, changes[]}`（changes 每条含 op=add|update|delete、字段、**reason=AI Explain**）；
  有 changes → status=pending 提案；纯问答 → status=answered。
- `GET /{id}/suggestions`；`POST /{id}/suggestions/{sid}/apply|reject|revert`：
  apply 前存 stops 快照（回滚依据），add op 自动高德补坐标；revert 恢复快照。
- ai/seed 对**非空行程**改走提案（replace_all op），空行程维持直落。
- 前端右栏改 Copilot：快捷指令 chips（减少步行/降预算/亲子化/加美食/加夜景）+
  输入框；提案卡展示 changes 列表（op 徽章 + reason）+ 采纳/拒绝，已采纳可恢复。

## Phase 38 — 协同深化

- **评论**：`travel_trip_comment`（trip_id/stop_id/user_id/content）。卡片 💬 展开
  评论串 + 输入；仅本人可删。
- **Presence**：member 表加 `last_seen/editing_day`；GET 详情顺带上报（?editing_day=），
  members 返回 online（last_seen<8s，轮询 2.5s）与 editing_day；头像绿点 +「在看 DayN」。
- **修改记录**：`travel_trip_event`（trip_id/user_id/action）。写入点：条目增删改、
  串路线、提案采纳/拒绝/恢复、邀请接受。右栏底部「🕘 修改记录」抽屉。

## Phase 39 —（可落地子集）真实交通时间

- `amap.route_time(origin, dest, mode)`：步行/驾车用 v3/direction 接口（现有 REST key），
  返回分钟+公里；公交/地铁回退驾车估、打车=驾车。
- `GET /{id}/segment-times?day=N`：选中天相邻带坐标条目逐段计算（Semaphore 3 限流），
  交通方式取后一条目的 transport（未填按距离启发：>3km 驾车否则步行）。
- 前端：选中天的卡片间显示「↓ 步行 12 分钟 · 0.9km」。
- **明确暂缓**：高德 JS 互动地图（需用户到高德控制台申请 Web 端 JS key + 域名白名单，
  申请后再开工）；WebSocket（轮询在 2-5 人规模够用的结论不变）；拖拽（等 JS 地图一起）。

## 验收（每阶段独立可测）

- 37：copilot 纯问答不产生提案；优化指令产生含 reason 的 diff；apply 后条目变化且
  可 revert；reject 不改数据；非空行程 seed 走提案（自动化）；
- 38：评论 CRUD+权限、presence 在线/所在天、六类操作留痕（自动化）+ 双账号手工；
- 39：segment-times 返回逐段分钟/公里（fake 高德自动化）+ 线上真实展示。
