# 视觉输入下，思考链要靠 json_object 刹车（写 prompt 没用）

**日期**：2026-08-21（Phase 105 接入 `deepseek-v4-flash-vision-exp` 时实测）

## 现象

用视觉模型从小红书配图抽结构化信息，6 张真实图，`max_tokens=3000`：

```
空正文 2/6     out=3000  reasoning=3000     ← 思考链吃满整个预算，正文为空
延迟中位 23.7s
```

而 prompt 里**已经写了**Phase 101/102 那套久经验证的思考纪律：

> **思考纪律**：这是抽取任务，答案都在图里，思考最多两三行要点，把输出预算留给 JSON 正文。

**它照样烧满。** 加 max_tokens 也只是让它想得更久（1600→3000，out 中位从 743 涨到 2622）。

## 原因

DeepSeek 思考模式对结构化抽取过度推理，这已经是第四次撞了
（Phase 11 ITINERARY / Phase 101 quick_take / Phase 102 五处抽取 / 本次）。
但前三次「在 system 里写思考纪律」都管用，这次不管用——**视觉输入下 prompt 遵循度更低**。

## 解决办法

打开 `response_format={"type": "json_object"}`：

| 模式（同为 max_tokens=3000） | 空正文 | 延迟中位 | out 中位 |
| --- | --- | --- | --- |
| 裸 prompt + 思考纪律 | 2/6 | 23.7s | 2622 |
| **json_object** | **0/6** | **7.4s** | **743** |

思考链自己收住了。所以 `LLMClient.parse_image` **强制**走 `parse()`（它本来就带
json_object），不给调用方关掉的余地。

## 一般化

仓库里那条不变式——

> 结构化输出必须走 `parse()` 而非裸 prompt

——一直被当成**格式保证**（省得解析 markdown 代码块里的 JSON）。这次实测说明它还是
**思考链的刹车**，而且在视觉输入下这才是它的主要价值。

推论两条：
1. **别把正确性押在 prompt 遵循上**（Phase 89 已有的教训），这次连「已验证过三次的措辞」
   都失效了；能用协议层约束（response_format / schema / tool 定义）的地方就别写规矩。
2. **加预算不是治法**。`max_tokens` 1600→3000 只让它想得更久：这类问题的正确旋钮是
   「限制它能自由发挥的形状」，不是「给它更多空间」。

## 排查线索

`usage.completion_tokens == max_tokens` 且 `completion_tokens_details.reasoning_tokens`
约等于同一个数 ⇒ 就是这个问题。表现是**空白回答**，不是报错——不看 usage 会以为模型「不会答」。
