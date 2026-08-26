/**
 * 好友分享版旅行攻略业务编排层
 * 将 Trip 原始数据转换为结构化 ShareGuideSchema
 */

import type {
  ShareGuideSchema,
  CoverSection,
  OverviewSection,
  OverviewTimelineDay,
  DaySection,
  DayHighlight,
  EventCard,
  Badge,
  TipCard,
  FoodSection,
  RestaurantCard,
  StaySection,
  HotelCard,
  TipsSection,
  TipCategory,
  PackingSection,
  BudgetSection,
} from './shareGuideSchema'
import {
  resolveDisplayName,
  cleanNullable,
  stripMarkdown,
  stripSourceMetadata,
  dedupeTexts,
  textSimilarity,
  validateDuration,
  anonymizePackedStatus,
  atomizeTip,
  isActionLabel,
  type AtomicTip,
} from './contentCleaner'

// 类型定义（从 Trips.tsx 导入的类型，这里先声明，后续会统一）
type TripDetail = {
  id: string
  title: string
  destination: string
  start_date: string
  days: number
  stops: TripStop[]
  day_titles?: Record<number, string>
}

type TripStop = {
  id: string
  day: number
  order_no: number
  name: string
  note: string
  location: string
  start_time: string
  transport: string
  ticket_price: number | null
  tags: string[]
}

type FoodItem = {
  id: string
  name: string
  city: string
  category: string
  meal_type: string
  price: number | null
  rating: number | null
  address: string
  recommend_food: string[]
  business_hours: string
  note: string
  day: number | null
  is_favorite: boolean
  checked_in: boolean
}

type TipItem = {
  id: string
  content: string
  level: string
}

type PackingData = {
  members: string[]
  items: Array<{
    name: string
    category: string
    states: Record<string, string>
  }>
}

type Expense = {
  title: string
  category: string
  amount: number
  payer: string
}

export type ComposeOptions = {
  includePacking?: boolean
  includeBudget?: boolean
  memberCount?: number              // 用于计算人均预算
  exportMode?: 'friend' | 'personal' // 好友分享版 | 个人完整版（默认 friend）
}

/**
 * 主函数：将 Trip 数据编排为 ShareGuideSchema
 */
export function composeShareGuide(
  trip: TripDetail,
  foods: FoodItem[],
  tips: TipItem[],
  packing: PackingData,
  expenses: Expense[],
  options: ComposeOptions = {}
): ShareGuideSchema {
  const { includePacking = false, includeBudget = true, memberCount, exportMode = 'friend' } = options

  // 酒店合并只算一次，overview 复用（避免重复跑 mergeExportHotelStays）
  const stays = composeStays(trip)

  return {
    cover: composeCover(trip),
    overview: composeOverview(trip, foods, stays),
    days: composeDays(trip),
    foods: composeFoods(foods),
    stays,
    tips: composeTips(tips),
    ...(includePacking ? { packing: composePacking(packing, exportMode) } : {}),
    ...(includeBudget ? { budget: composeBudget(expenses, memberCount, exportMode) } : {}),
  }
}

// ===== 封面 =====
function composeCover(trip: TripDetail): CoverSection {
  const cityLine = exportCoverTitle(trip)          // "吉隆坡 · 仙本那 · 亚庇"
  const region = inferRegion(`${trip.title} ${trip.destination}`)
  const nights = Math.max(0, (trip.days || 1) - 1)
  // 主标题：地区名 + 天数（PRD 第 8 条），如"马来西亚 8天7晚"；地区未知时退回城市串
  const regionCn = regionChineseName(region)
  const title = regionCn ? `${regionCn} ${trip.days}天${nights}晚` : cityLine
  // 副标题：城市串（主标题已是地区时）或完整旅行主题
  const subtitle = regionCn ? cityLine : extractSubtitle(trip)
  const dateRange = formatExportDateRange(trip)
  const tags = generateTripTags(trip)

  return {
    type: 'cover',
    title,
    subtitle,
    region,
    dateRange,
    days: trip.days || 1,
    nights,
    tags,
  }
}

function exportCoverTitle(trip: TripDetail): string {
  const source = trip.destination || trip.title || '协同行程'
  return source
    .replace(/\s*\d+\s*天\s*\d*\s*晚.*$/, '')
    .replace(/[+、，,]/g, ' · ')
    .replace(/\s*·\s*/g, ' · ')
    .trim() || '协同行程'
}

