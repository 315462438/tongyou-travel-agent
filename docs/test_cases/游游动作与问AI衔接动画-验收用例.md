# 游游动作与「问 AI」衔接动画 — 验收用例

## 自动化

| 用例 | 位置 | 结果 |
| --- | --- | --- |
| 待机动作不连续重复、只在空闲/完成播放、间隔 6–12s | `frontend/tests/travel-pet.test.mjs` | 通过 |
| 飞行关键帧终点精确落在标题栏游游、中途高于直线 | `frontend/tests/travel-pet.test.mjs` | 通过（7/7） |
| 原有宠物浏览器场景（点击/长按/拖动/设置/出发检查） | `frontend/tests/travel-pet-browser.mjs`（web-mobile） | 通过 |
| 常驻呼吸+眨眼生效；14s 内出现待机动作；点问 AI 出现飞行分身、面板 `ai-from-pet`（安卓为 `ai-from-pet-scale`）、目标游游飞行中隐藏，落地后分身移除、目标恢复、面板类移除；减少动态效果下无动画无飞行 | 临时脚本（见下） | 网页 / 安卓 UA / reduced 三项通过 |
| iOS `PetMotion`：排程确定、相邻窗口不重复、窗口外无动作、各状态标记、数值范围 | `ios/tests/TravelPetTests.swift` | 106 项通过 |
| 进度文案清洗（表情/网址/markdown/截断）、只读本轮、停止中不显示步骤、写正文显示「正在写回复…」 | `frontend/tests/travel-pet.test.mjs` | 通过 |
| 气泡优先级、指引按序只说一次、`tipsSeen` 容错读取 | `frontend/tests/travel-pet.test.mjs` | 通过（9/9） |
| 浏览器：空闲 6s 出现指引并记入 `tipsSeen`、✕ 收起；发送后收起 AI，气泡显示「搜索：杭州 周末 美食」并随进度更新为小红书；完成后出现「回复准备好啦」，点击打开 AI | 临时脚本 | 通过 |
| iOS 同一套进度/优先级/指引规则 + 部分键 JSON 解码 | `ios/tests/TravelPetTests.swift` | 122 项通过 |
| iOS 模拟器：空闲后游游上方出现指引气泡，位置不遮挡底栏 | 模拟器截图 | 通过 |
| iOS 编译 | `xcodebuild` Simulator Debug | 通过 |

```bash
cd frontend && node --test tests/travel-pet.test.mjs
xcrun swiftc -module-cache-path /tmp/tongyou-pet-module-cache ios/Tongyou/Core/TravelPet.swift ios/tests/TravelPetTests.swift -o /tmp/pet-tests && /tmp/pet-tests
```

## 手工（真机）

1. 首页游游会呼吸、眨眼、摆尾；静置十几秒能看到张望/挥手/举地图/伸懒腰/蹦跳之一。
2. 发起规划后，AI 标题栏小游游低头看地图；遇到确认卡时歪头冒 `?`；停止后打盹飘 `z`。
3. 点「问 AI」：游游起跳飞进标题栏，面板从游游的位置展开；收起后游游从上方落回角落。
4. 打开「减少动态效果」：以上全部静止，点问 AI 直接打开。
5. 拖动游游时身体朝拖动方向倾斜，松手吸边。
6. 发起规划后点「收起」，游游头顶气泡跟着显示正在做的那一步；完成后提示「回复准备好啦」，点它回到 AI。
7. 新装/新账号首次空闲时出现一句指引，之后每次启动最多一句、三句说完不再出现。

## 追加：对话气泡与直达对话（iOS 1.0.18）

| 用例 | 步骤 | 预期 | 自动化 |
| --- | --- | --- | --- |
| 完成提醒带对话名 | `bubble(task: ready, finished: true, title:)` | 「「标题」写好啦，点我看看」；标题为空/「新对话」退回通用文案；超长截断 | `ios/tests/TravelPetTests.swift` |
| 旧对话不覆盖进行中的轮次 | `accepts(ready, from: B, live: A)` | false；同对话或进行中状态为 true | 同上 |
| 离开对话页仍跟进度 | 发起提问 → 返回 AI 首页并收起 → 等完成 | 气泡进度持续变化，完成后出现完成提醒与触感 | 真机手测 |
| 点气泡直达对话 | 生成中/完成后点气泡 | AI 面板直接显示该对话，不经历史 | 真机手测 |
| 气泡形状 | 左右两侧停靠各看一次 | 尾巴指向游游头顶 | 真机手测 |

## 追加：网页对齐

| 用例 | 预期 | 自动化 |
| --- | --- | --- |
| 占位符在括号里 | 终稿只剩图片，普通括号保留 | `backend/tests/test_images.py::test_placeholder_in_parentheses_leaves_no_orphan_brackets` |
| 老攻略括号兜底 | `prepareMarkdown` 去掉包图括号 | `frontend/tests/interaction-utils.test.mjs` |
| 完成提醒带对话名 | `petDoneText` / `petBubble(..., title)` | `frontend/tests/travel-pet.test.mjs` |
| 切走后继续跟进 + 点气泡回到对话 | 发送 → 新对话 → 关面板：气泡仍显示进度；完成后出带名提醒 + 5 个表情，9 秒后仍在；点气泡打开原对话、无孤立括号、留白 18px | 定向 Playwright 脚本（390×844，已通过） |
