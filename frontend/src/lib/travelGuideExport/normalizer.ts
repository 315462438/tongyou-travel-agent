import { EXPORT_PROMPT_VERSION, type FoodRecommendation, type GuideDay, type GuideIssue, type HotelSummary, type NormalizedTravelGuide, type PackingGroup, type TimelineImportance, type TimelineItem, type TimelineType } from './schema'

type TripStop = {
  id: string
  day: number
  order_no: number
  name: string
  note: string
  location: string
  start_time: string
  stay_min: number | null
  transport: string
  ticket_price: number | null
  tags: string[]
}

type TripDetail = {
  id: string
  title: string
  destination: string
  days: number
  day_titles?: Record<string, string>
  start_date: string
  updated_at: string
  stops: TripStop[]
}

type FoodItem = {
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
}

type TipItem = { content: string; level: string }

type PackingData = {
  members: string[]
  items: Array<{ name: string; category: string; states: Record<string, string> }>
}

type Expense = { title: string; category: string; amount: number; payer: string }

const KNOWN_CITIES = ['吉隆坡', '仙本那', '亚庇', '斗湖', '曼谷', '普吉', '清迈', '东京', '大阪', '京都', '河内', '胡志明']

export function normalizeTravelGuideData(
  trip: TripDetail,
  foods: FoodItem[],
  tips: TipItem[],
  packing: PackingData,
  expenses: Expense[],
): NormalizedTravelGuide {
  const issues: GuideIssue[] = []
  const sortedStops = [...trip.stops]
    .filter((stop) => clean(stop.name))
    .sort((a, b) => a.day - b.day || (timeValue(a.start_time) - timeValue(b.start_time)) || a.order_no - b.order_no)
  const hotels = mergeHotels(sortedStops.filter(isHotelStop))
  const days = Array.from({ length: Math.max(1, trip.days) }, (_, idx) =>
    normalizeDay(trip, idx + 1, sortedStops, hotels, issues)
  )
  const foodRecommendations = dedupeFoods(foods)
  const packingList = normalizePacking(packing)
  const beforeDeparture = dedupeText([
    ...tips.map((tip) => tip.content),
    ...sortedStops.flatMap((stop) => splitSentences(stop.note).filter(isBeforeDepartureNote)),
  ]).slice(0, 12)
  const prices = [
    ...sortedStops.filter((stop) => stop.ticket_price !== null).map((stop) => `Day ${stop.day} ${cleanName(stop.name)} ¥${stop.ticket_price}`),
    ...foods.filter((food) => food.price !== null).map((food) => `${clean(food.name)} ¥${food.price}`),
    ...expenses.map((expense) => `${clean(expense.title)} ¥${expense.amount}`),
  ]
  const cities = dedupeText(days.map((day) => day.city).filter(Boolean))
  const highlights = dedupeText(days.map((day) => day.highlight).filter(Boolean)).slice(0, 5)

  days.forEach((day) => detectDayConflicts(day, issues))

  return {
    meta: {
      travelPlanId: trip.id,
      title: buildTitle(trip),
      subtitle: extractCitiesFromText(`${trip.title} ${trip.destination}`).join(' · ') || clean(trip.destination) || '旅行攻略',
      destination: clean(trip.destination),
      dateRange: formatDateRange(trip),
      days: trip.days,
      nights: Math.max(0, trip.days - 1),
      tags: buildTripTags(trip, sortedStops, foodRecommendations),
      promptVersion: EXPORT_PROMPT_VERSION,
      sourceUpdatedAt: trip.updated_at || '',
    },
    summary: {
      overview: `${trip.days} 天行程，按每日时间线整理为可打印旅行手册。`,
      rhythm: buildRhythm(days),
      cities,
      highlights,
    },
    days,
    foodRecommendations,
    hotels,
    packingList,
    beforeDeparture,
    checklist48h: buildChecklist48h(beforeDeparture, days),
    importantNotes: dedupeText([
      ...beforeDeparture.filter((text) => /注意|必须|提前|预约|安检|护照|签证|MDAC|不可更改|安全/.test(text)),
      ...days.flatMap((day) => day.warnings),
    ]).slice(0, 12),
    issues,
    raw: { trip, foods, tips, packing, expenses },
    hardFacts: {
      dates: [trip.start_date, formatDateRange(trip), ...days.map((day) => day.date)].filter(Boolean),
      times: sortedStops.filter((stop) => clean(stop.start_time)).map((stop) => ({ day: stop.day, sourceId: stop.id, time: stop.start_time })),
      hotelNames: hotels.map((hotel) => hotel.name),
      prices,
    },
  }
}