function regionChineseName(region: string): string {
  const map: Record<string, string> = {
    MALAYSIA: '马来西亚',
    THAILAND: '泰国',
    JAPAN: '日本',
    VIETNAM: '越南',
  }
  return map[region] || ''
}

function extractSubtitle(trip: TripDetail): string | undefined {
  // 用完整旅行主题（去掉出发地前缀和天数），不做贪婪截断
  const title = (trip.title || '').trim()
  if (!title) return undefined
  const cleaned = title
    .replace(/^[^·]+·\s*/, '')            // 去"南京出发·"前缀
    .replace(/\d+\s*天\s*\d*\s*晚/g, '')  // 去"8天7晚"
    .trim()
  return cleaned || undefined
}

function inferRegion(title: string): string {
  const text = title.toLowerCase()
  if (/malaysia|马来|吉隆坡|仙本那|亚庇|kl|kuala|semporna|sabah/i.test(text)) return 'MALAYSIA'
  if (/thailand|泰国|曼谷|普吉|清迈|bangkok|phuket|chiang mai/i.test(text)) return 'THAILAND'
  if (/japan|日本|东京|大阪|京都|tokyo|osaka|kyoto/i.test(text)) return 'JAPAN'
  if (/vietnam|越南|河内|胡志明|hanoi|ho chi minh/i.test(text)) return 'VIETNAM'
  return 'TRAVEL'
}

function generateTripTags(trip: TripDetail): string[] {
  const tags: string[] = []
  const text = `${trip.title} ${trip.destination}`.toLowerCase()

  if (/海岛|island|beach/i.test(text)) tags.push('海岛')
  if (/浮潜|snorkel|dive|潜水/i.test(text)) tags.push('浮潜')
  if (/跳岛|island hopping/i.test(text)) tags.push('跳岛')
  if (/度假|vacation|resort/i.test(text)) tags.push('度假')
  if (/马来|malaysia/i.test(text)) tags.push('马来西亚')
  if (/泰国|thailand/i.test(text)) tags.push('泰国')
  if (/日本|japan/i.test(text)) tags.push('日本')
  if (/美食|food|餐厅/i.test(text)) tags.push('美食')
  if (/购物|shopping/i.test(text)) tags.push('购物')
  if (/亲子|family|儿童/i.test(text)) tags.push('亲子')

  return tags.slice(0, 5)
}

function formatExportDateRange(trip: TripDetail): string {
  if (trip.start_date) {
    const start = new Date(`${trip.start_date}T00:00:00`)
    if (!Number.isNaN(start.getTime())) {
      const end = new Date(start)
      end.setDate(start.getDate() + Math.max(1, trip.days) - 1)
      const fmt = (date: Date) =>
        `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}.${String(date.getDate()).padStart(2, '0')}`
      return `${fmt(start)} — ${fmt(end)}`
    }
  }
  const titleRange = trip.title.match(/(\d{1,2})[./月](\d{1,2})(?:日)?\s*[—–-]\s*(\d{1,2})[./月](\d{1,2})/)
  if (!titleRange) return '日期待定'
  return `${titleRange[1]}.${titleRange[2]} — ${titleRange[3]}.${titleRange[4]}`
}

// ===== 总览 =====
function composeOverview(trip: TripDetail, foods: FoodItem[], stays: StaySection): OverviewSection {
  const timeline = buildOverviewTimeline(trip)
  const cities = extractCities(trip)
  // 酒店数量从 merge 后的列表统计（PRD Bug 5），复用已算好的 stays，不重复合并
  const hotels = stays.hotels.length
  const highlights = extractHighlights(trip, foods)

  return {
    type: 'overview',
    timeline,
    stats: {
      totalDays: trip.days,
      cities,
      hotels,
      highlights,
    },
  }
}

function buildOverviewTimeline(trip: TripDetail): OverviewTimelineDay[] {
  return Array.from({ length: trip.days }, (_, i) => i + 1).map((day) => {
    const date = displayTripDayDate(trip, day)
    const weekday = exportWeekLabel(trip, day)
    const dayTitle = trip.day_titles?.[day] || ''
    const { routeTitle } = splitExportDayTitle(dayTitle, day)
    const city = extractCityFromDayTitle(dayTitle) || extractCityFromStops(trip, day)
    const hotel = findDayHotel(trip, day)

    return {
      day,
      date: date.replace(/^\d{4}年/, '').replace(/日.*$/, ''),  // "10.01"
      weekday,
      city: cleanNullable(city) || '',  // 缺失时不填"待定"，直接空
      theme: routeTitle || `第 ${day} 天`,
      hotel: hotel || '—',
    }
  })
}

