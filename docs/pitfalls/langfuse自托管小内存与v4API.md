# 踩坑：Langfuse 自托管上 3.6G 小机 + SDK v4 API 改名

Phase 24 把 Langfuse v3 服务端自托管到 3.6G 内存的腾讯云（与 travelX 后端同机）踩到两个坑。

## 1. langfuse-web 容器 Node 堆 OOM

**现象**：`docker compose up` 后 web 容器反复重启，日志尾部：
```
FATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory
```
health 一直 000。

**原因**：给 web 容器设了 900M 内存限额，但 Next.js 服务端的 Node 堆不够。

**解法**：限额提到 1300M 并**显式设 Node 堆**：`NODE_OPTIONS: --max-old-space-size=1024`
（worker 同理给 448）。小内存机所有容器都要 `deploy.resources.limits.memory` 封顶——
OOM 时只杀该容器（restart: always 自动拉起），不波及宿主机上的后端/浏览器池。

**小机全套预算**（实测跑起来 used ~2.7G / avail ~0.9G，个人流量可用但紧）：
ClickHouse 1100M（另有 lowmem.xml 把 max_server_memory_usage 压到 900M）、
web 1300M、worker 600M、MinIO 300M、Redis 128M；PostgreSQL 复用宿主机现有实例
（省一个容器）；全部 host 网络，UI 只听 127.0.0.1:3000（外网不可达，SSH 隧道访问）。

## 2. SDK v4 把 v3 的 span API 改名了

**现象**：后端日志 `AttributeError: 'Langfuse' object has no attribute 'start_as_current_span'`，
trace 一条都没写进去。

**原因**：网上资料/文档多是 v3 API；langfuse SDK **v4** 改成：
- 建 span：`lf.start_as_current_observation(name=..., as_type="span", input=...)`
- trace 级属性（session_id/user_id/metadata）：**不再** `span.update_trace(...)`，
  改用 `from langfuse import propagate_attributes` 上下文包住（内部创建的所有 span 自动带上）；
- span 对象只有 `.update()/.end()`。

**教训**：我的离线单测最初只测了「禁用时 no-op」，没在启用态真正调建 span 的方法，
所以本地绿灯、线上才炸。已补 `test_enabled_turn_trace_and_span_yield_real_objects`
（启用态断言 span 非 None 且可 update）。**对第三方 SDK 的封装，单测必须至少
真实调用一次目标 API**，光测开关逻辑挡不住版本改名。

另：requirements 从 `langfuse>=3.0` 钉到 `>=4.14`，避免环境间版本漂移。

## 追加（2026-07-14）：大 observations 查询会打挂 langfuse-web

深度研究一轮的 trace 有 200-300 条 observation、带完整 prompt/输出 payload，
`GET /api/public/observations?limit=100` 单次响应十几 MB，langfuse-web（限额 1300M）
组装响应时直接崩掉（当天重启 5 次），期间平台内调用链面板显示「调用链服务暂时不可用」。

**规则：对自托管实例查 observations 一律小分页（limit≤25）翻页**。平台内
`trace_api._fetch_observations` 已按 25/页、上限 8 页实现；手动排查时同理，
别一把 limit=100。
