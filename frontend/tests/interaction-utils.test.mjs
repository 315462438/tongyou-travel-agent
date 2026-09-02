import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ATTENTION_BADGE_MAX,
  pickNavUrl,
  canSendComposer,
  addPendingImages,
  removePendingImage,
  pickImageFiles,
  badgedTitle,
  extractGuideHeadings,
  formatTripTimeRange,
  firstLine,
  formatThinkingElapsed,
  headingAnchor,
  initialLayoutMode,
  initialThemeMode,
  MAX_PROMPT_LENGTH,
  normalizePrompt,
  latestLine,
  shouldSubmitComposer,
  thinkingRowLabel,
} from '../src/interaction.ts'

test('trip event time is a range derived from duration or the next event', () => {
  assert.equal(formatTripTimeRange('08:30', 135), '08:30 – 10:45')
  assert.equal(formatTripTimeRange('11:00', null, '12:30'), '11:00 – 12:30')
  assert.equal(formatTripTimeRange('23:30', 90), '23:30 – 次日 01:00')
  assert.equal(formatTripTimeRange('20:00', null), '20:00 – 待定')
  assert.equal(formatTripTimeRange('', 60), '时间待定')
})

test('layout mode defaults to mobile on phones and preserves desktop preview choice', () => {
  assert.equal(initialLayoutMode(390, null), 'mobile')
  assert.equal(initialLayoutMode(390, 'desktop'), 'mobile')
  assert.equal(initialLayoutMode(1440, null), 'desktop')
  assert.equal(initialLayoutMode(1440, 'mobile'), 'mobile')
  assert.equal(initialLayoutMode(844, 'desktop', true), 'mobile')
})

test('theme mode persists only supported values and otherwise falls back to modern', () => {
  assert.equal(initialThemeMode(null), 'modern')
  assert.equal(initialThemeMode('modern'), 'modern')
  assert.equal(initialThemeMode('ink'), 'ink')
  assert.equal(initialThemeMode('green'), 'modern')
})

test('composer submits with plain Enter', () => {
  assert.equal(shouldSubmitComposer({ key: 'Enter', shiftKey: false, isComposing: false }), true)
})

test('composer keeps newline and IME composition intact', () => {
  assert.equal(shouldSubmitComposer({ key: 'Enter', shiftKey: true, isComposing: false }), false)
  assert.equal(shouldSubmitComposer({ key: 'Enter', shiftKey: false, isComposing: true }), false)
  assert.equal(shouldSubmitComposer({ key: 'a', shiftKey: false, isComposing: false }), false)
})

test('prompt normalization trims and enforces the UI limit', () => {
  assert.equal(normalizePrompt('  成都三日游  '), '成都三日游')
  assert.equal(normalizePrompt('x'.repeat(MAX_PROMPT_LENGTH + 25)).length, MAX_PROMPT_LENGTH)
})

test('guide outline extracts h2/h3 headings with stable anchors', () => {
  const headings = extractGuideHeadings('# 成都攻略\n## Day 1 · 老城\n正文\n### 午餐推荐\n## Day 2')
  assert.deepEqual(headings, [
    { level: 2, title: 'Day 1 · 老城', id: 'guide-day-1-老城' },
    { level: 3, title: '午餐推荐', id: 'guide-午餐推荐' },
    { level: 2, title: 'Day 2', id: 'guide-day-2' },
  ])
  assert.equal(headingAnchor('  **预算 / 交通** '), 'guide-预算-交通')
})

test('elapsed time formats across minute and hour boundaries', () => {
  assert.equal(formatThinkingElapsed(-1), '00:00')
  assert.equal(formatThinkingElapsed(38), '00:38')
  assert.equal(formatThinkingElapsed(252), '04:12')
  assert.equal(formatThinkingElapsed(3723), '1:02:03')
})

test('thinking row summary follows the tail while running, the head when done', () => {
  // 两种取法不同是有原因的：跑动时用户要知道「它现在想到哪了」，
  // 读完之后要知道「这段思考讲的是什么」。取反了两种状态都会变得没用。
  const chain = '先确定目的地\n再看天数和预算\n最后排每天的路线'
  assert.equal(latestLine(chain), '最后排每天的路线')
  assert.equal(firstLine(chain), '先确定目的地')
  // 流式尾部常带一个还没写完的换行，不能因此显示成空行
  assert.equal(latestLine('第一步\n第二步\n'), '第二步')
  assert.equal(latestLine(''), '')
  assert.equal(firstLine(''), '')
  assert.equal(latestLine('只有一行'), '只有一行')
  assert.equal(firstLine('只有一行'), '只有一行')
})

