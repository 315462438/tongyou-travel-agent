# 协同行程板 PRD 改造（Phase 87）— 验收用例

自动化实现：`backend/tests/test_trip_modules.py`（17 个用例，sqlite + TestClient 全离线）

```bash
cd backend && .venv/bin/python -m pytest tests/test_trip_modules.py -q
```

## 一、模块 2 · 美食

| # | 用例 | 期望 | 测试函数 |
| --- | --- | --- | --- |
| 1.1 | 增改删 + TOP 置顶 | TOP 排最前；取消 TOP 回到时间序；未填城市回落行程目的地 | `test_food_crud_and_top_ordering` |
| 1.2 | 空名 | 400 | `test_food_rejects_blank_name` |
| 1.3 | 非成员访问 | 读写都 404（不泄露存在性） | `test_food_isolated_to_members` |
| 1.4 | 拿 A 行程的记录 id 去 B 行程路径下删 | 404 | `test_food_cross_trip_id_mismatch_is_404` |

## 二、模块 5 · 任务分工

| # | 用例 | 期望 | 测试函数 |
| --- | --- | --- | --- |
| 2.1 | 新建默认待认领 → 认领 → 完成 | 状态流转正确；完成动作落进动态时间线 | `test_task_lifecycle_claim_and_done` |
| 2.2 | 指派给非成员 | 400 报错，**不静默丢弃**（否则用户以为派出去了） | `test_task_assignee_must_be_a_member` |
| 2.3 | 取消指派 | 回到待认领池 | `test_task_unassign_back_to_pool` |
| 2.4 | 非法 status | 保留原状态，不写坏数据 | `test_task_bad_status_keeps_previous` |

## 三、模块 6 · 行李三态

| # | 用例 | 期望 | 测试函数 |
| --- | --- | --- | --- |
| 3.1 | 两人分别设置同一物品 | 各占一格互不覆盖（不用 JSON 整体覆写的原因） | `test_packing_grid_is_per_member` |
| 3.2 | 代同伴勾 | 成功且 `marked_by` 记下代勾人 | `test_can_mark_on_behalf_of_another_member` |
| 3.2b | 自己勾自己 | 不产生「由 X 代勾」标记 | `test_self_marking_leaves_no_proxy_mark` |
| 3.2c | 代非成员勾 | 400 | `test_cannot_mark_for_a_non_member` |
| 3.3 | 三态循环 + 非法值 | packed/unpacked/na 均可；其他 400 | `test_packing_state_cycles_and_validates` |
| 3.4 | 删物品 | 连带删掉所有成员的格子 | `test_packing_delete_removes_states` |
| 3.5 | 连续切换状态 | **不写动态时间线**（高频操作会刷爆时间线） | `test_packing_state_toggles_do_not_flood_event_log` |

## 四、模块 7 · 避坑

| # | 用例 | 期望 | 测试函数 |
| --- | --- | --- | --- |
| 4.1 | 增改删 + 级别排序 | important 排在 notice 前 | `test_tips_crud_and_level_ordering` |
| 4.2 | 非法 level | 回落 notice | `test_tip_bad_level_falls_back_to_notice` |
| 4.3 | 空内容 | 400 | `test_tip_rejects_blank` |

## 五、跨模块

| # | 用例 | 期望 | 测试函数 |
| --- | --- | --- | --- |
| 5.1 | 任一模块写操作 | 刷新 `trip.updated_at`，否则协作方 2.5s 轮询看不到新内容 | `test_writes_touch_trip_updated_at` |
| 5.2 | 新增路由鉴权 | 全部通过 `tests/test_agent_api_auth.py` 的 AST 全量扫描 | （该文件 7 passed） |

## 六、前端手工验收

1. **标签栏**：打开任一行程板，顶部应只有**一栏**标签（Day 1~N ｜ 🍜美食 🏨住宿 💰记账
   ✅任务 🧳行李 ⚠️避坑 📷相册 ✦助手 ◷动态），横向可滚动。右栏原先那套重复的
   「🤖助手/🏨住宿/💰费用/🕘动态」应已消失。
2. **状态角标**：标题右侧显示 未开始 / 进行中 / 已结束 / 未定日期（按 `start_date + days` 计算）。
3. **悬浮按钮**：右下角按钮文案随标签变化（行程表「+ 加地点」、美食「+ 加美食」、
   任务「+ 加任务」、行李「+ 加物品」、避坑「+ 加提醒」、记账「+ 记一笔」）；
   在助手/动态/住宿/相册标签下不显示。点击应聚焦并滚动到对应输入框。
4. **行李表**：任何一格都可点击循环三态；替别人勾过的格子右上角有代勾人首字母角标，
   悬停显示「由 X 代勾」；成员多时表格内部横滑，页面本身不出现横向滚动条。
5. **移动端**：切到移动模式，四个新面板不溢出，悬浮按钮避开 iOS 安全区。

## 七、已知无关失败

全量套件另有 6 个失败（`test_context_security.py` 1 + `test_research_context.py` 5）：
本地沙箱 DNS 把 `example.com` 解析到保留段 `198.18.1.84`，Phase 69 的 `url_guard`
正确拒绝。与本改造无关。
