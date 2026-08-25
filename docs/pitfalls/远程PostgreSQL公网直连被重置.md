# 踩坑：远程 PostgreSQL 公网直连 5432 被重置

> 日期：2026-07-03　|　阶段：Phase 1 数据库部署

## 现象

- 服务器（腾讯云 <服务器IP>，Ubuntu 24.04，PostgreSQL 16.14）配置了 `listen_addresses='*'` + pg_hba 放行，`ss` 确认监听 0.0.0.0:5432
- 本地 `nc -z <服务器IP> 5432` **TCP 握手成功**
- 但 psycopg 真实连接报 `server closed the connection unexpectedly`
- **关键证据**：PostgreSQL 日志里完全没有任何连接记录——数据包在到达 PG 之前就被丢弃/重置

## 原因

TCP 握手能通但协议数据被重置，且服务器端 iptables（仅腾讯云主机安全 YJ-FIREWALL 的少量 IP REJECT）无相关规则 → 判定为**中间网络（运营商或云平台安全策略）对数据库端口明文流量的拦截**。国内网络环境对 3306/5432/6379 等数据库端口的跨网直连常有此类干扰。

排查路径（供复用）：
1. `nc -z` 测 TCP 可达性 → 通，排除安全组直接 DROP
2. 服务器上 `psql -h 127.0.0.1` → 通，排除认证/pg_hba 问题
3. 查 PG 日志有无连接记录 → 无，确定包没到 PG
4. 查 iptables → 无相关规则 → 锁定中间网络

## 解决办法

放弃公网直连，改用 **SSH 隧道**（走已验证可用的 22 端口）：

```bash
# backend/scripts/db_tunnel.sh
ssh -f -N -L 15432:localhost:5432 $DEPLOY_HOST
# .env 改为
DATABASE_URL=postgresql+psycopg://travel_agent:***@127.0.0.1:15432/travel_agent
```

附带收益：
- PostgreSQL 改回只监听 localhost，**不暴露公网**，安全性更好
- 顺手配置了 SSH 密钥认证（`ssh-copy-id`），隧道免密自动重连（ServerAliveInterval=30）

## 使用注意

- 启动后端前先跑 `backend/scripts/db_tunnel.sh`（幂等，已有隧道会跳过）
- 隧道断开会导致 DB 连接失败，engine 已配 `pool_pre_ping=True` 可自动检测重连