function normalizeDay(
  trip: TripDetail,
  day: number,
  stops: TripStop[],
  hotels: HotelSummary[],
  issues: GuideIssue[],
): GuideDay {
  const dayStops = stops.filter((stop) => stop.day === day)
  const dayTitle = clean(trip.day_titles?.[String(day)] || '')
  const city = inferDayCity(dayTitle, dayStops) || inferNearestCity(trip, stops, day)
  const timeline = dayStops.map((stop) => toTimelineItem(stop))
  const route = dedupeText(timeline.map((item) => item.title).filter((name) => !isActionName(name))).slice(0, 8)
  const food = timeline.filter((item) => item.type === 'food').map((item) => item.title)
  const warnings = dedupeText(timeline.flatMap((item) => splitSentences(item.description).filter(isWarningText))).slice(0, 4)
  const tips = dedupeText(timeline.flatMap((item) => splitSentences(item.description).filter((text) => !isWarningText(text) && isTipText(text)))).slice(0, 5)
  const outfit = dedupeText(timeline.flatMap((item) => splitSentences(item.description).filter(isOutfitText))).join('；')
  const hotel = hotels.find((h) => h.sourceId && stops.some((s) => s.id === h.sourceId && s.day === day))
  const title = cleanDayTitle(dayTitle) || summarizeDayTitle(route, timeline, day)
  if (timeline.length === 0) {
    issues.push({ type: 'MISSING_DATA', severity: 'info', day, message: `Day ${day} 暂无时间线条目` })
  }

  return {
    day,
    date: displayTripDayDate(trip, day),
    city,
    title,
    subtitle: route.join(' → '),
    highlight: pickHighlight(timeline, title),
    route,
    tags: buildDayTags(timeline, title),
    timeline,
    food,
    outfit,
    tips,
    warnings,
    ...(hotel ? { hotel } : {}),
  }
}

function toTimelineItem(stop: TripStop): TimelineItem {
  const title = cleanName(stop.name)
  const description = cleanDescription(stop.note)
  return {
    sourceId: stop.id,
    time: normalizeTime(stop.start_time),
    title,
    description,
    type: classifyStop(stop),
    importance: importanceOf(stop, description),
    ...(stop.stay_min ? { duration: `${stop.stay_min} 分钟` } : {}),
    ...(stop.ticket_price !== null ? { price: `¥${stop.ticket_price}` } : {}),
    ...(clean(stop.transport) ? { transport: clean(stop.transport) } : {}),
    originalTitle: stop.name,
    originalDescription: stop.note,
  }
}

function classifyStop(stop: TripStop): TimelineType {
  const text = `${stop.name} ${stop.note} ${stop.transport} ${(stop.tags || []).join(' ')}`.toLowerCase()
  if (/航班|飞机|起飞|抵达|机场|flight|airport/.test(text)) return 'flight'
  if (/酒店|入住|退房|住宿|hotel|resort/.test(text)) return 'hotel'
  if (/餐|美食|海鲜|咖啡|夜宵|food|restaurant|cafe/.test(text)) return 'food'
  if (/购物|超市|特产|market|shopping/.test(text)) return 'shopping'
  if (/穿搭|泳衣|外套|水母服|防晒|墨镜|草帽/.test(text)) return 'outfit'
  if (/预约|集合|签到|船班|不可更改|reservation|booking/.test(text)) return 'reservation'
  if (/注意|小心|安全|安检|noshow|损失|warning/.test(text)) return 'warning'
  if (/grab|打车|公交|步行|码头|车程|船程|接机|送机|transport/.test(text)) return 'transport'
  if (/浮潜|跳岛|水屋|日落|景点|游艇|沙滩|activity|snorkel/.test(text)) return 'activity'
  return 'attraction'
}

