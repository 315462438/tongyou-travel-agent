# Phase 24 Langfuse 埋点 — 验收用例

自动化：`backend/tests/test_observability.py`（4 例，全离线不发网络）。
命令：`cd backend && .venv/bin/python -m pytest tests/test_observability.py -q`

| # | 用例 | 期望 | 覆盖 |
| --- | --- | --- | --- |
| 1 | 默认（无 key） | enabled=False；handler/wrapper=None；turn_trace/span yield None；flush 不抛 | `test_disabled_is_full_noop` |
| 2 | 只开开关没 key | 仍 no-op（enabled=False） | `test_enabled_requires_keys` |
| 3 | 开关+key 齐 | CallbackHandler / langfuse.openai 包装类可创建（不发网络） | `test_enabled_creates_handler_and_wrapper` |
| 4 | 未启用时 LLMClient | `_client` 是裸 openai 模块的类（零行为变化） | `test_llm_client_fallback_plain_openai` |

## 无 key 回归（✅）
本地一轮 direct 问题 20s 正常完成，uvicorn 日志零 langfuse 痕迹；全量 196 单测通过；
已部署线上（默认关闭）。

## 埋点覆盖（填 key 后用户侧验证清单）

在 Langfuse 界面应看到：
1. **Sessions 按会话分组**（session_id=cid），每轮一条 `conversation_turn` trace，
   metadata 含 route/deep_reasoning/turn_id；
2. trace 下嵌套**每次 LLM generation 的完整 messages 输入与输出**（路由分类、parse、
   直答/攻略流式、记忆提炼——LLMClient 全走 langfuse.openai 包装）；
3. **研究模式**：agent 全图 trace 树——每轮模型请求（含拼好的 [system]+history messages）、
   write_todos / web_search / open_page / `task`（api-researcher 子 agent 及其内部
   amap_city_brief / fetch_url 调用）的入参与返回；
4. guide 流水线：`web_search` / `open_page` 手动 span（查询词/URL → 结果数/字符数）。

## 启用方法

1. https://cloud.langfuse.com 注册（有免费额度）或 self-host，建项目拿 pk/sk；
2. `.env` 加：
   ```
   LANGFUSE_ENABLED=true
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_SECRET_KEY=sk-lf-...
   # 自托管才需要：LANGFUSE_HOST=https://your-host
   ```
3. 重启后端。铁律：无 key 即全 no-op，埋点异常只 warn 不影响业务。

## 自托管部署（腾讯云同机，✅ 已上线）

- 栈：`/home/ubuntu/langfuse/docker-compose.yml`（ClickHouse+Redis+MinIO+web+worker，
  全 host 网络，PostgreSQL 复用宿主机实例，内存限额裁剪版——见
  docs/pitfalls/langfuse自托管小内存与v4API.md）。
- 密钥：`/home/ubuntu/langfuse/.env`（openssl 随机生成，LANGFUSE_INIT_* 无头引导出
  固定 pk/sk）；数据全在本机磁盘（clickhouse/minio 卷 + 宿主 PG langfuse 库）。
- UI 只监听 127.0.0.1:3000（外网不可达）：本地 `ssh -L 3000:localhost:3000 ubuntu@42.194.202.233`
  后开 http://localhost:3000，账号 admin@travelx.local（密码在服务器 .env 的 LF_ADMIN_PASSWORD）。
- 线上 E2E（✅）：一轮 direct 对话 → Langfuse API 查到 1 条 conversation_turn trace
  （sessionId=cid、userId、latency 14.9s），下挂 3 个 GENERATION 均含完整 messages
  （flash 路由分类 / v4-pro 直答 / flash 记忆提炼）+ 根 span。
- 服务管理：`cd /home/ubuntu/langfuse && docker compose ps|logs|restart`；
  containers restart: always，随 docker 开机自启。
