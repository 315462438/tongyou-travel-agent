# Task Plan — Phase 45：记忆机制三项优化（对照《AI Agent 记忆》章节）

## 背景

对照 bojieli/ai-agent-book chapter3 的记忆设计，现有系统（Phase 4/17/30）已覆盖
三元组归槽、ADD/UPDATE/DELETE、双层注入、来源标记、新鲜度标注。补三个真实缺口
（企业级 RAG/向量库/GraphRAG 按文档「不过度设计」原则明确不做）。

## ① 补齐重要性评分：访问频率（hit_count）

文档四因素（访问频率/时间衰减/情感强度/独特性）里，现状只用了 explicit(weight)
+ updated_at，**缺访问频率**——高频命中但久未更新的核心偏好会在排序沉底、剪枝被误删。

- `travel_memory` 加 `hit_count INTEGER default 0`（迁移幂等加列）；
- `gather_context` 里对**实际注入**的记忆 +1（写失败只 warn，不阻塞本轮）；
- `load_memories` 排序改 `weight↓, hit_count↓, updated_at↓`——explicit 仍最高优先，
  同档内高频靠前；`_prune` 因复用此排序，自动保护高频记忆不被误删。

## ② 补程序记忆类型：规划习惯（procedural）

文档认知三分法（情景/语义/程序），现状只有语义(fact)+偏好(preference)，缺**程序记忆**
（行为流程）。旅行场景有实际价值：「先定酒店再排景点」「自由行不跟团」「提前很久订」。

- `MEMORY_TYPES` 加 `procedural`；`CANONICAL_KEYS` 加 `规划习惯: procedural`；
- `EXTRACT_SYSTEM` 加一条提炼纪律；`format_memories_block` 类型标签加「习惯」。

## ③ 情景→语义提炼：旅行足迹（历史行程沉淀）

`trip_state` 是单槽，新行程覆盖旧的 → 「去过哪些地方」历史丢失。对应文档「第三层压缩：
从情景提炼一般性规律」。

- `CANONICAL_KEYS` 加 `旅行足迹: fact`（累积去过/规划过的城市）；
- `EXTRACT_SYSTEM` 加纪律：覆盖「当前行程」到新目的地时，把旧目的地并入「旅行足迹」
  （LLM 驱动，不做脆弱的文本解析）；
- `CONSOLIDATE_SYSTEM` 注明旅行足迹是累积槽，合并不丢城市。

## 验收

- hit_count：注入后自增；排序/剪枝纳入（自动化：构造高频久未更新 vs 新低频，前者排前
  且剪枝保留）；
- procedural：规划习惯类输入提炼到 key=规划习惯 type=procedural（fake llm）；注入块
  类型标签正确；
- 旅行足迹：EXTRACT/CONSOLIDATE prompt 含相应纪律；canonical key 映射正确；
- 全部单测通过；线上部署 + 迁移生效。

## 明确不做

向量库 / BM25 / GraphRAG / RAPTOR / User-as-Engram / 多模态 / PII 本地脱敏——
个人+小团体量级（几十条），全量注入+小模型挑选已最优，文档亦不建议。