function importanceOf(stop: TripStop, description: string): TimelineImportance {
  const text = `${stop.name} ${description}`.toLowerCase()
  if (/不可更改|必须|noshow|全损|护照|签证|mdac|安检|安全/.test(text)) return 'critical'
  if (/预约|集合|签到|起飞|抵达|入住|退房|船班|提前/.test(text)) return 'important'
  if (/可选|自由|逛逛|备选/.test(text)) return 'optional'
  return stop.ticket_price ? 'important' : 'normal'
}

function mergeHotels(stops: TripStop[]): HotelSummary[] {
  const hotels: HotelSummary[] = []
  for (const stop of stops.sort((a, b) => a.day - b.day || a.order_no - b.order_no)) {
    const name = cleanName(stop.name)
    const last = hotels[hotels.length - 1]
    if (last && hotelKey(last.name) === hotelKey(name) && last.checkOut === `Day ${stop.day - 1}`) {
      last.checkOut = `Day ${stop.day}`
      last.nights = Math.max(1, (last.nights || 1) + 1)
      continue
    }
    hotels.push({
      name,
      city: inferCity(`${stop.location} ${stop.note} ${stop.name}`),
      checkIn: `Day ${stop.day}`,
      checkOut: `Day ${stop.day}`,
      nights: 1,
      note: cleanDescription(stop.note),
      sourceId: stop.id,
    })
  }
  return hotels
}

