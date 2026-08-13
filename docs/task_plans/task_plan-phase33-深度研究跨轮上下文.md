# Task Plan — Phase 33：深度研究跨轮上下文（全量历史 + 分层压缩 + 记忆/轮末钩子）

## 背景

盘点确认：深度研究每轮是全新 agent 实例，输入只有本轮 user_text + 技能——不带历史、
不带记忆；轮末只落终稿消息，不提炼记忆、不折叠历史摘要。追问场景（「按我说的预算
重新对比」）完全接不住。

用户拍板方案：不走 guide/direct 的「近 5 轮 + 摘要」窄窗，**仿 Claude Code 带全量
上下文**，靠分层压缩管理窗口，最大程度保留 prompt cache。

## 方案

### A. 全量历史注入（跨轮 prompt cache 友好）

研究轮消息结构：

```
system                        固定（技能清单/纪律）——轮内几十次迭代共享前缀
user/assistant × 全部历史轮    逐字、不截断（真实交替角色，排除 progress/action）
user                          <background_memory>记忆</> + 本轮研究问题
```

历史部分是 append-only 的：第 N+1 轮的前缀 = 第 N 轮的前缀 + 上轮问答——DeepSeek
自动前缀缓存跨轮命中。易变的记忆块放**末条 user 消息**，不打破历史前缀。

**构建期保险**：全量历史超过 `deep_research_history_max_chars`(60k 字符) 时回退
Phase 30 形态（<conversation_summary> + 近 5 轮截断）——防止病态长会话的首包过大；
正常增长交给轮内压缩（见 B）。`deep_research_carry_history`(True) 总开关，关掉退回
旧行为（只带本轮问题）。

### B. 分层压缩（对齐 Claude Code microcompact + autocompact）

1. **工具结果定向清理**（已有，Phase 29）：`ClearToolUsesEdit` 超 30k token 清旧工具
   结果、保最近 5 个；
2. **临近窗口全量压缩**（勘误：框架内置，无需自研）：deepagents 已为主 agent 和每个
   subagent 内置加强版 SummarizationMiddleware（被驱逐历史落盘
   /conversation_history/{thread_id}.md 可 read_file 找回、溢出自动压缩重试）。
   **自己再挂同名实例会触发 "duplicate middleware instances" 断言**（线上踩坑，
   见 docs/pitfalls/deepagents内置Summarization中间件与同名判重.md）。
   我们只保留 ClearToolUsesEdit（第一层，deepagents 没有内置）。

### C. 记忆注入 + 轮末钩子

- 轮初 `gather_context`（含 Phase 30 选择器）→ `<background_memory>` 进末条 user 消息；
  `meta.memories_used` 一并写终稿消息（前端「🧠 记忆」卡片与另两条链路对齐）；
- 轮末成功路径补 `extract_and_save`（研究轮透露的偏好进三元组记忆）+
  `update_history_summary`（为回退路径和 guide/direct 维护摘要）。

## 涉及模块

- `backend/app/config.py` —— 三个配置
- `backend/app/agent/orchestrator.py` —— `_full_history_messages(cid)`（全量逐字版）
- `backend/app/agent/deep_research.py` —— 消息装配、SummarizationMiddleware、轮末钩子
- `backend/tests/test_deep_research_context.py`（新增）

## 验收标准

- 全量模式：消息 = 交替历史（逐字，含长报告全文）+ 末条 user（记忆标签+问题）；
- 超限回退：历史字符超限时出现 <conversation_summary> + 截断近窗；
- 开关关：退回单条 user 消息；
- 主 agent middleware 含 ContextEditing + Summarization（后者 trigger/model 正确）；
- 研究成功后 extract_and_save 与 update_history_summary 各被调用一次，失败/超时不调；
- meta 带 memories_used；全部单测通过；线上回归：研究后追问（再开深度推理）能接住上文。

## 风险

- 全量历史 + 研究长报告 → 首包变大：60k 字符上限 + 轮内 Summarization 双保险；
- SummarizationMiddleware 触发时打断 prompt cache：与 Claude Code autocompact 同款
  取舍，触发频率低（40k 才触发）；
- 历史里的旧报告可能干扰新问题：模型有完整上下文自行判断相关性，观察线上效果，
  必要时降 history_max_chars。
