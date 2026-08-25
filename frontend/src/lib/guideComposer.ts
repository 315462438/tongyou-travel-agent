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
  memberCount?: number  // 用于计算人均预算
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
  const { includePacking = false, includeBudget = true, memberCount } = options

  return {
    cover: composeCover(trip),
    overview: composeOverview(trip, foods),
    days: composeDays(trip),
    foods: composeFoods(foods),
    stays: composeStays(trip),
    tips: composeTips(tips),
    ...(includePacking ? { packing: composePacking(packing) } : {}),
    ...(includeBudget ? { budget: composeBudget(expenses, memberCount) } : {}),
  }
}

// ===== 封面 =====
function composeCover(trip: TripDetail): CoverSection {
  const title = exportCoverTitle(trip)
  const subtitle = extractSubtitle(trip)
  const region = inferRegion(title)
  const dateRange = formatExportDateRange(trip)
  const nights = Math.max(0, trip.days - 1)
  const tags = generateTripTags(trip)

  return {
    type: 'cover',
    title,
    subtitle,
    region,
    dateRange,
    days: trip.days,
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

function extractSubtitle(trip: TripDetail): string | undefined {
  const title = trip.title || ''
  // 提取"海岛跳岛浮潜度假"这类副标题
  const match = title.match(/[一-龥]{4,}(?:旅行|度假|攻略|计划)/)
  return match?.[0]
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
function composeOverview(trip: TripDetail, foods: FoodItem[]): OverviewSection {
  const timeline = buildOverviewTimeline(trip)
  const cities = extractCities(trip)
  const hotels = countHotels(trip)
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
      city: city || '待定',
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

function countHotels(trip: TripDetail): number {
  const hotelNames = new Set<string>()
  trip.stops.filter(isStayStop).forEach((s) => {
    hotelNames.add(normalizeExportStopName(s.name))
  })
  return hotelNames.size
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
  return Array.from({ length: trip.days }, (_, i) => i + 1).map((day) => {
    const date = displayTripDayDate(trip, day)
    const monthLabel = exportMonthDayLabel(date)
    const dayTitle = trip.day_titles?.[day] || ''
    const { routeTitle, description } = splitExportDayTitle(dayTitle, day)
    const city = extractCityFromDayTitle(dayTitle) || extractCityFromStops(trip, day) || '待定'
    const theme = routeTitle || description || `第 ${day} 天`
    const stops = trip.stops.filter((s) => s.day === day && isTimelineStop(s)).sort((a, b) => a.order_no - b.order_no)
    const route = stops.map((s) => normalizeExportStopName(s.name)).filter(Boolean)
    const events = stops.map((stop) => composeEventCard(stop))

    return {
      type: 'day',
      day,
      date,
      monthLabel,
      city,
      theme,
      route,
      events,
    }
  })
}

function composeEventCard(stop: TripStop): EventCard {
  const time = formatStopTime(stop)
  const place = normalizeExportStopName(stop.name)
  const description = stop.note || undefined
  const badges = composeEventBadges(stop)
  const tips = composeEventTips(stop)

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

  // 从 note 提取时长
  const duration = extractDuration(stop.note)
  if (duration) {
    badges.push({
      icon: '⏱',
      label: duration,
      type: 'duration',
    })
  }

  return badges
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

function extractDuration(text: string): string | undefined {
  const match = text.match(/(\d+)\s*(?:min|分钟|小时|h|hour)/i)
  if (match) {
    const num = match[1]
    if (/min|分钟/i.test(match[0])) return `${num} min`
    if (/hour|小时|h/i.test(match[0])) return `${num}h`
  }
  return undefined
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
    name: food.name,
    category: food.category || undefined,
    pricePerPerson: food.price || undefined,
    rating: food.rating || undefined,
    dishes: food.recommend_food?.length ? food.recommend_food : undefined,
    reason: extractFoodReason(food),
    address: food.address || undefined,
    businessHours: food.business_hours || undefined,
    mealType: food.meal_type !== '待定' ? food.meal_type : undefined,
  }
}

function extractFoodReason(food: FoodItem): string | undefined {
  const note = food.note?.trim()
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
    const last = groups[groups.length - 1]

    // 合并连续同名酒店
    if (last && last.name === name && stay.day <= last.endDay + 1) {
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
    city: stay.city || '待定',
    checkIn: formatDateShort(stay.startDate),
    checkOut: formatDateShort(stay.endDate),
    nights: stay.nights,
    relatedDays: Array.from({ length: stay.nights }, (_, i) => stay.startDay + i),
    pricePerNight: stay.price || undefined,
    note: stay.note || undefined,
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

function categorizeTips(tips: TipItem[]): TipCategory[] {
  const categoryDefs = [
    { title: '证件', icon: '📄', keywords: ['证件', '护照', '签证', 'visa', 'passport'] },
    { title: '交通', icon: '🚗', keywords: ['交通', '打车', 'grab', '机场', '航班', 'flight'] },
    { title: '安全', icon: '🛡️', keywords: ['安全', '注意', '小心', '谨防', '骗', 'safety', 'danger'] },
    { title: '浮潜', icon: '🤿', keywords: ['浮潜', '潜水', '装备', 'snorkel', 'dive', '水下'] },
    { title: '购物', icon: '🛍️', keywords: ['购物', '买', '价格', '砍价', 'shopping', 'market'] },
    { title: '现金', icon: '💰', keywords: ['现金', '货币', '汇率', '换钱', 'cash', 'currency'] },
    { title: '机场', icon: '✈️', keywords: ['机场', '值机', '登机', '行李', 'airport', 'checkin'] },
  ]

  const categorized = categoryDefs
    .map((def) => ({
      title: def.title,
      icon: def.icon,
      tips: tips
        .filter((tip) => def.keywords.some((kw) => tip.content.toLowerCase().includes(kw.toLowerCase())))
        .map((tip) => composeTipCard(tip)),
    }))
    .filter((cat) => cat.tips.length > 0)

  // 未分类的放到"其他"
  const categorizedTipIds = new Set(categorized.flatMap((cat) => cat.tips.map((t) => t.content)))
  const uncategorized = tips
    .filter((tip) => !categorizedTipIds.has(tip.content))
    .map((tip) => composeTipCard(tip))

  if (uncategorized.length > 0) {
    categorized.push({
      title: '其他',
      icon: '📌',
      tips: uncategorized,
    })
  }

  return categorized
}

function composeTipCard(tip: TipItem): TipCard {
  const level = tip.level === 'important' ? 'warning' : tip.level === 'notice' ? 'info' : undefined
  const icon = level === 'warning' ? '⚠️' : level === 'info' ? '💡' : '📝'

  // 从 content 提取标题和正文
  const lines = tip.content.split('\n').filter(Boolean)
  const title = lines[0]?.length < 20 ? lines[0] : '提示'
  const content = lines.length > 1 ? lines.slice(1).join('\n') : lines[0]

  return {
    type: 'tip',
    icon,
    title,
    content,
    level,
  }
}

// ===== 行李 =====
function composePacking(packing: PackingData): PackingSection {
  const groups = Array.from(new Set(packing.items.map((i) => i.category || '通用')))
    .map((category) => ({
      category,
      items: packing.items
        .filter((i) => (i.category || '通用') === category)
        .map((item) => ({
          name: item.name,
          packedBy: packing.members.filter((m) => item.states[m] === 'packed'),
          unpackedBy: packing.members.filter((m) => item.states[m] === 'unpacked'),
        })),
    }))
    .filter((g) => g.items.length > 0)

  return {
    type: 'packing',
    groups,
  }
}

// ===== 预算（聚合，过滤个人信息）=====
function composeBudget(expenses: Expense[], memberCount?: number): BudgetSection {
  const breakdown: Record<string, number> = {}

  expenses.forEach((exp) => {
    const cat = mapExpenseCategory(exp.category || '其他')
    breakdown[cat] = (breakdown[cat] || 0) + exp.amount
  })

  const total = Object.values(breakdown).reduce((sum, val) => sum + val, 0)

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
