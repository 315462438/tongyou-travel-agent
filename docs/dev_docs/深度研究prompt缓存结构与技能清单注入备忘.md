# 备忘：深度研究 prompt 缓存结构 与 技能清单注入方案（未改造，留档复盘）

> 2026-07-17 讨论结论：**保留现状，不做改造**。本文记录当时的结构分析、两个候选
> 优化的成本收益账、以及后续值得重启的触发条件。

## 1. 现状：研究轮的前缀缓存结构（Phase 33 后）

```
┌ system ──────────────────────────────────────┐
│ RESEARCH_SYSTEM（纪律，静态）                  │  ← 变更频率：仅部署
│ + SANDBOX_NOTE（仅本轮开沙箱时拼接）⚠️         │  ← 变更频率：用户每条消息可切开关
│ + deepagents 生成段（技能清单/文件工具/子agent）│  ← 变更频率：技能增删时
├ 全量历史（user/assistant 交替，append-only）──┤  ← 只增不改 → 跨轮前缀命中
└ 末条 user（<background_memory> + 本轮问题）──┘  ← 每轮变（刻意放尾部）
```

- DeepSeek 自动前缀缓存：前缀逐字节相同即命中。稳态（技能不变、沙箱开关不变）下，
  连续研究轮的 system + 已有历史全部命中，只有尾部新增付全价。
- 技能清单虽在 system，但**逐字节稳定**——稳态缓存效果与任何「增量公告」方案相同。

## 2. 候选方案 A：announced_skills（Claude Code 式技能公告，未采纳）

**做法**：关闭 deepagents SkillsMiddleware 的清单注入；技能元数据改为 user 角色
公告消息进历史（首次出现才发），会话表加 `announced_skills` 字段记录已公告集合；
中途上传技能只追加增量公告，不改 system。

**唯一优于现状的场景**：会话中途上传/删除技能。现状下这改变 system → 整条前缀作废、
付一次全量 prefill；公告方案只在尾部追加。

**不采纳的三个理由**（当时判断）：
1. 触发频率太低：个人使用技能增删是「几天一次」量级，每次省的只是一次 prefill；
2. 工程成本：对抗框架（关中间件、自管公告落库与重建顺序、新 DB 字段）；
3. 质量风险：清单从 system 挪到历史中部后，弱模型（DeepSeek）的技能命中率可能下降
   ——Claude Code 敢这么做有专用 Skill 工具 + 强模型托底，我们靠 system 清单 +
   read_file。

**重启触发条件**（满足其一再做）：
- 技能上传/删除频率上升到每周多次（多用户或高频迭代技能库）；
- 技能总数上到几十个、清单本身开始占显著 token；
- 换到对上下文中部内容遵循更强的模型。

## 3. 候选方案 B：SANDBOX_NOTE 移出 system（更划算，暂也不改）

分析发现当前结构里**真正高频的 cache 杀手不是技能清单，而是沙箱说明**：
`SANDBOX_NOTE` 按「本轮沙箱开关」拼进 system，用户每条消息都可切换开关——切一次，
system 变一次，整条历史前缀作废。

**建议做法**（约 10 行改动）：沙箱说明挪到末条 user 消息（本轮指令，语义也更贴切），
system 对同一用户完全静态。general-purpose subagent 的同款说明同理。

**暂不改的原因**：用户要求保留现状统一复盘。**重启触发条件**：复盘时若 Langfuse
显示研究轮 prefill 耗时/费用显著（连续轮次首调用输入 token 远超增量），优先做这个。

## 4. 复盘时可直接采信的量化方法

- Langfuse 里取连续两轮研究的首次 LLM 调用，比较第二轮 input tokens 与「上轮总输入 +
  增量」——若接近全量说明缓存没命中，查 system 是否变了（沙箱开关是最可能的原因）；
- DeepSeek 返回的 usage 里有 prompt_cache_hit_tokens / miss 字段（v4 系列），
  可直接在 LLMClient 层打日志量化命中率。

## 相关

- `docs/task_plans/task_plan-phase33-深度研究跨轮上下文.md`（全量历史 + 分层压缩）
- `docs/pitfalls/deepagents内置Summarization中间件与同名判重.md`
- Claude Code 机制调研结论见 phase29 task plan 开头的对照表
