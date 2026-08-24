export const MAX_PROMPT_LENGTH = 4000

export type LayoutMode = 'desktop' | 'mobile'
export type ThemeMode = 'modern' | 'ink'

export function initialThemeMode(storedMode?: string | null): ThemeMode {
  return storedMode === 'ink' ? 'ink' : 'modern'
}

export function initialLayoutMode(
  width: number,
  storedMode?: string | null,
  coarsePointer = false,
): LayoutMode {
  // 真机始终优先移动布局，避免用户曾在大屏选择网页端后，手机继续加载桌面三栏。
  if (width <= 820 || coarsePointer) return 'mobile'
  return storedMode === 'mobile' ? 'mobile' : 'desktop'
}

export interface ComposerKeyLike {
  key: string
  shiftKey: boolean
  isComposing: boolean
}

export function shouldSubmitComposer(event: ComposerKeyLike): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing
}

export function normalizePrompt(value: string): string {
  return value.trim().slice(0, MAX_PROMPT_LENGTH)
}

function clockMinutes(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (hours > 23 || minutes > 59) return null
  return hours * 60 + minutes
}

function formatClock(totalMinutes: number): string {
  const normalized = ((totalMinutes % 1440) + 1440) % 1440
  return `${String(Math.floor(normalized / 60)).padStart(2, '0')}:${String(normalized % 60).padStart(2, '0')}`
}

/** 协同行程事件卡统一显示时间段，不拿单个开始时间冒充完整日程。 */
export function formatTripTimeRange(startTime: string, stayMin: number | null, nextStartTime = ''): string {
  const start = clockMinutes(startTime)
  if (start === null) return '时间待定'
  if (stayMin !== null && Number.isFinite(stayMin) && stayMin > 0) {
    const end = start + stayMin
    const dayPrefix = end >= 1440 ? '次日 ' : ''
    return `${formatClock(start)} – ${dayPrefix}${formatClock(end)}`
  }
  const next = clockMinutes(nextStartTime)
  return `${formatClock(start)} – ${next === null ? '待定' : formatClock(next)}`
}

export interface GuideHeading {
  level: 2 | 3
  title: string
  id: string
}

export function headingAnchor(title: string): string {
  const normalized = title
    .toLowerCase()
    .replace(/[*_`~]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
  return `guide-${normalized || 'section'}`
}

export function extractGuideHeadings(markdown: string): GuideHeading[] {
  return markdown
    .split('\n')
    .map((line) => /^(#{2,3})\s+(.+?)\s*$/.exec(line))
    .filter((match): match is RegExpExecArray => match !== null)
    .slice(0, 12)
    .map((match) => ({
      level: match[1].length as 2 | 3,
      title: match[2].replace(/[*_`~]/g, '').trim(),
      id: headingAnchor(match[2]),
    }))
}

/**
 * 渲染前的 Markdown 修补（2026-07 走查 P2-c）。
 *
 * CommonMark 定界符规则：`**` 的关闭侧前面是 CJK 标点、后面紧跟文字时不构成
 * right-flanking（如 `，**烤匠（春熙路店）**解决午餐`），星号原样漏进正文——中文里
 * 标点紧邻加粗是高频写法。修法：在 `**…**` 内侧垫零宽空格（U+200B，非空白非标点），
 * 让定界符两侧恒成立；渲染完全不可见。
 * 注意配套：remark-gfm 需以 `{ singleTilde: false }` 挂载（`¥400~600` 的两个 `~`
 * 会互相配成删除线把中间吞掉），见各 ReactMarkdown 挂载点。
 */
export function prepareMarkdown(markdown: string): string {
  return markdown.replace(/\*\*([^*\n]+?)\*\*/g, '**\u200b$1\u200b**')
}

export const THINKING_STAGES = [
  { id: 'understand', label: '理解需求' },
  { id: 'research', label: '搜集资料' },
  { id: 'organize', label: '整理方案' },
  { id: 'generate', label: '生成内容' },
  { id: 'review', label: '检查优化' },
] as const

