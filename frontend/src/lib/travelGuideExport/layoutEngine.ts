import type { ExportOptions, GuideDay, TravelGuideSchema } from './schema'

export type GuideLayoutBlock =
  | { kind: 'cover'; guide: TravelGuideSchema }
  | { kind: 'overview'; guide: TravelGuideSchema }
  | { kind: 'beforeDeparture'; guide: TravelGuideSchema }
  | { kind: 'day'; day: GuideDay }
  | { kind: 'foods'; guide: TravelGuideSchema }
  | { kind: 'hotels'; guide: TravelGuideSchema }
  | { kind: 'packing'; guide: TravelGuideSchema }
  | { kind: 'checklist'; guide: TravelGuideSchema }
  | { kind: 'notes'; guide: TravelGuideSchema }

export type GuideLayout = {
  blocks: GuideLayoutBlock[]
  rules: {
    pageSize: 'A4'
    dayStartsOnNewPage: true
    keepCardsTogether: true
    repeatTableHeaders: true
    protectHardFacts: true
  }
}

export function buildTravelGuideLayout(guide: TravelGuideSchema, options: ExportOptions): GuideLayout {
  const blocks: GuideLayoutBlock[] = [
    { kind: 'cover', guide },
    { kind: 'overview', guide },
    { kind: 'beforeDeparture', guide },
    ...guide.days.map((day) => ({ kind: 'day' as const, day })),
  ]
  if (options.includeFoods && guide.foodRecommendations.length > 0) blocks.push({ kind: 'foods', guide })
  if (options.includeHotels && guide.hotels.length > 0) blocks.push({ kind: 'hotels', guide })
  if (options.includePacking && guide.packingList.length > 0) blocks.push({ kind: 'packing', guide })
  if (options.includeChecklist && guide.checklist48h.length > 0) blocks.push({ kind: 'checklist', guide })
  if (guide.importantNotes.length > 0 || guide.issues.length > 0) blocks.push({ kind: 'notes', guide })

  return {
    blocks,
    rules: {
      pageSize: 'A4',
      dayStartsOnNewPage: true,
      keepCardsTogether: true,
      repeatTableHeaders: true,
      protectHardFacts: true,
    },
  }
}