test('thinking row label keeps the elapsed time and the expected duration together', () => {
  // ⚠️ Phase 71 的实测结论：流失的原因是「不知道还要多久」。把工作台压成一行时，
  // 这两个数是唯一不能丢的东西——它们在这一个字符串里，丢了就是整条线索没了。
  const label = thinkingRowLabel('智能规划', 47)
  assert.match(label, /智能规划/)
  assert.match(label, /00:47/)
  assert.match(label, /通常 3-4 分钟/)
  // 未知模式回落到智能规划的预期，而不是显示一个空档
  assert.match(thinkingRowLabel('未知模式', 5), /通常 3-4 分钟/)
  assert.match(thinkingRowLabel('深度推理', 5), /通常 4-6 分钟/)
})

// ---------- Phase 71：等待预期管理 ----------

const { expectedSecondsFor, expectedHintFor, waitReassurance } =
  await import('../src/interaction.ts')

test('每种任务有各自的预计时长与提示', () => {
  assert.equal(expectedSecondsFor('深度推理'), 330)
  assert.equal(expectedSecondsFor('手账生成'), 75)
  assert.match(expectedHintFor('深度推理'), /4-6 分钟/)
  // 未知模式回落到默认，不能是 undefined/NaN
  assert.ok(expectedSecondsFor('未知模式') > 0)
  assert.ok(expectedHintFor('未知模式').length > 0)
})

test('等待文案随时长升级，且超时后不暗示卡死', () => {
  const early = waitReassurance(10, '深度推理')
  const late = waitReassurance(400, '深度推理')
  const veryLate = waitReassurance(900, '深度推理')
  assert.match(early, /4-6 分钟/)
  assert.match(early, /关掉页面/)          // 早期就告诉用户可以离开
  assert.match(late, /比平时久|正常推进/)
  assert.ok(!/卡死|失败|错误/.test(late))   // 绝不能暗示挂了
  assert.match(veryLate, /仍在服务器上跑|停止重来/)
})

// ---------- Phase 71.1：模式不能被用户内容污染 ----------
// Phase 112 注：同一节原来还钉着「阶段推断不被搜索词污染」的三条用例
// （stageSignal / 「攻略」误判 / 序列单调）。五阶段步骤条随本次改造删除，
// 那三个纯函数一并删掉——留着没有生产调用方的函数比少一个功能更糟
// （Phase 96 的 truncate.py 就是这么变成死代码的）。模式推断仍在用，故保留。

const { inferThinkingMode } = await import('../src/interaction.ts')

test('模式按实际路由判定，而不是前端开关', () => {
  assert.equal(inferThinkingMode(['正在理解你的旅行需求…', '已获取高德实时数据（天气 + 景点）']), '智能规划')
  assert.equal(inferThinkingMode(['🧭 这是个开放式问题，进入深度研究模式（规划 → 搜集 → 汇总）…']), '深度推理')
  assert.equal(inferThinkingMode(['正在整理手账海报…']), '手账生成')
  assert.equal(inferThinkingMode([]), '智能规划')
})

// ---------- 2026-07-30 走查修复：Markdown 渲染修补 ----------
test('prepareMarkdown pads strong delimiters so CJK punctuation-adjacent bold renders', async () => {
  const { prepareMarkdown } = await import('../src/interaction.ts')
  const out = prepareMarkdown('，**烤匠麻辣烤鱼（春熙路店）**解决午餐')
  assert.equal(out, '，**​烤匠麻辣烤鱼（春熙路店）​**解决午餐')
  // 幂等性无所谓，但不能破坏无加粗文本与波浪线区间
  assert.equal(prepareMarkdown('¥400~600/晚'), '¥400~600/晚')
  assert.equal(prepareMarkdown('普通文本'), '普通文本')
})

