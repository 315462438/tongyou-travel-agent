import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const cssPath = fileURLToPath(new URL('../src/index.css', import.meta.url))
const css = readFileSync(cssPath, 'utf8')
const tripsPath = fileURLToPath(new URL('../src/pages/Trips.tsx', import.meta.url))
const trips = readFileSync(tripsPath, 'utf8')
const homePath = fileURLToPath(new URL('../src/pages/Home.tsx', import.meta.url))
const home = readFileSync(homePath, 'utf8')
const socialPath = fileURLToPath(new URL('../src/components/SocialHub.tsx', import.meta.url))
const social = readFileSync(socialPath, 'utf8')
const notificationsPath = fileURLToPath(new URL('../src/components/Notifications.tsx', import.meta.url))
const notifications = readFileSync(notificationsPath, 'utf8')
const notificationUnreadPath = fileURLToPath(new URL('../src/hooks/useNotificationUnread.ts', import.meta.url))
const notificationUnread = readFileSync(notificationUnreadPath, 'utf8')
const authPath = fileURLToPath(new URL('../src/Auth.tsx', import.meta.url))
const auth = readFileSync(authPath, 'utf8')
const brandPath = fileURLToPath(new URL('../src/components/Brand.tsx', import.meta.url))
const brand = readFileSync(brandPath, 'utf8')
const indexPath = fileURLToPath(new URL('../index.html', import.meta.url))
const indexHtml = readFileSync(indexPath, 'utf8')
const faviconPath = fileURLToPath(new URL('../public/favicon.svg', import.meta.url))
const favicon = readFileSync(faviconPath, 'utf8')

test('single-entry hero returns to quiet travel content instead of a full-screen color wash', () => {
  assert.doesNotMatch(home, /<Aurora/)
  assert.match(home, /className="hero-soft-glow"/)
  assert.match(css, /\.hero-soft-glow\s*\{[^}]*radial-gradient[^}]*animation:\s*hero-glow-breathe/s)
  assert.match(css, /\.hero \.hero-title\s*\{[^}]*linear-gradient\(102deg, #244fc1[^}]*background-size:\s*180%[^}]*font-family:\s*"PingFang SC"[^}]*font-weight:\s*800[^}]*animation:\s*hero-sheen 9s/s)
  assert.match(css, /\.inspiration-launchpad\.simple\s*\{[^}]*rgba\(117, 136, 230, \.52\)[^}]*0 0 0 4px rgba\(101, 119, 224, \.055\)/s)
  assert.match(css, /\.destination-card\s*\{[^}]*animation:\s*destination-card-rise/s)
  assert.match(css, /prefers-reduced-motion: reduce\)[\s\S]*\.hero \.hero-title \{ animation: none; background-position: 45% center; \}/)
  assert.match(css, /prefers-reduced-motion: reduce\)[\s\S]*\.hero-soft-glow, \.destination-card \{ animation: none/)
})

