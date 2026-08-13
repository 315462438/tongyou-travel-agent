# Task Plan — Phase 57：睡眠整合（记忆自主整理，chapter8 机制⑤）

## 背景
读 ai-agent-book chapter8「自我进化」。评估后：完整自我进化套件对本项目过早（无 embedding、
成功信号弱、个人量级），但**记忆自主整合**是现有机制的自然延伸、低风险，值得做。
现状：`consolidate_memories`（LLM 把零散记忆重写成规范三元组）**只有手动按钮触发**，缺自动调度。

## 方案：轮末门控 + 后台整合（不阻塞、复用现有 consolidate_memories）
- 新增 `TravelUser.memory_consolidated_at`（上次整合时间，门控频率用；migrate 幂等加列）。
- `_should_sleep_consolidate(db, uid)`（纯判断、可测）门控三条同时满足才整：
  1. 距上次整合 ≥ `memory_consolidate_min_hours`(6h)；
  2. 距上次后新增/变更记忆（`updated_at > 上次`）≥ `memory_consolidate_min_new`(5)；
  3. 记忆总量 ≥ `memory_consolidate_min_total`(8)（太少不值得整）。
- `maybe_consolidate_async(uid)`：查门控 → 满足则起 daemon 线程整合；`_consolidating` 集合 +
  锁防同一用户并发。
- `_run_sleep_consolidate(uid)`：后台调 `consolidate_memories` + 更新 `memory_consolidated_at`；
  失败只记日志。
- 接入点：`extract_and_save` 末尾调 `maybe_consolidate_async`——每轮提炼完顺带门控检查，
  攒够才整，绝不阻塞回复。
- 开关 `memory_sleep_consolidate_enabled`（默认 True）。

## 为什么这样设计
- **门控而非每轮整**：整理烧 LLM，攒够新记忆 + 隔够久才整，省 token 也更像「睡眠期沉淀」。
- **DB 时间戳门控频率**（naive 去 tz 比较，对齐 site_router）；**记忆 updated_at** 判「新」，无需额外计数器。
- **复用 consolidate_memories**：整合逻辑（LLM 重写 + 空结果不清空兜底）已验证，不重写。
- **纯判断拆出可测**：`_should_sleep_consolidate` 单独可离线测所有门控分支。

## 取舍（chapter8 其余机制暂不做）
prompt 自动优化（漂移风险，人工手调更稳）/ 工作流录制回放（携程反爬+改版脆）/ 工具合成
（就3个工具）/ 失败→自动改 prompt（保持人工写 pitfall）——见「响应速度优化复盘」外的分析。
技能自动生成留作「人在环」未来项（好行程后提示用户存成技能）。

## 验收
- `test_memory_sleep_consolidate.py`：门控 5 分支（首次够多/总量不足/刚整过/无新记忆/够久够多）
  + 触发起线程 + 并发去重 + 开关关——7 例过。
- 全量 pytest 过；线上迁移自动加列、health ok。
- 线上观察：活跃用户攒够新记忆隔够久后，日志出现 `sleep-consolidated memories for ...`。