// ---------- Phase 72：生成期间的滚动跟随 ----------
test('只有贴着底部才跟随滚动，用户上翻立即脱离', async () => {
  const { isNearBottom, shouldFollowBottom, NEAR_BOTTOM_PX } = await import('../src/interaction.ts')
  const atBottom = { scrollTop: 3000, scrollHeight: 3600, clientHeight: 600 }
  const scrolledUp = { scrollTop: 1200, scrollHeight: 3600, clientHeight: 600 }
  const almostBottom = { scrollTop: 3000 - (NEAR_BOTTOM_PX - 20), scrollHeight: 3600, clientHeight: 600 }

  assert.equal(isNearBottom(atBottom), true)
  assert.equal(isNearBottom(almostBottom), true)   // 容差内仍算贴底
  assert.equal(isNearBottom(scrolledUp), false)

  assert.equal(shouldFollowBottom(atBottom), true)
  assert.equal(shouldFollowBottom(scrolledUp), false)
  // 关键：滚轮往上的那一刻就脱离，不等 onScroll 复算——否则平滑滚动动画会把判定拽回 true
  assert.equal(shouldFollowBottom(atBottom, true), false)
})

// ---------- Phase 73：在线状态相对时间 ----------
test('formatLastSeen 分档，且不受客户端时钟快于服务端影响', async () => {
  const { formatLastSeen } = await import('../src/interaction.ts')
  const now = Date.parse('2026-08-04T12:00:00Z')
  const ago = (s) => new Date(now - s * 1000).toISOString()

  assert.equal(formatLastSeen(null, now), '从未活跃')       // 存量用户不能伪造活跃
  assert.equal(formatLastSeen('乱码', now), '从未活跃')
  assert.equal(formatLastSeen(ago(10), now), '刚刚')
  assert.equal(formatLastSeen(ago(12 * 60), now), '12 分钟前')
  assert.equal(formatLastSeen(ago(3 * 3600), now), '3 小时前')
  assert.equal(formatLastSeen(ago(2 * 86400), now), '2 天前')
  assert.equal(formatLastSeen(ago(400 * 86400), now), '很久以前')
  // 服务端时间比本机快几秒时，不能显示成「-1 分钟前」
  assert.equal(formatLastSeen(new Date(now + 5000).toISOString(), now), '刚刚')
})

test('formatLastSeen 依赖带时区的 ISO —— 裸时间戳会差一个时区', async () => {
  const { formatLastSeen } = await import('../src/interaction.ts')
  const now = Date.parse('2026-08-04T12:00:00Z')
  // 后端 iso_utc 保证带 +00:00；这里锁住「带偏移量时结果正确」
  assert.equal(formatLastSeen('2026-08-04T11:58:00+00:00', now), '2 分钟前')
})

// ---------- Phase 75：新用户开口率 ----------
test('热门示例用平台真实目的地，并在已知常驻城市时带上出发地', async () => {
  const { buildTrendingChips } = await import('../src/interaction.ts')
  const chips = buildTrendingChips(['平潭岛', '武功山', '皖南', '天堂寨'], '合肥')
  assert.equal(chips.length, 4)                       // 图片卡片集展示榜单前 4
  assert.equal(chips[0].label, '平潭岛怎么玩')
  assert.match(chips[0].text, /从合肥出发去平潭岛/)   // 不再是写死的成都
  // 没有常驻城市时不能凭空编一个出发地
  const noHome = buildTrendingChips(['平潭岛'], '')
  assert.doesNotMatch(noHome[0].text, /出发/)
  assert.deepEqual(buildTrendingChips([], '合肥'), [])
})


test('三下起步：只点一项也要能成句，不强制填满', async () => {
  const { buildQuickPrompt } = await import('../src/interaction.ts')
  assert.equal(buildQuickPrompt({}), '')
  // 强制三项都选 = 换个方式要求用户想清楚，等于没解决问题
  assert.match(buildQuickPrompt({ from: '合肥' }), /^我从合肥出发，还没想好去哪/)
  assert.match(buildQuickPrompt({ days: '周末两天' }), /打算玩周末两天/)
  const full = buildQuickPrompt({ from: '合肥', days: '周末两天', who: '和家人' })
  assert.match(full, /我从合肥出发，打算玩周末两天，和家人，还没想好去哪，帮我推荐几个合适的目的地/)
  // 「不确定」要转成自然表达，不能原样塞进句子
  assert.match(buildQuickPrompt({ from: '武汉', days: '不确定' }), /时间还没定/)
  assert.doesNotMatch(buildQuickPrompt({ from: '武汉', who: '不确定' }), /不确定/)
})

