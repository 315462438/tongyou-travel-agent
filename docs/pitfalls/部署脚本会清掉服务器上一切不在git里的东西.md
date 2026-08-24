# 部署脚本会清掉服务器上一切不在 git 里的东西

## 现象

部署之后跑抽取评估，5 条样本全部报：

```
❌ run_error  .../evals/samples/tiantangzhai_3d_short.md 不存在——先跑 `python -m evals.fetch_samples`
```

同时之前几轮的评估快照（`evals/runs/*.json`）也少了大半，before/after 无从比起。

## 原因

`backend/deploy/deploy.sh` 的第一步是：

```bash
rsync -az --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude 'static' \
    backend "$SERVER:$REMOTE_DIR/"
```

`--delete` 的语义是「让目标端与源端一致」——**源端没有的，目标端一律删掉**。
而评估的两个目录恰好都是「本地没有 / 服务器独有」：

- `evals/samples/`：按设计**不进 git**（真实用户会话的产物，后续可能开源），
  服务器上用 `fetch_samples` 拉；
- `evals/runs/`：历次评估的快照，产生在哪台机器就留在哪台机器。

所以每次部署都在清空评估的**输入和历史**。它一直是这样，只是以前没人在部署后紧接着跑评估。

## 为什么危险不止于「要重新拉一次」

`run_error 样本不存在` 在报表里**跟「模型抽取失败」长得一模一样**——都是一行 ❌。
当天我差点把它读成「新配置导致抽取失败」，而它其实是文件没了。

`evals/verify` 那套设计里专门有一条「凡生产有失败静默降级的地方，评估都不能复用那条路径」，
这里是同一个道理的另一面：**评估自身的基础设施故障，必须与被测对象的失败长得不一样。**
（`extract_eval` 用 `run_error` 单独标记、退出码 2≠1，正是为此——但只有真去看退出码才分得出。）

## 解决办法

把这两个目录从 `--delete` 的管辖范围里摘出去：

```bash
rsync -az --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.env' --exclude 'static' \
    --exclude 'evals/samples' --exclude 'evals/runs' \
    backend "$SERVER:$REMOTE_DIR/"
```

排除之后这两个目录由服务器自己管：样本用 `python -m evals.fetch_samples` 拉，
快照原地累积。

**刻意不做**：不把样本提交进 git。仓库目前私有，但后续可能开源，
而样本是真实用户会话的产物——「现在放进去，将来开源时再摘出来」在 git 历史里做不到。

## 后续约束

> **凡是 `rsync --delete` 的目标目录，都要先问一句：目标端有没有源端不该管的状态？**

服务器上的「非 git 状态」不止评估数据，还有 `.env`、`static`（已排除）、
`chrome-agent-profiles/`（在 `$REMOTE_DIR` 之外，安全）。新增任何一类服务器侧独有的数据时，
要同步确认它在不在部署脚本的射程内——**这类丢失不报错、不回滚，只在下次用到时才发现。**