function extractCities(trip: TripDetail): string[] {
  const cities = new Set<string>()
  trip.stops.forEach((stop) => {
    const city = extractCityFromLocation(stop.location || stop.note || stop.name)
    if (city) cities.add(city)
  })
  Object.values(trip.day_titles || {}).forEach((title) => {
    const city = extractCityFromDayTitle(title)
    if (city) cities.add(city)
  })
  return Array.from(cities).slice(0, 5)
}

function extractCityFromLocation(text: string): string {
  const known = ['吉隆坡', '仙本那', '亚庇', '曼谷', '普吉', '清迈', '东京', '大阪', '京都', '胡志明', '河内']
  return known.find((city) => text.includes(city)) || ''
}

function extractCityFromDayTitle(title: string): string {
  return extractCityFromLocation(title)
}

function extractCityFromStops(trip: TripDetail, day: number): string {
  const dayStops = trip.stops.filter((s) => s.day === day)
  for (const stop of dayStops) {
    const city = extractCityFromLocation(stop.location || stop.note || stop.name)
    if (city) return city
  }
  return ''
}

function findDayHotel(trip: TripDetail, day: number): string {
  const stay = trip.stops.find((s) => s.day === day && isStayStop(s))
  if (stay) return normalizeExportStopName(stay.name)
  return ''
}

function extractHighlights(trip: TripDetail, foods: FoodItem[]): string[] {
  const highlights: string[] = []
  const text = `${trip.title} ${trip.destination}`.toLowerCase()

  if (/浮潜|snorkel|dive/i.test(text)) highlights.push('浮潜')
  if (/跳岛|island hopping/i.test(text)) highlights.push('跳岛')
  if (foods.length > 5) highlights.push('海鲜大餐')
  if (trip.stops.some((s) => /购物|市场|market/i.test(s.name))) highlights.push('购物')
  if (trip.stops.some((s) => /日落|sunset/i.test(s.name))) highlights.push('日落')

  return highlights.slice(0, 5)
}

// ===== 每日攻略 =====
function composeDays(trip: TripDetail): DaySection[] {
  const days = Array.from({ length: trip.days }, (_, i) => i + 1).map((day) => {
    const date = displayTripDayDate(trip, day)
    const monthLabel = exportMonthDayLabel(date)
    const dayTitle = trip.day_titles?.[day] || ''
    const { routeTitle, description } = splitExportDayTitle(dayTitle, day)
    // 城市缺失时留空由渲染层隐藏，不填"待定"
    const city = cleanNullable(extractCityFromDayTitle(dayTitle) || extractCityFromStops(trip, day)) || ''
    let theme = cleanNullable(routeTitle || description) || `第 ${day} 天`
    // theme 与 city 相同则视为重复，用兜底避免"亚庇 / 亚庇"（PRD Content UI）
    if (city && theme.trim() === city.trim()) theme = `第 ${day} 天`
    const rawStops = trip.stops.filter((s) => s.day === day && isTimelineStop(s)).sort((a, b) => a.order_no - b.order_no)
    // 过滤无效地点节点（"时间/待定"等），并生成 EventCard（内部再解析有效名）
    const events = rawStops
      .map((stop) => composeEventCard(stop))
      .filter((e): e is EventCard => e !== null)
    // 路线只保留真实地点，剔除行为标签（退房/晚餐/返程等噪音），时间线仍保留
    const route = events.map((e) => e.place).filter((p) => p && !isActionLabel(p))

    const dayTags = generateDayTags(events, theme)
    const highlight = pickDayHighlight(events, rawStops)

    return {
      type: 'day' as const,
      day,
      date,
      monthLabel,
      city,
      theme,
      dayTags,
      route,
      events,
      ...(highlight ? { highlight } : {}),
    }
  })

  // 城市前向填充：某天城市空时，继承前一天（水屋/离岛等无城市名的天）
  let lastCity = ''
  for (const d of days) {
    if (d.city) lastCity = d.city
    else if (lastCity) d.city = lastCity
  }

  return days
}