// ---------- Phase 77：旅行预演与灵感入口 ----------


test('收藏炼金从分享文本提取、去重并限制公开 HTTP(S) 链接', async () => {
  const { extractPublicInspirationUrls, isPublicInspirationUrl, buildInspirationImportPrompt } =
    await import('../src/interaction.ts')
  assert.equal(isPublicInspirationUrl('javascript:alert(1)'), false)
  assert.equal(isPublicInspirationUrl('https://www.xiaohongshu.com/explore/abc'), true)
  const urls = extractPublicInspirationUrls(
    '成都收藏 https://example.com/a。 再看 https://example.com/a 和 https://example.org/b！',
  )
  assert.deepEqual(urls, ['https://example.com/a', 'https://example.org/b'])
  const prompt = buildInspirationImportPrompt({ urls, origin: '武汉', days: '3 天', note: '少排队' })
  assert.match(prompt, /实际读取链接内容/)
  assert.match(prompt, /合并重名地点/)
  assert.match(prompt, /哪些内容没有成功读取/)
  assert.equal(buildInspirationImportPrompt({ urls: ['file:///etc/passwd'] }), '')
})


test('打字机：无积压立即完成，终稿/隐藏直接追平全量', async () => {
  const { typewriterStep } = await import('../src/interaction.ts')
  // 无积压 → done
  assert.deepEqual(typewriterStep({ shown: 5 }, 'abcde'), { shown: 5, done: true })
  // inactive → 直接追平
  assert.deepEqual(typewriterStep({ shown: 2 }, 'abcde', { inactive: true }), { shown: 5, done: true })
  // 空目标 → done
  assert.deepEqual(typewriterStep({ shown: 0 }, ''), { shown: 0, done: true })
})

test('打字机：积压越大揭示越快，最终追平目标且不越界', async () => {
  const { typewriterStep } = await import('../src/interaction.ts')
  const target = 'x'.repeat(1000)
  // 积压 1000（>400）→ 每步 6 字符
  let s = { shown: 0 }
  s = typewriterStep(s, target)
  assert.equal(s.shown, 6)
  // 积压 300（>200）→ 每步 4 字符
  s = { shown: 700 }
  s = typewriterStep(s, target)
  assert.equal(s.shown, 704)
  // 积压 150（>100）→ 每步 2 字符
  s = { shown: 850 }
  s = typewriterStep(s, target)
  assert.equal(s.shown, 852)
  // 积压 50（≤100）→ 每步 1 字符
  s = { shown: 950 }
  s = typewriterStep(s, target)
  assert.equal(s.shown, 951)
  // 最后一步不越界
  s = { shown: 999 }
  assert.deepEqual(typewriterStep(s, target), { shown: 1000, done: true })
  // 目标变短（理论上不出现）→ 对齐不越界
  assert.deepEqual(typewriterStep({ shown: 10 }, 'abc'), { shown: 3, done: true })
})

test('消息增量合并：未变化保持原引用，变化/新增才替换', async () => {
  const { mergeMessages } = await import('../src/interaction.ts')
  const prev = [
    { id: 'a', role: 'user', content: 'hello' },
    { id: 'b', role: 'assistant', content: 'part1', meta: { streaming: true } },
  ]
  // 完全未变 → 返回原数组（引用相等）
  assert.equal(mergeMessages(prev, [
    { id: 'a', role: 'user', content: 'hello' },
    { id: 'b', role: 'assistant', content: 'part1', meta: { streaming: true } },
  ]), prev)
  // 流式增长 → 只有 b 换新对象，a 保持引用
  const next = mergeMessages(prev, [
    { id: 'a', role: 'user', content: 'hello' },
    { id: 'b', role: 'assistant', content: 'part1part2', meta: { streaming: true } },
  ])
  assert.notEqual(next, prev)
  assert.equal(next[0], prev[0])
  assert.notEqual(next[1], prev[1])
  // 新增消息 → 追加且 a/b 引用不变
  const added = mergeMessages(prev, [
    { id: 'a', role: 'user', content: 'hello' },
    { id: 'b', role: 'assistant', content: 'part1', meta: { streaming: true } },
    { id: 'c', role: 'progress', content: 'x' },
  ])
  assert.equal(added[0], prev[0])
  assert.equal(added[1], prev[1])
  assert.equal(added.length, 3)
  // 终稿：content 相同但 meta 去 streaming → 换新对象（停止场景，_ensure_stopped_message）
  const finalized = mergeMessages(prev, [
    { id: 'a', role: 'user', content: 'hello' },
    { id: 'b', role: 'assistant', content: 'part1', meta: {} },
  ])
  assert.notEqual(finalized[1], prev[1])
  // 空 prev → 直接返回 next
  assert.equal(mergeMessages([], [{ id: 'x', role: 'user', content: '1' }]).length, 1)
})

