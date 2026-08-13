# Task Plan — Phase 50：开发清单（18 项，按优先级分批）

用户提供的下一轮开发清单，按建议实施顺序分批做，每批部署验证后再往下。

## 批次 1（本批，已完成）：两个 P0

### P0-1 部署后「导入协同行程」整页空白
- 根因：`deploy.sh` 用 `rsync --delete` 每次删掉服务器上旧哈希 chunk；已打开页面点
  lazy chunk（Trips.tsx 独立 chunk）→ 404 → 白屏。
- 修复：
  - `deploy.sh`：代码同步排除 static，static 单独 rsync **不带 --delete**（新旧 chunk 并存）；
  - `main.tsx`：监听 `vite:preloadError` → 自动刷新一次（sessionStorage 防死循环）。
- 验收：旧页面跨版本操作不白屏，最差自动刷新恢复。✓

### P0-2 快速回答在酒店介绍中途截断
- 根因：direct 快答 `max_tokens=2000`（≈1500 字），长攻略写到酒店就到顶；前端/后端
  都没识别截断。
- 修复：
  - direct max_tokens 2000→4000；
  - `stream_generate_with_reasoning` 末块 yield `('finish', reason)`；direct/guide 消费方
    据此识别 `length` 截断，**不静默**——补一段「已截断，开深度推理拿完整版 / 分段生成」说明；
  - guide 流式同步跳过 finish 信号（否则把 reason 追加进正文）。
- 验收：截断必有明确提示 + 完整版路径。✓（force-guide 那条见下）

## 后续批次（待做，按用户建议顺序）

**批 2 — 路由 + 一键深度重试（P1）✓ 已完成**
- 后端 `orchestrator.run_conversation_turn` 的快答提示 progress 携带 `meta.hint_prompt=user_text`
  （存原问题）；文案由「请打开开关重新提问」改为「点下方按钮用深度模式重新回答」。
- 前端 `Home.tsx`：
  - 新增 `regenerateDeep(text)`——`enableDeep()` 点亮开关 + 在**当前会话**用 `deep_reasoning:true`
    重发原问题（复用 send 的 POST 路径），不用复制粘贴；
  - 提示卡按钮改为「🧠 用深度模式重新回答（约 2-6 分钟）」，`disabled={running}` 防重复点；
    仅当 `meta.hint_prompt` 存在时显示（旧消息无该字段回退老「打开深度推理」按钮，兼容历史）。
  - `Msg.meta` 类型加 `hint_prompt?: string`。
- 验收：点击一次即可用深度模式重新生成，无需复制粘贴；预计耗时标注在按钮上。✓
- （可选）「规划+天数+酒店/预算」重需求快思考给概览而非硬答：仍不强制 guide（尊重 Phase 44
  开关），靠 P0-2 截断提示 + 本批一键深度兜底形成闭环。

**批 3 — 结构化导入（P1）✓ 已完成**（详见 task_plan-phase51-结构化导入.md）：
攻略导入扩展 `TripDraft.stays[day,city,hotel,price,source]` + `budget_items[category,amount]`
→ 住宿落 🏨 stop（带 ticket_price，住宿面板显示酒店名+¥价格）、预算归一到六类落
`travel_trip.budget_breakdown_json`（费用 tab 显示「计划预算（按类别）」）。攻略没写则留空、不虚构。

**批 4 — 路线检查计算（P1）✓ 已完成**：
- `trip_planner.classify_days(stops, total_days)`：每天定性 stay/transit/return + overnight_required
  + span_km（几何+是否末日，零成本可测）。transit=首末点直线≥60km 的城际赶路日；return=末日不过夜。
- `build_issues`：里程改逐腿**道路估算**（直线×1.4，`_day_legs`），步行告警只在 stay 日判（转移/返程
  大里程不误报），告警带 `detail`「计算依据：A→B x.xkm…」；transit 日出 info「城际转移日」。
  保留检查中心「零成本即时」不变式（不引入 amap 实时调用，实测每段真实数据仍走 segment-times）。
- `/issues` 传 total_days；`/day-cities` 返回 `day_types`+`overnight`。
- 前端：检查中心告警渲染 detail 副行；住宿 tab 返程日（overnight=false）显示「返程日 · 无需住宿」
  不再提示查酒店。
- 取舍：「统一用地图路线腿」按「分腿道路估算 + 附计算依据」落地，而非给高频轮询的 /issues 挂
  amap 实时请求（违背零成本不变式）；精确实拉仍在 segment-times 按需触发。

**批 5 — 日期追问 + 实时数据可信度（P1）✓ 已完成**（详见 task_plan-phase52-实时数据可信度.md）：
新增 `app/agent/realtime_guard.py`（realtime_kind / extract_travel_date / credibility_directive，
纯函数可测），在 `generate_guide_streaming` + `run_direct_answer` 注入可信度纪律——酒店/交通类无日期
→ 标「参考价（非实时）」+ 先追问日期；有日期 → 标查询日期+来源。HOTEL_SYSTEM 加预算硬约束
（超预算单列「上浮备选」）。取舍：不接真·铁路/航空抓取（诚实标参考、引导补日期走实时链路），
amap 板酒店无价格不做过滤。

**批 6 — 长行程导航 / 历史会话 / 进度展示（P2）+ admin 口令（P1）✓ 已完成**
（详见 task_plan-phase53-P2收尾与admin口令.md）：
- ✅ admin 默认口令强改（P1）：must_change_password 标志 + change-password 端点 + 顶部横幅内联改密。
- ✅ 高原/健康建议去绝对化（HEALTH_POLICY 追加三 prompt）。
- ✅ 历史会话标题去重（同名附 · MM-DD）。
- ✅ 地图默认中心=首个有坐标的日。
- ✅ 长行程左栏折叠非当前日。
- ⏸ 延后：阶段进度条、携程侧抽屉回板（UI 工作量大/收益偏观感，单开一轮再做）。

---
## 清单总结
批 1-6 全部落地（P0×2 + P1×多 + P2 主要项），仅「阶段进度条」「携程侧抽屉回板」两个 P2 观感项延后。
每批：task plan → 实现 → 单测 → 构建 → 部署 → 线上健康验证，全程遵循 CLAUDE.md 强制流程。

## 明确取舍
- P0-2 的「强制 guide」暂不做：与 Phase 44（快/慢由用户开关掌控）冲突。改为「截断必提示
  + 一键深度重试（批 2）」——既不静默截断，也不夺走用户对速度的控制权。
