# 纯记账写会连带刷新 updated_at，把「最后更改」悄悄变成「最后使用」

**日期**：2026-08-24　**涉及**：`app/db/models.py` `TravelMemory`、`app/agent/memory.py::_bump_hit_count`

## 现象

`travel_memory.updated_at` 看上去一切正常：一直有值、一直在变、活跃用户显示「最近更新」——
完全合理。无报错、无日志、无告警。

直到拿它回答一个具体问题：**「这条偏好用户多久没提过了？」**

线上 47 行记忆里 25 行答错：

```
293cbea7 住宿偏好   prompt写「2 天前」，实际建于 25 天前
293cbea7 预算偏好   prompt写「2 天前」，实际建于 25 天前
（该用户 7 条全部如此）
```

## 原因

`updated_at` 声明了 `onupdate=_now`。**SQLAlchemy 的 `onupdate` 对该行的任何 UPDATE 都生效，
与你改的是哪一列无关。**

而 `_bump_hit_count` 是一处**纯记账写**——它只想给 `hit_count` 加一：

```python
for m in memories:
    m.hit_count = (m.hit_count or 0) + 1
db.commit()          # ← onupdate 在这里把 updated_at 也推到了当下
```

它每轮跑一次，对本轮注入的每条记忆都跑。于是 `updated_at` 的**实际语义**从
「内容最后一次变化」变成了「最后一次被注入」，而全系统仍按前者在读它。

最贵的一处：`format_memories_block` 把年龄标签贴进 prompt（Phase 30，专为触发模型的
**过期意识**而建，docstring 写着「『47 天前』比裸时间戳更能触发过期意识」）。修复前
一条记忆只要上一轮被注入过，这一轮就标成「今天」——**越活跃的用户偏得越狠**，
天天聊的人所有记忆永远是「今天」。一年前说的「爱吃辣」和今天刚说的，模型看到的一模一样。

## 解决

把该列**显式列进 SET 子句自赋值**——SQLAlchemy 只在列不在 SET 里时才套用 `onupdate`：

```python
db.execute(
    update(TravelMemory).where(TravelMemory.id.in_(ids)).values(
        hit_count=func.coalesce(TravelMemory.hit_count, 0) + 1,
        last_used_at=_now(),                 # 记账时间另立一列
        updated_at=TravelMemory.updated_at,  # ← 自赋值，压住 onupdate
    ).execution_options(synchronize_session=False)
)
```

已实测两个方向都对（只记账不动 / 内容变更要动）。

## 一般化

1. **`onupdate` 是「行级」的，不是「列级」的。** 只要一张表上有「与内容无关的记账列」
   （hit_count / last_seen / view_count / retry_count…），它就会污染同表的 `updated_at`。
   凡是这种表，记账写都要显式压住时间列——或者干脆别在这种表上用 `onupdate`。
2. **两个方向的测试都要有。** 只钉「记账时 updated_at 不动」的话，把整列 `onupdate`
   删掉也能过——那会让真正的内容变更也不再更新时间，问题从一头换到另一头。
   已用变异检验验过：删 `onupdate` → 方向二红两条；删自赋值 → 方向一红两条。
3. **历史数据不可恢复。** 真实的内容变更时间从来没有任何地方留过。这类 bug 的修复窗口
   是单向的：**发现得越晚，能挽回的越少**。回填只能取保守下界（`created_at`），
   并记一个语义断点日期。
4. **失效特征同 Phase 107 的 `color: transparent`**：规则命中、语法正确、值一直存在、
   方向还合理，就是答的不是你问的那个问题。这类 bug 找不出来靠读代码，得靠**拿它去
   回答一个具体问题**。