test('智能规划档预期文案不能混入深度推理的 4-6 分钟（Phase 71.1 回归）', async () => {
  const { expectedHintFor, expectedSecondsFor, inferThinkingMode } = await import('../src/interaction.ts')
  // 按实际进度推断模式：guide 流水线绝不显示深度推理的预期
  assert.equal(inferThinkingMode(['正在搜索：成都 旅游攻略'], true), '智能规划')
  assert.match(expectedHintFor('智能规划'), /3-4|2-3/)
  assert.doesNotMatch(expectedHintFor('智能规划'), /4-6|6 分钟/)
  assert.ok(expectedSecondsFor('智能规划') < expectedSecondsFor('深度推理'))
})

// ---------- 标签页未读提醒（Phase 98） ----------

test('未读数拼进标题，0 时还原', () => {
  assert.equal(badgedTitle('17同游 · 一起规划', 0), '17同游 · 一起规划')
  assert.equal(badgedTitle('17同游 · 一起规划', 3), '(3) 17同游 · 一起规划')
})

test('反复加工不会把徽标叠起来', () => {
  // 这是最容易写出来的 bug：拿 document.title 反复加工会变成 `(1) (2) 标题`。
  const base = '17同游'
  const once = badgedTitle(base, 1)
  assert.equal(badgedTitle(once, 2), badgedTitle(base, 2))
  assert.equal(badgedTitle(badgedTitle(badgedTitle(base, 5), 7), 0), base)
})

test('超过上限显示 99+，标题不被大数字撑长', () => {
  assert.equal(badgedTitle('17同游', ATTENTION_BADGE_MAX), `(${ATTENTION_BADGE_MAX}) 17同游`)
  assert.equal(badgedTitle('17同游', ATTENTION_BADGE_MAX + 1), `(${ATTENTION_BADGE_MAX}+) 17同游`)
  assert.equal(badgedTitle('17同游', 99999), `(${ATTENTION_BADGE_MAX}+) 17同游`)
  // 99+ 的产物再进一次也要能剥干净
  assert.equal(badgedTitle(badgedTitle('17同游', 500), 0), '17同游')
})

test('脏输入不炸', () => {
  assert.equal(badgedTitle('', 3), '(3) ')
  assert.equal(badgedTitle('标题', -1), '标题')
  assert.equal(badgedTitle('标题', 1.7), '(1) 标题')
  assert.equal(badgedTitle('标题', NaN), '标题')
})

// ---------- 地点导航链接选择（Phase 100） ----------

const NAV_CN = { amap: 'https://uri.amap.com/cn', apple: 'https://maps.apple.com/cn', domestic: true }
const NAV_JP = {
  amap: 'https://uri.amap.com/jp', apple: 'https://maps.apple.com/jp',
  google: 'https://www.google.com/maps/jp', domestic: false,
}

const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1'
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36'
const WINDOWS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

test('境内地点一律走高德，哪怕在苹果设备上', () => {
  // 这是第一版的 bug：按设备判 /Macintosh/，Mac 用户点国内地点被送进苹果地图。
  // 国内用户装的是高德，POI 与导航体验都对。
  for (const ua of [MAC, IPHONE, ANDROID, WINDOWS]) {
    assert.equal(pickNavUrl(NAV_CN, ua), NAV_CN.amap)
  }
})

test('境外地点在苹果设备上走苹果地图', () => {
  assert.equal(pickNavUrl(NAV_JP, MAC), NAV_JP.apple)
  assert.equal(pickNavUrl(NAV_JP, IPHONE), NAV_JP.apple)
})