const THINKING_STAGE_PATTERNS: ReadonlyArray<RegExp> = [
  /理解|解析|需求|偏好|记忆|判断|分类|正在处理/,
  /搜索|搜集|检索|浏览|读取|抓取|来源|网页|高德|小红书|携程|酒店|天气|实时|排队|浏览器|补充资料|打开/,
  /整理|汇总|综合|路线|规划|提取|定位|排序|结构化|计算|准备/,
  /生成|撰写|输出|回答|成稿|终稿|攻略|报告/,
  /自检|反思|检查|优化|重排|修订|重写|复核|校验/,
]

/**
 * 只保留进度文案里「描述动作」的那部分，丢掉冒号后的查询词和括号里的抓取内容。
 *
 * 踩坑（Phase 71.1）：进度改成携带发现内容后，「📕 正在小红书搜索：六安 旅游攻略 美食」
 * 里的「攻略」命中了「生成内容」的正则，阶段直接跳到 4/5，而实际还在搜集资料。
 * 阶段推断只能看**我们自己写的动作词**，绝不能被用户输入/抓回来的内容左右。
 */
export function stageSignal(progressText: string): string {
  let t = progressText || ''
  const cut = t.search(/[：:]/)
  if (cut > 0) t = t.slice(0, cut)
  const paren = t.search(/[（(]/)
  if (paren > 0) t = t.slice(0, paren)
  return t.trim()
}

export function inferThinkingStage(
  rawText: string,
  options: { streaming?: boolean; reasoning?: boolean } = {},
): number {
  const progressText = stageSignal(rawText)
  if (/进入深度研究模式|理解你的旅行需求/.test(progressText)) return 0
  // 后面的阶段优先，避免「正在检查并重新生成」被较早的“生成”误判。
  for (let index = THINKING_STAGE_PATTERNS.length - 1; index >= 0; index -= 1) {
    if (THINKING_STAGE_PATTERNS[index].test(progressText)) return index
  }
  if (options.streaming) return 3
  if (options.reasoning) return 2
  return 0
}

export function inferThinkingProgress(
  progressTexts: readonly string[],
  options: { streaming?: boolean; reasoning?: boolean } = {},
): number {
  return progressTexts.reduce(
    (furthest, text) => Math.max(furthest, inferThinkingStage(text)),
    inferThinkingStage('', options),
  )
}

export function formatThinkingElapsed(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds))
  const seconds = safe % 60
  const minutes = Math.floor(safe / 60) % 60
  const hours = Math.floor(safe / 3600)
  const mm = String(minutes).padStart(2, '0')
  const ss = String(seconds).padStart(2, '0')
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`
}

// ---------- 等待预期管理（Phase 71） ----------
// 用户放弃等待的主因不是「久」，而是「不知道还要多久」+「以为卡死了」。
// 这里给每种任务一个预计时长，让进度条对照预期走，而不是只显示一个越滚越大的秒数。

export const THINKING_EXPECTED_SEC: Record<string, number> = {
  深度推理: 330, // 实测 4-6 分钟
  手账生成: 75,
  // 2026-07 走查实测：首轮（含小红书逐篇抓取）首字 ~4 分钟。此前写 140s 导致 1 分半就显示
  // 「快好了」，之后还要等 2 分半——过度承诺比慢本身更伤信任。宁可报高，提前完成是惊喜。
  智能规划: 260,
}

export const THINKING_EXPECTED_HINT: Record<string, string> = {
  深度推理: '通常 4-6 分钟',
  手账生成: '通常 1 分钟出头',
  智能规划: '通常 3-4 分钟',
}

export function expectedSecondsFor(mode: string): number {
  return THINKING_EXPECTED_SEC[mode] ?? THINKING_EXPECTED_SEC.智能规划
}

export function expectedHintFor(mode: string): string {
  return THINKING_EXPECTED_HINT[mode] ?? THINKING_EXPECTED_HINT.智能规划
}

/** 进度比例 0-1。超出预期后不回退也不满格，缓慢逼近 1（还在动=还活着）。 */
export function thinkingProgressRatio(elapsedSec: number, expectedSec: number): number {
  const e = Math.max(0, elapsedSec)
  const exp = Math.max(1, expectedSec)
  if (e <= exp) return Math.min(0.92, e / exp)
  // 超时后每多等一个预期时长，把剩下的差距吃掉一半，永远不到 100%
  const over = (e - exp) / exp
  return Math.min(0.99, 0.92 + 0.07 * (1 - Math.exp(-over)))
}

/** 等待期的安抚文案：正常区间给预期，超时给「比平时久」而不是「可能卡死」。 */
export function waitReassurance(elapsedSec: number, mode: string): string {
  const exp = expectedSecondsFor(mode)
  if (elapsedSec < exp * 0.6) return `${expectedHintFor(mode)}，可以关掉页面，完成后在历史里查看。`
  if (elapsedSec < exp) return '快好了，正在把资料整理成完整答案…'
  if (elapsedSec < exp * 2) return '比平时久一点，说明查到的资料比较多，仍在正常推进。'
  return '这次耗时偏长，任务仍在服务器上跑；你可以关掉页面稍后回来，也可以停止重来。'
}


/**
 * 任务模式按**实际发生的事**推断，而不是 composer 上的开关。
 *
 * 踩坑（Phase 71.1）：开着「深度推理」问一个明确的规划问题，后端按设计仍走攻略流水线
 * （约 2 分钟），UI 却因为读开关而显示「深度推理 · 通常 4-6 分钟」，进度条永远走不满。
 * 开关表达的是意愿，进度消息才是事实。
 */
export function inferThinkingMode(progressTexts: readonly string[], streaming = false): string {
  const all = progressTexts.join('\n')
  if (/手账|海报/.test(all)) return '手账生成'
  if (/进入深度研究模式/.test(all)) return '深度推理'
  if (!all.trim() && !streaming) return '智能规划'
  return '智能规划'
}


/** 距底部小于该像素数视为「用户在追最新内容」。 */
export const NEAR_BOTTOM_PX = 120

export interface ScrollMetrics {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

export function isNearBottom(m: ScrollMetrics, threshold = NEAR_BOTTOM_PX): boolean {
  return m.scrollHeight - m.scrollTop - m.clientHeight < threshold
}

/**
 * 生成期间要不要跟随滚动到底部。
 *
 * 踩坑（Phase 72）：流式攻略每 1.5s 轮询刷新一次消息，原实现无条件
 * `scrollIntoView`，用户往上翻看前文会被立刻拽回底部，等于没法读。
 * 规则：只有贴着底部才跟随；用户一往上滚就脱离，直到自己滚回底部或点「回到最新」。
 */
export function shouldFollowBottom(
  m: ScrollMetrics,
  scrolledUp = false,
  threshold = NEAR_BOTTOM_PX,
): boolean {
  if (scrolledUp) return false
  return isNearBottom(m, threshold)
}


/** 相对时间文案（Phase 73 在线状态）。`iso` 必须带时区偏移，否则会被按本地时区解读。 */
export function formatLastSeen(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return '从未活跃'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '从未活跃'
  const sec = Math.floor((nowMs - t) / 1000)
  if (sec < 0) return '刚刚'          // 客户端时钟略快于服务端时不显示「-3 分钟前」
  if (sec < 60) return '刚刚'
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`
  if (sec < 86400 * 30) return `${Math.floor(sec / 86400)} 天前`
  return '很久以前'
}


