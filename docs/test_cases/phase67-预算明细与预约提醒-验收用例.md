# Phase 67 预算明细 + 预约提醒 — 验收用例

自动化测试：`backend/tests/test_budget.py`（15 例，纯离线，不打 LLM/网络/DB）

```bash
cd backend && .venv/bin/python -m pytest tests/test_budget.py -q
```

## 一、自动化用例（已落地）

汇总口径是本期的核心正确性要求——**总额一律服务端重算，绝不采信模型给的数字**。

| 用例 | 断言 | 对应风险 |
| --- | --- | --- |
| `test_total_is_recomputed_server_side` | total == 逐项之和 | TripStar 让 LLM 算总额，输出 `30+54+120=324` 非法 JSON |
| `test_category_normalized_and_summed` | 机票+高铁→大交通 1000；地铁→交通；民宿→住宿 | 分类口径与协同行程导入不一致 |
| `test_unknown_category_falls_back_to_other` | 未知类别→其他 | 模型自创类别导致丢项 |
| `test_category_order_is_stable` | 顺序固定为 大交通→门票→其他（与金额无关） | 多次生成顺序跳动 |
| `test_pct_sums_to_about_100` | 占比之和 ≈100%（容差 0.2） | 占比条视觉失真 |
| `test_total_lines_are_dropped` | 「合计」「总预算」行被剔除，total 不翻倍 | 模型无视约束输出总计行 |
| `test_nonpositive_amounts_dropped` | 0/负数金额不入明细 | 脏数据污染汇总 |
| `test_by_day_and_shared_split` | day=0 归 shared，不混入逐天 | 整趟通用开销被算进某一天 |
| `test_group_total_uses_headcount` | 人均 500 × 3 人 = 1500 | 人均/总价口径混淆 |
| `test_headcount_never_below_one` | headcount=0 → 归一为 1 | 除零/总价为 0 |
| `test_empty_guide_yields_empty_payload` | 无预算 → 空明细、total=0 | 编造数字 |
| `test_reservations_kept_and_blank_names_dropped` | 保留有名项，丢弃空名项 | 空白徽章 |
| `test_notes_capped_at_three` | notes 截断到 3 条 | 面板被说明淹没 |
| `test_blank_item_name_gets_placeholder` | 空名→「未命名开销」 | 空白行 |
| `test_negative_day_clamped` | day=-3 → 0（归通用） | 负数天导致排序错乱 |

## 二、真实 LLM 抽取验证（已执行）

用一段含预约信息的北京 3 日攻略实跑 `llm.parse`，结果：

| 检查项 | 结果 |
| --- | --- |
| 分类归一 | ✅ 高铁→大交通、包车/地铁→交通、民宿→住宿 |
| 预约识别 | ✅ 故宫（提前7天·官方公众号）、国博（提前1天·官网）两条全中 |
| 多晚住宿合并 | ✅ 「前门附近连锁酒店2晚」900 元，note 注明「450元/晚」 |
| 跨天开销归属 | ✅ 高铁/住宿/地铁归 day=0（通用 2040），逐日只留当天消费 |
| 汇总自洽 | ✅ sum(items) == total == 2822；分类合计 1100+900+405+227+190 一致 |
| notes | ✅ 抽出「不含购物」「旺季房价上浮」 |

## 三、手工验收清单（线上）

1. **入口**：攻略消息底部出现「💰 预算明细」按钮，与「🎨 生成手账海报」并排。
2. **生成中**：点击后按钮变「统计中…」，页面保持轮询（占位消息 streaming），不卡死。
3. **面板内容**：
   - 右上角显示人均总额；多人出行时额外显示「合计 ¥X」
   - 「📋 需提前预约」区块（橙色）列出景点 + 提前天数徽章 + 渠道
   - 分类占比条按 大交通/住宿/餐饮/门票/交通/其他 固定顺序，颜色区分
   - 明细表可按分类筛选，按天排序（通用项排最后），金额右对齐
   - 逐日汇总胶囊 + 通用胶囊（紫色）
4. **无预算攻略**：提示「这份攻略里没有写明具体花费…」，**不编造数字**。
5. **失败路径**：抽取失败提示「预算信息提取失败了，请重试。」，占位消息必须终稿
   （不残留 streaming，前端不会无限等待）。
6. **移动端**：面板不撑破页面，明细表内部横滑，占比数字列隐藏。
7. **不污染记忆**：预算面板消息不被 `_first_guide_reply` 当作攻略（`memory.py` 已排除）。

## 四、已知边界

- 金额为**人均**口径；攻略若混用总价/人均，以正文写法为准，面板不做二次推断。
- 多币种未做换算，`currency` 仅占位（当前恒为 CNY）。
- 预约信息完全依赖攻略正文是否提及；正文没写则不显示该区块（不联网核实）。
