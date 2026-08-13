#!/bin/bash
# 启动带调试端口的独立 profile Chrome（评审 🔴2）
# 独立 profile 只登录旅行平台，不暴露个人主 profile 的登录态
set -e

# 端口用 9223：9222 常被主 Chrome 占用，且新版 Chrome 在默认 profile 下
# 会禁用远程调试端点（/json/version 404），必须独立 user-data-dir
PROFILE_DIR="$HOME/chrome-agent-profile"
PORT=9223

if lsof -i ":$PORT" >/dev/null 2>&1; then
    echo "端口 $PORT 已被占用，调试 Chrome 可能已在运行"
    exit 0
fi

mkdir -p "$PROFILE_DIR"

"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=$PORT \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    >/dev/null 2>&1 &

echo "调试 Chrome 已启动: http://127.0.0.1:$PORT"
echo "profile: $PROFILE_DIR"
echo "提示：在这个 Chrome 里登录携程/小红书等平台后，Agent 即可共享登录态"
