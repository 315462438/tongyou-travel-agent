# 协同行程 PRD 评审与分阶段路线图

> 2026-07-18。输入：用户提供的《协同旅行规划 PRD v1.0》（Figma+Notion+GMaps+ChatGPT 愿景）。
> 现状基线：Phase 35/35b（行程板、邀请确认流、AI 起草/串路线/检查、一键导入、轮询协同）。
> 本文=评审意见 + 翻译成现有技术栈的分阶段计划。各阶段动工前照例单写 task plan。

## 一、评审结论

### 采纳（价值高且可在现有栈落地）

| PRD 项 | 评注 |
| --- | --- |
| 三栏布局（Timeline/Map/Copilot） | **最优先**。现在右侧空白=Demo 感的根源 |
| 地图路线展示 + 点击联动 | 有零成本捷径：复用海报的静态地图链路（`/api/staticmap` 后端签名 + 编号 marker），每天一张；互动 JS SDK 放二期 |
| 卡片字段扩展（时间/停留/交通/门票/标签） | 数据模型小改，AI 检查和预算统计的地基 |
| AI Proposal（AI 不直接改 → Preview → Accept/Reject） | **设计上最重要的采纳项**。现 ai/seed 直接覆盖条目，多人场景必须改为提案制 |
| AI 检查中心（结构化 issues + 点击定位） | build_review_facts 已有事实计算，从 Markdown 文本升级为结构化 issue 列表即可 |
| 预算统计 | 有 ticket_price 字段后是纯前端聚合 |
| 评论系统 | 一张表 + 轮询，成本低协同价值高 |
| Presence（谁在看/正在编辑 Day几） | 轻量版：成员心跳（轮询上报 last_seen + 正在编辑的 day），不做光标 |
| 修改记录（Version History 轻量版） | activity log 表（谁何时做了什么）；快照回滚放二期 |
| AI Explain | 挂在 Proposal 上（diff 附带理由），几乎免费 |

### 缓做（价值真实但成本/收益比不划算，二期后）

- **高德 JS SDK 互动地图**（需申请 web-js key + 域名白名单；静态图先验证需求）
- **拖拽排序**（需引 dnd-kit；按钮换序已可用，等三栏布局稳定后加）
- **WebSocket 替代轮询**（轮询在 2-5 人规模够用；等 presence/评论出现明显延迟感再换）
- **实时交通/打车价/公交方案**（高德路径规划 API，替代现在的直线距离——二期第一项）
- **PDF 导出**（已有「导出长图」和手账海报，PDF 边际价值低）
- 酒店/门票预订、航班火车导入、日历同步（PRD 第二阶段原文照收，远期）

### 划掉（此产品形态/规模下不值得做）

- **CRDT/OT + 光标同步**：2-5 人协同用不上，工程量巨大。条目级 last-write-wins +
  presence 提示 + activity log 已覆盖冲突可见性
- **冲突 Merge 弹窗**：同上，发生率太低
- **热力图/卫星图等地图模式**：装饰性
- **Spring Boot/Redis/MinIO/Zustand/Tailwind**：技术栈按现有 FastAPI+PG+React 执行，不迁移

## 二、分阶段计划

### Phase 36 — 三栏布局 + 地图 + 检查中心（把 Demo 变产品的最小闭环）

1. 规划板改三栏：左 Timeline（现有天列改纵向单列）｜中 每日静态地图（编号 marker
   对应卡片序号，复用海报 staticmap 机制；点卡片高亮该天地图、点日切换）｜右 预留 Copilot 栏；
2. Stop 字段扩展：`start_time / stay_min / transport / ticket_price / tags`（迁移加列），
   卡片按 PRD 样式展示（时间线 + ↓ 连接）；
3. 底部 **AI 检查中心**：`ai/review` 从 Markdown 改为结构化 issues
   `[{level, day, stop_id?, text}]`（步行过长/时间冲突/无坐标/备注缺失/预算超标），
   点击 issue 左栏定位闪烁；天气检查用现有高德天气数据（trip 加 start_date 才能对上日期）；
4. 预算条：门票+交通估算合计，超 trip.budget 变红（budget 字段加列）。

### Phase 37 — AI Copilot + Proposal 制

1. 右栏 Copilot：针对本行程的对话（system 注入行程 JSON 上下文，流式回答，
   复用 direct 链路机制）；
2. **提案制改造**：新表 `travel_trip_suggestion`（type/diff_json/status/reason）。
   AI 优化类指令（减少步行/换亲子/降预算…）产出 **diff 提案**（增/删/改/移动的条目列表
   + 每条理由 = AI Explain），前端 Preview（旧→新对照）→ Accept 应用 / Reject 丢弃；
   ai/seed 对非空行程也改走提案（解决现在直接覆盖的粗暴行为）；
3. AI 快捷指令 chips：减少步行 / 降预算 / 亲子化 / 加美食 / 加夜景。

### Phase 38 — 协同深化

1. **评论**：`travel_trip_comment`（trip_id/stop_id/user_id/content），卡片评论气泡 +
   轮询刷新；@成员 用纯文本高亮（不做通知系统）；
2. **Presence**：轮询请求顺带上报 `{editing_day}`，详情返回在线成员及所在 Day，
   头像挂「正在看 Day2」角标；
3. **Activity log**：`travel_trip_event`（who/when/what），底部「修改记录」抽屉；
   写入点=所有 stop 变更 + AI 提案应用；
4. 快照回滚（每次提案应用前存 stops 快照，可一键恢复）——本阶段末尾视余力。

### Phase 39+（远期，按需触发）

高德 JS SDK 互动地图（联动/路线动画）→ 拖拽排序 → WebSocket → 路径规划 API 真实
交通时间 → 预订/导入类集成。

## 三、风险与原则

- 每阶段保持「可独立上线」，不追求一次到位；
- 8G 服务器约束：不引 Redis/MinIO/WS 常驻连接，轮询节奏与现有一致（2.5s 板内、30s 全局）；
- AI 一律提案制后，弱模型输出错误的代价从「改坏共享数据」降为「一次被 Reject 的提案」——
  这是多人场景下最重要的安全阀。
