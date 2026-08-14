# SubagentTracker 缺回调属性导致深度研究必崩

- 日期：2026-08-14
- 现象：深度研究模式进入后立刻报「抱歉，研究过程中出错了，请重试。」，且初步判断消息
  落在报错**之后**（消息顺序反常）
- 涉及：`app/agent/subagent_trace.py`、`requirements.txt`

## 根因

`SubagentTracker`（Phase 88 子代理面板）刻意不继承 `AsyncCallbackHandler`（注释：避免版本间
基类签名漂移），按属性名鸭子调用。但 **langchain-core 1.4.x 的回调管理器对每个 handler 无条件
执行 `getattr(handler, "ignore_chain")`（chain 事件）和 `handler.raise_error`**——缺属性直接
AttributeError 冒泡，`agent.astream` 炸掉 → `run_deep_research` 捕获后把「研究过程中出错了」
终稿进占位。`requirements.txt` 全是 `>=`（`langchain-deepseek>=1.0`），每次部署 pip install
拉新 → langchain-core 被升到 1.4.9 触发新行为（此前版本不查这些属性）。

消息顺序反常的原因：quick take 在 `asyncio.to_thread` 里调 LLM（真实网络），主流程 agent 先
失败终稿占位，quick take 线程随后完成才落 preliminary 消息。

## 修复

1. `SubagentTracker` 补上与 `BaseCallbackHandler` 一致的默认属性集：`raise_error=False` +
   `ignore_chain/agent/llm/chat_model/tool/retriever/parser/custom=False`；
2. `requirements.txt` 锁 `langchain-core==1.4.9`（当前实测工作版本）——`>=` 无约束是漂移根源，
   升级需显式改并重测；
3. 回归测试 `test_subagent_tracker_survives_langchain_callback_manager`：真实
   `CallbackManager` 触发 chain/llm/tool 事件不抛。

## 教训

- **鸭子类型 handler 也要按官方基类的属性契约补齐**（`run_inline`/`raise_error`/`ignore_*`），
  只实现方法钩子不够——回调管理器会读属性；
- **`>=` 依赖是"部署即升级"**：行为变化只在线上炸、本地测不出（本地与服务器同版本才复现）。
  涉回调/中间件这类行为敏感库要锁版本；
- 测试里真实调 LLM 的增强路径（quick take）要显式关闭，否则网络通不通决定测试过不过
  （`test_run_deep_research_streaming_finalizes` 已补 `deep_research_quick_take=False`）。

---

## 追加（2026-08-14）：重启续跑把「被中断」提示插进用户新轮次

修复 SubagentTracker 后用户重测：初步判断正常了，但轮次中间又冒出
「⚠️ 上一轮处理被服务重启中断了」——**用户以为又被中断**。真相（时间线实证）：

- 16:18 部署重启 → `resume_inflight_turns` 后台线程续跑旧轮（research 无 checkpoint）
- 用户 16:21:53 **已重发新轮次**，正在正常跑（初步判断/高德/小红书 progress 都正常）
- 续跑线程直到 16:22:10 才判失败 → `_append_interrupted` **无条件写提示** → 插进新轮次中间

叠加问题：续跑线程本身可能很慢（checkpoint 在 collect 中途的 guide 轮要重新采集分钟级），
且与用户新轮次抢浏览器/LLM。

修复（`app/db/maintenance.py`）：
1. 新增 `_user_sent_after(cid, after)`：turn 之后已有新 user 消息 = 用户已重发；
2. `_resume_one` **续跑前**查：已重发 → 放弃续跑，只清残留占位 + 清 inflight，不写提示；
3. 续跑**限时 60s**（`asyncio.wait_for`），超时放弃；
4. 失败提示前**再查一次**（续跑期间用户可能又重发）——`_maybe_interrupted` 兜底。

**教训：启动恢复逻辑写"提示消息"前，必须检查会话是否已有更新的用户活动**——恢复提示
是给"等结果的用户"看的，不是给"已经重发的用户"看的。测试：
`test_user_sent_after_detects_resend` / `test_user_sent_after_ignores_progress`。
