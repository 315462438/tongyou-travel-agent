# db_tunnel.sh 误判隧道存活（lsof 把 CLOSED socket 当占用）

> 记录：2026-07-06（Phase 3 冒烟测试时发现）

## 现象

SSH 隧道进程早已死亡，但 `backend/scripts/db_tunnel.sh` 一直输出「隧道已在运行」，
后端连 `127.0.0.1:15432` 报 `connection refused`，且反复跑脚本都不会重建隧道。

## 原因

脚本用 `lsof -i ":$LOCAL_PORT"` 判断端口是否被占用。但 `lsof -i` 会匹配到
**任何状态**的 socket —— 包括其它进程（当时是一个残留的 uvicorn）连向 15432 的
`CLOSED` 状态客户端 socket：

```
python3.1 924 ... TCP localhost:62004->localhost:15432 (CLOSED)
```

隧道（LISTEN 端）没了，但这些尸体 socket 让脚本以为端口还被隧道占着，直接 exit 0。

## 解决办法

判断改为只认 LISTEN 状态的 socket：

```bash
lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN
```

只有真正有进程在本地端口上监听（即隧道活着）才会命中；客户端残留 socket 不再误判。

## 经验

- 判断「服务是否在运行」永远用 `-sTCP:LISTEN` 过滤，别裸用 `lsof -i`。
- 隧道假死时，`nc -z` / psycopg 直连是最快的真伪验证手段。
