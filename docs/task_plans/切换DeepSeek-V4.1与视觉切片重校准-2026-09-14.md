# 切换 DeepSeek V4.1 + 视觉切片重校准（2026-09-14）

## 背景

- 2026-09-10 DeepSeek 发布 **V4.1 Flash**（原生多模态），正式模型名 `deepseek-flash`。
  `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` 已下线，**临时转发**到 V4.1 Flash。
  `deepseek-v4-pro` 继续服务、计费不变；**尚无 V4.1 Pro**（`/models` 只列 `deepseek-flash`、`deepseek-v4-pro`，
  传 `deepseek-v4.1-flash` 直接 400）。
- 读 `deepseek-harness` 上游 09-09~09-10：默认模型切到 `deepseek-flash`（bc5fd3b8dc）、
  图片 token 计算器改 v41 配置（a64dc3a690：544×544 放大下限、约 1300×1300 缩小目标、**单图 1024 token 上限**）。

## 目标

1. 分类 / 视觉模型改用正式名 `deepseek-flash`，避免转发停掉后 400。
2. 规划 / 抽取是否从 `deepseek-v4-pro` 换成 `deepseek-flash`：**用 `extract_eval` 数据决定**，不拍脑袋。
3. 视觉切片重校准（本次最重要的发现，见下）。

## 发现：线上长截图读图已静默退化

转发生效后，Phase 111 的切片（单片高 ≤8000、最多 4 片）在 V4.1 上：
1800×25242 长图（525 行随机数字）**按行对齐 0%、集合命中 38%**，行数却全对——不报错、看不出来。
原因：8192 只是尺寸闸门，V4.1 每张图压到 ≈1024 token，8000 高的一片字被缩糊。

实测（20px 中文随机数字，单片）：1800×2000 100% / ×3000 99% / ×4096 79% / ×5500 0%。
长图按 3000 高切 9 片、2000 高切 14 片均 100%，单次调用 ~11s、prompt 9–13k token。单次 50 张图照收。

## 方案

- `image_prep.tile_side(width, max_side) = min(max_side, vision_max_tile_pixels // width)`；
  规格内判定、切片高度、先缩后切的预算都改用它。
- `vision_max_tile_pixels = 4_000_000`，`vision_max_tiles` 4 → 16。
- 不变式照旧：规格内原样返回无 notice、切片覆盖整页、不够切先缩不丢尾部、降级带说明。

## 涉及模块

`app/config.py`、`app/agent/image_prep.py`、`app/agent/vision.py`（docstring）、`app/llm/client.py`（docstring）、
`.env.example`、服务器 `.env`（`MODEL_CLASSIFIER`）、`tests/test_image_prep.py`。

## 验收

- `tests/test_image_prep.py` 全绿（新增 3 条），全量后端单测不回退。
- 服务器上用真实代码路径复验 1800×25242 长图读数准确率。
- `extract_eval` pro vs flash 对照结果记录在本文。

## 结果

- 单测：`test_image_prep.py` + `test_vision.py` + `test_image_failure_visible.py` 55 passed；全量后端
  1457 passed / 6 failed，6 条均为 `fetch_url`/`read_source` 在本机被 `url_guard` 判 example.com
  解析到保留地址（`docs/pitfalls/测试依赖真实DNS会被VPN变红.md`），与本改动无关。
- 线上复验（服务器、新 `image_prep.py` 真实代码路径 → `deepseek-flash`）：1800×25242、525 行随机数字，
  **切 12 片、按行对齐 100%、集合命中 100%**、prompt 11945 token、10.0s（改造前同图 0% / 38%）。

### extract_eval：抽取模型 pro vs flash（服务器，5 篇固定攻略）

| 样本 | pro 耗时 / 点 / 开销 / 人数 | flash 耗时 / 点 / 开销 / 人数 | 基线(08-24) 人数 |
| --- | --- | --- | --- |
| tiantangzhai_3d_short | 221.6s / 14 / 11 / 1 | 9.9s / 15 / 13 / 1 | 2 |
| wuhan_3d | 66.1s / 14 / 14 / 2 | 7.8s / 14 / **5** / 2 | 2 |
| chongqing_5d_drive | 216.3s / 23 / 13 / 3 | 11.4s / 22 / **5** / 3 | 3 |
| malaysia_7d_overseas | 105.8s / 44 / 30 / 2 | 14.7s / 45 / 31 / 2 | 2 |
| yushu_10d_long | 113.0s / 57 / 32 / 2 | 7.6s / 55 / **13** / 2 | 2 |

