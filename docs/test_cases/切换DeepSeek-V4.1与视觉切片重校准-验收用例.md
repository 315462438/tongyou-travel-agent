# 切换 DeepSeek V4.1 与视觉切片重校准 — 验收用例

自动化：`backend/tests/test_image_prep.py`

| # | 用例 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 1 | 默认单片像素预算 | `vision_max_tile_pixels ≤ 5.4MP`（实测 99% 的档位） | `test_default_tile_pixel_budget_stays_under_the_measured_readable_limit` |
| 2 | 1800×8000（过得了 8192 闸门）| 仍按像素预算切片，每片 ≤ 预算，不缩小 | `test_tall_image_within_side_limit_is_still_split_by_pixel_budget` |
| 3 | 线上 1800×25242 长图、默认配置 | 片数 ≤ 上限、宽度保持 1800、不缩小、每片 ≤ 预算 | `test_real_long_screenshot_is_tiled_without_shrinking_by_default` |
| 4 | Phase 111/112 原有不变式 | 规格内原样返回无 notice；覆盖整页；片数不够先缩不丢尾部；降级带说明 | 原有 19 条 |
| 5 | 模型名 | `model_classifier`/`model_vision` 默认 `deepseek-flash`；服务器 `.env` 同步 | 部署后 `grep ^MODEL_ .env` |
| 6 | 线上复验（手动） | 服务器真实代码路径读 1800×25242 随机数字长图，准确率 ≥95% | 手动脚本，结果记入 task plan |

## 订正：预算覆盖率检查（2026-09-14）

自动化：`backend/tests/test_evals_extract.py`、`backend/tests/test_ontology.py`

| # | 用例 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 7 | 覆盖率口径 | 逐项人均合计 ÷（正文合计 ÷ 人数） | `test_coverage_is_per_person_sum_over_stated_per_person` |
| 8 | 少量分类大项、合计贴正文（重庆 flash 形状） | 不报 | `test_few_category_items_that_match_the_stated_total_do_not_warn` |
| 9 | 很多单顿价格、漏住宿（重庆 v4-pro 形状） | 报 `ext_cost_coverage_low`，level=warn | `test_many_small_items_missing_lodging_warn` |
| 10 | 正文没写合计 | 不检查、不乱报 | `test_no_stated_total_skips_the_coverage_check` |
| 11 | 「合计」行混入逐项 | 不计入覆盖率 | `test_total_rows_do_not_inflate_coverage` |
| 12 | 只跑 cost 路（预算面板） | 不打「itinerary lane returned empty」假告警，lanes 只有 cost | `test_ontology.py` 新增 |
| 13 | 服务器重跑 `extract_eval --tag ds41-flash-cov` | 5/5 通过，覆盖列有值 | 手动 |

## 团组金额均摊（2026-09-14）

| # | 用例 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 14 | 覆盖率偏高（团组金额当人均） | 报 `ext_cost_coverage_high`，level=warn | `test_group_amounts_filled_as_per_person_warn_high` |
| 15 | scope=group 的开销 | 按**并入人数兜底后**的最终人数均摊，备注留「全体X元÷N人」且保留原备注；per_person 不再被除 | `test_group_amounts_are_split_by_the_final_headcount` |
| 16 | scope 为枚举外的值 | 不让 cost 路校验失败，按人均处理 | `test_unknown_scope_is_treated_as_per_person` |
| 17 | 缓存失效 | `SCHEMA_VERSION` 升到 2，v1 缓存重抽 | `test_cache_invalidated_on_schema_version_bump`（既有） |
| 18 | 服务器真实模型：重庆样本连跑 4 次 | 覆盖率全部落在 0.6–1.5（实测 103–106%，改前 3/4 次 318%） | 手动 |
| 19 | 服务器 `extract_eval --tag ds41-flash-scope` | 5/5 通过、无覆盖率告警 | 手动（实测 88/78/103/100/101%） |
