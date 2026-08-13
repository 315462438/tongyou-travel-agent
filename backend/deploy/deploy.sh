#!/bin/bash
# 部署到服务器（本地执行）：rsync 代码 → 服务器侧装依赖 → 重启服务
set -e
SERVER=ubuntu@42.194.202.233
REMOTE_DIR=/home/ubuntu/travel-agent

cd "$(dirname "$0")/../.."   # 项目根目录

echo "== 1. 同步代码 =="
# 代码用 --delete（清理旧文件），但排除 static——前端哈希 chunk 单独同步且【不删旧版】，
# 保证已打开的旧页面点 lazy chunk 不会 404 白屏（P0，见 task_plan-phase50）
rsync -az --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude 'static' \
    backend "$SERVER:$REMOTE_DIR/"
# static：不带 --delete → 新旧哈希 chunk 并存；index.html 会被覆盖到最新
rsync -az backend/static "$SERVER:$REMOTE_DIR/backend/"

echo "== 2. 服务器侧安装依赖 + 重启 =="
ssh "$SERVER" "
set -e
cd $REMOTE_DIR/backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
sudo systemctl restart travel-backend
healthy=0
for _ in {1..15}; do
    if curl -fsS http://localhost:8080/api/health; then
        echo
        healthy=1
        break
    fi
    sleep 2
done
if [ \"\$healthy\" -ne 1 ]; then
    echo '后端在 30 秒内未通过健康检查' >&2
    sudo journalctl -u travel-backend -n 50 --no-pager >&2
    exit 1
fi
"
echo "== 部署完成: http://42.194.202.233/travel/ =="
