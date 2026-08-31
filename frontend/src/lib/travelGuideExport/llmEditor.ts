import { API, authFetch } from '../../api'
import { EXPORT_PROMPT_VERSION, type NormalizedTravelGuide, type TravelGuideSchema } from './schema'
import { fallbackTravelGuide, validateTravelGuideSchema } from './validator'

export async function editTravelGuideWithLLM(normalized: NormalizedTravelGuide): Promise<TravelGuideSchema> {
  const cacheKey = await exportCacheKey(normalized)
  const cached = readCachedGuide(cacheKey)
  if (cached) return validateTravelGuideSchema(cached, normalized)

  try {
    const res = await authFetch(`${API}/trips/${normalized.meta.travelPlanId}/export-guide/edit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt_version: EXPORT_PROMPT_VERSION,
        normalized,
      }),
    })
    if (!res.ok) throw new Error(`LLM 编辑接口失败：HTTP ${res.status}`)
    const body = await res.json()
    const guide = validateTravelGuideSchema(body.guide || body, normalized)
    writeCachedGuide(cacheKey, guide)
    return guide
  } catch (error) {
    return fallbackTravelGuide(normalized, error instanceof Error ? error.message : 'LLM 编辑失败，已使用原始数据生成精致攻略。')
  }
}

async function exportCacheKey(normalized: NormalizedTravelGuide): Promise<string> {
  const input = JSON.stringify({
    id: normalized.meta.travelPlanId,
    updatedAt: normalized.meta.sourceUpdatedAt,
    version: EXPORT_PROMPT_VERSION,
  })
  if (window.crypto?.subtle) {
    const bytes = new TextEncoder().encode(input)
    const digest = await window.crypto.subtle.digest('SHA-256', bytes)
    return `travel-guide-export:${Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('')}`
  }
  return `travel-guide-export:${btoa(unescape(encodeURIComponent(input))).slice(0, 80)}`
}

function readCachedGuide(key: string): TravelGuideSchema | null {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as TravelGuideSchema
  } catch {
    return null
  }
}

function writeCachedGuide(key: string, guide: TravelGuideSchema) {
  try {
    window.localStorage.setItem(key, JSON.stringify(guide))
  } catch {
    // localStorage quota should never block exporting.
  }
}
