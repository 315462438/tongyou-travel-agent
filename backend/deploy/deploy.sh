#!/bin/bash
# 部署到服务器（本地执行）：rsync 代码 → 服务器侧装依赖 → 重启服务
set -e
REMOTE_DIR=/home/ubuntu/travel-agent

cd "$(dirname "$0")/../.."   # 项目根目录
ENV_FILE="backend/.env"
# 服务器地址不写进仓库（本仓库公开）。优先取环境变量，其次读 backend/.env 的 DEPLOY_HOST。
if [ -z "$DEPLOY_HOST" ] && [ -f "$ENV_FILE" ]; then
    DEPLOY_HOST=$(grep -E '^DEPLOY_HOST=' "$ENV_FILE" | head -1 | cut -d= -f2-)
fi
: "${DEPLOY_HOST:?未设置 DEPLOY_HOST。在 backend/.env 里加一行 DEPLOY_HOST=user@host，或导出同名环境变量}"
SERVER="$DEPLOY_HOST"

echo "== 1. 同步代码 =="
# 代码用 --delete（清理旧文件），但排除 static——前端哈希 chunk 单独同步且【不删旧版】，
# 保证已打开的旧页面点 lazy chunk 不会 404 白屏（P0，见 task_plan-phase50）
#
# ⚠️ evals/samples 与 evals/runs 也必须排除（2026-08-24 加）。它们是**服务器侧独有的状态**：
# 样本按设计不进 git（真实用户会话产物，后续可能开源），产出是历次评估快照——
# 而 --delete 会把「本地没有的」一律删掉，等于每次部署清空评估的输入和历史。
# 当天真撞上了：部署后跑评估报 `run_error 样本不存在`，而那看起来跟「模型抽失败」
# 长得一模一样；同时之前几轮的对照快照也被抹了，before/after 无从比起。
# 排除之后这两个目录由服务器自己管：样本用 `python -m evals.fetch_samples` 拉。
rsync -az --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude 'static' \
    --exclude 'evals/samples' --exclude 'evals/runs' \
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
echo "== 部署完成: https://17tongyou.com/travel/ =="