function dedupeFoods(foods: FoodItem[]): FoodRecommendation[] {
  const seen = new Set<string>()
  const result: FoodRecommendation[] = []
  for (const food of foods) {
    const name = clean(food.name)
    if (!name) continue
    const key = `${name.toLowerCase()}|${clean(food.city)}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push({
      name,
      city: clean(food.city) || '未标城市',
      category: clean(food.category) || undefined,
      mealType: clean(food.meal_type) && food.meal_type !== '待定' ? clean(food.meal_type) : undefined,
      price: food.price !== null ? `¥${food.price}/人` : undefined,
      rating: food.rating !== null ? String(food.rating) : undefined,
      address: clean(food.address) || undefined,
      recommendation: clean([food.recommend_food?.join('、'), food.note].filter(Boolean).join('；')) || undefined,
    })
  }
  return result
}

function normalizePacking(packing: PackingData): PackingGroup[] {
  const groups = new Map<string, string[]>()
  for (const item of packing.items || []) {
    const name = clean(item.name)
    if (!name) continue
    const category = clean(item.category) || '通用'
    groups.set(category, dedupeText([...(groups.get(category) || []), name]))
  }
  return Array.from(groups.entries()).map(([category, items]) => ({ category, items }))
}

function detectDayConflicts(day: GuideDay, issues: GuideIssue[]) {
  const jettyNames = day.timeline.map((item) => item.title).filter((name) => /Jetty|码头/i.test(name))
  if (new Set(jettyNames.map((name) => name.toLowerCase())).size > 1) {
    issues.push({
      type: 'DATA_CONFLICT',
      severity: 'warning',
      day: day.day,
      message: `Day ${day.day} 同时出现 ${jettyNames.join(' 和 ')}`,
    })
  }
}

function buildChecklist48h(beforeDeparture: string[], days: GuideDay[]): string[] {
  return dedupeText([
    '确认护照、证件、签证或入境登记信息。',
    '核对航班、酒店、集合时间和预约单截图。',
    '把第一天交通、酒店地址和紧急联系人离线保存。',
    ...beforeDeparture.filter((text) => /提前|预约|确认|截图|集合|船班|安检/.test(text)),
    ...days.flatMap((day) => day.timeline.filter((item) => item.importance === 'critical').map((item) => `${day.date || `Day ${day.day}`}：${item.title}`)),
  ]).slice(0, 10)
}

function buildTitle(trip: TripDetail): string {
  const text = `${trip.title} ${trip.destination}`
  const region = /马来|吉隆坡|仙本那|亚庇|Malaysia/i.test(text) ? '马来西亚' : clean(trip.destination) || '旅行'
  return `${region}${trip.days}天${Math.max(0, trip.days - 1)}晚`
}

function buildTripTags(trip: TripDetail, stops: TripStop[], foods: FoodRecommendation[]): string[] {
  const text = `${trip.title} ${trip.destination} ${stops.map((s) => `${s.name} ${s.note}`).join(' ')}`
  const rules: Array<[RegExp, string]> = [
    [/浮潜|潜水|snorkel/i, '浮潜'],
    [/跳岛|游艇|船/i, '跳岛'],
    [/水屋|度假村|resort/i, '度假'],
    [/日落|夜景/i, '日落'],
    [/海鲜|美食|餐/i, '美食'],
    [/购物|特产|超市/i, '购物'],
  ]
  return dedupeText([...rules.filter(([re]) => re.test(text)).map(([, tag]) => tag), ...(foods.length ? ['美食收藏'] : [])]).slice(0, 6)
}

function buildDayTags(timeline: TimelineItem[], title: string): string[] {
  const text = `${title} ${timeline.map((item) => `${item.title} ${item.description}`).join(' ')}`
  const rules: Array<[RegExp, string]> = [
    [/机场|航班|飞|转场/i, '交通'],
    [/浮潜|潜水/i, '浮潜'],
    [/跳岛|游艇|码头|船/i, '海岛'],
    [/日落|夜景/i, '景观'],
    [/餐|海鲜|夜市|咖啡/i, '美食'],
    [/水屋|酒店|度假村/i, '住宿'],
    [/购物|特产|超市/i, '购物'],
  ]
  return rules.filter(([re]) => re.test(text)).map(([, tag]) => tag).slice(0, 4)
}

function buildRhythm(days: GuideDay[]): string {
  const parts = days.map((day) => `Day ${day.day} ${day.title}`).slice(0, 8)
  return parts.length ? parts.join('；') : '按每日时间线推进，重点事项优先确认。'
}

function pickHighlight(timeline: TimelineItem[], title: string): string {
  const ranked = [...timeline].sort((a, b) => importanceRank(b.importance) - importanceRank(a.importance) || scoreHighlight(b) - scoreHighlight(a))
  const experiential = ranked.find((item) => /activity|attraction|food|shopping/.test(item.type))
  return experiential?.title || ranked[0]?.title || title
}

function scoreHighlight(item: TimelineItem): number {
  return (/浮潜|跳岛|水屋|日落|KLCC|双子塔|海鲜|度假/.test(`${item.title} ${item.description}`) ? 10 : 0) + (item.description.length > 20 ? 2 : 0)
}

function importanceRank(value: TimelineImportance): number {
  return { critical: 4, important: 3, normal: 2, optional: 1 }[value]
}

function summarizeDayTitle(route: string[], timeline: TimelineItem[], day: number): string {
  const first = route[0]
  const last = route[route.length - 1]
  const main = pickHighlight(timeline, '')
  if (first && last && first !== last) return `${first} → ${last}`
  return main || `第 ${day} 天`
}

function cleanDayTitle(value: string): string {
  return value
    .replace(/^Day\s*\d+\s*/i, '')
    .replace(/^\d{1,2}[./月]\d{1,2}(?:日)?\s*/, '')
    .replace(/^周[一二三四五六日天]\s*/, '')
    .replace(/^[·:：\-\s]+/, '')
    .trim()
}

function isHotelStop(stop: TripStop): boolean {
  const text = `${stop.name} ${stop.note}`
  if (/退房|返回酒店|酒店早餐|集合|取行李/.test(text)) return false
  return /住宿|入住|当晚落脚|落脚点/i.test(text) || stop.name.startsWith('🏨')
}

function isActionName(value: string): boolean {
  return /^(退房|入住|早餐|午餐|晚餐|集合|签到|候机|返程|自由活动)$/.test(value)
}

function inferDayCity(dayTitle: string, stops: TripStop[]): string {
  return inferCity(`${dayTitle} ${stops.map((s) => `${s.name} ${s.note} ${s.location}`).join(' ')}`)
}

function inferNearestCity(trip: TripDetail, stops: TripStop[], day: number): string {
  for (let d = day; d >= 1; d -= 1) {
    const city = inferDayCity(trip.day_titles?.[String(d)] || '', stops.filter((s) => s.day === d))
    if (city) return city
  }
  return inferCity(`${trip.destination} ${trip.title}`)
}

function inferCity(text: string): string {
  return KNOWN_CITIES.find((city) => text.includes(city)) || ''
}

function extractCitiesFromText(text: string): string[] {
  return KNOWN_CITIES.filter((city) => text.includes(city))
}

function displayTripDayDate(trip: TripDetail, day: number): string {
  if (!trip.start_date) return ''
  const date = new Date(`${trip.start_date}T00:00:00`)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + day - 1)
  const week = ['日', '一', '二', '三', '四', '五', '六'][date.getDay()]
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 周${week}`
}

function formatDateRange(trip: TripDetail): string {
  if (!trip.start_date) return '日期待定'
  const start = new Date(`${trip.start_date}T00:00:00`)
  if (Number.isNaN(start.getTime())) return '日期待定'
  const end = new Date(start)
  end.setDate(start.getDate() + Math.max(1, trip.days) - 1)
  const fmt = (d: Date) => `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
  return `${fmt(start)} - ${fmt(end)}`
}

function normalizeTime(value: string): string {
  const text = clean(value)
  const match = text.match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return text
  return `${String(Number(match[1])).padStart(2, '0')}:${match[2]}`
}

function timeValue(value: string): number {
  const match = normalizeTime(value).match(/^(\d{2}):(\d{2})$/)
  return match ? Number(match[1]) * 60 + Number(match[2]) : 9999
}

function cleanName(value: string): string {
  return clean(value).replace(/^🏨\s*/, '').replace(/^[•●]\s*/, '')
}

function cleanDescription(value: string): string {
  return clean(value)
    .replace(/[#*_`>]/g, '')
    .replace(/[⭐🤿🏝️🍽️✈️🌊🦞🚤🌅🛍️🚕🚌🚶⛵🚆🎫📍⏱💡⚠️📝📄🛡️💰📌]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function clean(value: unknown): string {
  return String(value ?? '').replace(/\s+/g, ' ').trim()
}

function splitSentences(value: string): string[] {
  return cleanDescription(value).split(/[。；;！!？?\n]/).map(clean).filter((text) => text.length > 3)
}

function isWarningText(text: string): boolean {
  return /注意|小心|不要|避免|不可|安全|全损|风险|安检/.test(text)
}

function isTipText(text: string): boolean {
  return /建议|记得|提前|确认|准备|可以|优先|保存|带/.test(text)
}

function isBeforeDepartureNote(text: string): boolean {
  return /护照|签证|MDAC|提前|预约|确认|安检|现金|防晒|装备|晕船|船班/.test(text)
}

function isOutfitText(text: string): boolean {
  return /穿搭|泳衣|水母服|长裙|短裤|衬衫|外套|拖鞋|墨镜|草帽|防晒/.test(text)
}

function hotelKey(value: string): string {
  return value.toLowerCase().replace(/\s+/g, '').replace(/[·・\-—–_（）()]/g, '')
}

function dedupeText(values: string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of values) {
    const value = clean(raw)
    if (!value) continue
    const key = value.toLowerCase().replace(/\s+/g, '')
    if (seen.has(key)) continue
    seen.add(key)
    result.push(value)
  }
  return result
}
