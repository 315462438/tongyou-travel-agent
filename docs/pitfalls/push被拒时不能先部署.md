# push 被拒时不能先部署

2026-08-18

## 现象

本地提交完，`git push` 被拒：

```
hint: Updates were rejected because the remote contains work that you do not have locally.
```

此时**部署脚本仍然能跑通、健康检查仍然会绿**——因为 `backend/deploy/deploy.sh` 是
`rsync` 本地文件到服务器，根本不经过 GitHub。于是很容易顺手先部署、回头再解决 push。

**这一步会静默回滚线上代码。**

## 原因

`deploy.sh` 同步 backend 时带 `--delete`：

```bash
rsync -az --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude 'static' \
    backend "$SERVER:$REMOTE_DIR/"
```

「远端有我没有的提交」意味着别的机器/会话改过代码。如果那些改动里有后端文件
（这次是 `trip_api.py` / `migrate.py` / `geocode.py` / `models.py` / `config.py`），
用未 rebase 的本地树部署，就是拿旧版覆盖它们。服务重启正常、健康检查 200、
日志没有一行 error——**线上功能悄悄退回几天前**。

## 做法

push 被拒 → 先 `git fetch` 看清分歧 → rebase → 跑测试 → 再部署。顺序不能换。

真要在 push 不通（比如网络连不上 GitHub）时先部署，**必须先用 dry-run 看会动什么**：

```bash
rsync -azn --delete --itemize-changes \
  --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude 'static' \
  backend $DEPLOY_HOST:/home/ubuntu/travel-agent/
```

`*deleting` 和对源码文件的 `<f` 变更就是将要覆盖的内容。这次正是靠它发现了问题。

## 附带一条：rebase 后前端必须重建

`backend/static/` 在 `.gitignore` 里（`.gitignore:33`）。rebase 拉下来的是前端**源码**，
本地 `backend/static/` 里还是旧的构建产物。这次远端两笔提交改了
`Trips.tsx`(+1719) / `index.css`(+753)，不重建就等于只部署了后端：

```bash
cd frontend && npm run build && cp -r dist/. ../backend/static/
```

末尾 `/.` 不能省，原因见 `前端构建产物拷成了嵌套目录.md`。

## 一般化

> **「部署成功」只证明服务起来了，不证明部署的是对的东西。**

凡是 `rsync --delete` / 镜像式发布，源端的完整性都必须在发布**之前**独立确认——
发布流程本身永远不会告诉你「你少带了别人的改动」。
