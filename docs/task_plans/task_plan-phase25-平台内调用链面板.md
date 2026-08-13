# Phase 25 — 平台内调用链面板（右侧抽屉展示每轮 trace）

## 目标

不用开 Langfuse UI，在 travelX 聊天界面上直接看每轮的调用链：
助手消息下加「🔗 调用链」按钮 → 右侧抽屉展示该轮 trace 树
（每次 LLM 调用的完整 prompt/输出、span/工具、模型、耗时）→ 再点按钮或 ✕ 隐藏。

## 方案

### 后端 `app/api/trace_api.py`
`GET /api/chat/{cid}/trace?turn_id=<用户消息id>`（需登录 + 会话归属校验）：
1. `obs.enabled()` 为假 → `{"enabled": false}`（前端提示未开启埋点）；
2. 服务端用 pk/sk（不出后端）调本机 Langfuse 公共 API：
   `traces?sessionId=cid` → 按 `metadata.turn_id` 匹配该轮（匹配不到回退最新一条）；
   `observations?traceId=...` 拉观测列表；
3. 化简返回：trace {id,name,latency,timestamp} + nodes[{id,parentId,type,name,model,
   durMs,input,output,usage}]，input/output 截断（≤4000 字符）防大包。
   拆 `_pick_trace` / `_simplify` 纯函数便于离线单测。

### 前端
- 助手终稿消息按钮排加「🔗 调用链」；turn_id = 该消息之前最近一条 user 消息 id
  （渲染时在 Home 计算传入）。
- 右侧固定抽屉（~460px，overlay 不挤压正文）：节点树按时间排序、类型徽章
  （GENERATION/SPAN/TOOL/AGENT 分色）、每节点显示名称/模型/耗时，点击展开
  input/output（等宽字体 pre）。同按钮再点或 ✕ 关闭。

## 验收
1. 点按钮右侧出抽屉：能看到路由分类/生成等 GENERATION 的完整 messages 与输出、耗时；
   再点隐藏。研究轮可见工具树。
2. 旧轮次（早于埋点）/未启用 → 抽屉内友好提示，不报错。
3. 离线单测：`_pick_trace`（turn_id 匹配/回退）、`_simplify`（截断/父子/耗时）、
   未启用返回 enabled=false。
4. 线上 E2E：真实轮次 curl 接口出节点；UI 点击验证。
