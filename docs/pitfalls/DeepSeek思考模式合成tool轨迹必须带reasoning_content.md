# DeepSeek 思考模式：合成 tool_calls 轨迹的 assistant 消息必须回传 reasoning_content

## 现象

Phase 31 把攻略生成重建为标准 agent 轨迹（`assistant.tool_calls → tool×N → 生成`），
首次真实 API 冒烟直接 400：

```
The `reasoning_content` in the thinking mode must be passed back to the API.
```

## 原因

DeepSeek v4 思考模式下，历史里**任何带 `tool_calls` 的 assistant 消息**都必须附
`reasoning_content` 字段——真实 agent 循环里这个字段是模型自己吐的、回传时自然带上；
但我们的轨迹是**代码合成的**（确定性流水线收集完再重建），默认没有这个字段。

## 解决

合成的 assistant 消息补一段简短的 `reasoning_content`（如「需要先检索并抓取相关
网页与实时数据来源，再基于资料生成」），见 `orchestrator.build_guide_messages`。
内容写什么不重要（模型只是要求字段存在），但要与 tool_calls 语义一致，别误导后续推理。

## 另两条同场景实测结论（省得下次再验）

- 不传 `tools` 参数、只在消息里出现 `tool_calls`/`tool` 角色：**接受**（无需伪造工具定义）；
- 在合成轨迹上继续流式生成 + reasoning_content 输出：正常。

相关：`docs/task_plans/task_plan-phase31-结构化消息与注入防护.md`。
