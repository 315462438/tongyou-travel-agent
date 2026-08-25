#!/bin/bash
# 数据库 SSH 隧道：本地 15432 → 服务器 localhost:5432
# 背景：公网直连 5432 被中间网络重置（见 docs/pitfalls/远程PostgreSQL公网直连被重置.md）
# 使用 SSH 密钥认证或密码认证（从环境变量 SSH_PASSWORD 读取）
set -e

LOCAL_PORT=15432
ENV_FILE="$(dirname "$0")/../.env"
# 服务器地址不写进仓库（本仓库公开）。优先取环境变量，其次读 backend/.env 的 DEPLOY_HOST。
if [ -z "$DEPLOY_HOST" ] && [ -f "$ENV_FILE" ]; then
    DEPLOY_HOST=$(grep -E '^DEPLOY_HOST=' "$ENV_FILE" | head -1 | cut -d= -f2-)
fi
: "${DEPLOY_HOST:?未设置 DEPLOY_HOST。在 backend/.env 里加一行 DEPLOY_HOST=user@host，或导出同名环境变量}"
SERVER="$DEPLOY_HOST"

# 只认 LISTEN 状态：残留的 CLOSED 客户端 socket 也会被 lsof -i 匹配到，
# 曾导致隧道已死却误报「已在运行」（见 docs/pitfalls/db_tunnel误判隧道存活.md）
if lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "隧道已在运行（本地端口 $LOCAL_PORT）"
    exit 0
fi

# 如果设置了 SSH_PASSWORD 环境变量，使用密码认证
if [ -n "$SSH_PASSWORD" ]; then
    sshpass -p "$SSH_PASSWORD" ssh -f -N \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -o StrictHostKeyChecking=no \
        -L "$LOCAL_PORT:localhost:5432" \
        "$SERVER"
else
    # 否则使用 SSH 密钥认证
    ssh -f -N \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        -L "$LOCAL_PORT:localhost:5432" \
        "$SERVER"
fi

echo "数据库隧道已建立: localhost:$LOCAL_PORT → $SERVER:5432"
