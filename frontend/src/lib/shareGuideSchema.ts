/**
 * 好友分享版旅行攻略中间格式
 * 解耦业务编排与文档渲染
 */

// ===== 顶层结构 =====
export type ShareGuideSchema = {
  cover: CoverSection
  overview: OverviewSection
  days: DaySection[]
  foods: FoodSection
  stays: StaySection
  tips: TipsSection
  packing?: PackingSection
  budget?: BudgetSection
}

// ===== 封面 =====
export type CoverSection = {
  type: 'cover'
  title: string              // "吉隆坡 · 仙本那 · 亚庇"
  subtitle?: string          // "海岛跳岛浮潜度假"
  region: string             // "MALAYSIA" | "TRAVEL"
  dateRange: string          // "2026.10.01 — 2026.10.08"
  days: number
  nights: number
  tags: string[]             // ["海岛", "浮潜", "跳岛", "度假", "马来西亚"]
  heroImage?: string         // 封面图 URL（future）
  description?: string       // "探索仙本那海底世界，体验亚庇日落风情"
}

// ===== 总览 =====
export type OverviewSection = {
  type: 'overview'
  timeline: OverviewTimelineDay[]
  stats: {
    totalDays: number
    cities: string[]
    hotels: number
    highlights: string[]     // ["浮潜", "跳岛", "海鲜大餐"]
    budgetRange?: string     // "¥8000 - ¥12000/人"（可选）
  }
}

export type OverviewTimelineDay = {
  day: number
  date: string               // "10.01"
  weekday: string            // "周二"
  city: string
  theme: string              // "抵达吉隆坡 · 市区观光"
  hotel: string
}

// ===== 每日攻略 =====
export type DaySection = {
  type: 'day'
  day: number
  date: string               // "2026年10月1日 周二"
  monthLabel: string         // "OCT 01"
  city: string
  theme: string              // "抵达吉隆坡 · 市区观光"
  route: string[]            // ["KLIA2", "酒店", "中央公园", "阿罗街"]
  events: EventCard[]
}

export type EventCard = {
  type: 'event'
  time?: string              // "09:30" | "上午" | undefined
  place: string              // "吉隆坡国际机场 KLIA2"
  description?: string       // 主要描述
  badges: Badge[]            // 交通/时长/价格统一用 Badge
  tips?: TipCard[]           // 内联提示
}

export type Badge = {
  icon: string               // "🚕" | "⏱" | "🎫" | "📍"
  label: string              // "Grab · ¥30" | "20 min" | "¥250/人"
  type: 'transport' | 'duration' | 'cost' | 'location'
}

export type TipCard = {
  type: 'tip'
  icon: string               // "⚠️" | "💡" | "📷" | "🤿" | "🍽"
  title: string              // "注意" | "建议" | "拍照点" | "浮潜装备" | "美食推荐"
  content: string
  level?: 'warning' | 'info' | 'highlight'
}

// ===== 美食 =====
export type FoodSection = {
  type: 'foods'
  cityGroups: FoodCityGroup[]
}

export type FoodCityGroup = {
  city: string
  top: RestaurantCard[]      // Top 3-5
  more: RestaurantCard[]     // 其余收藏
}

export type RestaurantCard = {
  name: string
  category?: string          // "海鲜" | "咖啡" | "中餐"
  pricePerPerson?: number
  rating?: number
  dishes?: string[]          // 推荐菜
  reason?: string            // 一句推荐理由
  address?: string
  businessHours?: string
  mealType?: string          // "早餐" | "午餐" | "晚餐" | "待定"
}

// ===== 住宿 =====
export type StaySection = {
  type: 'stays'
  hotels: HotelCard[]        // 已合并，同一酒店只出现一次
}

export type HotelCard = {
  name: string
  city: string
  checkIn: string            // "10月1日"
  checkOut: string           // "10月3日"
  nights: number
  relatedDays: number[]      // [1, 2]
  pricePerNight?: number
  note?: string
}

// ===== 避坑（改名：出发前一定要看）=====
export type TipsSection = {
  type: 'tips'
  categories: TipCategory[]  // 按主题分类
}

export type TipCategory = {
  title: string              // "证件" | "交通" | "安全" | "浮潜" | "购物" | "现金" | "机场"
  icon: string
  tips: TipCard[]
}

// ===== 行李 =====
export type PackingSection = {
  type: 'packing'
  groups: PackingGroup[]
}

export type PackingGroup = {
  category: string           // "衣物" | "电子产品" | "洗漱用品"
  items: PackingItem[]
}

export type PackingItem = {
  name: string
  packedBy: string[]         // 已打包的成员列表
  unpackedBy: string[]       // 未打包的成员列表
}

// ===== 预算（聚合版，无个人信息）=====
export type BudgetSection = {
  type: 'budget'
  total?: number
  perPerson?: number
  breakdown: BudgetCategory[]
}

export type BudgetCategory = {
  category: string           // "交通" | "住宿" | "餐饮" | "门票/玩乐"
  amount: number
  percentage?: number
}
