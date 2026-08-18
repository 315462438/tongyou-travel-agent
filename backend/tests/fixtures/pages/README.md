# reducer 测试用的真实页面与快照（Phase 96）

`app/agent/reducers.py` 的验收样本。全部 gzip 存放（共 ~220KB），测试用
`gzip.open` 直接读，无需解压。

| 文件 | 来源 | 用途 |
| --- | --- | --- |
| `wikipedia_xihu.html.gz` | zh.wikipedia.org/wiki/西湖 | 主菜单 + 目录占满窗口的典型页；改造前 4000 字窗口里 3566 字是 chrome |
| `ctrip_travels.html.gz` | you.ctrip.com/travels/hangzhou14/ | 顶部导航 + 筛选器；chrome 词 6 → 0 |
| `qunar_hangzhou.html.gz` | travel.qunar.com/p-cs299914-hangzhou | 第二个 HTML 样本，验证不是对维基过拟合 |
| `snapshot_qunar.txt.gz` | 同上页面的 a11y 快照 | 31144 → 4324（-86%） |
| `snapshot_bing.txt.gz` | 必应搜索结果页快照 | 8896 → 3130（-65%） |
| `snapshot_baike.txt.gz` | 百度百科·西湖快照 | 995 → 203（-80%） |

## 为什么入库而不是按需拉取

Phase 93 的 evals 样本是「不进 git + 脚本按 id 拉 + 校验 sha256」，因为那些样本可以
用一条 API 精确复现。**这里不行**：

- **a11y 快照复现不了**——必须起一个真实 Chrome、导航、`take_snapshot`，而页面内容
  每天都在变，拉到的不会是同一份；
- **HTML 页面也拉不稳**——马蜂窝、知乎、杭州政府网在服务器侧 curl 全部被反爬挡回
  （只回几百字节）。这也正是生产环境要走浏览器的原因。

所以这里选择**冻结样本入库**。代价是它们会逐渐偏离线上真实形态，收益是测试可复现、
不依赖网络、不依赖反爬策略。**若 reducer 规则有较大改动，应重新抓一批样本**，
抓取脚本见 git 历史里的 `capture_snapshots.py`（用项目自己的 `ChromeMCP`，只导航 + 快照）。

## 采集日期

2026-08-18。快照格式对应 chrome-devtools-mcp（`uid=` + role + 引号 label + `key="v"` 属性）。