两边都 5/5 通过、flash 快 10–20 倍，天数和停留点基本持平；但 **flash 的开销条目在 3 篇里只剩 1/3–1/2**
（14→5、13→5、32→13）。检查项只防「合计行进逐项」「人数错」这类硬错，不数开销召回，所以没亮红——
而开销条目少了会让预算面板直接漏项、总额偏低且不报错（Phase 67 服务端按逐项求和）。
**决定（2026-09-14，用户拍板）：全部换 `deepseek-flash`**。依据是 DeepSeek 开放平台公告：V4.1 Flash
在性能、费用、速度、总用时上全面超过 V4 Pro，且 **V4.1 Pro 上线前对 V4 Pro 的请求会全部路由到 V4.1 Flash**
并按 Flash 计价——留在 v4-pro 名下也躲不开 flash，只是多一层转发。
规划模型未做端到端对照（runner 一轮 ~1 小时），上线后观察。

### ⚠️ 订正：「开销条目变少」不是漏抽，flash 的预算总额反而更准

上面按条目数得出的「flash 漏开销」是**数错了筐**。逐项打出来对照正文自报合计（团组 ÷ 人数 = 人均）：

| 样本 | 正文人均 | flash 逐项合计 | v4-pro 逐项合计 |
| --- | --- | --- | --- |
| wuhan_3d | 1050 | 894（14 项，含住宿、交通） | 401（12 项，只有餐饮门票） |
| chongqing_5d_drive | 1500 | 1592（5 项：住宿/餐饮/油费/门票/其他） | 650（13 项，全是每顿饭） |
| yushu_10d_long | 4800 | 4907（13 项，含 9 晚住宿） | 3146（33 项，漏了 9 晚住宿） |

flash 抽的是正文的**分类预算表**，v4-pro 抽的是散在逐日表里的**单顿价格**——条目多、总额却差一截。
预算面板要的是总额对得上，所以 **flash 更好，cost 路 prompt 不改**。代价是 flash 的条目常常
`day=0`（整趟通用），逐日分布那栏会变空——这是粒度取舍，不是错误。

修的是**评估本身**：
- `evals/extract_checks.py` 新增 `cost_coverage` / `check_cost_coverage`：逐项人均合计 ÷ 正文人均合计，
  低于 0.6 报 warn（分母也是模型抄的，不做硬闸门）；报表加「覆盖」列。
- 顺带修 `extract.py` 假告警：只跑 cost 路（预算面板）时也会打「itinerary lane returned empty」，
  判空条件漏了 `LANE_ITINERARY in want`。

### 覆盖率检查当场抓到的真缺陷：团组金额当人均（预算面板 3 倍）

加了覆盖率后重跑，重庆样本覆盖 **318%**。连跑 4 次：**3 次**把「预算估算表（两大一小）」的全家金额
（住宿 1800、餐饮 1100、油费 700…）原样填进「按一个人算」的 `amount`，只有 1 次除了 3。
v4-pro 没犯这个错，是因为它根本没抽那张表（漏住宿油费，偏低）——两个模型错在相反方向。

修法沿用 Phase 67「不让模型算数」：
- `ExpenseExtraction.amount` 改为**照抄正文**，新增 `scope`（`per_person`/`group`，只标口径）；
  `extract._per_person` 在服务端用**并入人数兜底路之后的最终人数**均摊 group，备注留痕「全体1800元÷3人」。
  人数合并挪到建开销之前（顺序反了会按没修正的人数除）。
- `scope` 用 `str` 不用 `Literal`：枚举外的值会让整条 cost 路校验失败；只认 `group`，其余按人均。
- `SCHEMA_VERSION` 1→2：v1 缓存里可能存着 3 倍错账，必须重抽。
- 评估覆盖率区间补上限：>1.5 报 `ext_cost_coverage_high`（warn）。

复验（服务器隔离副本，真实 V4.1 Flash）：重庆连跑 4 次覆盖 103%/103%/106%/106%（改前 318%×3）；
`extract_eval --tag ds41-flash-scope` 5/5 通过，覆盖 88%/78%/103%/100%/101%。
另注：天堂寨人数两个模型都认成 1，而 08-24 基线是 2——与本次换模型无关，单独跟进。

## 未搬的上游特性（记录判断）

- **in-history 系统提示替换**（V4.1 Flash 能力：对话中途的 system 消息替换首条，保前缀缓存）：
  我们是投影架构、每次调用重建 prompt，易变项已末置到 user（Phase 58），收益小，不做。
- **模型切换通知**（48cc1cf1d6）：我们没有会话内换模型，不适用。