// 根据当天事件生成 2-4 个标签（PRD 第 12 条，禁止硬编码）
function generateDayTags(events: EventCard[], theme: string): string[] {
  const text = `${theme} ${events.map((e) => `${e.place} ${e.description || ''}`).join(' ')}`
  const rules: Array<{ test: RegExp; tag: string }> = [
    { test: /跳岛|island hop/i, tag: '🌊 跳岛' },
    { test: /浮潜|snorkel|潜水|dive/i, tag: '🤿 浮潜' },
    { test: /海鲜|seafood|大排档/i, tag: '🦞 海鲜' },
    { test: /游艇|快艇|boat|yacht/i, tag: '🚤 游艇' },
    { test: /日落|sunset|夕阳/i, tag: '🌅 日落' },
    { test: /水屋|overwater|海上屋/i, tag: '🏝️ 水屋' },
    { test: /购物|市场|market|夜市/i, tag: '🛍️ 购物' },
    { test: /美食|餐|咖啡|café/i, tag: '🍽️ 美食' },
    { test: /机场|航班|飞机|flight/i, tag: '✈️ 交通' },
  ]
  const tags = rules.filter((r) => r.test.test(text)).map((r) => r.tag)
  return tags.slice(0, 4)
}

// 选出当天重点活动（PRD 第 16 条）：门票项目/体验型活动/核心景点优先
function pickDayHighlight(events: EventCard[], rawStops: TripStop[]): DayHighlight | undefined {
  if (events.length === 0) return undefined
  // 优先选带门票或体验关键词的事件
  const experienceRe = /跳岛|浮潜|潜水|游艇|演出|门票|乐园|表演|dive|snorkel/i
  const scored = events.map((e, idx) => {
    let score = 0
    const stop = rawStops[idx]
    if (experienceRe.test(`${e.place} ${e.description || ''}`)) score += 3
    if (stop?.ticket_price) score += 2
    if (e.badges.some((b) => b.type === 'cost')) score += 1
    return { event: e, score }
  }).sort((a, b) => b.score - a.score)

  let top = scored[0]
  // 无门票/体验型事件时降级：取描述最丰富的事件兜底，保证每天都有一个重点（PRD 第 16 条）
  if (!top || top.score === 0) {
    const byDesc = [...events].sort((a, b) => (b.description?.length || 0) - (a.description?.length || 0))
    if (!byDesc[0] || !byDesc[0].description) return undefined // 全无描述才放弃
    top = { event: byDesc[0], score: 0 }
  }

  // places：取当天其余地点名作为副信息
  const places = events.filter((e) => e.place !== top.event.place).slice(0, 3).map((e) => e.place)
  const tags = generateDayTags([top.event], top.event.place).slice(0, 3)

  return {
    title: top.event.place,
    places,
    tags,
  }
}

function composeEventCard(stop: TripStop): EventCard | null {
  // 无效地点（"时间/待定"等）过滤掉；能推断行为的用行为描述
  const place = resolveDisplayName(normalizeExportStopName(stop.name), stop.note)
  if (place === null) return null

  const time = formatStopTime(stop)
  const badges = composeEventBadges(stop)
  const tips = composeEventTips(stop)

  // 描述：去 Markdown 控制字符；若与某条 tip 高度重复（同源于一段 note），丢弃描述避免渲染两遍
  const rawDesc = cleanNullable(stop.note)
  let description = rawDesc ? stripMarkdown(rawDesc) : undefined
  if (description && tips.length) {
    const dup = tips.some((t) => textSimilarity(t.content, description!) >= 0.85)
    if (dup) description = undefined
  }

  return {
    type: 'event',
    time,
    place,
    description,
    badges,
    ...(tips.length ? { tips } : {}),
  }
}

function composeEventBadges(stop: TripStop): Badge[] {
  const badges: Badge[] = []

  if (stop.transport) {
    badges.push({
      icon: inferTransportIcon(stop.transport),
      label: stop.ticket_price ? `${stop.transport} · ¥${stop.ticket_price}` : stop.transport,
      type: 'transport',
    })
  } else if (stop.ticket_price) {
    badges.push({
      icon: '🎫',
      label: `¥${stop.ticket_price}/人`,
      type: 'cost',
    })
  }

  // 时长校验：优先用 start/end 计算，源值偏差>30min 用计算值，无结束时间则隐藏
  const sourceDurationMin = extractDurationMinutes(stop.note)
  const validated = validateDuration(
    /^\d{1,2}:\d{2}$/.test(stop.start_time) ? stop.start_time : undefined,
    undefined, // TripStop 目前无 end_time 字段，只能靠 stay_min（见下）
    sourceDurationMin,
  )
  if (validated) {
    badges.push({ icon: '⏱', label: validated, type: 'duration' })
  }

  return badges
}

