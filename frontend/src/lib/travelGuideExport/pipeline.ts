import { buildTravelGuideLayout } from './layoutEngine'
import { editTravelGuideWithLLM } from './llmEditor'
import { normalizeTravelGuideData } from './normalizer'
import { DEFAULT_EXPORT_OPTIONS, type ExportOptions, type TravelGuideSchema } from './schema'
import { renderTravelGuideDocx } from './docxTravelGuideRenderer'

type PipelineInput = Parameters<typeof normalizeTravelGuideData>

export type TravelGuideExportResult = {
  blob: Blob
  guide: TravelGuideSchema
  usedLLM: boolean
  issues: TravelGuideSchema['issues']
}

export async function exportTravelGuideDocx(
  ...args: [...PipelineInput, Partial<ExportOptions>?]
): Promise<TravelGuideExportResult> {
  const options = { ...DEFAULT_EXPORT_OPTIONS, ...(args[5] || {}) }
  const normalized = normalizeTravelGuideData(args[0], args[1], args[2], args[3], args[4])
  const edited = options.polished ? await editTravelGuideWithLLM(normalized) : normalized
  const guide = applyExportOptions(edited, options)
  const layout = buildTravelGuideLayout(guide, options)
  const blob = renderTravelGuideDocx(layout)
  return {
    blob,
    guide,
    usedLLM: options.polished && !guide.issues.some((issue) => issue.type === 'LLM_FAILED'),
    issues: guide.issues,
  }
}

function applyExportOptions(guide: TravelGuideSchema, options: ExportOptions): TravelGuideSchema {
  return {
    ...guide,
    days: guide.days.map((day) => ({
      ...day,
      food: options.includeFoods ? day.food : [],
      hotel: options.includeHotels ? day.hotel : undefined,
    })),
    foodRecommendations: options.includeFoods ? guide.foodRecommendations : [],
    hotels: options.includeHotels ? guide.hotels : [],
    packingList: options.includePacking ? guide.packingList : [],
    checklist48h: options.includeChecklist ? guide.checklist48h : [],
  }
}
