# Phase 28 验收用例 — 深度研究工具硬配额 + 产出纪律

对应自动化测试：`backend/tests/test_research_quota.py`。

## A. 工具硬配额（自动化）

| # | 用例 | 步骤 | 预期 |
| --- | --- | --- | --- |
| A1 | 搜索配额 | 上限 3，连调 4 次 web_search | 前 3 次真实执行；第 4 次返回「配额已用完」引导文案，不触发浏览器 |
| A2 | 读页配额 | 上限 2，连调 3 次 open_page | 第 3 次被拒，session 只被调 2 次 |
| A3 | fetch 配额 | 上限 0，调 fetch_url | 直接返回配额文案，不发起任何 HTTP 请求 |
| A4 | 全轮共享 | 同一 build_tools 产物多次调用 | 主/子 agent 共用一份计数（闭包共享） |
| A5 | 按轮重置 | 两次 build_tools 各调一次 | 第二轮不受第一轮计数影响 |
| A6 | prompt 纪律 | 检查常量 | RESEARCH_SYSTEM 含「时间纪律/硬配额」，SANDBOX_NOTE 含「一次成稿/禁止」按页派子任务 |
| A7 | 心跳进度 | HEARTBEAT_EVERY_S 缩到 2s，agent 假装跑 3s | 至少写一条「研究进行中」progress（长推理阶段前端不再像卡死） |
| A8 | 搜索对应性校验 | `_query_matches` 各分支（28.1） | 框值空/无关 → 拒绝；词元有包含关系 → 接受；查询过短 → 放行 |
| A9 | open_page 计入来源 | 读一个 ≥120 字符正文的页面 | `sources` 里出现该 hostname 条目 |
| A10 | trace 小分页 | 假 client 两页/超长 50 页 | 25/页、末页不满即停；超长在 8 页处截断（不再打挂 langfuse-web） |

## B. 线上手工回归（部署后）

1. 沙箱 + pptx 技能重发「商丘有什么好玩的地方，生成一个ppt文件给我」：
   - 进度气泡里「🔎 搜索」不超过 3 条、「📄 读取」不超过 10 条、「🌐 浏览器读取」不超过 3 条；
   - 不再出现按页拆分的子任务（「创建Slide-0X…」）；
   - **整轮在 600s 内完成**并产出 artifacts 下载卡片（收集阶段应明显缩短到 ~2-3min 内）。
2. 普通深度研究问题（如「对比厦门和青岛哪个适合亲子」）仍能正常出报告，来源数 ≤10。

## 运行

```bash
cd backend && .venv/bin/python -m pytest tests/test_research_quota.py -q
```