// 从 note 里提取声明的时长（分钟），仅作为校验参考值
function extractDurationMinutes(note: string): number | null {
  const text = note || ''
  const hourMatch = text.match(/(\d+(?:\.\d+)?)\s*(?:小时|h|hour)/i)
  const minMatch = text.match(/(\d+)\s*(?:分钟|min)/i)
  if (hourMatch) return Math.round(Number(hourMatch[1]) * 60)
  if (minMatch) return Number(minMatch[1])
  return null
}

function inferTransportIcon(transport: string): string {
  const t = transport.toLowerCase()
  if (/taxi|grab|car|出租|打车/i.test(t)) return '🚕'
  if (/bus|巴士|公交/i.test(t)) return '🚌'
  if (/walk|步行/i.test(t)) return '🚶'
  if (/boat|船|ferry/i.test(t)) return '⛵'
  if (/flight|飞机|航班/i.test(t)) return '✈️'
  if (/train|火车|地铁/i.test(t)) return '🚆'
  return '🚗'
}

function composeEventTips(stop: TripStop): TipCard[] {
  const tips: TipCard[] = []
  const note = stop.note || ''

  // 检测注意事项
  if (/注意|小心|谨防|danger|warning/i.test(note)) {
    tips.push({
      type: 'tip',
      icon: '⚠️',
      title: '注意',
      content: note,
      level: 'warning',
    })
  }

  return tips
}

function formatStopTime(stop: TripStop): string | undefined {
  if (!stop.start_time) return undefined
  // "09:30" | "上午" | "下午"
  if (/^\d{2}:\d{2}$/.test(stop.start_time)) return stop.start_time
  if (/上午|下午|早上|中午|晚上|morning|afternoon|evening/i.test(stop.start_time)) return stop.start_time
  return undefined
}

// ===== 美食 =====
function composeFoods(foods: FoodItem[]): FoodSection {
  const cityGroups = groupFoodsByCity(foods)
  return {
    type: 'foods',
    cityGroups: cityGroups.map((group) => {
      const { top, more } = selectTopFoods(group.foods)
      return {
        city: group.city,
        top: top.map(composeRestaurantCard),
        more: more.map(composeRestaurantCard),
      }
    }),
  }
}

function groupFoodsByCity(foods: FoodItem[]): Array<{ city: string; foods: FoodItem[] }> {
  const groups = new Map<string, FoodItem[]>()
  foods.forEach((food) => {
    const city = food.city?.trim() || '未标城市'
    groups.set(city, [...(groups.get(city) || []), food])
  })
  return Array.from(groups.entries()).map(([city, foods]) => ({ city, foods }))
}

function selectTopFoods(foods: FoodItem[]): { top: FoodItem[]; more: FoodItem[] } {
  const scored = foods
    .map((f) => ({
      food: f,
      score: (f.rating || 0) * 10 + (f.is_favorite ? 20 : 0) + (f.recommend_food?.length || 0) * 2,
    }))
    .sort((a, b) => b.score - a.score)

  return {
    top: scored.slice(0, 5).map((s) => s.food),
    more: scored.slice(5).map((s) => s.food),
  }
}

function composeRestaurantCard(food: FoodItem): RestaurantCard {
  return {
    name: stripSourceMetadata(food.name),
    category: food.category || undefined,
    pricePerPerson: food.price || undefined,
    rating: food.rating || undefined,
    dishes: food.recommend_food?.length ? food.recommend_food : undefined,
    reason: extractFoodReason(food),
    address: cleanNullable(food.address) || undefined,
    businessHours: food.business_hours || undefined,
    mealType: food.meal_type !== '待定' ? food.meal_type : undefined,
  }
}

function extractFoodReason(food: FoodItem): string | undefined {
  const note = cleanNullable(food.note)
  if (!note) return undefined
  // 提取第一句作为推荐理由
  const firstSentence = note.split(/[。！？\n]/)[0]
  return firstSentence.length > 0 && firstSentence.length < 50 ? firstSentence : undefined
}

// ===== 住宿 =====
function composeStays(trip: TripDetail): StaySection {
  const allStays = trip.stops.filter(isStayStop).map((s) => ({
    ...s,
    date: displayTripDayDate(trip, s.day),
  }))
  const merged = mergeExportHotelStays(allStays)

  return {
    type: 'stays',
    hotels: merged.map(composeHotelCard),
  }
}

