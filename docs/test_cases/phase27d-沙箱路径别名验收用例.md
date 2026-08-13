# Phase 27d 验收用例 — 沙箱 /workspace 路径别名 + /user/ 技能源条件挂载

对应自动化测试：`backend/tests/test_docker_sandbox.py`（/workspace 别名分组）、
`backend/tests/test_deep_research_skills.py`（`_build_agent` 条件装配分组）。

## A. /workspace 别名（test_docker_sandbox.py）

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A1 | 写 /workspace 前缀路径落到根 | `write("/workspace/slides/gen.py")` | host 落在 `root/slides/gen.py`，**不产生** `root/workspace/` 一层；`read("/workspace/slides/gen.py")` 与 `read("/slides/gen.py")` 内容一致 |
| A2 | 裸 /workspace 即根目录 | 根下有文件后 `ls("/workspace")` | 无 error，能列出根下文件 |
| A3 | 只剥一层前缀 | `write("/workspace/workspace/a.txt")` | host 落在 `root/workspace/a.txt`（与容器视角一致），不是 `root/a.txt` |
| A4 | 相似名不误伤 | `write("/workspace2/b.txt")` | host 落在 `root/workspace2/b.txt` |
| A5 | 别名不放开路径穿越 | `ls("/workspace/../../etc")` | 抛 `ValueError`（traversal） |

## B. agent 装配（test_deep_research_skills.py）

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| B1 | 有用户技能 | `_build_agent(..., user_skills=True)` | 主 agent 与 general-purpose 的 skills 均为 `["/main/", "/user/"]` |
| B2 | 无用户技能 | `_build_agent(..., user_skills=False)` | skills 均为 `["/main/"]`（不再触发 deepagents 的 `/user/` path_not_found 告警）；api-researcher 仍为 `["/researcher/"]` |
| B3 | 沙箱开启才注入路径说明 | `backend=None` / `backend=object()` 各建一次 | 前者 prompt 不含 `/workspace`；后者主 agent 与 general-purpose 的 prompt 含 `/workspace` 映射说明，api-researcher 不含 |

## C. 线上手工回归（部署后）

1. 绑定 pptx-generator 技能 + 打开沙箱执行，发送「商丘有什么好玩的地方，生成一个ppt文件给我」。
2. 预期：不再出现「write_file 成功但 execute 找不到文件」的循环；要么正常产出
   `meta.artifacts` 下载卡片，要么因镜像缺依赖（容器无网络装不了 python-pptx/pptxgenjs）
   给出明确失败说明，但**不应**撞 recursion limit。
3. 用户无上传技能的账号跑一轮深度研究，`journalctl` 中不再出现
   `Cannot load skills from '/user/'` 告警。

## 运行

```bash
cd backend && .venv/bin/python -m pytest tests/test_docker_sandbox.py tests/test_deep_research_skills.py -q
```