test('境外地点在非苹果设备上走谷歌，不能退回高德', () => {
  // 这一格此前落回高德，而高德没有境外数据（线上实测：马来西亚仙本那的酒店点导航，
  // 地图停在北京 + 服务超时）。只修「境内外判定」的话，安卓/Windows 上 bug 依旧。
  assert.equal(pickNavUrl(NAV_JP, ANDROID), NAV_JP.google)
  assert.equal(pickNavUrl(NAV_JP, WINDOWS), NAV_JP.google)
})

test('老数据没有 google 字段时退回苹果，仍不回高德', () => {
  const legacy = { amap: NAV_JP.amap, apple: NAV_JP.apple, domestic: false }
  assert.equal(pickNavUrl(legacy, ANDROID), legacy.apple)
})

test('userAgent 缺失时不炸', () => {
  assert.equal(pickNavUrl(NAV_CN, ''), NAV_CN.amap)
  // 境外 + 认不出设备 → 谷歌（宁可给个通用地图，也不给没数据的高德）
  assert.equal(pickNavUrl(NAV_JP, undefined), NAV_JP.google)
})

// ---------- 对话框图片附件（Phase 105） ----------

const IMG = (id) => ({ id, url: `/api/uploads/${id}` })

test('只发图也能发送——「这是哪，帮我安排」是真实用法', () => {
  assert.equal(canSendComposer('', 0), false)
  assert.equal(canSendComposer('   ', 0), false)
  assert.equal(canSendComposer('', 1), true)
  assert.equal(canSendComposer('杭州三天', 0), true)
})

test('追加图片受上限约束', () => {
  const got = addPendingImages([IMG('a')], [IMG('b'), IMG('c'), IMG('d')], 3)
  assert.deepEqual(got.map((i) => i.id), ['a', 'b', 'c'])
})

test('同一次上传被加两遍要去重', () => {
  // 拖拽会同时触发 drop 与 change，不去重就出现两个一样的缩略图
  const got = addPendingImages([IMG('a')], [IMG('a'), IMG('b')], 4)
  assert.deepEqual(got.map((i) => i.id), ['a', 'b'])
})

test('移除图片不影响其余顺序', () => {
  const got = removePendingImage([IMG('a'), IMG('b'), IMG('c')], 'b')
  assert.deepEqual(got.map((i) => i.id), ['a', 'c'])
})

test('粘贴时只挑图片文件并按剩余额度截断', () => {
  const files = [
    { type: 'text/plain' }, { type: 'image/png' }, { type: 'image/jpeg' }, { type: 'image/webp' },
  ]
  assert.equal(pickImageFiles(files, 2).length, 2)
  assert.equal(pickImageFiles(files, 0).length, 0)
  assert.equal(pickImageFiles([{ type: 'application/pdf' }], 4).length, 0)
})

test('首页只传图不打字也算有效输入', () => {
  // 首页的 unified-start 表单此前只认「文字或链接或(出发地+预算)」，
  // 传了图但没打字会被拦下报「输入一个目的地或攻略链接」——而那正是最自然的用法。
  assert.equal(canSendComposer('', 2), true)
})

// ---------- 记忆时间戳（2026-08-24）----------
// 面板要把「建立 / 更新 / 最后使用」三个时间分开显示，见
// docs/task_plans/记忆时间戳语义修复-2026-08-24.md。

test('formatMemoryAge 分档到年，不像 formatLastSeen 那样在 30 天处塌成「很久以前」', async () => {
  const { formatMemoryAge } = await import('../src/interaction.ts')
  const now = Date.parse('2026-08-24T12:00:00')
  // 造**本地**无时区串（库里就是这种）。用 toISOString() 会先转 UTC，
  // 再被按本地时间解析回来，凭空差一个时区——正是这个函数要防的那个坑。
  const pad = (n) => String(n).padStart(2, '0')
  const ago = (sec) => {
    const d = new Date(now - sec * 1000)
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }

  assert.equal(formatMemoryAge(ago(10), now), '刚刚')
  assert.equal(formatMemoryAge(ago(600), now), '10 分钟前')
  assert.equal(formatMemoryAge(ago(7200), now), '2 小时前')
  assert.equal(formatMemoryAge(ago(86400 * 25), now), '25 天前')
  // 记忆的价值恰恰在于分辨 25 天和 300 天——这是不复用 formatLastSeen 的全部理由
  assert.equal(formatMemoryAge(ago(86400 * 90), now), '3 个月前')
  assert.equal(formatMemoryAge(ago(86400 * 400), now), '1 年前')
})

