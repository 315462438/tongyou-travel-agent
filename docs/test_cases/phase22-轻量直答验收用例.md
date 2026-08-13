# Phase 22 轻量直答通道 — 验收用例

自动化：`backend/tests/test_deep_research.py` 路由段（Phase 22 重写为三路）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_deep_research.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 分类=research 且开关开 | 走 research | `test_route_research_when_enabled` |
| 2 | 分类=research 但开关关 | 降级 guide | `test_route_research_disabled_downgrades_to_guide` |
| 3 | 分类=direct 且开关开 | 走 direct | `test_route_direct_when_enabled` |
| 4 | 分类=direct 但开关关 | 降级 guide | `test_route_direct_disabled_downgrades_to_guide` |
| 5 | 分类=guide / 未知 kind / 空消息 | 一律 guide | `test_route_guide_default` |
| 6 | 分类 LLM 挂了 | 回落 guide（宁慢勿错） | `test_route_classify_failure_falls_back_to_guide` |

## E2E 计时（✅）

| 环境 | 问题 | 通道 | 首字 | 全程 | 采集 |
| --- | --- | --- | --- | --- | --- |
| 本地 | 鼓浪屿要提前订船票吗 | direct | 14s | **26s** | 0 条 progress，无浏览器 |
| 线上 | 哈尔滨冬天穿什么 | direct | **6s** | **17s** | 0 |
| 线上 | 帮我规划珠海2天路线（回归） | guide | — | 189s（≈原基线） | 搜索+读取正常，4 来源 |

对比：此前同类简单问题走全量流水线约 2-4 分钟 → **direct 通道 17-26s，提速 ~6-8 倍**。

## 附加验证
- 记忆注入生效：本地用例中模型基于「当前行程=泉州」三元组记忆主动纠正
  「鼓浪屿在厦门，不在泉州」。
- direct 回复后照常旁路记忆提炼（meta.memories_saved）。
- 流式占位/停止按钮沿用 guide 同一套机制（is_cancelled 打点）。

## 关键设计
- 三路路由 = v4-flash 单次分类（~1s，取代原 research 关键词门）；
  分类失败/未知/空消息/开关关 → 一律 guide。
- direct 无浏览器、无 sources、无 checkpoint；注入三元组记忆 + 近 5 轮历史；
  prompt 要求时效性信息注明「可让我联网查询」。
