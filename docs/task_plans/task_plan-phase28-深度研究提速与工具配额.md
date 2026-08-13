# Task Plan — Phase 28：深度研究提速（工具硬配额 + 产出纪律）

## 背景 / 现象

Phase 27d 修掉沙箱路径死循环后，线上回归（2026-07-14 17:06 那轮，trace
`25ff319be2e675b5fe68dad221724072`）不再撞步数上限，但整轮跑满 600s 超时，
产出全部作废，用户反馈「深度思考时间太久了」。

Langfuse trace 时间账：

- **前半程过度收集**：web_search 5+ 次（prompt 纪律写的是 ≤3，长上下文里漂移了）、
  fetch_url 读了 18+ 个来源、另有多次浏览器 open_page。每多读一个来源，后续每次
  LLM 调用的上下文都更肥更慢。
- **后半程低效产出**：主 agent 给**每一页幻灯片**单独派 general-purpose 子任务
  （「创建Slide-03商丘概况」「创建Slide-04景点TOP10」…），每个子任务又是几轮
  20-30s 的 DeepSeek 调用。仅 trace 尾部 200 条 observation 里 LLM 调用就有 32 次
  共 257s。
- 600s 兜底超时一到，`asyncio.wait_for` 取消任务，所有已完成工作直接丢弃。

## 根因

1. prompt 层的资源纪律（≤3 次搜索）没有强制力：上下文一长、弱模型就忘。
2. 没有任何机制阻止「按页拆子任务」这类烧时间的产出模式。
3. fetch 单次超时 15s 偏宽，坏来源最多能各吃 15s。

## 方案

1. **工具层硬配额**（代码强制，prompt 漂移也拦得住）：`research_tools.build_tools`
   闭包里记账，超限直接返回引导性文案（「配额已用完，基于已有资料进入下一步」），
   不再真的执行。配额进 settings：
   - `deep_research_max_searches: int = 3`
   - `deep_research_max_fetches: int = 10`
   - `deep_research_max_open_pages: int = 3`
   配额按**轮**计（build_tools 每轮调用一次），主 agent 与所有 subagent 共享同一份
   闭包计数——正好符合「浏览器/来源是全轮共享稀缺资源」的设计。
2. **产出纪律进 prompt**：
   - `RESEARCH_SYSTEM` 增加时间纪律：整轮有硬超时，来源 5-8 个够用就转产出。
   - `SANDBOX_NOTE` 增加一次成稿纪律：代码/文档由当前 agent 自己 write_file 一次写完，
     **禁止**为每个文件/页面/章节派 subagent。
3. **fetch 单次超时** 15s → 10s（坏来源止损更快）。
4. **心跳进度**（追加，同日线上反馈）：配额生效后工具调用变少，模型长推理/子任务/
   沙箱写代码期间前端最后一个气泡一直转圈，看起来像卡死。`_invoke_with_cancel` 的
   看护循环里每 `HEARTBEAT_EVERY_S`(60s) 写一条「🧠 研究进行中（第 N 分钟 / 预算约
   M 分钟）」progress（纯叙述、无 meta，轮末照常被 clear_plain_progress 清掉）；
   写失败只 warn 不影响主流程。

不动 `deep_research_timeout_s`（600s）：用户嫌的是「久」，加长只会更久；配额生效后
收集阶段被压缩，600s 预算大头留给产出，足够。

## 追加（28.1，同日线上反馈）

5. **搜索结果对应性校验**：`BrowserTool.search_web` 的 `_parse_search_payload` 一直
   提取搜索框值 `q`「用于校验结果对应当前查询」，但判断处只看 results 非空，**校验
   从没实现**——必应限流返回垃圾页/旧 DOM 时无关结果原样透传（线上搜「商丘古城」
   混进 Doomworld 论坛），agent 的搜索配额全被垃圾吃掉，终稿只剩高德一个来源。
   补 `_query_matches(box_value, query)`：框值为空判不匹配；任一 ≥2 长度查询词元
   与框值有包含关系即匹配（必应可能改写查询，不做全等）。不匹配 → 重试 → 360 兜底。
6. **open_page 计入来源**：来源卡此前只统计 fetch_url 成功 + 高德，浏览器读成功的
   页面漏计。与 fetch_url 同口径（正文 ≥120 字符）补记。
7. **调用链面板稳态**：`trace_api` 原来一次 `limit=100` 拉 observation（深度研究一轮
   带完整 payload 十几 MB），会把小内存自托管 langfuse-web 直接打挂（今日 5 次重启），
   前端显示「调用链服务暂时不可用」。改 25/页翻页、上限 8 页（200 条截断）。

- `backend/app/config.py` —— 三个配额项
- `backend/app/agent/research_tools.py` —— 配额记账 + FETCH_TIMEOUT_S
- `backend/app/agent/deep_research.py` —— RESEARCH_SYSTEM / SANDBOX_NOTE 纪律文案
- `backend/tests/test_research_quota.py`（新增）

## 验收标准

- web_search 第 4 次调用不触发真实搜索，返回配额文案；open_page 第 4 次同理；
  fetch_url 超过上限同理；配额跨主/子 agent 共享（同一 build_tools 产物）；
- 配额值可经 settings 覆盖（monkeypatch 验证）；
- SANDBOX_NOTE 含「禁止按页/按文件派 subagent」纪律；RESEARCH_SYSTEM 含超时预算提示；
- 全部单测通过；
- 线上回归：同样的「商丘 PPT」问题应在 600s 内完成并产出 artifacts（收集阶段
  显著缩短）。
