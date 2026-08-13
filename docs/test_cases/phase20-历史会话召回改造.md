# Phase 20 历史会话召回改造 — 验收用例

## 背景

记忆注入含两块：提炼型长期记忆（偏好/事实，Phase 17 三元组）+ 历史会话引用
（`recall_past_chats`）。后者原来「优先目的地命中，否则倒灌最近会话」，且直接取助手首条
回复前 160 字——导致注入无关旧行程、甚至把「已停止本轮」等无效回复当历史攻略引用。

## 改造（`app/agent/memory.recall_past_chats`）

1. **只按目的地命中**：不再倒灌无关的最近会话；无目的地/无命中 → 不注入。
2. **过滤无效首回复**：跳过流式占位(`meta.streaming`)/海报(`meta.poster`)/停止报错
   （「已停止」「抱歉」「生成失败」…前缀）/过短(<120 字)，取第一条『像样攻略』。
3. **清洗摘录**：`_clean_snippet` 去 markdown 记号、折叠空白，避免注入 `## ** ` 噪声。

## 自动化（`backend/tests/test_memory.py`）

| 用例 | 期望 |
| --- | --- |
| `test_recall_only_destination_match` | 只返回标题含目的地的会话 |
| `test_recall_no_match_returns_empty` | 无命中/无目的地 → `[]`（不再倒灌最近） |
| `test_recall_skips_junk_first_reply` | 首回复是「已停止本轮」→ 跳过；有后续像样攻略则取它 |
| `test_recall_skips_streaming_and_poster` | 流式占位/海报回复不被引用 |
| `test_clean_snippet_strips_markdown` | `## Day1 **上午**` → 去记号 |

命令：`cd backend && .venv/bin/python -m pytest tests/test_memory.py -q`

## 线上验证（真实 admin 数据 ✅）

```
目的地=厦门 → 命中 2（厦门2天/厦门3天，摘录干净：「厦门2日慢享海鲜之旅…」）
目的地=开封 → 命中 3（全开封相关）
目的地=拉萨 → 命中 0（新目的地，不再倒灌无关旧行程）
```
此前的「已停止本轮」残片不再出现在历史对话卡。

## 概念澄清（回答用户）

- 「历史对话」卡 = 跨会话**检索**（≈ ChatGPT「引用聊天记录」），**按用户隔离**（只读自己的）。
- 真正「dreaming/reflection」味的是**偏好卡**：每轮回复后旁路 LLM 把对话消化成三元组记忆
  （同步触发，非空闲后台）。二者是不同机制。