test('formatMemoryAge 对缺失/非法/未来时间都有确定归宿', async () => {
  const { formatMemoryAge } = await import('../src/interaction.ts')
  const now = Date.parse('2026-08-24T12:00:00')
  assert.equal(formatMemoryAge(null, now), '—')          // last_used_at 可能是 NULL
  assert.equal(formatMemoryAge(undefined, now), '—')     // 老前端/老数据没有这个字段
  assert.equal(formatMemoryAge('不是时间', now), '—')
  // 客户端时钟快于服务端时不能显示「-3 分钟前」
  assert.equal(formatMemoryAge('2026-08-24T12:00:30', now), '刚刚')
})

test('formatMemoryAge 把无时区时间串按本地时间解析（勿加 Z）', async () => {
  const { formatMemoryAge } = await import('../src/interaction.ts')
  // 库里是 timestamp without time zone，psycopg 写入时已转成服务器本地时区（CST）。
  // 当成 UTC 解读会让所有时间凭空「新 8 小时」——2026-07-31 在后端踩过同一个坑。
  const now = Date.parse('2026-08-24T12:00:00')
  assert.equal(formatMemoryAge('2026-08-24T10:00:00', now), '2 小时前')
})

// ---------- Phase 110：剪贴板取图必须同时读 files 与 items ----------

const mkFile = (name, type = 'image/png', size = 10) => ({
  name, type, size, lastModified: 1,
})

test('剪贴板取图：files 为空时必须能从 items 拿到（原来只读 files，这条路静默失效）', async () => {
  const { extractClipboardImages } = await import('../src/interaction.ts')
  const img = mkFile('web.png')
  // 从网页右键「复制图片」的形态：files 空，图片只在 items 里
  const got = extractClipboardImages({
    files: [],
    items: [{ kind: 'file', getAsFile: () => img }],
  }, 4)
  assert.equal(got.length, 1)
  assert.equal(got[0].name, 'web.png')
})

test('剪贴板取图：files 有内容时照常работ（截图/Finder 复制）', async () => {
  const { extractClipboardImages } = await import('../src/interaction.ts')
  const got = extractClipboardImages({ files: [mkFile('shot.png')], items: [] }, 4)
  assert.equal(got.length, 1)
})

test('剪贴板取图：同一张图在两个通道里各出现一次时只取一份', async () => {
  const { extractClipboardImages } = await import('../src/interaction.ts')
  const img = mkFile('dup.png')
  const got = extractClipboardImages({
    files: [img],
    items: [{ kind: 'file', getAsFile: () => img }],
  }, 4)
  assert.equal(got.length, 1, '去重失败会导致同一张图被上传两次')
})

test('剪贴板取图：非图片与非 file 类型一律忽略', async () => {
  const { extractClipboardImages } = await import('../src/interaction.ts')
  const got = extractClipboardImages({
    files: [mkFile('a.pdf', 'application/pdf')],
    items: [
      { kind: 'string', getAsFile: () => null },
      { kind: 'file', getAsFile: () => mkFile('b.txt', 'text/plain') },
    ],
  }, 4)
  assert.deepEqual(got, [])
})

test('剪贴板取图：按剩余额度截断，额度为 0 时不返回', async () => {
  const { extractClipboardImages } = await import('../src/interaction.ts')
  const files = [mkFile('1.png'), mkFile('2.png'), mkFile('3.png')]
  assert.equal(extractClipboardImages({ files, items: [] }, 2).length, 2)
  assert.equal(extractClipboardImages({ files, items: [] }, 0).length, 0)
})

test('剪贴板取图：clipboardData 为 null 不抛异常', async () => {
  const { extractClipboardImages } = await import('../src/interaction.ts')
  assert.deepEqual(extractClipboardImages(null, 4), [])
  assert.deepEqual(extractClipboardImages(undefined, 4), [])
})
