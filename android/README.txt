17同游 Android 好友测试版

当前发布：0.6.0 (9)，启动时检查更新；系统深浅外观覆盖登录页及更新提示。保留0.5.0各模块排版、首页字号与开场动画。
下载：https://17tongyou.com/downloads/android/0.6.0-9/17tongyou-android-0.6.0-9.apk
直接覆盖安装，无需卸载旧版。0.1.0 (1) 历史产物与旧链接保留。

三端边界
- Android：本目录；com.tongyou.travel；独立 versionName/versionCode 与签名。
- iOS：../ios，原生 SwiftUI，独立版本和签名。
- Web：../frontend，经原网页部署流程上线。
- API/账号/协同行程/账本数据共享线上后端。Android 的界面资源随 APK 发布，不追随网页部署。
- Android 构建只输出 app/build/generated/webAssets，不写 frontend/dist、backend/static，不部署服务器。

运行环境：JDK 17+、Node/npm、Python 3、Android SDK 35 / Build Tools 35。
本地 SDK 路径写 local.properties（sdk.dir=...），此文件不提交。

首次准备
  cd ../frontend && npm ci
  cd ../android
  python3 scripts/create-signing.py

构建、测试、发布
  ./gradlew :app:testDebugUnitTest :app:lintRelease :app:assembleRelease
  ./gradlew :app:connectedDebugAndroidTest
  python3 scripts/package-release.py

也可直接运行已启动的专用模拟器（避开 Gradle UTP 首次额外下载）：
  python3 scripts/test-emulator.py --serial emulator-5556
该脚本仅接受模拟器，测试包使用本地假数据，不登录真实账号。

网页专项测试：先在 frontend 启动 npm run dev -- --host 127.0.0.1 --port 4181，
再运行 node tests/android-browser.mjs（需要 playwright；可用 PLAYWRIGHT_MODULE 指定已有安装）。

签名管理
- 私有密钥和配置默认在 ~/.config/17tongyou/android/；也可通过 TONGYOU_ANDROID_SIGNING 指定配置。
- 必须备份整个私有目录至自己安全的存储，不能发给测试者，不能提交 Git。
- 同包名后续更新必须沿用同一密钥、递增 versionCode，才能覆盖安装保留本地状态。
- debug 使用 com.tongyou.travel.debug，不能拿 debug APK 给朋友当正式测试包。
- 发布 APK、SHA256SUMS、release.json 和安装说明在 releases/<version>/，不提交大文件。

能力与边界
- Android 8+，需要 Android System WebView 111+ 且支持 WEB_MESSAGE_LISTENER；宿主会检测并提示更新。
- 系统文件选择、导出后保存/分享、PDF 系统打印、来源白名单、断网提示、分层返回。
- 在网页分享菜单中选择 17同游，或系统允许时直接打开 https://17tongyou.com/travel/ 邀请链接。
- 未保存输入不会因断网主动刷新；进程被系统回收后的未保存草稿不保证恢复。
- 不提供离线记账、后台通知推送、静默安装更新或鸿蒙原生支持。0.6.0起支持前台检查版本、提示后跳转浏览器下载，安装仍由用户确认。
- 系统外部链接在浏览器打开。网络权限之外不申请相册/全盘存储权限。
- 后端 API 要保持向后兼容；改变 API 时需同时评估 Web、iOS 和已安装的 Android 版本。

链接唤起
- Manifest 对 https://17tongyou.com/travel/ 和 /t/ 声明 autoVerify。
- links/assetlinks.json 只包含正式包名及公开签名证书指纹，没有私钥。
- 生成：python3 scripts/generate-app-links.py；使用新签名时必须先处理升级兼容，不能随意换 key。
- 域名配置部署：仓库根目录 backend/.venv/bin/python android/scripts/deploy-app-links.py。
  仅写 /var/www/html/.well-known/assetlinks.json，保留其他应用关联；不部署 Web/后端。
- 验证：adb shell pm verify-app-links --re-verify com.tongyou.travel；
  adb shell pm get-app-links com.tongyou.travel。
- 未安装则保持网页；已安装但系统关闭“打开支持的链接”、或微信拦截时仍可能停留网页。
- iOS 旧包不具备该能力；用户随后单独追加的 iOS 1.0.6 (7) 支持从网页按钮手动唤起。
  iOS 使用免费个人签名的自定义协议，不是 Universal Links；与本 Android 包分开构建和发布。

App内更新（0.6.0起）
- 冷启动页面就绪后读取 https://17tongyou.com/downloads/android/latest.json；后台返回按6小时间隔检查，失败5分钟后可随再次返回重试。
- 高于当前versionCode且兼容系统才提示；“稍后”同版延后24小时。无强制更新、不自动下载、不获取通知/安装/存储权限。
- 更新清单无账号信息，不发送用户token；仅接受官方HTTPS精确版本化APK地址。
- 0.5.0及以前没有此能力，必须先手动覆盖安装0.6.0一次；不能通过发布清单给旧包远程添加检查功能。
- 发布新版：先递增versionCode并构建/测试/package-release，再执行（仓库根目录）：
  backend/.venv/bin/python android/scripts/publish-release.py --release 0.6.0-9 --notes-file android/release-notes/0.6.0.txt
  backend/.venv/bin/python android/scripts/verify-download.py --release 0.6.0-9 --latest
- 以后替换上述版本参数和更新说明。脚本先上传校验APK、再原子切换latest清单，旧下载URL继续保留；禁止降级和同versionCode替换不同包。
- 紧急暂停提示可将服务端latest.json的enabled设为false（保留schema/platform/application_id）；已下载APK不受影响。不要将清单指向尚未上传或未经测试的版本。
