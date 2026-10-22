export type PetPhase = 'idle' | 'working' | 'waiting' | 'ready' | 'stopped' | 'error'
export interface PetTask { phase: PetPhase; label: string; turn: string; detail?: string }
export interface PetMessage {
  id: string; role: string; content: string
  meta?: { streaming?: boolean; preliminary?: boolean; confirm?: { id: string }; handoff?: unknown; confirm_reply?: { confirm_id: string }; cancelled?: boolean; error?: unknown } | null
}

/** Read only the current turn. A completed historical answer never starts an animation. */
export function petTask(messages: readonly PetMessage[], running: boolean, stopped = false, error = false): PetTask {
  const index = messages.findLastIndex(m => m.role === 'user')
  const turn = index < 0 ? '' : messages[index].id
  const current = messages.slice(index + 1)
  const final = current.findLast(m => m.role === 'assistant' && !m.meta?.streaming && !m.meta?.preliminary && m.content.trim())
  if (error) return { phase: 'error', label: '这次没能完成，点开看看', turn }
  if (running) {
    const last = current.filter(m => m.role !== 'action').at(-1)
    const answered = current.some(m => m.meta?.confirm_reply?.confirm_id === last?.meta?.confirm?.id)
    if (last?.role === 'progress' && ((last.meta?.confirm && !answered) || last.meta?.handoff)) return { phase: 'waiting', label: '有件事需要你确认', turn }
    const detail = stopped ? undefined : last?.role === 'assistant' && last.meta?.streaming && last.content.trim() ? '正在写回复…' : last?.role === 'progress' ? petProgressText(last.content) : undefined
    return { phase: 'working', label: stopped ? '正在保存，稍等一下' : '正在整理你的旅行想法', turn, ...(detail ? { detail } : {}) }
  }
  if (stopped || final?.meta?.cancelled || final?.content.trim() === '已停止本轮。') return { phase: 'stopped', label: '已停下，随时可以继续', turn }
  if (final?.meta?.error || /^(模型服务（DeepSeek）暂时不可用|抱歉，处理过程中出错了)/.test(final?.content.trim() || '')) return { phase: 'error', label: '这次没能完成，点开看看', turn }
  if (final) return { phase: 'ready', label: '回复准备好啦', turn }
  return { phase: 'idle', label: '想去哪儿，我陪你想想', turn }
}

export interface PetPreferences { visible: boolean; quiet: boolean; side: 'left' | 'right'; tipsSeen?: string[] }
export const DEFAULT_PET_PREFERENCES: PetPreferences = { visible: true, quiet: false, side: 'right' }
export function readPetPreferences(raw: string | null): PetPreferences {
  try {
    const value = JSON.parse(raw || '{}')
    const tipsSeen = Array.isArray(value?.tipsSeen) ? value.tipsSeen.filter((id: unknown): id is string => typeof id === 'string').slice(0, 20) : []
    return { visible: typeof value?.visible === 'boolean' ? value.visible : true, quiet: value?.quiet === true, side: value?.side === 'left' ? 'left' : 'right', ...(tipsSeen.length ? { tipsSeen } : {}) }
  } catch { return { ...DEFAULT_PET_PREFERENCES } }
}

export function addedPetMembers(previous: readonly string[] | null, current: readonly string[], username: string): string[] {
  if (previous === null) return []
  const known = new Set(previous)
  return [...new Set(current)].filter(name => name && name !== username && !known.has(name))
}

export interface PetTrip {
  id: string; title: string; destination?: string | null; start_date?: string | null
  stops: { name: string; location?: string | null; start_time?: string | null; tags?: string[] | null }[]
}
export interface PetCheck { text: string; level: 'warn' | 'info' }
export function petPreparation(trip: PetTrip, issues: readonly { text: string; level?: string }[]): PetCheck[] {
  const items: PetCheck[] = []
  const add = (text: string, level: 'warn' | 'info' = 'info') => { if (!items.some(item => item.text === text)) items.push({ text, level }) }
  if (!trip.destination?.trim()) add('补充这次旅行的目的地')
  if (!trip.start_date?.trim()) add('确认并填写出发日期')
  if (!trip.stops.length) add('把想去的地方加入每日路线')
  const unlocated = trip.stops.filter(stop => {
    if (stop.tags?.includes('no_location')) return false
    const parts = stop.location?.split(',').map(part => part.trim())
    return !parts || parts.length !== 2 || parts.some(part => !part || !Number.isFinite(Number(part))) || Math.abs(Number(parts[0])) > 180 || Math.abs(Number(parts[1])) > 90
  }).length
  if (unlocated) add(`${unlocated} 个地点还需要补充地图位置`)
  const untimed = trip.stops.filter(stop => !stop.start_time?.trim()).length
  if (untimed) add(`${untimed} 个地点的游览时间还可补充`)
  for (const issue of issues) if (issue.text?.trim()) add(issue.text.trim(), issue.level === 'warn' ? 'warn' : 'info')
  return items
}

