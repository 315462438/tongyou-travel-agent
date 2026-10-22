# 17同游 iOS（原生 SwiftUI）

当前版本：1.0.12 (13)。攻略分享改为简版逐日计划单，可预览、保存相册和系统分享；长行程分多张，完整攻略可导出分页文字 PDF。同行邀请新增可轻拖回弹的行程卡、链接复制/系统分享/关闭、用户名邀请反馈，并适配深浅色与减少动态。行程大地图 + 可拖动底部面板、景点详情、紧凑时间摘要继续保留。主导航为旅行 / 记账 / 我的，右下角独立问 AI；支持草稿与会话收起恢复。默认联网开启、深度推理关闭，保留用户明确关闭联网的偏好。

原生 iOS 26 App，直接调用线上接口 `https://17tongyou.com/travel/api`，界面全部用 SwiftUI + Liquid Glass（`glassEffect`、`.glass` 按钮、自定义三项玻璃底栏）。

| 模块 | 文件 | 内容 |
| --- | --- | --- |
| 登录 | Features/LoginView.swift | 登录 / 邀请码注册，token 存 Keychain |
| 旅行首页 / AI | Features/TravelHomeView.swift、Features/HomeView.swift | 旅行册横滑、新建/导入、目的地灵感、通知；独立 AI 面板、任务回填与历史 |
| 对话 | Features/Chat/* | 800 ms 轮询、思考进度与子任务、候选目的地、登录确认/扫码卡、深度推理提示、Markdown 攻略、参考来源、预算明细、手账海报、转协同行程、图片上传（最多 4 张） |
| 历史 | Features/HistoryView.swift | 搜索、左滑删除 |
| 行程 | Features/Trips/* | 新建、邀请处理、按天切换、地图与当天时间线同屏、地点联动定位、详情隐藏底部主导航、Apple 地图标注与路线（GCJ-02 转 WGS-84）、时间线、一键导航；原生编辑：增删改地点、拖动排序、行程设置、成员邀请、让 AI 改行程（采纳/忽略/撤销）、行程群聊、记账 |
| 记账 | Features/LedgerView.swift | 可选关联行程、独立成员邀请与编辑/只读权限、链接分享/粘贴加入、支出增改删、原币分类与逐日汇总、自选汇总币种、在线最新参考汇率与刷新；原币金额保留 |
| 旧社交代码 | Features/SocialView.swift | 主入口已移除，保留原数据和代码；该文件同时提供通知中心 |
| 我的 | Features/Me/* | 记忆、技能、连接（扫码）、公告、联系客服；管理员：用户管理（角色调整）、邀请码、发布/撤回公告、客服收件箱 |
| 网页兜底 | Web/* | 尚未原生的少数功能可用网页打开，自动带上原生登录状态；下载与 PDF 走系统分享 |

## 构建

```bash
python3 scripts/generate-project.py      # 新增 Swift 文件后重跑
xcodebuild -project Tongyou.xcodeproj -scheme Tongyou -destination 'id=<设备ID>' -allowProvisioningUpdates build
```

最低系统 iOS 26。签名使用个人免费开发者团队，7 天后需要重新安装。图标由 `scripts/render-icon.swift` 按 `frontend/public/favicon.svg` 绘制。

自 1.0.6（7）起：账本网页邀请支持点击“在 App 中打开”，协议为
`tongyou://ledger/join?token=…`。接收后先登录、预览，再由用户确认加入；分享出去仍为
`https://17tongyou.com/travel/?ledger_join=…`，与 Android/Web 互通。
免费个人团队未启用 Associated Domains，因此这里不是 HTTPS 自动 Universal Links。
测试：`xcrun swiftc Tongyou/Core/LedgerDeepLink.swift tests/LedgerDeepLinkTests.swift -o /tmp/tongyou-ios-link-tests && /tmp/tongyou-ios-link-tests`。
冷/热启动及系统确认 UI 测试：`python3 scripts/test-links-ui.py --device <专用模拟器 UDID>`。

## 验证与发布状态

当前发布仍为个人签名安装，未上架 App Store / TestFlight。Android 的 APK 更新清单不用于 iOS。三端分别管理，详见[发布记录](../docs/dev_docs/mobile-release-management.txt)。

```bash
# 在 ios/ 下；选择本机可用的专用模拟器
xcodebuild -project Tongyou.xcodeproj -scheme Tongyou -configuration Debug -destination 'platform=iOS Simulator,id=<模拟器ID>' -only-testing:TongyouUITests/JourneyUITests CODE_SIGNING_ALLOWED=NO test
swiftc Tongyou/Features/Trips/TripModels.swift tests/TripSummaryTests.swift -o /tmp/tongyou-trip-summary-tests
/tmp/tongyou-trip-summary-tests
```

2026-10-22：分享/邀请三项与 JourneyUITests 两项通过；最后的深色小字对比度修正后复跑分享三项通过。摘要解析 14 项、6 张实际 PNG 像素、完整 PDF 多页及末尾内容检查通过；1.0.12 (13) 实机 Release 编译、签名、覆盖安装与启动成功。UI fixture 仅在 DEBUG 且显式测试参数下启用，不连接真实账号。景点图片与事实来自后端已鉴权详情接口；无图保留中性占位。

分享专项：`-only-testing:TongyouUITests/ShareUITests`；测试 App 的 Documents/share-qa 产物可用 `python3 scripts/verify-share-export.py <目录>` 检查。测试与发布详情见 `../docs/test_cases/双端简版分享与邀请动效-2026-10-22.md`。
