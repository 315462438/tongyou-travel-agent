import type { GuideIssue, NormalizedTravelGuide, TravelGuideSchema } from './schema'

export function validateTravelGuideSchema(
  candidate: TravelGuideSchema,
  normalized: NormalizedTravelGuide,
): TravelGuideSchema {
  const repaired = repairShape(candidate, normalized)
  const issues = [...normalized.issues, ...(repaired.issues || [])]

  normalized.hardFacts.times.forEach((fact) => {
    const day = repaired.days.find((d) => d.day === fact.day)
    const item = day?.timeline.find((entry) => entry.sourceId === fact.sourceId)
    if (item && item.time !== fact.time) {
      issues.push({
        type: 'HARD_INFO_CHANGED',
        severity: 'critical',
        day: fact.day,
        sourceIds: fact.sourceId ? [fact.sourceId] : undefined,
        message: `LLM 修改了 Day ${fact.day} 的硬时间：${fact.time} -> ${item.time}`,
      })
      item.time = fact.time
    }
  })

  const hotelNames = new Set(normalized.hardFacts.hotelNames.map(normalizeKey))
  repaired.hotels.forEach((hotel) => {
    if (hotel.name && hotelNames.size > 0 && !hotelNames.has(normalizeKey(hotel.name))) {
      issues.push({ type: 'HARD_INFO_CHANGED', severity: 'critical', message: `LLM 返回了不存在的酒店名称：${hotel.name}` })
    }
  })
  repaired.days.forEach((day) => {
    if (day.hotel?.name && hotelNames.size > 0 && !hotelNames.has(normalizeKey(day.hotel.name))) {
      issues.push({ type: 'HARD_INFO_CHANGED', severity: 'critical', day: day.day, message: `LLM 修改了 Day ${day.day} 的酒店名称：${day.hotel.name}` })
      const original = normalized.days.find((d) => d.day === day.day)?.hotel
      if (original) day.hotel = original
    }
  })

  repaired.meta.travelPlanId = normalized.meta.travelPlanId
  repaired.meta.promptVersion = normalized.meta.promptVersion
  repaired.meta.sourceUpdatedAt = normalized.meta.sourceUpdatedAt
  repaired.meta.dateRange = normalized.meta.dateRange
  repaired.meta.days = normalized.meta.days
  repaired.meta.nights = normalized.meta.nights
  repaired.days = repaired.days
    .filter((day) => Number.isFinite(day.day))
    .sort((a, b) => a.day - b.day)
    .map((day) => {
      const source = normalized.days.find((d) => d.day === day.day)
      return {
        ...day,
        date: source?.date || day.date,
        timeline: (day.timeline || []).sort((a, b) => timeValue(a.time) - timeValue(b.time)),
      }
    })
  repaired.issues = dedupeIssues(issues)
  return repaired
}

export function fallbackTravelGuide(normalized: NormalizedTravelGuide, reason: string): TravelGuideSchema {
  return {
    ...normalized,
    issues: [
      ...normalized.issues,
      { type: 'LLM_FAILED', severity: 'warning', message: reason },
    ],
  }
}

function repairShape(candidate: TravelGuideSchema, normalized: NormalizedTravelGuide): TravelGuideSchema {
  return {
    meta: { ...normalized.meta, ...(candidate?.meta || {}) },
    summary: { ...normalized.summary, ...(candidate?.summary || {}) },
    days: Array.isArray(candidate?.days) && candidate.days.length ? candidate.days : normalized.days,
    foodRecommendations: Array.isArray(candidate?.foodRecommendations) ? candidate.foodRecommendations : normalized.foodRecommendations,
    hotels: Array.isArray(candidate?.hotels) ? candidate.hotels : normalized.hotels,
    packingList: Array.isArray(candidate?.packingList) ? candidate.packingList : normalized.packingList,
    beforeDeparture: Array.isArray(candidate?.beforeDeparture) ? candidate.beforeDeparture : normalized.beforeDeparture,
    checklist48h: Array.isArray(candidate?.checklist48h) ? candidate.checklist48h : normalized.checklist48h,
    importantNotes: Array.isArray(candidate?.importantNotes) ? candidate.importantNotes : normalized.importantNotes,
    issues: Array.isArray(candidate?.issues) ? candidate.issues as GuideIssue[] : [],
  }
}

function timeValue(value: string): number {
  const match = String(value || '').match(/^(\d{1,2}):(\d{2})$/)
  return match ? Number(match[1]) * 60 + Number(match[2]) : 9999
}

function normalizeKey(value: string): string {
  return String(value || '').toLowerCase().replace(/\s+/g, '').replace(/[·・\-—–_（）()]/g, '')
}

function dedupeIssues(issues: GuideIssue[]): GuideIssue[] {
  const seen = new Set<string>()
  return issues.filter((issue) => {
    const key = `${issue.type}|${issue.day || ''}|${issue.message}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}
