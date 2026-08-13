#!/bin/bash
# 一键本地启动后端：DB 隧道 + 调试 Chrome + uvicorn（前台，Ctrl-C 退出）。
# 前端另开一个终端：cd frontend && npm run dev  →  http://localhost:5173
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"

bash "$DIR/scripts/db_tunnel.sh"        # 幂等：已建则跳过
bash "$DIR/scripts/start_chrome.sh" || true  # 调试 Chrome（已在跑则跳过；纯直答/研究不依赖）

cd "$DIR"
exec .venv/bin/uvicorn app.main:app --reload --port 8000
