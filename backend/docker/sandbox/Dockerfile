# 深度研究 agent 的 Docker 沙箱镜像（Phase 27c）。
#
# 容器运行时 --network=none（安全考量，见 docs/pitfalls/Docker沙箱共享内核隔离与非root挂载权限.md），
# 所以任何依赖都必须在构建期装好，不能指望运行时 pip install。这里预装办公文档/数据/绘图相关的
# 常用库，让 agent 能真正产出 PPT/Word/Excel/PDF/图表这类"产物"，而不只是能跑纯文本脚本。
#
# 构建（在服务器上手动执行，不接入 deploy.sh 自动构建——镜像构建耗时且不需要每次部署都重来）：
#   docker build -t travel-sandbox:latest backend/docker/sandbox/
FROM python:3.12-slim

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
