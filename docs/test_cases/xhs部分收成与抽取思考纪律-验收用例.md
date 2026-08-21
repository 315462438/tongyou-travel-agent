# xhs 部分收成 + 抽取思考纪律 — 验收用例

对应计划：`docs/task_plans/xhs部分收成与抽取思考纪律-2026-08-21.md`（Phase 102）
自动化落点：`backend/tests/test_xhs_mcp.py`（新增 4 条，共 20 条，全离线打桩）

```bash
cd backend && .venv/bin/python -m pytest tests/test_xhs_mcp.py -q
```

## A. 部分收成

| # | 用例 | 断言 | 测试 |
| --- | --- | --- | --- |
| 1 | 第一篇秒回、第二篇永久阻塞、预算 0.5s | 交回那 **1 篇**，不再全丢 | `test_budget_timeout_keeps_partial_harvest` |
| 2 | 采集中用户停止 | `CancelledError` 照旧向上冒，不被部分收成吞掉 | `test_user_cancel_still_propagates` |
| 3 | 预算默认值 | `xhs_collect_timeout_s == 75` | `test_budget_default_is_75` |

用例 1 是改动的理由本身：线上实测一轮 xhs 各段合计 149.9s、预算 150s——**差 0.1 秒就
白等两分半、一篇不剩**。用例 2 钉住边界：部分收成只针对预算超时，不针对用户取消。

## B. 抽取思考纪律

| # | 用例 | 断言 | 测试 |
| --- | --- | --- | --- |
| 4 | 五个抽取 system（IMPORT_DAYS / IMPORT_SUMMARY / ontology / poster / budget） | 都含「思考纪律」「两三行」 | `test_extraction_prompts_carry_thinking_discipline` |

防后人重构 prompt 时删掉——删了不报错，只悄悄变慢回 118s/块。

## 回归

```
tests/test_xhs_mcp.py    20 passed
tests/                   1130 passed, 6 failed（VPN-DNS 环境项，服务器全过）
```

## 上线后验证

1. 服务器 `.env` **无** `XHS_COLLECT_TIMEOUT_S` 覆盖（有则 config 默认值不生效）
2. Langfuse：xhs 各段合计不再超过 ~75s；导入行程板的抽取调用 reason token 从五位数掉到三位数
3. 整轮 guide P50 预期 ~200s → ~130-150s