function mergeExportHotelStays(
  stays: Array<TripStop & { date: string }>
): Array<{
  name: string
  startDay: number
  endDay: number
  startDate: string
  endDate: string
  nights: number
  city: string
  note: string
  price: number | null
}> {
  const sorted = [...stays].sort((a, b) => a.day - b.day || a.order_no - b.order_no)
  const groups: Array<{
    name: string
    startDay: number
    endDay: number
    startDate: string
    endDate: string
    nights: number
    city: string
    note: string
    price: number | null
  }> = []

  sorted.forEach((stay) => {
    const name = normalizeExportStopName(stay.name)
    const key = normalizeHotelKey(name)
    const last = groups[groups.length - 1]

    // 合并连续同名酒店（用归一化 key 比较：忽略大小写/空格差异）
    if (last && normalizeHotelKey(last.name) === key && stay.day <= last.endDay + 1) {
      last.endDay = Math.max(last.endDay, stay.day)
      last.endDate = stay.date || last.endDate
      last.nights = Math.max(1, last.endDay - last.startDay + 1)
      last.note = last.note || stay.note || stay.location
      last.city = last.city || exportCityFromStay(stay)
      last.price = last.price ?? stay.ticket_price
      return
    }

    groups.push({
      name,
      startDay: stay.day,
      endDay: stay.day,
      startDate: stay.date,
      endDate: stay.date,
      nights: 1,
      city: exportCityFromStay(stay),
      note: stay.note || stay.location,
      price: stay.ticket_price,
    })
  })

  return groups
}

// 已知城市前缀，酒店名归一化时剥离（"仙本那 DBC" 与 "DBC" 视为同一家）
const KNOWN_CITY_PREFIXES = ['吉隆坡', '仙本那', '亚庇', '斗湖', '曼谷', '普吉', '清迈', '东京', '大阪', '京都', '胡志明', '河内']

/** 酒店名归一化 key：忽略大小写、空格、全半角、城市前缀差异，用于合并判定 */
function normalizeHotelKey(name: string): string {
  let key = (name || '').toLowerCase().replace(/\s+/g, '').replace(/[（）()·・]/g, '').trim()
  // 剥离开头的城市名（可能出现多次）
  let changed = true
  while (changed) {
    changed = false
    for (const city of KNOWN_CITY_PREFIXES) {
      const c = city.toLowerCase()
      if (key.startsWith(c) && key.length > c.length) {
        key = key.slice(c.length)
        changed = true
      }
    }
  }
  return key
}

function exportCityFromStay(stay: TripStop): string {
  const source = [stay.location, stay.note, stay.name].filter(Boolean).join(' ')
  return extractCityFromLocation(source)
}

function composeHotelCard(
  stay: {
    name: string
    startDay: number
    endDay: number
    startDate: string
    endDate: string
    nights: number
    city: string
    note: string
    price: number | null
  }
): HotelCard {
  return {
    name: stay.name,
    city: cleanNullable(stay.city) || '',  // 城市空则留空，渲染层隐藏，不填"待定"
    checkIn: formatDateShort(stay.startDate),
    checkOut: formatDateShort(stay.endDate),
    nights: stay.nights,
    relatedDays: Array.from({ length: stay.nights }, (_, i) => stay.startDay + i),
    pricePerNight: stay.price || undefined,
    note: cleanNullable(stay.note) || undefined,
  }
}

function formatDateShort(date: string): string {
  // "2026年10月1日 周二" → "10月1日"
  const match = date.match(/(\d{1,2})月(\d{1,2})日/)
  if (match) return `${match[1]}月${match[2]}日`
  return date
}

// ===== 避坑 =====
function composeTips(tips: TipItem[]): TipsSection {
  const categories = categorizeTips(tips)
  return {
    type: 'tips',
    categories,
  }
}

// 分类定义：按 PRD 第 29 条主题；顺序即优先级，一个 Tip 只归第一个命中的主类
const TIP_CATEGORY_DEFS = [
  { title: '证件', icon: '📄', keywords: ['证件', '护照', '签证', 'visa', 'passport', 'mdac'] },
  { title: '机场', icon: '✈️', keywords: ['机场', '值机', '登机', '安检', 'airport', 'checkin'] },
  { title: '交通', icon: '🚗', keywords: ['交通', '打车', 'grab', '航班', 'flight', '包车', '接送'] },
  { title: '浮潜', icon: '🤿', keywords: ['浮潜', '潜水', '装备', 'snorkel', 'dive', '水下', '晕船'] },
  { title: '安全', icon: '🛡️', keywords: ['安全', '注意', '小心', '谨防', '骗', 'safety', 'danger'] },
  { title: '现金', icon: '💰', keywords: ['现金', '货币', '汇率', '换钱', 'cash', 'currency', '小费'] },
  { title: '购物', icon: '🛍️', keywords: ['购物', '砍价', 'shopping', 'market', '特产'] },
  { title: '其他', icon: '📌', keywords: [] },
]

