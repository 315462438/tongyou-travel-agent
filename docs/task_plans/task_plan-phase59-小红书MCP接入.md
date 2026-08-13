# Task Plan — Phase 59：小红书 MCP 接入（来源分工重排 + 提速）

## 背景
Phase 3 想接小红书被「风控封云 IP」坑住（XHS_ENABLED=false），路线/攻略来源一直靠必应——
杂乱、慢（2 次搜索 + 最多 8 页浏览器抓取）。已验证 xpzouying/xiaohongshu-mcp（14.8k star）：
服务器 docker 部署（127.0.0.1:18060，限内存 800M），扫码登录 cookie 已文件挂载持久化，
**云 IP + 登录态实测通过风控**（搜索 22 条 + 笔记详情完整），内容质量远超必应。

## 来源分工（用户定的新策略）
- **小红书**：攻略/路线/美食/玩法体验（质量最高）
- **高德**：天气/景点坐标/POI（已有）
- **携程**：酒店实价（已有）
- **必应**：兜底补充——**小红书可用时缩减**（查询 2→1、抓取 8→4），整轮提速

## 实现
1. `app/tools/xhs_mcp.py`（薄客户端，全失败静默降级）：
   - `enabled()` = 配置了 `XHS_MCP_URL`；
   - `_parse_feeds/_parse_detail` 纯函数（可离线测；列表页 title 常空，以详情为准）；
   - `search_notes(keyword)` / `note_detail(feed_id, token)`：mcp streamable HTTP，整体超时
     `xhs_mcp_timeout_s`(25s)，异常/未登录返回空；
   - `collect_xhs_sources(dest, query, limit)`：搜索 → 取前 N 篇详情 → source dict
     （site="xhs"，url=explore 链接，summary=正文截断）。
2. guide 流水线（`collect_sources`）：非 hotel 意图先并入小红书来源（纯 HTTP，在浏览器会话
   建立前跑）；**拿到 ≥2 篇 → 必应轻量化**（1 个查询、max_fetch=4）；小红书失败/未启用 →
   必应全量（行为不变）。progress 全程可见。
3. 深度研究：`api-researcher` 加 `xhs_search`/`xhs_detail`（配额 `deep_research_max_xhs`(4)，
   共享 `_stash_source` 留存换引用 + wrap_external）；RESEARCH_SYSTEM 资源纪律更新：
   攻略/美食/体验类信息优先小红书，web_search 降为「高德+小红书都覆盖不了才用」。
4. 安全：笔记正文是外部内容，进 prompt 一律走 wrap_external（guide 的 tool 消息 + 研究的
   stash 都已有该防线）。
5. 登录态失效：collect 返回空 → 自动回退必应全量 + progress 提示「小红书暂不可用」；
   重新扫码暂走人工（docker 容器 get_login_qrcode），做进 handoff 卡片留作后续。

## 验收
- 单测：feeds/detail 解析（真实返回结构）、enabled 开关、collect 组装 + 失败降级；
- 全量 pytest 过；服务器 .env 加 `XHS_MCP_URL` 部署；
- 线上实测：发一条路线规划，progress 出现「小红书」来源、必应缩为 1 次查询，
  攻略引用小红书笔记；总时长应明显缩短。
