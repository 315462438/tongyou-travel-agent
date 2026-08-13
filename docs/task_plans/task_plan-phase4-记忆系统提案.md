# Task Plan — Phase 4 提案：记忆系统（Memory）

> 创建：2026-07-06　状态：已完成（自动化 14 例 + 端到端冒烟通过）

> 同批修复：①多轮修改判定按意图匹配来源类型（先查酒店再要行程时不再错误复用
> 携程来源，重新走小红书路由+搜索），并真正校验目的地是否变化；
> ②前端接入 remark-gfm，预算表等 Markdown 表格正常渲染。

## 实现细化

- 新表 `TravelMemory`（startup create_all 自动建表）。
- `app/agent/memory.py`：`load_memories` / `format_memories_block` /
  `recall_past_chats`（目的地匹配旧会话 → 标题+助手首段摘要）/
  `plan_memory_ops`（v4-flash parse 出 add/update/delete 操作）/ `apply_ops`。
  所有 DB 函数接受 Session 参数，便于 sqlite 内存库离线测试。
- 编排：生成攻略前注入「长期记忆 + 相关历史会话」；生成后、落库前同步跑一次
  记忆提炼（失败不阻塞），assistant meta 增加 `memories_used` / `memories_saved`。
- API：`GET /api/memory`、`DELETE /api/memory/{id}`。
- 前端：助手消息上方「🧠 记忆 · N」可折叠（用到的记忆/历史会话）；
  回复末尾「已记住 N 条」提示；侧边栏底部「记忆」入口 → 管理面板（查看/删除）。
- 测试：sqlite 内存库跑 apply_ops / recall / 注入块构造；LLM 用 fake 对象。

## 背景

目标是做出类 GPT 的记忆体验：回答时能引用「过去的对话」和「用户长期偏好」，
并在 Activity 面板里展示用了哪些记忆。用户提出的问题：是
「fork_session 做记忆抽取 + 向量数据库」还是别的方案。

## 结论（推荐方案）

**抽取用「对话后旁路后台任务」（等价于 fork_session 的服务端版本）；
存储直接用现有 PostgreSQL；检索第一版全量注入，量大后再上 pgvector。
不引入独立向量数据库。**

理由：

1. **fork_session 是交互式 CLI 的概念**，本项目后端天然有 BackgroundTasks——
   assistant 回复落库后追加一个「记忆提炼」任务即可，效果相同（旁路、不阻塞、
   不污染主对话上下文），实现只有几十行。
2. **个人工具的记忆量级是几十~几百条**。独立向量库（Qdrant/Milvus）是为百万级
   向量准备的，多一个服务要部署、备份、保活，纯属过度设计。
3. **第一版甚至不需要向量**：全部记忆序列化后只有几百 token，直接注入
   PreferenceNode / 生成 prompt，按 type + 时间排序截断即可，检索准确率 100%。
4. 量大以后升级路径也在 Postgres 里：**pgvector 扩展**（服务器 PG16 一条
   `CREATE EXTENSION vector` 就行）。注意 **DeepSeek 没有 embedding 接口**，
   届时 embedding 要另选（硅基流动 bge-m3 / 智谱 embedding-3，都便宜）；
   中间态也可以用「LLM 检索」：把记忆清单给 v4-flash 挑相关条目，零新依赖。

## 两类记忆，分两步做

| 类型 | 内容 | 实现难度 | 对应 GPT 截图里的 |
| --- | --- | --- | --- |
| A. 历史会话引用（Past chat） | 检索旧会话的标题+首条摘要，注入上下文 | 低（表已有） | Memory 面板里的 "Past chat" 卡片 |
| B. 提炼型长期记忆 | 稳定偏好/事实：口味、节奏、预算习惯、忌口、家庭构成 | 中 | 「已记住你喜欢…」 |

**Step 1（先做 A）**：`travel_conversation` / `travel_message` 已有全部数据。
新增检索函数：按目的地/关键词匹配旧会话 → 取标题+assistant 首段 →
注入 PREF/生成 prompt；meta 里记 `memories_used`，前端展示「记忆 · N」可展开卡片。

**Step 2（再做 B）**：
- 新表 `travel_memory`：`id / type(preference|fact|trip_state) / content /
  weight / source_conversation_id / created_at / updated_at`（embedding 列留空，
  将来 pgvector 再加）。
- 抽取：本轮回复完成后 BackgroundTasks 跑 v4-flash `parse()`，输入=
  （本轮用户输入 + 回复摘要 + **已有记忆清单**），输出=结构化操作列表
  `[{op: add|update|delete, id?, type, content}]` —— 让模型做去重/更新/失效，
  而不是只会新增（GPT 的记忆更新就是这个机制）。
- 注入：会话开始时把全部（或 top-N）记忆放进 PREF_SYSTEM 的上下文。
- 前端：Activity 区显示「用到的记忆」+「本轮新记住的」，参照 GPT 面板样式。

## 验收标准（待细化）

- 第二个会话里说「按我的口味来」能命中第一个会话里记下的「爱吃辣」。
- 用户说「别记这个/我不吃辣了」能触发 update/delete。
- 记忆展示可展开查看、可手动删除（`DELETE /api/memory/{id}`）。

## 非目标

- 不做独立向量数据库部署；不做多用户隔离（单人工具）。