test('new conversation uses one automatically-routed inspiration entry', () => {
  assert.match(home, /想去哪儿，就从这里出发/)
  assert.match(home, /function InspirationLaunchpad\(/)
  assert.match(home, /extractPublicInspirationUrls\(idea\)/)
  assert.match(home, /const routeKind = urls\.length[\s\S]*\? 'import'/)
  assert.match(home, /!idea\.trim\(\) && origin\.trim\(\) && budget\.trim\(\)/)
  assert.match(home, /isCompactDestinationIdea\(idea\) \? 'preview' : 'question'/)
  assert.match(home, /routeKind === 'question'[\s\S]*\? idea\.trim\(\)/)
  assert.match(home, /buildJourneyPreviewPrompt\(\{ destination: idea, origin, days, pace, budget \}\)/)
  assert.match(home, /buildInspirationImportPrompt\(\{ urls, origin, days \}\)/)
  assert.match(home, /buildBudgetRoulettePrompt\(\{ origin, budget, days, vibe: pace \}\)/)
  assert.match(home, /onLaunch\(\{ prompt, deepReasoning: true \}\)/)
  assert.doesNotMatch(home, /className="inspiration-tabs"/)
  assert.match(css, /\.inspiration-launchpad\.simple\s*\{[\s\S]*backdrop-filter:\s*blur/)
  assert.match(css, /\.view-mobile \.unified-constraints\s*\{\s*grid-template-columns:\s*repeat\(2/)
  // 通用问题走同一个 textarea，不再展开第二个 Composer。
  assert.doesNotMatch(home, /className="direct-ask-toggle"/)
  assert.match(home, /直接问“第一次去日本怎么准备？”/)
})

test('trip actions menu owns the top layer above the map', () => {
  assert.match(css, /\.trip-board-head\s*\{[^}]*z-index:\s*60[^}]*overflow:\s*visible/s)
  assert.match(css, /\.trip-3col\s*\{[^}]*position:\s*relative[^}]*z-index:\s*1/s)
})

test('collaborative trip follows the reference layout while inheriting platform colors', () => {
  const phase86 = css.slice(css.indexOf('Phase 86：协同行程参考稿视觉重构'))
  assert.match(trips, /className="trip-workspace-tabs"/)
  assert.match(trips, /TRIP_TOOL_TABS\.map/)
  assert.match(trips, /setAiTab\(tab\.id\)[\s\S]*setWorkspaceView\('tool'\)/)
  assert.match(phase86, /--trip-bg:\s*var\(--tx-bg\)/)
  assert.match(phase86, /--trip-accent:\s*var\(--tx-brand\)/)
  assert.doesNotMatch(phase86, /#f7f4ef|#c4612f|sepia\(/)
  assert.match(phase86, /\.trip-day-nav button\.active\s*\{[^}]*background:\s*var\(--trip-accent\)/s)
  assert.match(phase86, /\.trips-overlay \.trip-jsmap,[\s\S]*max-width:\s*none/s)
})

test('desktop trip board uses budget-days, itinerary table, and map columns', () => {
  const phase86 = css.slice(css.indexOf('Phase 86：协同行程参考稿视觉重构'))
  assert.match(trips, /trip-3col trip-view-\$\{workspaceView\}/)
  assert.match(trips, /days\.filter\(\(d\) => d === selectedDay\)\.map/)
  assert.match(trips, /className="trip-day-sidebar"/)
  assert.match(trips, /className="trip-budget-summary"/)
  assert.match(trips, /className="trip-table-shell"/)
  assert.match(trips, /className="trip-table-header"/)
  assert.match(trips, /className=\{`trip-table-row/)
  assert.match(trips, /className="trip-table-col-time">时段/)
  assert.match(trips, /className="trip-table-col-activity">地点与活动/)
  assert.match(trips, /className="trip-map-card-head"/)
  assert.match(trips, /右：每日地图（桌面固定，参考 HTML 的地图侧栏）/)
  // 三栏宽度是**设计快照**：改了就红，红了不代表坏了，而是提醒确认这次调整是有意的。
  // 2026-08-18 跟随 commit 0b2e6fe「Polish trip planning interface」更新——
  // 左侧日期栏与右侧地图栏收窄、中间行程表加宽（把版面让给主角）。
  assert.match(phase86, /\.trips-overlay \.trip-3col\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:\s*clamp\(176px, 14vw, 220px\) minmax\(520px, 1fr\) clamp\(320px, 24vw, 390px\)/s)
  assert.match(phase86, /\.trips-overlay \.trip-day-sidebar\s*\{[^}]*grid-column:\s*1/s)
  assert.match(phase86, /\.trips-overlay \.trip-col-timeline\s*\{[^}]*grid-column:\s*2/s)
  assert.match(phase86, /\.trips-overlay \.trip-col-map\s*\{[^}]*grid-column:\s*3/s)
  assert.match(phase86, /\.trips-overlay \.trip-view-tool \.trip-col-timeline\s*\{\s*display:\s*none/)
  assert.match(phase86, /\.trips-overlay \.trip-view-day \.trip-col-ai\s*\{\s*display:\s*none/)
  assert.match(phase86, /\.trips-overlay \.trip-table-header,[\s\S]*\.trips-overlay \.trip-table-row\s*\{[^}]*display:\s*grid/s)
  assert.match(phase86, /\.trips-overlay \.trip-day-section:has\(\.trip-table\)::before\s*\{[^}]*display:\s*none/s)
})

test('collaborative trip keeps mobile pane navigation after the desktop restyle', () => {
  const phase86 = css.slice(css.indexOf('Phase 86：协同行程参考稿视觉重构'))
  assert.match(phase86, /@media \(max-width:\s*900px\)[\s\S]*\.trip-workspace-tabs\s*\{\s*display:\s*none/)
  assert.match(phase86, /\.trips-overlay\.mobile-layout \.trip-workspace-tabs\s*\{\s*display:\s*none/)
  assert.match(phase86, /\.trips-overlay\.mobile-layout \.trip-map-tabs,[\s\S]*\.trip-ai-tabs\s*\{\s*display:\s*flex/)
  assert.match(phase86, /@media \(max-width:\s*720px\)[\s\S]*\.trip-stop-ops button\s*\{[^}]*min-height:\s*30px/s)
})

test('trip invite controls stay inside the actions popover', () => {
  assert.match(css, /\.trip-actions-popover \.trip-invite > span\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/s)
  assert.match(css, /\.trip-actions-popover \.trip-invite \.trip-btn\s*\{[^}]*min-width:\s*52px/s)
  assert.match(css, /\.trip-actions-popover\s*\{[^}]*max-width:\s*calc\(100vw - 24px\)[^}]*overflow:\s*hidden/s)
})

test('trip import exposes hotel candidates and unambiguous budget labels', () => {
  assert.match(trips, /攻略推荐酒店/)
  assert.match(trips, /hotel_recommendations/)
  assert.match(trips, /景点票价已录入/)
  assert.doesNotMatch(trips, />门票合计/)
  assert.match(home, /正在提取地点、酒店与预算/)
})

test('thinking workspace keeps staged motion, stop control, and reduced-motion fallback', () => {
  assert.match(home, /className="thinking-workspace"/)
  assert.match(home, /THINKING_STAGES\.map/)
  assert.match(home, /className="thinking-stop"/)
  // Phase 71：静默文案改为「正常现象 + 可以关掉页面」，不再暗示卡死
  assert.match(home, /正在深入思考中/)
  assert.match(home, /可以关掉页面/)
  assert.doesNotMatch(home, /秒没有新消息/)  // 旧的「像卡死」文案已移除
  assert.match(css, /\.thinking-workspace\s*\{/)
  assert.match(css, /@keyframes thinking-spin/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.thinking-workspace[\s\S]*animation:\s*none !important/)
})

test('thinking workspace shows expected duration and a determinate progress bar (Phase 71)', () => {
  assert.match(home, /className="thinking-progress/)
  assert.match(home, /role="progressbar"/)
  assert.match(home, /expectedHintFor\(mode\)/)
  assert.match(home, /waitReassurance\(elapsedSec, mode\)/)
  assert.match(css, /\.thinking-progress\s*\{/)
  assert.match(css, /\.thinking-progress-fill\s*\{/)
  // 进度条动效也要尊重 reduced-motion
  assert.match(css, /prefers-reduced-motion: reduce\)\s*\{[\s\S]*\.thinking-progress-fill\s*\{\s*transition:\s*none/)
})

test('guide reading view has semantic title, day cards, responsive tables, and large images', () => {
  assert.match(home, /className="md guide-markdown"/)
  assert.match(home, /className="guide-title"/)
  assert.match(home, /guide-day-heading/)
  assert.match(home, /className="guide-table-wrap"/)
  assert.match(css, /\.guide-markdown \.guide-title\s*\{[\s\S]*border-radius:\s*20px/)
  assert.match(css, /\.guide-markdown \.guide-day-heading\s*\{[\s\S]*background:\s*linear-gradient/)
  assert.match(css, /\.guide-table-wrap\s*\{[\s\S]*overflow-x:\s*auto/)
  assert.match(css, /\.guide-markdown img\s*\{[\s\S]*object-fit:\s*contain/)
})

test('trip collaboration exposes a responsive group chat drawer', () => {
  assert.match(trips, /function TripChat\(/)
  assert.match(trips, /className=\{`trip-chat-trigger/)
  assert.match(trips, /\/chat`\)/)
  assert.match(trips, /open \? 2500 : 8000/)
  // Phase 74：回车/输入法处理随输入框一起抽到共享 ChatInput，这里只需确认群聊用了它
  assert.match(trips, /<ChatInput\s/)
  assert.match(trips, /具体地点仍可使用地点留言/)
  assert.match(trips, /querySelector\('\.trip-chat-panel,\s*\.trip-source-panel'\)/)
  assert.match(trips, /closeOnEscape/)
  assert.match(css, /\.trip-chat-panel\s*\{[\s\S]*width:\s*min\(420px,\s*94vw\)/)
  assert.match(css, /@media \(max-width:\s*720px\)[\s\S]*\.trip-chat-panel\s*\{[\s\S]*width:\s*100vw/)
})

test('trip members can read the imported guide without entering the owner private chat', () => {
  assert.match(trips, /function SourceGuideDrawer\(/)
  assert.match(trips, /\/source-guide/)
  assert.match(trips, /所有已加入成员都可只读查看/)
  assert.match(trips, /can_open_conversation/)
  // 2026-07 走查 P0-3：remark-gfm 必须以 singleTilde:false 挂载（`¥400~600` 防吞字）
  assert.match(trips, /remarkPlugins=\{\[\[remarkGfm, \{ singleTilde: false \}\]\]\}/)
  assert.match(css, /\.trip-source-panel\s*\{[\s\S]*width:\s*min\(780px,\s*96vw\)/)
  assert.match(css, /\.trip-source-markdown img\s*\{[\s\S]*object-fit:\s*cover/)
})

test('trip map exposes overseas coordinate repair and honest route estimates', () => {
  assert.match(trips, /\/geocode\/repair/)
  assert.match(trips, /🌐 重新定位/)
  assert.match(trips, /iss\.action === 'repair_geocode'/)
  assert.match(trips, /OpenStreetMap contributors/)
  assert.match(css, /\.trip-map-tools\s*\{/)
  assert.match(css, /\.trip-repair-btn:disabled\s*\{[^}]*cursor:\s*wait/s)
})

test('mobile shell exposes a view switch, drawer navigation, and safe-area bottom bar', () => {
  assert.match(home, /className=\{`app view-\$\{layoutMode\}/)
  assert.match(home, /className="layout-switch"/)
  assert.match(home, />\s*网页端\s*</)
  assert.match(home, />\s*移动端\s*</)
  assert.match(home, /className="mobile-bottom-nav"/)
  assert.match(home, /aria-label="打开历史对话"/)
  assert.match(home, /layoutMode=\{layoutMode\}/)
  assert.match(trips, /trips-overlay\$\{layoutMode === 'mobile' \? ' mobile-layout' : ''\}/)
  assert.match(css, /\.app\.view-mobile\.collapsed \.sidebar\s*\{[\s\S]*transform:\s*translateX\(-105%\)/)
  assert.match(css, /\.view-mobile \.mobile-bottom-nav\s*\{[\s\S]*env\(safe-area-inset-bottom\)/)
  assert.match(css, /\.view-mobile \.chips\s*\{[\s\S]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
})

test('mobile reading and composer layouts remain single-column and thumb friendly', () => {
  assert.match(css, /\.view-mobile \.guide-outline nav\s*\{\s*grid-template-columns:\s*1fr/)
  assert.match(css, /\.view-mobile \.guide-table-wrap\s*\{[\s\S]*max-width:\s*calc\(100% \+ 6px\)/)
  assert.match(css, /\.view-mobile \.message-actions\s*\{[\s\S]*overflow-x:\s*auto/)
  assert.match(css, /\.view-mobile \.composer\s*\{[\s\S]*grid-template-columns:\s*34px minmax\(0,\s*1fr\) 36px/)
  assert.match(css, /\.mobile-bottom-nav button\s*\{[\s\S]*min-height:\s*48px/)
  assert.match(css, /\.trips-overlay\.mobile-layout \.trip-mobile-tabs\s*\{[\s\S]*display:\s*grid/)
})

test('mobile bottom navigation closes the previous full-screen surface', () => {
  assert.match(home, /const openMobileChat = useCallback\(\(\) => \{[\s\S]*setShowTrips\(false\)[\s\S]*setTripsBoard\(null\)[\s\S]*newChat\(\)/)
  assert.match(home, /const openMobileHistory = useCallback\(\(\) => \{[\s\S]*setShowTrips\(false\)[\s\S]*setCollapsed\(false\)/)
  assert.match(home, /const openMobileSocial = useCallback\(\(\) => \{[\s\S]*setShowTrips\(false\)[\s\S]*setShowMemories\(false\)[\s\S]*openSocial\('station'\)/)
  assert.match(home, /onClick=\{openMobileChat\}/)
  assert.match(home, /onClick=\{openMobileTrips\}/)
  assert.match(home, /onClick=\{openMobileHistory\}/)
  assert.match(home, /onClick=\{openMobileSocial\}/)
})

test('17tongyou brand replaces the legacy lightning favicon and travelX wordmark', () => {
  assert.match(indexHtml, /<title>17同游 · 一起规划，一起出发<\/title>/)
  assert.match(indexHtml, /favicon\.svg\?v=2/)
  assert.match(indexHtml, /property="og:site_name" content="17同游"/)
  assert.match(brand, /className="brand-number">17</)
  assert.match(brand, /className="brand-cn">同游</)
  assert.match(favicon, /linearGradient id="brand-bg"/)
  assert.match(favicon, /stroke="#fff"/)
  assert.match(home, /<small>17tongyou<\/small>/)
  assert.match(home, /17同游 · 为你手绘/)
  assert.match(auth, /17tongyou · 一起规划，一起出发/)
  assert.doesNotMatch(`${indexHtml}\n${home}\n${auth}`, /travelX/)
})

test('生成期间不再无条件把用户拽回底部', () => {
  // 回归 Phase 72：轮询刷新时曾无条件 scrollIntoView，上翻看前文会被立刻拉走
  assert.doesNotMatch(home, /useEffect\(\(\) => \{\s*bottomRef\.current\?\.scrollIntoView/)
  assert.match(home, /if \(!stickBottomRef\.current\) return/)
  assert.match(home, /onScroll=\{onThreadScroll\}/)
  assert.match(home, /onWheel=\{onThreadWheel\}/)
  assert.match(home, /className="jump-bottom"/)
  assert.match(css, /\.jump-bottom \{[\s\S]*position: sticky/)
})

// ---------- Phase 73：在线状态 + 客服会话 ----------
const supportPath = fileURLToPath(new URL('../src/components/Support.tsx', import.meta.url))
const support = readFileSync(supportPath, 'utf8')

test('admin 面板展示在线状态，且不在前端重算在线阈值', () => {
  assert.match(home, /online-dot \$\{u\.online \? 'on' : ''\}/)
  assert.match(home, /u\.online \? '在线' : formatLastSeen\(u\.last_seen_at, now\)/)
  assert.match(home, /人在线/)
  // 阈值只能由服务端判定：前端出现秒数比较就是两端口径漂移的开始
  assert.doesNotMatch(home, /online_window|5 \* 60 \* 1000/)
  assert.match(css, /\.online-dot\.on \{[^}]*background: #34c759/)
})

test('客服会话：用户入口带红点，admin 面板有标签页与未读徽标', () => {
  assert.match(home, /<span>联系客服<\/span>/)
  assert.match(home, /supportUnread > 0 && <b className="support-badge">/)
  assert.match(home, /<SupportChat open=\{showSupport\}/)
  assert.match(home, /unreadTotal > 0 && <b className="support-badge">/)
  assert.match(home, /<AdminSupport \/>/)
  assert.match(css, /\.support-badge \{[\s\S]*background: #ff3b30/)
})

test('客服抽屉打开时暂停未读轮询，避免和消息轮询重复打接口', () => {
  assert.match(home, /useSupportUnread\(true, showSupport\)/)
  assert.match(support, /if \(!enabled \|\| paused\) return/)
})

test('客服输入框回车发送但不打断中文输入法候选', () => {
  // Phase 74 起输入框抽到共享的 ChatInput（客服 + 行程群聊共用）
  assert.match(chatInput, /isComposing: \(e\.nativeEvent as KeyboardEvent\)\.isComposing/)
})

test('Esc 关闭客服抽屉，且优先级在 admin 面板之前', () => {
  assert.match(home, /else if \(showSupport\) setShowSupport\(false\)\s*\n\s*else if \(showAdmin\)/)
})

// ---------- Phase 74：管理后台 / 公告 / 表情与图片 ----------
const chatInputPath = fileURLToPath(new URL('../src/components/ChatInput.tsx', import.meta.url))
const chatInput = readFileSync(chatInputPath, 'utf8')
const annPath = fileURLToPath(new URL('../src/components/Announcements.tsx', import.meta.url))
const ann = readFileSync(annPath, 'utf8')
const invitesPath = fileURLToPath(new URL('../src/components/AdminInvites.tsx', import.meta.url))
const invites = readFileSync(invitesPath, 'utf8')

test('侧栏展开按钮层叠必须高于顶栏，否则收起后再也展不开', () => {
  // 回归 2026-08-04：.app-topbar 是 z-index:24 且有不透明背景 + backdrop-filter，
  // .sidebar-expand 原为 20 → 被整个盖住。
  const expand = /\.sidebar-expand \{[\s\S]*?\}/.exec(css)[0]
  const topbar = /\.app-topbar \{[\s\S]*?\}/.exec(css)[0]
  const z = (block) => Number(/z-index:\s*(\d+)/.exec(block)[1])
  assert.ok(z(expand) > z(topbar), `展开按钮 z-index(${z(expand)}) 必须大于顶栏(${z(topbar)})`)
})

test('管理面板有四个标签页与角色升降级按钮', () => {
  assert.match(home, /'users' \| 'support' \| 'invites' \| 'announce'/)
  assert.match(home, /<AdminInvites \/>/)
  assert.match(home, /<AdminAnnouncements \/>/)
  assert.match(home, /u\.is_admin \? '取消管理员' : '设为管理员'/)
  // 服务端的防呆理由（改自己/最后一个管理员）必须原样透传给用户
  assert.match(home, /detail\?\.detail \|\| '操作失败'/)
})

test('统一通知中心：铃铛合并社交与公告未读，并可直达对应上下文', () => {
  assert.match(home, /notificationUnread = annUnread \+ socialUnread/)
  assert.match(home, /className=\{`topbar-bell\$\{notificationUnread > 0 \? ' has-unread' : ''\}`\}/)
  assert.match(home, /className="bell-count"/)
  assert.match(home, /<NotificationPanel/)
  assert.match(home, /item\.target_kind === 'relay'/)
  assert.match(home, /openSocial\('station', item\.meta\.destination/)
  assert.match(home, /openSocial\('friends'\)/)
  assert.match(home, /<AnnouncementPanel open=\{showAnn\}/)
  assert.match(notificationUnread, /\/notifications\/unread-count/)
  assert.match(notifications, /\/notifications\/read-all/)
  assert.match(notifications, /平台公告/)
  assert.match(ann, /list\.filter\(\(a\) => !a\.read\)\.map/)
  assert.match(css, /\.bell-count\s*\{[\s\S]*?background: #ef4b56/)
  assert.match(css, /\.notification-panel\s*\{[\s\S]*?position: absolute/)
})

test('邀请码：可复制、显示配额、用完标记失效', () => {
  assert.match(invites, /navigator\.clipboard\.writeText\(code\)/)
  assert.match(invites, /\{c\.used_count\} \/ \{c\.max_uses\}/)
  assert.match(invites, /c\.exhausted \? '已用完'/)
  // .env 里那把不限量的老钥匙仍然生效，必须提示管理员
  assert.match(invites, /REGISTER_INVITE_CODE/)
})

test('聊天输入：表情插到光标处、截图可粘贴、图片单独成条消息', () => {
  assert.match(chatInput, /el\.selectionStart \?\? text\.length/)
  assert.match(chatInput, /onPaste=/)
  assert.match(chatInput, /f\.type\.startsWith\('image\/'\)/)
  assert.match(chatInput, /!\[图片\]\(\$\{API\}\/uploads\/\$\{data\.id\}\)/)
})

test('客服与行程群聊共用同一套输入与渲染', () => {
  assert.match(support, /<ChatInput onSend=\{send\}/)
  assert.match(support, /<ChatInput onSend=\{reply\}/)
  assert.match(support, /<ChatBody content=\{m\.content\} \/>/)
  assert.match(trips, /<ChatBody content=\{message\.content\} \/>/)
  assert.match(trips, /<ChatInput\s/)
})

test('新公告首次弹窗：任务运行中不打断、确认才已读', () => {
  // 红点太弱用户发现不了 → 首次弹窗；但两条约束必须守住
  assert.match(home, /annUnread > 0 && !annDismissed && !running && !showAnn/)
  assert.match(home, /<AnnouncementModal/)
  // 弹窗可能在用户不在电脑前时自动出现：一显示就标已读会让公告永远消失
  const modal = ann.slice(ann.indexOf('export function AnnouncementModal'))
  assert.doesNotMatch(modal.slice(0, modal.indexOf('const acknowledge')), /\/read`/)
  assert.match(modal, /const acknowledge[\s\S]*\/read`/)
  // 新用户未读=全部历史公告，弹窗只展示最新 5 条
  assert.match(modal, /unread\.slice\(0, 5\)/)
  assert.match(css, /\.topbar-bell\.has-unread/)
  assert.match(css, /prefers-reduced-motion[\s\S]*bell-swing|bell-swing[\s\S]*prefers-reduced-motion/)
})

test('空状态把真实热门目的地做成异步实景图片卡片集', () => {
  // Phase 75：08-04 新用户 33% 注册后零提问；示例全是成都而他们都是合肥/武汉的
  assert.match(home, /trendingDestinations = onboarding\?\.trending\?\.length \? onboarding\.trending : FALLBACK_DESTINATIONS/)
  assert.match(home, /buildTrendingChips\(trendingDestinations/)
  assert.doesNotMatch(home, /\{CHIPS\.map\(/)          // 不再直接渲染静态成都示例
  assert.match(home, /onboarding\/covers\?/)
  assert.match(home, /suggestions=\{starterChips\.slice\(0, 4\)\}/)
  assert.match(home, /className="trending-destination-grid"/)
  assert.match(home, /className="destination-card"/)
  assert.match(home, /\$\{API\}\/img\?u=\$\{encodeURIComponent\(cover\)\}/)
  assert.match(home, /近 30 天真实热问/)
  assert.match(home, /setIdea\(city\)/) // 点击卡片回填唯一入口，不直接发送
  assert.match(css, /\.trending-destination-grid\s*\{[^}]*repeat\(4/s)
  assert.match(css, /\.view-mobile \.trending-destination-grid\s*\{[^}]*scroll-snap-type:\s*x mandatory/s)
  assert.doesNotMatch(home, /<QuickStart\s/)
})

test('接力站先展示真实热门目的地，再提供无原生黑框的任意目的地搜索', () => {
  assert.match(home, /lazy\(\(\) => import\('\.\.\/components\/SocialHub'\)\)/)
  assert.match(home, /className="social-entry"/)
  assert.match(home, /有人正在天堂寨，把现场情况留给下一位/)
  assert.match(home, /<SocialHub[\s\S]*initialTab=\{socialLaunch\.tab\}/)
  assert.doesNotMatch(home, /<ImmersivePreview/)
  assert.match(home, />同游圈</)
  assert.match(home, /onProfileChanged=\{onProfileChanged\}/)
  assert.match(social, /role="dialog" aria-modal="true"/)
  assert.match(social, /'station' \| 'friends' \| 'profile'/)
  assert.match(social, /\/social\/station\?/)
  assert.match(social, /\/social\/friends\/request\//)
  assert.match(social, /\/social\/posts\/\$\{post\.id\}\/react/)
  assert.match(social, /输入任意目的地，例如黄山、京都或冰岛/)
  assert.match(social, /import Aurora from '\.\/Aurora'/)
  assert.match(social, /\$\{API\}\/onboarding/)
  assert.match(social, /\$\{API\}\/onboarding\/covers\?/)
  assert.match(social, /className="station-hot-aurora"/)
  assert.match(social, /近 30 天真实热问/)
  assert.match(social, /className="station-hot-grid"/)
  assert.match(social, /hotDestinations\.map/)
  assert.ok(social.indexOf('className="station-hot"') < social.indexOf('className="station-search-panel"'))
  assert.match(social, /onSubmit=\{\(event\) => \{ event\.preventDefault\(\); enterDestination\(\) \}\}/)
  assert.match(social, /POST_PHASE_BY_KIND/)
  assert.match(social, /question: 'planning'/)
  assert.match(social, /condition: 'on_trip'/)
  assert.match(social, /route: 'returned'/)
  assert.match(social, /问一个问题/)
  assert.match(social, /报个现场/)
  assert.match(social, /分享路线/)
  assert.match(social, /72 小时有效/)
  assert.doesNotMatch(social, /value=\{postPhase\}/)
  assert.match(social, /不会自动看到你的私人行程/)
  assert.match(social, /accept="image\/png,image\/jpeg,image\/gif,image\/webp"/)
  assert.match(social, /className="social-me-mini"[\s\S]*<Avatar user=\{profile\} size="lg"/)
  assert.match(social, /profile_public/)
  assert.match(social, /initialTab\?: SocialTab/)
  assert.match(social, /initialDestination\?: string/)
  assert.match(social, /最近留下的旅行接力/)
  assert.match(social, /加为好友/)
  assert.match(css, /\.social-overlay\s*\{[^}]*position:\s*fixed[^}]*z-index:\s*10020/s)
  assert.match(css, /\.social-rail\s*\{[\s\S]*background:\s*linear-gradient/s)
  assert.match(css, /\.social-me-mini \.social-avatar\.lg\s*\{[^}]*width:\s*46px[^}]*height:\s*46px[^}]*border:/s)
  assert.match(css, /\.social-me-mini \.social-avatar img\s*\{[^}]*object-fit:\s*contain[^}]*object-position:\s*center/s)
  assert.match(css, /\.station-search\s*\{[^}]*grid-template-columns:/s)
  assert.match(css, /\.station-hot-aurora\s*\{[^}]*pointer-events:\s*none/s)
  assert.match(css, /\.station-hot-grid\s*\{[^}]*repeat\(4,/s)
  assert.match(css, /\.station-search-panel \.station-search input\s*\{[^}]*border:\s*0[^}]*appearance:\s*none/s)
  assert.match(css, /\.relay-kind-picker\s*\{[^}]*repeat\(3,/s)
  assert.match(css, /Phase 83b：社交页可读字号基线/)
  assert.match(css, /\.relay-card > p\s*\{[^}]*font-size:\s*15px/s)
  assert.match(css, /\.relay-author small\s*\{[^}]*font-size:\s*12px/s)
  assert.match(css, /\.relay-phase, \.relay-kind\s*\{[^}]*font-size:\s*11px/s)
  assert.match(css, /\.relay-reactions button\s*\{[^}]*font-size:\s*11px/s)
  assert.match(css, /\.station-current \.station-phase-tabs button b, \.station-phase-tabs button b\s*\{[^}]*font-size:\s*11px/s)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.social-rail\s*\{[^}]*position:\s*fixed/s)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.social-rail nav button span\s*\{\s*font-size:\s*11px/s)
  assert.match(css, /@media \(max-width: 760px\)[\s\S]*\.station-hot-grid\s*\{[^}]*scroll-snap-type:\s*x mandatory/s)
})

test('区域型提问给候选卡而不是反问，点一下即发出', () => {
  // Phase 76：08-04 有 3/8 首问是「合肥周边」「皖南」这类区域型表达，原来一律被反问
  assert.match(home, /msg\.meta\?\.candidates\?\.length/)
  assert.match(home, /className="cand-card"/)
  assert.match(home, /onPickDestination\?\.\(c\.name\)/)
  assert.match(home, /send\(`去\$\{name\}`\)/)
  // 候选之外必须留出路，不能变成「只能三选一」
  assert.match(home, /都不合适？直接说个地名，或者让我来定/)
  assert.match(css, /\.cand-card \{/)
})

test('攻略后主动给「接下来」，不再把入口埋在小按钮堆里', () => {
  // Phase 76：08-04 拿到攻略的 8 人里只有 1 个自己摸到「海报→带日期回来重排」
  assert.match(home, /className="next-steps"/)
  assert.match(home, /接下来/)
  assert.match(home, /日期定了？排到每一天/)
  assert.match(home, /叫上同行的人一起改/)
  assert.match(home, /生成手账海报<\/b>|>\{clicked \? '手账生成中…' : '生成手账海报'\}</)
  // 三张卡必须是卡片形态而不是又一排小按钮
  assert.match(css, /\.next-step-card \{[\s\S]*?flex-direction: column/)
  assert.match(css, /\.next-steps-grid \{[\s\S]*?grid-template-columns/)
})
