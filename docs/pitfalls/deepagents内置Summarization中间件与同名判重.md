# deepagents 内置 Summarization 中间件：自己再挂同名实例线上必炸

## 现象

Phase 33 给主 agent 加 `SummarizationMiddleware`（临近窗口全量压缩）后部署，线上每轮
深度研究在 `create_deep_agent` 处直接失败：

```
AssertionError: Please remove duplicate middleware instances.
```

单测全绿（全部 mock 了 `create_deep_agent`），完全没拦住。

## 原因

两个叠加：

1. **deepagents 本来就内置** `create_summarization_middleware(model, backend)`
   （graph.py 为主 agent 与每个 subagent 各挂一份）——而且是**加强版**：压缩前把被
   驱逐的历史落盘到 backend 的 `/conversation_history/{thread_id}.md`（agent 可用
   read_file 找回，比 LangChain 裸版的「驱逐即丢」好）、大 write_file 参数先截断、
   provider 报上下文溢出时自动压缩重试。
2. langchain `create_agent` 按 `AgentMiddleware.name` 判重，deepagents 的包装类与
   LangChain 原版同名——我们在 `middleware=` 再传一个就是 duplicate。

## 解决

删掉自挂的 SummarizationMiddleware，autocompact 这层由框架内置承担；我们只保留
`ContextEditingMiddleware`（工具结果定向清理，deepagents 没有内置这个）。

## 教训（防复发措施已落地）

- **用框架前先看它送了什么**：deepagents 的内置中间件清单（todo/filesystem/subagents/
  summarization）要当作已占用的坑位，加东西前查 `graph.py` 的装配。
- **mock 挡不住装配错误**：新增了 `test_build_agent_real_construction_smoke`
  （不 mock deepagents 真实构建一次图），任何 middleware/参数改动必须过它。
  Phase 29 上线前做过手工真实构建冒烟所以没事，Phase 33 省了这步就翻车——
  这类冒烟必须进测试套件而不是靠手工记得做。

相关：`docs/task_plans/task_plan-phase33-深度研究跨轮上下文.md`。
