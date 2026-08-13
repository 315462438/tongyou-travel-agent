# 停止链路两坑 + 旧行程记忆污染（2026-07-31，线上用户「不能中途停止」「怎么是国庆」排障）

## 坑 1：budget/poster 完全没接协作式取消

**现象**：预算/海报生成期间点「停止」，toast 提示「已请求停止」，任务照跑到底；
更糟：残留的取消标记会把**下一轮**正常消息在首个检查点误杀成「已停止本轮」。

**原因**：Phase 16 的协作式取消只埋在主流水线（搜索/抓取/流式生成），
`budget.py`/`poster.py` 这类独立 BackgroundTasks 一个检查点都没有，也没人清标记；
graph 的 `critique_node`（静默反思）同样没有检查点。

**解决**：三处补 `cancel.check`；`generate_budget`/`generate_poster` 捕获
TurnCancelled 终稿「已停止…」并 **finally clear_cancel**。

## 坑 2：`asyncio.run` 退出会 join 默认线程池——停止逻辑触发了，用户却看不到

**现象**（补上坑 1 之后仍复现）：停止后 `TurnCancelled` 1 秒内就抛了（探针日志证实），
但「已停止」消息要等 40s～3min 才出现，与被放弃的 LLM 调用自然结束的时间完全一致。

**原因**：`generate_budget` 结构是 `asyncio.run(_run(...))` + 在**外层**捕获 TurnCancelled
做终稿。而 `asyncio.run` 退出时会 `shutdown_default_executor()`——join 掉
`asyncio.to_thread` 里那个还在跑的孤儿 LLM 线程。异常传播被卡在这一步，
外层的 finalize 只能等孤儿线程跑完。

**解决**：**终稿处理必须放进传给 asyncio.run 的协程内部**（`_run` 里 except TurnCancelled
→ 立即 `_finalize` + `clear_cancel` → return）。外层 except 只留作兜底。
配套 `cancel.wait_cancellable(cid, awaitable)`：等待 LLM 结果期间每秒轮询停止标记，
取消时放弃结果立刻抛（孤儿线程后台自然结束，结果丢弃）。
实测：点停止后 ≤2 秒可见「已停止」。

**通用教训**：凡「asyncio.run + to_thread 跑长调用 + 想提前退出」的组合，
提前退出后的**用户可见副作用（写库/发消息）都要在协程内完成**，
asyncio.run 之后的代码要按「可能晚几分钟才执行」对待。

## 坑 3：旧行程的「当前行程」记忆污染新行程（时间/预算凭空出现）

**现象**：用户问「合肥→武汉沿途有什么可逛」（没提任何时间），攻略里却写
「国庆期间大概率不堵」「都在用户整体 5000 元预算内」——国庆和 5000 来自记忆里
**上一次成都行程**（「2026年10月国庆去成都，4天3晚，预算5000」）。

**原因**：记忆全量注入 + 注入块只说「请在规划时考虑」，没有约束「记忆里的日期/预算
属于当时那次行程」；`is_explicit_itinerary_request` 只在「完整规划请求」时过滤
trip_state，沿途推荐这类请求不命中。

**解决**（双层）：
1. `filter_foreign_trip_memories`（确定性）：目的地已知时，内容不含本次目的地的
   trip_state 记忆直接不注入；
2. `format_memories_block` 尾部加「记忆使用纪律」：日期/节假日/目的地/预算除非本轮
   重申，不得写进回答。

**通用教训**：时点型记忆（trip_state）注入前要过「与本轮是否同一件事」的门；
偏好型记忆（口味/节奏）才适合无条件注入。
