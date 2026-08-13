# Task Plan — Phase 32：调用链面板重设计（Langfuse 式左树右详情）

## 背景

Phase 25 的调用链抽屉是「扁平列表 + margin 缩进 + 点击行内展开原始 JSON」，
节点多（深度研究一轮 40+ 条）时层级看不出来、payload 撑开列表，人不可读。
用户提供 Langfuse 官方 UI 截图为目标形态。

## 方案（纯前端，后端 /trace 数据已含 parentId/type/durMs/input/output，够用）

1. **左树右详情双栏**：抽屉加宽（min(920px, 94vw)）。左栏观测树，右栏选中节点详情，
   点击树节点切换详情（不再行内展开）。
2. **真树**：按 parentId 建树、子节点按 startTime 排序、可折叠（▸/▾）；顶部合成
   TRACE 根节点（trace 名 + 总耗时）。孤儿节点（父不在集合内）挂根下。
3. **类型徽章配色**（对齐 Langfuse）：TRACE 紫 / CHAIN 蓝 / AGENT 靛 / GEN 绿 /
   TOOL 红 / SPAN·EVENT 灰。
4. **迷你时间条**：每行名字下一条相对时间条——左偏移 =(start−t0)/总时长，
   宽度 = dur/总时长（最小 1.5%），一眼看出谁耗时、谁并行。
5. **详情面板**：头部徽章+名称+耗时+模型；分节展示 tokens 用量 / 输入 / 输出，
   JSON 尝试 parse 后 2 空格 pretty-print（解析失败显示原文——截断的 payload 本就
   不是合法 JSON）。

## 涉及模块

- `frontend/src/pages/Home.tsx` —— TraceDrawer 重写
- `frontend/src/index.css` —— 样式

## 验收标准（手工，无前端自动化基建）

- 深度研究轮（40+ 节点）：树层级清晰、可折叠；agent 下嵌套 GEN、tools 下嵌套 TOOL；
- 点击节点右栏显示 pretty JSON 详情，长 payload 在右栏内滚动、不撑坏树；
- 时间条能看出耗时大头（LLM 调用）；guide/direct 轮同样正常；
- 空态/未启用/服务不可用三种提示保留；build 通过、线上可用。
