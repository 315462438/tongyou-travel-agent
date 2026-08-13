# Phase 17 记忆 triplet 归槽 — 验收用例

自动化测试：`backend/tests/test_memory_triplet.py`（9 例，全绿）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_memory_triplet.py -q`

| # | 用例 | 策略 | 期望 | 自动化 |
| --- | --- | --- | --- | --- |
| 1 | 同一 key（口味偏好）连续写两次 | 相同 key 覆盖 | 只 1 条，内容为最新 | `test_same_key_overwrites_not_appends` |
| 2 | 「当前行程」写开封→宁波→厦门 | 单槽覆盖 | 只保留厦门 1 条，type=trip_state | `test_trip_state_single_slot` |
| 3 | 口味/节奏/常驻 三个不同 key | key 区分 | 3 条共存 | `test_distinct_keys_coexist` |
| 4 | explicit 记忆被推断内容覆盖 | 明确表达优先（粘性） | explicit 保持 True、weight=2.0 | `test_explicit_is_sticky_and_weighted` |
| 5 | explicit 与非 explicit 同列 | 明确表达优先（排序） | explicit 条排最前 | `test_explicit_ranks_first` |
| 6 | u1/u2 各写口味偏好 | 用户隔离 | 各 1 条互不影响 | `test_key_isolated_per_user` |
| 7 | 写 6 条、上限设 3 | 兜底剪枝 | 只保留 3 条 | `test_prune_caps_rows` |
| 8 | consolidate 7 条脏数据（含重复 key） | 去重合并替换 | before=7/after=3，无重复 key | `test_consolidate_dedups_and_replaces` |
| 9 | consolidate LLM 返回空 | 兜底不清空 | before=after，记忆保留 | `test_consolidate_empty_result_keeps_memories` |

## 线上手工验收（已执行 ✅）

对 admin 账号真实脏数据（22 条：14 条堆积 trip_state + 8 条重复/近义 preference）调
`POST /api/memory/consolidate`：

```
before=22 → after=6
  口味偏好 | 用户喜欢吃海鲜和辣，不太能吃甜      （合并「海鲜」「特别爱吃辣」「不太能吃甜」）
  兴趣偏好 | 用户喜欢鲜花、历史文化、美食和夜景  （合并 3 条）
  当前行程 | 用户计划前往黄山旅行，两天一晚      （14 条行程 → 只留最新）
  住宿偏好 / 节奏偏好 / 预算偏好                （各归 1 条）
```

再次调用幂等（6→6）。前端「🧠 记忆」弹窗新增「✨ 整理记忆」按钮触发同一流程。

## 结论

四条策略（相同 key 覆盖 / 相似合并 / 时间更新优先 / 明确表达优先）全部落地并线上验证，
无需向量模型/向量库。记忆行数由无界追加变为按 key 有界（单用户 ≤ ~12 + 兜底剪枝上限 40）。
