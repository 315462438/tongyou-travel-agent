# Phase 23 深度推理开关 — 验收用例

自动化：`backend/tests/test_deep_research.py` resolve_route 段（4 例）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_deep_research.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 开关开 | 跳过分类直接 research | `test_resolve_toggle_on_forces_research` |
| 2 | 开关开但服务器 research 关 | 降级 guide 不报错 | `test_resolve_toggle_on_but_server_disabled` |
| 3 | 开关关 + 判为 research | **direct 快速回答 + suggest 提示**（direct 关则 guide） | `test_resolve_toggle_off_research_suggests` |
| 4 | 开关关 + direct/guide | 照旧，无提示 | `test_resolve_toggle_off_normal_paths` |

## 线上 E2E（✅）

**场景 A（开关关 + 复杂问题）**：「哈尔滨 vs 长春冬天哪个好玩」→ **19s** direct 快速对比
（含对比表，并结合三元组记忆提醒"长春偏甜口，你不太吃甜"）+ 提示卡
「🧠 适合深度推理…打开开关重新提问」（带按钮，meta.hint 常驻不被终稿清理）。

**场景 B（开关开）**：同问题 → 强制进研究模式，289s 产出完整对比报告（10 来源）。
中途踩到 `GraphRecursionError`（40 步上限不够）→ 上限提 80 + 超限优雅降级提示
（"研究步骤太多，建议拆小或先要快速回答"）。

**UI**：composer「🧠 深度推理」胶囊开关（开=品牌渐变高亮，状态存 localStorage，
running 时禁用，title 说明适用场景）；提示卡按钮点击即置开开关。

## 行为变更（重要）

**research 不再自动触发**——只经用户开关进入。开关关时判为复杂的问题走 direct
快速回答 + 建议提示，把「是否等 4-6 分钟」的决定权交给用户。

## 设计要点
- 提示 progress 带 `meta.hint="deep_reasoning"` → `clear_plain_progress` 不清（带 meta），
  提示在终稿后仍可见可点。
- `SendMessageRequest.deep_reasoning` 默认 False，旧前端/脚本兼容。
