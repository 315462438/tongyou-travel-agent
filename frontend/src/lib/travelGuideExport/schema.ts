export const EXPORT_PROMPT_VERSION = 'travel-guide-export-v1'

export type GuideIssueType =
  | 'DATA_CONFLICT'
  | 'MISSING_DATA'
  | 'LLM_FAILED'
  | 'SCHEMA_REPAIR_FAILED'
  | 'HARD_INFO_CHANGED'

export type GuideIssue = {
  type: GuideIssueType
  message: string
  day?: number
  severity?: 'info' | 'warning' | 'critical'
  sourceIds?: string[]
}

export type TimelineType =
  | 'transport'
  | 'flight'
  | 'hotel'
  | 'attraction'
  | 'food'
  | 'activity'
  | 'shopping'
  | 'outfit'
  | 'warning'
  | 'tip'
  | 'reservation'

export type TimelineImportance = 'critical' | 'important' | 'normal' | 'optional'

export type TravelGuideMeta = {
  travelPlanId: string
  title: string
  subtitle: string
  destination: string
  dateRange: string
  days: number
  nights: number
  tags: string[]
  promptVersion: string
  sourceUpdatedAt: string
}

export type TimelineItem = {
  sourceId?: string
  time: string
  title: string
  description: string
  type: TimelineType
  importance: TimelineImportance
  duration?: string
  price?: string
  transport?: string
  originalTitle?: string
  originalDescription?: string
}

export type DayHotel = {
  name: string
  city?: string
  checkIn?: string
  checkOut?: string
  nights?: number
  note?: string
  sourceId?: string
}

export type GuideDay = {
  day: number
  date: string
  city: string
  title: string
  subtitle: string
  highlight: string
  route: string[]
  tags: string[]
  timeline: TimelineItem[]
  food: string[]
  outfit: string
  tips: string[]
  warnings: string[]
  hotel?: DayHotel
}

export type FoodRecommendation = {
  name: string
  city: string
  category?: string
  mealType?: string
  price?: string
  rating?: string
  address?: string
  recommendation?: string
}

export type HotelSummary = DayHotel

export type PackingGroup = {
  category: string
  items: string[]
}

export type TravelGuideSchema = {
  meta: TravelGuideMeta
  summary: {
    overview: string
    rhythm: string
    cities: string[]
    highlights: string[]
  }
  days: GuideDay[]
  foodRecommendations: FoodRecommendation[]
  hotels: HotelSummary[]
  packingList: PackingGroup[]
  beforeDeparture: string[]
  checklist48h: string[]
  importantNotes: string[]
  issues: GuideIssue[]
}

export type NormalizedTravelGuide = TravelGuideSchema & {
  raw: {
    trip: unknown
    foods: unknown[]
    tips: unknown[]
    packing: unknown
    expenses: unknown[]
  }
  hardFacts: {
    dates: string[]
    times: Array<{ day: number; sourceId?: string; time: string }>
    hotelNames: string[]
    prices: string[]
  }
}

export type ExportOptions = {
  polished: boolean
  includePacking: boolean
  includeHotels: boolean
  includeFoods: boolean
  includeChecklist: boolean
}

export const DEFAULT_EXPORT_OPTIONS: ExportOptions = {
  polished: true,
  includePacking: true,
  includeHotels: true,
  includeFoods: true,
  includeChecklist: true,
}
