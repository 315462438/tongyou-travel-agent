# `Base.metadata.create_all` 只补缺失的**表**，不给已存在的表加**列**

2026-08-13，Phase 87 上线当天踩到。

## 现象

给 `TravelTripPackingState` 加了一个 `updated_by` 列，部署后查库：

```
\d travel_trip_packing_state
 item_id | user_id | trip_id | state | updated_at        ← 没有 updated_by
```

模型里有、库里没有。任何写这一列的请求都会 500。

## 原因

`migrate_and_bootstrap()` 里的 `Base.metadata.create_all(engine)` 语义是
**「建缺失的表」**，对已经存在的表它什么都不做——包括不会加新列。

本次特别容易中招，因为是**同一天的两次部署**：

1. 第一次部署：表不存在 → `create_all` 建表（那时模型还没有 `updated_by`）；
2. 加了 `updated_by` 列 → 第二次部署：表已存在 → `create_all` 直接跳过。

如果是全新环境反而不会暴露（`create_all` 会按最新模型一次建全），所以**本地测试
（sqlite 每次新建）永远发现不了**——`tests/test_trip_modules.py` 19 个用例全绿。

## 解决

新增列必须在 `app/db/migrate.py` 里显式写一条幂等 DDL：

```python
"ALTER TABLE travel_trip_packing_state ADD COLUMN IF NOT EXISTS updated_by VARCHAR(32) DEFAULT ''",
```

## 教训

1. **新建表**靠 `create_all` 就够；**给已有表加列**一定要手写 `ADD COLUMN IF NOT EXISTS`。
   判断标准很简单：这张表在**任何**已部署环境里已经存在过吗？是 → 必须写迁移。
2. **sqlite 单测证明不了迁移正确**。它每次 `create_all` 到一个空库，永远走「建新表」
   那条路。涉及模型字段变更的改动，部署后要真去 `\d 表名` 看一眼。
3. 同一天多次部署时风险最高——第一次部署把表"固化"成了旧结构。
