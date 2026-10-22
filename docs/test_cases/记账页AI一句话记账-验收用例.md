# 记账页 AI 一句话记账 · 验收用例

| 用例 | 预期 | 自动化 |
| --- | --- | --- |
| 日本行程账本说三笔 | 3 笔 JPY，餐饮/交通/购物，1200/2800/12000，不提醒 | `backend/tests/test_ledger_draft.py::test_japan_trip_splits_items_with_trip_currency` |
| 日本行程写「¥300」 | JPY 且 `currency_guessed` | `test_yen_symbol_in_japan_trip_is_flagged` |
| 币种默认链 | 行程 > 历史 > CNY；新账本无线索提醒、写了「元」不提醒 | `test_default_chain_history_then_fallback` |
| 日期 | 昨天/前天/具体日期服务端换算，未来日期回落今天 | `test_dates_resolved_on_server` |
| 金额/分类兜底 | 免费/0/负数/超限剔除并计数；分类外值→其他；空标题用分类名 | `test_amounts_bad_values_and_unknown_category` |
| 币种分类集合与账本一致 | 两处常量相同 | `test_currency_and_category_sets_match_ledger` |
| 草稿接口 | 读行程目的地、`effort=low`、不写库；只读成员 403；没认出金额 422 | `test_draft_endpoint_*` |
| 批量入账 | 同一事务；重复提交只记一次；一条非法全部不记；同 id 改内容 409；只读成员 403 | `test_batch_commit_*` |
| 网页流程 | 输入→识别中→3 条草稿+「1 处没认出」→确认前不写库→移除一条、改币种清除提醒、非法金额禁用确定→一次批量请求→清空；手机/桌面深色无横向溢出 | 定向 Playwright（390 浅色 / 1280 深色，已通过） |
| 真实模型 | 5 句样例（中文数字、昨天/前天、RM/美元、¥ 歧义、无金额）全部正确，0.7–1.8s | 服务器上手动跑（本机连不上 DeepSeek） |
