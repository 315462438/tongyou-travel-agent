# 踩坑：LangGraph checkpoint 反序列化未注册类型告警

## 现象

启动 / 续跑时日志出现：

```
Deserializing unregistered type app.schemas.chat_schema.Preference from checkpoint.
This will be blocked in a future version. Set LANGGRAPH_STRICT_MSGPACK=true to block now,
or add to allowed_msgpack_modules to allow explicitly: [('app.schemas.chat_schema', 'Preference')]
```

## 原因

`AsyncPostgresSaver`（langgraph-checkpoint-postgres）用 msgpack 序列化图 state。
我们的 `AgentState` 里放了 Pydantic 模型（如 `Preference`），langgraph 出于安全，
对「非白名单模块的自定义类型」在反序列化时给告警，未来大版本会**默认拒绝**。

## 影响

**当前不阻塞**：checkpoint 正常读写、续跑正常产出完整攻略。仅为未来兼容告警。

## 解决办法（未来收紧时）

三选一：

1. **state 里只放可 JSON 化的基础类型**（dict/list/str），Pydantic 模型在节点内即时构造，
   不进 state —— 最稳，推荐。
2. 升级 langgraph 后按提示把模块加进 `allowed_msgpack_modules` 白名单。
3. 自定义 serde，显式注册这些类型。

暂不处理，保持现状；升级 langgraph 前若日志开始报错再按方案 1 改。
