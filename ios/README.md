# 17同游 iOS（原生 SwiftUI）

当前版本：1.0.7 (8)。首页与聊天默认联网开启、深度推理关闭；保留用户明确关闭联网的偏好。

原生 iOS 26 App，直接调用线上接口 `https://17tongyou.com/travel/api`，界面全部用 SwiftUI + Liquid Glass（`glassEffect`、`.glass` 按钮、系统 TabView 玻璃底栏）。

| 模块 | 文件 | 内容 |
| --- | --- | --- |
| 登录 | Features/LoginView.swift | 登录 / 邀请码注册，token 存 Keychain |
| 首页 | Features/HomeView.swift | 问候、玻璃输入卡、热门城市快捷问、旅行者接力入口、热门目的地封面、通知 |
| 对话 | Features/Chat/* | 800 ms 轮询、思考进度与子任务、候选目的地、登录确认/扫码卡、深度推理提示、Markdown 攻略、参考来源、预算明细、手账海报、转协同行程、图片上传（最多 4 张） |
| 历史 | Features/HistoryView.swift | 搜索、左滑删除 |
| 行程 | Features/Trips/* | 新建、邀请处理、按天切换、Apple 地图标注与路线（GCJ-02 转 WGS-84）、时间线、一键导航；原生编辑：增删改地点、拖动排序、行程设置、成员邀请、让 AI 改行程（采纳/忽略/撤销）、行程群聊、记账 |
| 记账 | Features/LedgerView.swift | 可选关联行程、独立成员邀请与编辑/只读权限、链接分享/粘贴加入、支出增改删、原币分类与逐日汇总、自选汇总币种、在线最新参考汇率与刷新；原币金额保留 |
| 同游圈 | Features/SocialView.swift | 目的地切换、阶段筛选、提问/报现场/分享路线、有用/属实/已失效 |
| 我的 | Features/Me/* | 记忆、技能、连接（扫码）、公告、联系客服；管理员：用户管理（角色调整）、邀请码、发布/撤回公告、客服收件箱 |
| 网页兜底 | Web/* | 尚未原生的少数功能可用网页打开，自动带上原生登录状态；下载与 PDF 走系统分享 |

## 构建

```bash
python3 scripts/generate-project.py      # 新增 Swift 文件后重跑
xcodebuild -project Tongyou.xcodeproj -scheme Tongyou -destination 'id=<设备ID>' -allowProvisioningUpdates build
```

最低系统 iOS 26。签名使用个人免费开发者团队，7 天后需要重新安装。图标由 `scripts/render-icon.swift` 按 `frontend/public/favicon.svg` 绘制。

当前 1.0.6（7）：账本网页邀请支持点击“在 App 中打开”，协议为
`tongyou://ledger/join?token=…`。接收后先登录、预览，再由用户确认加入；分享出去仍为
`https://17tongyou.com/travel/?ledger_join=…`，与 Android/Web 互通。
免费个人团队未启用 Associated Domains，因此这里不是 HTTPS 自动 Universal Links。
测试：`xcrun swiftc Tongyou/Core/LedgerDeepLink.swift tests/LedgerDeepLinkTests.swift -o /tmp/tongyou-ios-link-tests && /tmp/tongyou-ios-link-tests`。
冷/热启动及系统确认 UI 测试：`python3 scripts/test-links-ui.py --device <专用模拟器 UDID>`。
