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
