# Phase 61 — 协同行程群聊验收用例

## 自动化用例

运行：

```bash
cd backend
.venv/bin/python -m pytest tests/test_trip_collab.py -q

cd ../frontend
npm test
npm run lint
./node_modules/.bin/tsc --noEmit -p tsconfig.app.json
npm run build
```

### TC-61-01 群聊成员权限

- 行程成员可以读取和发送消息；
- 待接受邀请和非成员读取、发送均返回 404；
- 消息发送者可以删除自己的消息；
- 其他成员删除消息返回 403。

对应自动化：`backend/tests/test_trip_collab.py::test_trip_chat_flow_incremental_and_permissions`。

### TC-61-02 消息输入边界

- 纯空白消息返回 400；
- 正文保存前去除首尾空白；
- 超过 1000 字时只保存前 1000 字；
- `after=<message_id>` 只返回游标之后的新消息。

对应自动化：`backend/tests/test_trip_collab.py::test_trip_chat_flow_incremental_and_permissions`。

### TC-61-03 前端群聊契约

- 行程板存在群聊入口和抽屉；
- 打开时 2.5 秒刷新，关闭时 8 秒检查未读；
- Enter 发送，Shift+Enter 和输入法组合输入不误发；
- 桌面抽屉与手机全屏样式同时存在。

对应自动化：`frontend/tests/visual-regressions.test.mjs`。

## 手工交互用例

### TC-61-04 多人即时沟通

1. Alice 和 Bob 同时打开同一行程；
2. Alice 打开群聊发送「明早八点酒店集合」；
3. Bob 在不刷新页面的情况下看到未读徽标；
4. Bob 打开群聊看到消息，回复后 Alice 在 2.5 秒内看到；
5. 自己的消息靠右、他人消息靠左，用户名和时间正确。

### TC-61-05 抽屉与滚动

- 打开抽屉后定位到最新消息；
- 接近底部时新消息自动跟随；
- 用户向上阅读历史时不被新消息强制拉回底部；
- 按 Escape、点击遮罩或关闭按钮可关闭，且不会连带关闭整个协同行程界面；
- 关闭后新消息累计未读徽标，重新打开后清零。

### TC-61-06 输入与异常

- Enter 发送、Shift+Enter 换行、中文输入法 Enter 不误发；
- 发送期间不能重复提交；
- 网络失败时保留输入内容并显示错误；
- 空状态说明整体讨论与地点留言的用途区别。

### TC-61-07 移动端

1. 390×844 视口打开群聊；
2. 面板占满屏幕，无横向滚动；
3. 顶部关闭按钮和底部发送按钮均可触达；
4. 输入区避让底部安全区和软键盘。
