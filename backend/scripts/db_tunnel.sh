#!/bin/bash
# 数据库 SSH 隧道：本地 15432 → 服务器 localhost:5432
# 背景：公网直连 5432 被中间网络重置（见 docs/pitfalls/远程PostgreSQL公网直连被重置.md）
# 使用 SSH 密钥认证（已配置 ~/.ssh/id_ed25519）
set -e

LOCAL_PORT=15432
SERVER=ubuntu@42.194.202.233

# 只认 LISTEN 状态：残留的 CLOSED 客户端 socket 也会被 lsof -i 匹配到，
# 曾导致隧道已死却误报「已在运行」（见 docs/pitfalls/db_tunnel误判隧道存活.md）
if lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "隧道已在运行（本地端口 $LOCAL_PORT）"
    exit 0
fi

ssh -f -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -L "$LOCAL_PORT:localhost:5432" \
    "$SERVER"

echo "数据库隧道已建立: localhost:$LOCAL_PORT → $SERVER:5432"
