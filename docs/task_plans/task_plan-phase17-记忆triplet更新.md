# Phase 17 — 记忆 triplet 更新机制（key-slot 覆盖/合并，无向量）

## 背景 / 问题

记忆当前是**追加式**：每轮让 LLM 对照已有记忆输出 add/update/delete，但实际几乎只 add，
导致记忆越积越多、越乱。典型脏数据（admin 账号截图）：

- `trip_state` 每规划一个目的地就新增一条「用户计划前往X旅行，两天」——本质是**瞬时状态**，
  不该长期累积，却堆了十几条。
- `preference` 重复/近义堆叠：「喜欢海鲜」「喜欢鲜花」「喜欢历史文化」「喜欢美食和夜景」…

用户要求：在**未接入向量模型/向量库**的前提下，按 triplet 机制更新记忆，落实四条策略：
1. 相同 key 直接覆盖
2. 相似度高的记忆合并
3. 时间更新的优先
4. 用户明确表达的优先

## 方案：canonical key-slot（三元组 = 用户 · key · content）

单用户场景下 subject 恒为「用户」，三元组退化为 **(key → content)**。给每条记忆一个
**规范化 key**（三元组的谓词），并强制 **每个 (user_id, key) 只保留一条**。四条策略即
可被确定性地实现，无需向量：

| 策略 | 实现 |
| --- | --- |
| 相同 key 直接覆盖 | apply 时按 (user,key) upsert，命中即改内容 |
| 相似度高合并 | LLM 把近义记忆归到**同一个规范 key** → 落到同一 slot 自动合并（语义相似度由 LLM 承担，key-slot 承担「合并」这一确定性动作） |
| 时间更新优先 | 覆盖时 bump `updated_at`，新内容胜出 |
| 用户明确表达优先 | `explicit` 标记 → 权重加成且「粘性」（一旦 explicit 不因推断内容降级） |

### 规范 key 集合（有界 → 行数有界，单用户 ≤ ~12 条）

- preference：`口味偏好` `兴趣偏好` `节奏偏好` `预算偏好` `住宿偏好` `出行方式`
- fact：`常驻城市` `忌口过敏` `同行情况`
- trip_state：`当前行程`（**单槽**，每次覆盖 → 行程不再堆积）

LLM 从固定集合里选 key（也允许在同类下细分，但优先复用），保证行数可控、命中率高。

## 涉及模块

- `app/db/models.py`：`TravelMemory` 加 `key`(String64, nullable, 索引) + `explicit`(bool)
- `app/schemas/memory_schema.py`：`MemoryOp` 加 `key`、`explicit`
- `app/agent/memory.py`：
  - `CANONICAL_KEYS` 常量；`EXTRACT_SYSTEM` 重写（列出 key 集合、强调 upsert/合并、当前行程单槽）
  - `plan_memory_ops`：已有记忆按 `key | content` 呈现
  - `apply_ops`：**按 (user,key) upsert**（add/update 都走 upsert；delete 仍按 id）；explicit 权重与粘性；按 `memory_max_rows` 兜底剪枝
  - `consolidate_memories(db, user_id, llm)`：一次性把某用户现有记忆用 LLM 重写成规范三元组并替换（清理存量脏数据）
- `app/db/migrate.py`：`ALTER ADD COLUMN IF NOT EXISTS key/explicit`
- `app/api/memory_api.py`：list 返回 `key`；新增 `POST /api/memory/consolidate`（当前用户）
- `app/config.py`：`memory_max_rows: int = 40`
- 前端 `MemoryPanel`：badge 用 `key`（无 key 回退 type）

## 验收标准

1. 同一 key 二次写入 → 覆盖而非新增（行数不变）。
2. 「当前行程」多次规划不同目的地 → 只保留最新一条。
3. explicit 记忆权重更高、注入排序靠前，且不被推断内容降级。
4. `consolidate` 把十几条脏记忆压到 ≤12 条规范三元组，无重复 key。
5. 全量单测通过；新增 `tests/test_memory_triplet.py` 覆盖 upsert/单槽/explicit/剪枝。
6. 部署后对 admin 账号跑一次 consolidate，记忆面板变干净。