function categorizeTips(tips: TipItem[]): TipCategory[] {
  // 1. 原子化：把复合 Tip 拆成单主题条目
  const atomicTips: AtomicTip[] = tips.flatMap((tip) => atomizeTip(tip.content, tip.level))

  // 2. 语义去重：相似度>0.85 视为重复
  const uniqueContents = dedupeTexts(atomicTips.map((t) => t.content))
  const uniqueTips = uniqueContents.map((content) => {
    const match = atomicTips.find((t) => t.content === content)
    return { content, level: match?.level }
  })

  // 3. 每条只归一个 Primary Category（第一个命中的）
  const buckets = new Map<string, TipCard[]>()
  uniqueTips.forEach((tip) => {
    const def = TIP_CATEGORY_DEFS.find((d) =>
      d.keywords.length > 0 && d.keywords.some((kw) => tip.content.toLowerCase().includes(kw.toLowerCase()))
    ) || TIP_CATEGORY_DEFS[TIP_CATEGORY_DEFS.length - 1] // 兜底"其他"
    const list = buckets.get(def.title) || []
    list.push(composeTipCard(tip))
    buckets.set(def.title, list)
  })

  // 4. 按定义顺序输出非空分类
  return TIP_CATEGORY_DEFS
    .filter((def) => buckets.has(def.title))
    .map((def) => ({ title: def.title, icon: def.icon, tips: buckets.get(def.title)! }))
}

function composeTipCard(tip: AtomicTip): TipCard {
  const level = tip.level
  const icon = level === 'warning' ? '⚠️' : level === 'info' ? '💡' : '📝'
  // 原子 Tip 本身就是单主题，取首句作标题、其余作正文；短内容整体即标题
  const content = stripSourceMetadata(tip.content.trim())
  const firstSentence = content.split(/[，。,]/)[0]
  const title = firstSentence.length <= 16 ? firstSentence : content.slice(0, 14)

  return {
    type: 'tip',
    icon,
    title,
    content,
    level,
  }
}

// ===== 行李 =====
function composePacking(packing: PackingData, exportMode: 'friend' | 'personal' = 'friend'): PackingSection {
  const groups = Array.from(new Set(packing.items.map((i) => i.category || '通用')))
    .map((category) => ({
      category,
      items: packing.items
        .filter((i) => (i.category || '通用') === category)
        .map((item) => {
          const packedReal = packing.members.filter((m) => item.states[m] === 'packed')
          const unpackedReal = packing.members.filter((m) => item.states[m] === 'unpacked')
          if (exportMode === 'friend') {
            // 好友版：不暴露成员姓名，只标记是否已带
            return {
              name: item.name,
              packedBy: anonymizePackedStatus(packedReal) ? ['✓'] : [],
              unpackedBy: [],
            }
          }
          return { name: item.name, packedBy: packedReal, unpackedBy: unpackedReal }
        }),
    }))
    .filter((g) => g.items.length > 0)

  return {
    type: 'packing',
    groups,
  }
}

// ===== 预算 =====
// 好友版：只给聚合总额与分类占比，不含付款人/明细
// 个人完整版：额外给逐笔明细（含付款人）
function composeBudget(
  expenses: Expense[],
  memberCount?: number,
  exportMode: 'friend' | 'personal' = 'friend',
): BudgetSection {
  const breakdown: Record<string, number> = {}

  expenses.forEach((exp) => {
    const cat = mapExpenseCategory(exp.category || '其他')
    breakdown[cat] = (breakdown[cat] || 0) + exp.amount
  })

  const total = Object.values(breakdown).reduce((sum, val) => sum + val, 0)

  // 详细记账仅个人完整版输出（PRD 第 32 条：好友版必须删除付款人/明细）
  const entries = exportMode === 'personal'
    ? expenses.map((exp) => ({
        title: exp.title,
        category: mapExpenseCategory(exp.category || '其他'),
        amount: exp.amount,
        payer: exp.payer,
        date: undefined,
      }))
    : undefined

  return {
    type: 'budget',
    total,
    perPerson: memberCount && memberCount > 0 ? Math.round(total / memberCount) : undefined,
    breakdown: Object.entries(breakdown)
      .map(([category, amount]) => ({
        category,
        amount,
        percentage: total > 0 ? Math.round((amount / total) * 100) : 0,
      }))
      .sort((a, b) => b.amount - a.amount),
    ...(entries ? { entries } : {}),
  }
}