/** Small idle behaviours. Only calm phases play them; working/waiting already have their own loop. */
export const PET_ACTS = ['look', 'wave', 'map', 'stretch', 'hop'] as const
export type PetAct = typeof PET_ACTS[number]
export const PET_ACT_MS = 1800
export function petActAllowed(phase: PetPhase) { return phase === 'idle' || phase === 'ready' }
/** Never repeats the previous act, so two identical moves in a row don't read as a loop. */
export function nextPetAct(previous: PetAct | null, random = Math.random()): PetAct {
  const pool = PET_ACTS.filter(act => act !== previous)
  return pool[Math.min(pool.length - 1, Math.floor(Math.max(0, random) * pool.length))]
}
/** Gap before the next act: 6–12s, so the pet feels alive without demanding attention. */
export function petActDelay(random = Math.random()) { return 6000 + Math.round(Math.max(0, Math.min(1, random)) * 6000) }

interface PetRect { left: number; top: number; width: number; height: number }
/** Jump from the dock into the AI header: crouch, arc over, land at the target size. Origin is top-left. */
export function petFlightFrames(from: PetRect, to: PetRect) {
  const dx = to.left - from.left, dy = to.top - from.top
  const scale = from.width ? to.width / from.width : 1
  const lift = Math.min(120, Math.max(48, Math.abs(dy) * 0.25))
  const mid = 1 + (scale - 1) * 0.6
  return [
    { offset: 0, transform: 'translate(0px, 0px) scale(1) rotate(0deg)' },
    { offset: 0.16, transform: 'translate(0px, 6px) scale(1.08, 0.9) rotate(0deg)' },
    { offset: 0.55, transform: `translate(${Math.round(dx * 0.6)}px, ${Math.round(dy * 0.6 - lift)}px) scale(${mid.toFixed(3)}) rotate(-10deg)` },
    { offset: 1, transform: `translate(${Math.round(dx)}px, ${Math.round(dy)}px) scale(${scale.toFixed(3)}) rotate(0deg)` },
  ]
}

/** 进度消息变成气泡里的一句话：取首行、去掉开头的表情/符号、网址只留域名、过长截断。 */
export const PET_BUBBLE_MAX = 22
export function petProgressText(content: string): string | undefined {
  const line = content.split('\n').map(part => part.trim()).find(Boolean)
  if (!line) return undefined
  const text = line
    .replace(/https?:\/\/(?:www\.)?([^/\s]+)\S*/g, '$1')
    .replace(/[*`#>_]+/g, '')
    .replace(/^[^\p{L}\p{N}]+/u, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return undefined
  const chars = [...text]
  return chars.length > PET_BUBBLE_MAX ? `${chars.slice(0, PET_BUBBLE_MAX - 1).join('')}…` : text
}

/** 新手指引：每条只说一次（记在当前设备的用户偏好里），按顺序来。 */
export const PET_TIPS = [
  { id: 'ask', text: '想去哪儿？点我直接问 AI', action: 'ask' },
  { id: 'tools', text: '长按我，能检查行程还缺什么', action: 'tools' },
  { id: 'drag', text: '挡住内容了？把我拖到另一边', action: 'dismiss' },
] as const
export type PetTip = typeof PET_TIPS[number]
export function nextPetTip(seen: readonly string[] | undefined, phase: PetPhase): PetTip | null {
  if (phase !== 'idle' && phase !== 'ready') return null
  return PET_TIPS.find(tip => !seen?.includes(tip.id)) ?? null
}

export type PetBubble = { kind: 'progress' | 'waiting' | 'error' | 'done'; text: string } | { kind: 'tip'; text: string; tip: PetTip }
/** 停靠处气泡选哪条：任务状态优先于指引，指引只在空闲时出现。 */
/** 完成提醒带上对话名（点进去去的就是它）；没名字或「新对话」退回通用文案。与 iOS TravelPetLogic.bubble 一致。 */
export function petDoneText(title?: string | null): string {
  const name = (title || '').trim()
  if (!name || name === '新对话') return '回复准备好啦，点我看看'
  return `「${[...name].length > 10 ? [...name].slice(0, 9).join('') + '…' : name}」写好啦，点我看看`
}

export function petBubble(task: PetTask, finished: boolean, tip: PetTip | null, title?: string | null): PetBubble | null {
  if (task.phase === 'waiting') return { kind: 'waiting', text: '有件事需要你确认，点我去看看' }
  if (task.phase === 'error') return { kind: 'error', text: '这次没能完成，点我看看' }
  if (task.phase === 'working') return { kind: 'progress', text: task.detail || task.label }
  if (finished) return { kind: 'done', text: petDoneText(title) }
  if (tip) return { kind: 'tip', text: tip.text, tip }
  return null
}
