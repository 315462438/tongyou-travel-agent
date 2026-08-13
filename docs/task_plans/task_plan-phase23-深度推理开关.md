# Phase 23 — 深度推理开关（用户掌控研究模式 + 复杂问题提示）

## 背景

深度研究（Phase 21）一轮 4-6 分钟，此前由路由器自动判入——用户没有预期就被拖进长等待。
产品上应该把「是否进入慢而深的模式」交给用户：composer 加**深度推理开关**；
路由判为复杂问题但开关未开时，**弹提示建议打开**，本轮先用普通流水线快速作答。

## 方案

### 路由语义（`deep_research.resolve_route(user_text, llm, deep_reasoning)`）

| 开关 | 分类结果 | 行为 |
| --- | --- | --- |
| ON | （跳过分类） | 直接 research（`deep_research_enabled=false` 则降级 guide） |
| OFF | research | **guide + 提示消息**「💡 适合深度推理，建议打开开关重新提问」 |
| OFF | direct / guide | 照旧 |

即：**research 只经开关进入，不再自动触发**（行为变更，写入 CLAUDE.md）。

### 后端
- `SendMessageRequest` 加 `deep_reasoning: bool = False`；`send_message` 透传。
- `run_conversation_turn(..., deep_reasoning=False)`：调 `resolve_route`；
  suggest 时写带 `meta.hint="deep_reasoning"` 的 progress（带 meta → 终稿后不被
  `clear_plain_progress` 清掉，提示常驻本轮）。

### 前端
- Composer 内加「🧠 深度推理」胶囊开关（running 时禁用），状态存 localStorage；
  发送体带 `deep_reasoning`。
- `meta.hint === "deep_reasoning"` 的 progress 渲染为提示卡：文案 + 「打开深度推理」
  按钮（点击直接置开关为开，提示"已开启，重新发送问题即可"）。

## 验收
1. 开关关 + 复杂问题（对比/预算）→ 走 guide 快速回答 + 出现提示卡；点卡上按钮开关变开。
2. 开关开 + 同问题 → 进研究模式（🧭 progress 可见）。
3. 开关开但服务器 `deep_research_enabled=false` → 降级 guide 不报错。
4. direct/guide 请求不受开关影响（开关只对 research 语义生效——开关开则强制 research）。
5. 离线单测 `resolve_route` 四象限；全量套件通过；线上 E2E。