// ---------- 记忆时间戳（2026-08-24）----------
// 记忆面板要把三个时间分开显示：建立 / 更新（内容真的变过）/ 最后使用（被注入进 prompt）。
// 不复用 formatLastSeen —— 它 30 天以上一律「很久以前」，而记忆的价值恰恰在于分辨
// 25 天和 300 天：「这条建立很久、最近没被用过」是用户该看到的信号。
// naive 时间串按**本地时间**解析（勿加 Z）：库里是 timestamp without time zone，
// psycopg 写入时已转成服务器本地时区（CST）——沿用会话列表既有约定。
export function formatMemoryAge(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '—'
  const sec = Math.floor((nowMs - t) / 1000)
  if (sec < 60) return '刚刚'                    // 含客户端时钟略快于服务端的负数
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`
  const days = Math.floor(sec / 86400)
  if (days < 30) return `${days} 天前`
  if (days < 365) return `${Math.floor(days / 30)} 个月前`
  return `${Math.floor(days / 365)} 年前`
}

// ---------- Phase 75：新用户开口率 ----------
// 08-04 那批新用户 12 个里 4 个注册后一个字没问就走了。提问的 8 个全部拿到了完整攻略，
// 所以门槛在**开口**，不在产出：首页示例写死成都（用户全是合肥/武汉的），
// 输入框又要求一次说清完整需求（已提问用户首问平均只有 29 字，说明没人愿意这么打字）。

export interface StarterChip {
  icon: string
  label: string
  description: string
  meta: string
  text: string
  deep?: boolean
}

const TRENDING_ICONS = ['🏝️', '⛰️', '🏮', '🌊', '🍜', '🚗']

/**
 * 用平台最近的真实目的地生成示例。
 *
 * 这是**社会证明 + 本地化**两件事一起做：新用户没有个人数据，但「别人最近在查什么」
 * 天然贴近同一批人的地理位置（本批用户高度集中在合肥/武汉，热门榜自然是平潭、武功山、
 * 皖南这些，而不是写死的成都）。
 */
export function buildTrendingChips(
  trending: readonly string[],
  homeCity = '',
  limit = 4,
): StarterChip[] {
  return trending.slice(0, limit).map((city, i) => ({
    icon: TRENDING_ICONS[i % TRENDING_ICONS.length],
    label: `${city}怎么玩`,
    description: homeCity ? `从${homeCity}出发的玩法与路线` : '路线、美食与住宿一次排好',
    meta: '最近很多人在查',
    text: homeCity
      ? `我想从${homeCity}出发去${city}玩3天，帮我排个行程`
      : `我想去${city}玩3天，帮我排个行程`,
  }))
}

/**
 * 是否像「只有一个目的地」的短输入。
 *
 * 只有这种输入才套旅行预演模板；完整问题直接交给后端 direct/guide/research 路由，避免把
 * 「日本签证怎么办」误当成一个叫“日本签证怎么办”的目的地。
 */
export function isCompactDestinationIdea(value: string): boolean {
  const text = (value || '').trim()
  if (!text || text.length > 12 || /[？?！!。；;，,\n]/.test(text)) return false
  if (/(怎么|如何|是否|能不能|要不要|多少钱|签证|酒店|机票|天气|推荐|帮我|想去|攻略|路线|预算)/.test(text)) return false
  return /^[\p{L}\p{N}·\-—\s]+$/u.test(text)
}

export interface QuickPick {
  from: string
  days: string
  who: string
}

/**
 * 「不知道去哪」三下起步：把点选拼成一句完整的话。
 *
 * 关键是**即使只点了一项也要能成句**——强制三项都选等于换了种方式要求用户想清楚，
 * 那就没解决原来的问题。
 */
export function buildQuickPrompt(pick: Partial<QuickPick>): string {
  const from = (pick.from || '').trim()
  const days = (pick.days || '').trim()
  const who = (pick.who || '').trim()
  if (!from && !days && !who) return ''
  const parts: string[] = []
  if (from) parts.push(`我从${from}出发`)
  if (days) parts.push(days === '不确定' ? '时间还没定' : `打算玩${days}`)
  if (who && who !== '不确定') parts.push(who)
  return `${parts.join('，')}，还没想好去哪，帮我推荐几个合适的目的地并说明理由`
}

export interface JourneyPreviewInput {
  destination: string
  origin?: string
  days?: string
  pace?: string
  companion?: string
  budget?: string
  wish?: string
}

export interface InspirationImportInput {
  urls: readonly string[]
  origin?: string
  days?: string
  note?: string
}

export interface BudgetRouletteInput {
  origin: string
  budget: string
  days?: string
  companion?: string
  vibe?: string
}

function cleanPromptPart(value?: string): string {
  return (value || '').trim().replace(/\s+/g, ' ')
}

/** 只允许浏览器链路能够安全导航的公开 HTTP(S) 灵感链接。 */
export function isPublicInspirationUrl(value: string): boolean {
  try {
    const url = new URL(value.trim())
    return (url.protocol === 'http:' || url.protocol === 'https:') && !!url.hostname
  } catch {
    return false
  }
}

/**
 * 兼容小红书/公众号常见的「标题 + 链接 + 复制口令」分享文本，只提取其中的公开链接。
 * 去重并限制 5 条，避免一次把无限 URL 塞进浏览器任务。
 */
export function extractPublicInspirationUrls(value: string, limit = 5): string[] {
  const matches = value.match(/https?:\/\/[^\s，,；;]+/gi) || []
  return [...new Set(matches.map((url) => url.replace(/[。.!！?？)）\]】]+$/g, '')))]
    .filter(isPublicInspirationUrl)
    .slice(0, limit)
}

/** 把少量选择翻译成强调“可执行 + 可预演”的真实规划请求。 */
export function buildJourneyPreviewPrompt(input: JourneyPreviewInput): string {
  const destination = cleanPromptPart(input.destination)
  if (!destination) return ''
  const origin = cleanPromptPart(input.origin)
  const days = cleanPromptPart(input.days)
  const pace = cleanPromptPart(input.pace)
  const companion = cleanPromptPart(input.companion)
  const budget = cleanPromptPart(input.budget)
  const wish = cleanPromptPart(input.wish)
  const facts = [
    origin ? `从${origin}出发` : '',
    days ? `行程${days}` : '天数请给出合理假设并明确标注',
    companion || '',
    pace ? `希望${pace}` : '',
    budget ? `总预算约${budget}元` : '预算尚未确定',
    wish ? `最期待：${wish}` : '',
  ].filter(Boolean).join('，')
  return `请为我制作一份「${destination}旅行预演」。${facts}。\n` +
    '不要只写传统攻略：先给一个10秒速览，再按天给出可执行时间轴；每一天标出预计步行/交通、' +
    '最值得期待的瞬间、容易疲劳或赶路的地方、花费区间，以及下雨/闭馆时的替代方案。' +
    '路线按地理位置就近安排，价格和营业信息注明数据时间与不确定性。最后像行程体检一样指出' +
    '这趟旅行最可能后悔的一个安排，并给出更松弛的改法。'
}

/** 把收藏链接变成浏览器 Agent 可执行的“提取 → 校验 → 排路”任务。 */
export function buildInspirationImportPrompt(input: InspirationImportInput): string {
  const urls = input.urls.filter(isPublicInspirationUrl).slice(0, 5)
  if (!urls.length) return ''
  const origin = cleanPromptPart(input.origin)
  const days = cleanPromptPart(input.days)
  const note = cleanPromptPart(input.note)
  const constraints = [
    origin ? `我从${origin}出发` : '',
    days ? `计划玩${days}` : '天数还没定',
    note ? `我的取舍是：${note}` : '',
  ].filter(Boolean).join('，')
  return '请把下面这些公开旅行灵感链接炼成一份真正能出发的行程：\n' +
    `${urls.map((url, index) => `${index + 1}. ${url}`).join('\n')}\n` +
    `${constraints || '出发地和天数尚未确定，请先从内容判断并标注你的假设。'}\n` +
    '请实际读取链接内容，提取里面出现的景点、餐厅、酒店和拍照点；合并重名地点，剔除无法核实或' +
    '明显绕路的推荐，并说明哪些内容没有成功读取。随后按距离排成逐日路线，补上交通时间、预约要求、' +
    '预算和雨天备选。不要把链接标题改写成一篇泛泛攻略。'
}

/** 在硬预算内反推目的地；该 prompt 应由调用方以 deep_reasoning=true 发送。 */
export function buildBudgetRoulettePrompt(input: BudgetRouletteInput): string {
  const origin = cleanPromptPart(input.origin)
  const budget = cleanPromptPart(input.budget)
  if (!origin || !budget) return ''
  const days = cleanPromptPart(input.days)
  const companion = cleanPromptPart(input.companion)
  const vibe = cleanPromptPart(input.vibe)
  const extras = [
    days ? `玩${days}` : '天数可以在推荐中给出',
    companion || '',
    vibe ? `偏爱${vibe}` : '',
  ].filter(Boolean).join('，')
  return `我从${origin}出发，总预算上限${budget}元，${extras}。请做一次「预算旅行盲盒」：` +
    '基于现实交通成本和当地消费给我3个差异明显的目的地，分别说明适配度、预算拆分、最值体验和' +
    '主要妥协；不能为了卡预算而漏掉往返大交通。最后选出一个首选，给出可执行的每日路线和至少' +
    '一个预算超支时的降级方案。所有价格注明查询时间或估算口径。'
}

// ---------- 流式丝滑（2026-08-13）：打字机平滑 + 消息增量合并 ----------

/** 打字机动画 tick 间隔（ms）。40ms ≈ 每秒 25 步，肉眼连续。 */
export const TYPEWRITER_TICK_MS = 40
/** 无积压时每 tick 揭示的字符数（25 字/s 起步）。 */
export const TYPEWRITER_BASE_CHARS = 1
/** 积压超过该字符数升一档速（×2）；再翻倍再升（×4），超过 4 倍封顶。 */
export const TYPEWRITER_FAST_BACKLOG = 100
/** 最快档每 tick 揭示的字符数（150 字/s，追平模型输出速率）。 */
export const TYPEWRITER_MAX_CHARS = 6

export interface TypewriterStep {
  shown: number
  done: boolean
}

/**
 * 打字机一步（纯函数）：把已揭示字符数 `state.shown` 向 `target` 推进。
 *
 * - 积压（target 长度 - shown）越大揭示越快（1 → 2 → 4 → 6 字符/tick），
 *   保证播放不落后于后端到达速率；无积压立即 done。
 * - `inactive=true`（流式终稿/页面隐藏/用户已上滚）直接追平全量，零延迟收尾——
 *   终稿瞬间不该再让用户等打字机播完。
 */
export function typewriterStep(
  state: { shown: number },
  target: string,
  opts: { inactive?: boolean } = {},
): TypewriterStep {
  const len = target.length
  if (opts.inactive || state.shown >= len) return { shown: len, done: true }
  const backlog = len - state.shown
  const perTick =
    backlog > TYPEWRITER_FAST_BACKLOG * 4 ? TYPEWRITER_MAX_CHARS
    : backlog > TYPEWRITER_FAST_BACKLOG * 2 ? TYPEWRITER_BASE_CHARS * 4
    : backlog > TYPEWRITER_FAST_BACKLOG ? TYPEWRITER_BASE_CHARS * 2
    : TYPEWRITER_BASE_CHARS
  const nextShown = Math.min(len, state.shown + perTick)
  return { shown: nextShown, done: nextShown >= len }
}

/** 轮询消息的最小结构（与 Home.tsx 的 Msg 结构兼容，避免跨文件耦合）。 */
export interface MsgLike {
  id: string
  role: string
  content: string
  reasoning?: string | null
  meta?: Record<string, unknown> | null
}

function msgSignature(m: MsgLike): string {
  const metaLen = m.meta ? JSON.stringify(m.meta).length : 0
  return `${m.role}|${m.content.length}|${m.content.slice(-64)}|${m.reasoning?.length ?? 0}|${metaLen}`
}

/**
 * 消息增量合并（纯函数）：next 相对 prev 只替换**有变化**的消息，
 * 未变化的消息保持原对象引用 —— React.memo 依赖引用相等跳过重渲染，
 * 消除「每次轮询全量重渲染 → react-markdown 全量重解析」的卡顿。
 *
 * 签名比对：role + content 长度/尾串 + reasoning 长度 + meta 序列化长度。
 * 流式消息 content 持续变长必然命中；终稿/停止的 meta 变化也会命中
 * （content 可能不变，见 orchestrator._ensure_stopped_message）。
 */
export function mergeMessages<T extends MsgLike>(prev: T[], next: T[]): T[] {
  if (prev.length === 0) return next
  const prevByKey = new Map(prev.map((m) => [m.id, m]))
  const prevSig = new Map(prev.map((m) => [m.id, msgSignature(m)]))
  let changed = false
  const out = next.map((m) => {
    const old = prevByKey.get(m.id)
    if (old && prevSig.get(m.id) === msgSignature(m)) return old
    changed = true
    return m
  })
  return changed || out.length !== prev.length ? out : prev
}

// ---------- 标签页未读提醒（Phase 98） ----------
//
// 国内收不到 Web Push（Chrome/Edge 走 FCM，服务器和用户浏览器都连不上 fcm.googleapis.com，
// 已实测），所以「人不在这个标签页时叫住他」只能靠浏览器本身就会显示的东西：标题和 favicon。
// 覆盖的是最高频的真实场景——人挂着页面在干别的事。

/** 未读徽标上限。超过就显示 99+，避免标题被一个大数字撑长。 */
export const ATTENTION_BADGE_MAX = 99

/**
 * 把未读数拼进标签页标题。
 *
 * **必须传原始标题**（组件挂载时捕获一次），不能拿 `document.title` 反复加工——
 * 那样会叠成 `(1) (2) 17同游`。这也是把它写成纯函数的原因：叠加是最容易写出来的 bug，
 * 而它有一条一句话就能测的性质：`badgedTitle(badgedTitle(t, 1), 2) === badgedTitle(t, 2)`。
 */
export function badgedTitle(baseTitle: string, unread: number): string {
  const base = (baseTitle || '').replace(/^\(\d+\+?\)\s*/, '')
  const count = Math.max(0, Math.floor(unread || 0))
  if (count <= 0) return base
  const shown = count > ATTENTION_BADGE_MAX ? `${ATTENTION_BADGE_MAX}+` : String(count)
  return `(${shown}) ${base}`
}

// ---------- 地点导航链接选择（Phase 100） ----------

export interface NavLinks {
  amap: string
  apple: string
  /** 境外 + 非苹果设备用它。老数据可能没有这个字段，取用时要兜底 */
  google?: string
  domestic: boolean
}

/**
 * 选用哪个地图打开这个地点。
 *
 * **按「地点在哪」分流，不是按「用户拿什么设备」**——这是第一版写错的地方：
 * 原本判 `/iPhone|iPad|iPod|Macintosh/`，结果 Mac 用户点国内地点被送进苹果地图。
 * 境内地点无论什么设备都该开高德（国内用户装的是它，POI 与导航体验都对），
 * 只有境外才轮到苹果/谷歌（高德境外数据弱）。
 */
export function pickNavUrl(nav: NavLinks, userAgent: string): string {
  // 选哪个地图取决于「地点在哪」，其次才是「设备是什么」：
  // 境内一律高德（国内用户装的就是它，POI 与导航体验都对，苹果设备也一样）；
  // 境外分设备——苹果设备开苹果地图，其余开谷歌。
  // ⚠️ 境外 + 非苹果这一格此前落回高德，而高德没有境外数据（线上实测：马来西亚仙本那
  // 的酒店点导航，地图停在北京 + 服务超时）。判对境内外只修好了苹果设备那一半。
  if (nav.domestic) return nav.amap
  const isApple = /iPhone|iPad|iPod|Macintosh/.test(userAgent || '')
  return isApple ? nav.apple : (nav.google || nav.apple)
}

// ---------- 对话框图片附件（Phase 105） ----------

/** 单条消息最多带几张图。与后端 settings.vision_max_user_images 保持一致 */
export const MAX_COMPOSER_IMAGES = 4

export interface PendingImage {
  id: string
  url: string
}

/** 能不能发送：有文字**或**有图就行——只发图（「这是哪，帮我安排」）是真实用法。 */
export function canSendComposer(text: string, imageCount: number): boolean {
  return text.trim().length > 0 || imageCount > 0
}

/**
 * 追加待发图片并按上限截断。
 *
 * 去重按 id：同一张图重复上传会拿到不同 id（服务端每次新建 upload 行），
 * 这里去的是「同一次上传被加两遍」（拖拽同时触发 drop 与 change）。
 */
export function addPendingImages(
  existing: PendingImage[],
  incoming: PendingImage[],
  max: number,
): PendingImage[] {
  const seen = new Set(existing.map((i) => i.id))
  const merged = [...existing]
  for (const img of incoming) {
    if (!img?.id || seen.has(img.id)) continue
    if (merged.length >= max) break
    seen.add(img.id)
    merged.push(img)
  }
  return merged
}

export function removePendingImage(list: PendingImage[], id: string): PendingImage[] {
  return list.filter((i) => i.id !== id)
}

/** 从粘贴/拖拽事件里挑出图片文件，按剩余额度截断。 */
export function pickImageFiles(files: File[], remaining: number): File[] {
  return files.filter((f) => f && f.type.startsWith('image/')).slice(0, Math.max(0, remaining))
}
