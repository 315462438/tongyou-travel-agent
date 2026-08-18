# 测试里混用固定时间基准和真实 now 会变成时间炸弹

2026-08-18

## 现象

`tests/test_surface_projection.py::test_send_allowed_again_after_the_turn_finishes`
（Phase 92 并发轮防护的配套测试）在**写它的当天通过，之后每天都失败**。
失败信息看起来像生产 bug：终稿之后再发消息被 `409` 挡回，也就是「输入框锁死」——
恰恰是这条测试要防的那件事。

因为它是「一直红着的既有失败」，很容易被当成背景噪音一路带下去。

## 原因

测试里有两种时间基准混用：

```python
_T0 = datetime(2026, 8, 14, 10, 0, 0, tzinfo=timezone.utc)   # 固定基准

def _add(db, role, content, n, **kw):
    ... created_at=_T0 + timedelta(minutes=n) ...             # 锚在 _T0

chat_api.send_message(...)      # 落的 user 消息 created_at = 真实 now
_add(db, "assistant", "答1", 50) # 落的 assistant created_at = 2026-08-14 10:50
```

`send_message` 内部按 `created_at` 排序取消息，于是实际顺序是：

```
assistant  答1   created_at=2026-08-14 10:50:00     ← 排在前面
user       问1   created_at=2026-08-18 03:03:38     ← 排在后面
```

`_is_running` 取**最后一条 user 之后**的消息判断本轮是否结束，而这里 user 是最后一条，
`after` 为空 → 落进「还没有任何回应」的过期兜底分支 → 判为运行中 → `409`。

只要真实时间越过 `_T0 + 50min`，这条就必挂。写它那天（2026-08-14 UTC 10:50 之前）
恰好是对的。

## 解法

需要和真实时间戳共存的那条消息，**锚在真实消息上**，不要锚在固定基准：

```python
out = chat_api.send_message("c1", SendMessageRequest(content="问1"), bg, db=db, user=_U())
user_msg = db.get(TravelMessage, out["user_message_id"])
db.add(TravelMessage(
    conversation_id="c1", role="assistant", content="答1",
    created_at=user_msg.created_at + timedelta(seconds=1),   # 跟在真实那条之后
))
```

固定基准 `_T0` 本身没问题——同文件里纯用 `_add` 构造消息序列的十来条测试都靠它保证
sqlite 下同秒不乱序。**问题只出在和写真实 now 的生产代码混用。**

## 一般化

> **一个测试文件里只要同时存在「固定时间基准」和「会写真实 now 的生产代码」，
> 两者相遇的地方就是时间炸弹。**

排查方法：`grep -rn "datetime(20[0-9][0-9]" tests/` 找出所有固定基准，逐个看它们是否
和调用生产写入路径的测试共处。本次扫描确认全仓库只有 `_T0` 一个固定基准，
且只有这一处混用。

另一个信号：**一条测试如果长期红着且没人解释得清为什么，优先怀疑它自己坏了**，
而不是默认「已知问题」。这条挂了 4 天，两次提交的说明里都把它列进「与本次改动无关」——
描述属实，但它掩盖了「它本身该修」。