function mapExpenseCategory(rawCategory: string): string {
  const cat = rawCategory.toLowerCase()
  if (/交通|打车|机票|车费|油费|taxi|flight|transport/.test(cat)) return '交通'
  if (/住宿|酒店|民宿|hotel|accommodation/.test(cat)) return '住宿'
  if (/餐饮|吃饭|美食|食物|food|meal|restaurant/.test(cat)) return '餐饮'
  if (/门票|玩乐|活动|景点|ticket|activity|attraction/.test(cat)) return '门票/玩乐'
  if (/购物|纪念品|shopping|souvenir/.test(cat)) return '购物'
  return '其他'
}

// ===== 工具函数 =====
function isTimelineStop(stop: TripStop): boolean {
  return !isStayStop(stop)
}

function isStayStop(stop: TripStop): boolean {
  return (stop.note || '').includes('🏨') || (stop.note || '').includes('住宿') || stop.name.startsWith('🏨')
}

function normalizeExportStopName(name: string): string {
  return name.replace(/^🏨\s*/, '').trim()
}

function displayTripDayDate(trip: TripDetail, day: number): string {
  if (!trip.start_date) {
    const title = trip.day_titles?.[day] || trip.title || ''
    return tripDayDateFromTitle(title, day)
  }
  const date = new Date(`${trip.start_date}T00:00:00`)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + day - 1)
  const WEEK = ['日', '一', '二', '三', '四', '五', '六']
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 周${WEEK[date.getDay()]}`
}

function tripDayDateFromTitle(title: string, day: number): string {
  const match = title.match(/(\d{1,2})[./月](\d{1,2})(?:日)?\s*[—–-]\s*(\d{1,2})[./月](\d{1,2})/)
  if (!match) return ''
  const startMonth = Number(match[1])
  const startDay = Number(match[2])
  if (!startMonth || !startDay) return ''
  const date = new Date(2024, startMonth - 1, startDay)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + day - 1)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function exportWeekLabel(trip: TripDetail, day: number): string {
  if (!trip.start_date) {
    const title = trip.day_titles?.[day] || ''
    return title.match(/周[一二三四五六日天]/)?.[0] || ''
  }
  const date = new Date(`${trip.start_date}T00:00:00`)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + day - 1)
  return `周${['日', '一', '二', '三', '四', '五', '六'][date.getDay()]}`
}

function exportMonthDayLabel(date: string): string {
  const parts = parseExportDateParts(date)
  if (!parts) return ''
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return `${MONTHS[Math.max(0, Math.min(11, parts.month - 1))]} ${String(parts.day).padStart(2, '0')}`
}

function parseExportDateParts(date: string): { month: number; day: number } | null {
  const value = date.trim()
  const zh = value.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/)
  const dot = value.match(/^(\d{1,2})[./](\d{1,2})$/)
  const iso = value.match(/^\d{4}-(\d{1,2})-(\d{1,2})$/)
  const match = zh || dot || iso
  if (!match) return null
  return { month: Number(match[1]), day: Number(match[2]) }
}

function splitExportDayTitle(title: string, day: number): { routeTitle: string; description: string } {
  const value = cleanExportDayTitle(title, day)
  if (!value) return { routeTitle: '', description: '' }
  const parts = value.split(/[：:]/).map((part) => part.trim()).filter(Boolean)
  if (parts.length >= 2) return { routeTitle: parts[0], description: parts.slice(1).join('：') }
  return { routeTitle: value, description: '' }
}

function cleanExportDayTitle(title: string, day: number): string {
  let value = (title || '').trim()
  value = value.replace(new RegExp(`^\\s*Day\\s*0?${day}\\b`, 'i'), '').trim()
  value = value.replace(/^[·.、:：\-—–\s]+/, '')
  value = value.replace(/^\(?\d{1,2}[./月]\d{1,2}(?:日)?(?:\s*周[一二三四五六日天])?\)?/, '').trim()
  value = value.replace(/^[·.、:：\-—–\s]+/, '')
  return value.replace(/\s+/g, ' ').trim()
}
