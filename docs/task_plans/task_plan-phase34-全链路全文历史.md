# Task Plan — Phase 34：direct/guide 升级全文历史（对齐 Claude Code 上下文管理）

## 背景

Phase 33 给了深度研究全量历史，但 direct/guide 仍是「近 5 轮 + 每条截 500 字」——
用户追问「解释一下上一轮的推荐」时，上一轮的长攻略只剩开头 500 字，答不准后半段的
具体推荐。用户拍板：direct/guide 也改全文，上下文管理仿 Claude Code。

## 机制映射（direct/guide 是单次生成调用，不是 agent 循环，挂不了 middleware）

| Claude Code | 研究链路（Phase 29/33） | direct/guide（本期） |
| --- | --- | --- |
| microcompact（清旧工具结果） | ClearToolUsesEdit 中间件 | **轮末蒸馏已天然等价**：来源原文/工具结果从不进跨轮历史，历史里只有 user/assistant 终稿，无可清理项 |
| autocompact（临近窗口全量压缩） | deepagents 内置 Summarization | **装配期压缩**：全文超限 → 旧轮次换 Phase 30 结构化摘要 + 近 N 轮保留**全文** |

## 方案

新增共享装配函数 `_assemble_history(cid, current_user_text)`（orchestrator）：

1. 取全量历史（`_full_history_messages`，逐字）；
2. 尾部与本轮问题重复的落库用户消息去重（guide 此前一直存在轻微重复，顺带修掉）；
3. 总字符 ≤ `history_full_max_chars`(60k) → 全文注入，摘要为空；
4. 超限 → 近 `history_rounds`(5) 轮**逐字保留**（不再截 500）+ 更早轮次用
   `conversation_summary`（Phase 30 轮末维护的结构化摘要）——即 Claude Code
   分段压缩的「recent verbatim + 旧前缀摘要」形态。

接入点：
- `build_guide_messages`：历史部分改用 `_assemble_history`（原 `_history_context`
  保留给 parse_request 的文本路径和研究回退路径）；
- `run_direct_answer`：同上。

缓存结构不变差：历史仍是 append-only 前缀，记忆/摘要仍在末条 user；全文化只是让
前缀更长——DeepSeek 前缀缓存跨轮命中，增量只付尾部。

## 涉及模块

- `backend/app/config.py` —— `history_full_max_chars: int = 60000`
- `backend/app/agent/orchestrator.py` —— `_assemble_history` + 两处接入
- `backend/tests/test_full_history.py`（新增）

## 验收标准

- 未超限：guide/direct 消息数组含全文历史（长攻略逐字），与本轮重复的用户消息去重；
- 超限：近 5 轮逐字 + <conversation_summary>，旧轮次不出现原文；
- guide 的轨迹结构（Phase 31 的 system→历史→user→tool_calls→tool）不变；
- 全部单测通过；线上回归：长攻略后追问「解释上一轮第 X 天的推荐」能引用到后半段细节。

## 风险

- direct 是高频链路，全文历史让未命中缓存时的 prefill 变贵/变慢（用户已知情拍板）；
  60k 上限 + 前缀缓存缓解；若线上首字延迟明显恶化，`history_full_max_chars` 可调小。
