/**
 * Content Cleaner
 * 内容清洗层：无效地点过滤、Markdown 清洗、去重、NULL 处理、Duration 校验、隐私过滤
 * 纯函数，不依赖渲染，供 Guide Composer 调用
 */

// ===== 无效地点过滤 =====
// 这些词单独出现时不是地点，是行为/占位符
const INVALID_PLACE_WORDS = [
  '时间', '待定', '入住', '退房', '吃饭', '晚饭', '午饭', '早饭',
  '返回', '出发', '集合', '休息', '自由活动', 'TBD', '待安排',
]

// 行为描述映射：无法生成地点名时的兜底
const ACTION_FALLBACKS: Array<{ test: RegExp; label: string }> = [
  { test: /入住|check.?in/i, label: '入住酒店' },
  { test: /退房|check.?out/i, label: '退房' },
  { test: /早餐|早饭/i, label: '早餐' },
  { test: /午餐|午饭|中饭/i, label: '午餐' },
  { test: /晚餐|晚饭/i, label: '晚餐' },
  { test: /集合/i, label: '集合' },
  { test: /返回|回程|返程/i, label: '返程' },
]

// 行为标签集合：这些是"行为"不是"地点"，路线摘要里应剔除（时间线里保留）
const ACTION_LABELS = new Set(['入住酒店', '退房', '早餐', '午餐', '晚餐', '集合', '返程'])

/** 判断展示名是不是纯行为标签（用于路线摘要过滤，时间线不过滤） */
export function isActionLabel(name: string): boolean {
  const t = (name || '').trim()
  if (ACTION_LABELS.has(t)) return true
  // "冲洗，吃饭" / "返回酒店" 这类以行为动词为主的短句
  if (/^(冲洗|吃饭|返回|退房|集合|出发|休息)/.test(t) && t.length <= 6) return true
  return false
}

/**
 * 判断一个名称是否是无效地点（纯占位/纯行为词）
 */
/** 剥离常见类型前缀（🏨🛩️✈️🚗🚕等），保留品牌 emoji */
function stripLeadingSymbols(name: string): string {
  // 用 u flag + Unicode 属性按 code point 剥离前导 emoji/符号/空白，
  // 不能把多 code point 的 emoji 塞进无 u flag 的字符类（会拆坏代理对）
  return (name || '')
    .replace(/^(?:[\p{Extended_Pictographic}️‍\s])+/u, '')
    .trim()
}

export function isInvalidPlaceName(name: string): boolean {
  const trimmed = stripLeadingSymbols(name)
  if (!trimmed) return true
  // 完全等于无效词
  if (INVALID_PLACE_WORDS.includes(trimmed)) return true
  // 纯时间格式："20 min" / "09:30" / "上午"
  if (/^\d{1,2}:\d{2}$/.test(trimmed)) return true
  if (/^\d+\s*(?:min|分钟|小时|h|hour)$/i.test(trimmed)) return true
  if (/^(?:上午|下午|早上|中午|晚上|傍晚)$/.test(trimmed)) return true
  return false
}

/**
 * 生成有效的展示名称。无法生成时用行为描述兜底，绝不返回"待定"
 * @returns 有效名称，或 null（应该被过滤掉的节点）
 */
export function resolveDisplayName(name: string, note?: string): string | null {
  const trimmed = (name || '').trim()

  // 有效名称直接用
  if (trimmed && !isInvalidPlaceName(trimmed)) return trimmed

  // 尝试从名称或备注推断行为描述
  const source = `${trimmed} ${note || ''}`
  for (const fallback of ACTION_FALLBACKS) {
    if (fallback.test.test(source)) return fallback.label
  }

  // 实在无法生成有效名称 → 过滤掉这个节点
  return null
}

// ===== NULL / 待定 处理 =====
/**
 * 清理值：空/待定/null 返回 undefined，让渲染层直接隐藏
 */
export function cleanNullable(value: string | null | undefined): string | undefined {
  const trimmed = (value || '').trim()
  if (!trimmed) return undefined
  if (/^(待定|TBD|待安排|未定|无|N\/A)$/i.test(trimmed)) return undefined
  return stripSourceMetadata(trimmed)
}

/**
 * 清除来源平台字段（如"去哪儿网"/"携程"/"马蜂窝"/"来源："）
 */
export function stripSourceMetadata(text: string): string {
  return (text || '')
    // 括号包裹的来源整体删；无括号时只删到下一个空格/标点，不吞掉后续有效内容
    .replace(/[（(]\s*来源[:：]?[^）)\n]*[）)]/g, '')
    .replace(/来源[:：]?[^\s，。、；,.]*/g, '')
    // 中文无词边界，不能用 \b；直接匹配平台名
    .replace(/去哪儿网?|携程旅行?|携程|马蜂窝|飞猪旅行?|同程旅行?/g, '')
    .replace(/(tripadvisor|booking\.com)/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
}

// ===== Markdown 清洗 =====
export type RichTextSegment = {
  text: string
  bold?: boolean
  italic?: boolean
}

export type RichTextBlock = {
  type: 'paragraph' | 'list-item'
  segments: RichTextSegment[]
}

/**
 * 解析 Markdown 为结构化 RichText 块
 * 支持：**bold** *italic* - list、换行
 */
export function parseMarkdown(text: string): RichTextBlock[] {
  const cleaned = (text || '').trim()
  if (!cleaned) return []

  const lines = cleaned.split(/\r\n|\r|\n/)
  const blocks: RichTextBlock[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    // 列表项
    const listMatch = trimmed.match(/^[-*+]\s+(.*)$/)
    if (listMatch) {
      blocks.push({ type: 'list-item', segments: parseInlineMarkdown(listMatch[1]) })
      continue
    }

    // 去掉标题标记 ## ，作为普通段落
    const headingStripped = trimmed.replace(/^#{1,6}\s+/, '')
    blocks.push({ type: 'paragraph', segments: parseInlineMarkdown(headingStripped) })
  }

  return blocks
}

/**
 * 解析行内 Markdown：**bold** *italic*
 */
export function parseInlineMarkdown(text: string): RichTextSegment[] {
  const segments: RichTextSegment[] = []
  // 匹配 **bold** 或 *italic*
  const regex = /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index) })
    }
    if (match[2] !== undefined) {
      segments.push({ text: match[2], bold: true })
    } else if (match[4] !== undefined) {
      segments.push({ text: match[4], italic: true })
    }
    lastIndex = regex.lastIndex
  }

  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex) })
  }

  return segments.length ? segments : [{ text }]
}

/**
 * 把 Markdown 转成纯文本（去掉所有控制字符），用于不支持 RichText 的场景
 */
export function stripMarkdown(text: string): string {
  return (text || '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')   // **bold**
    .replace(/\*([^*]+)\*/g, '$1')        // *italic*
    .replace(/^#{1,6}\s+/gm, '')          // ## heading
    .replace(/^[-*+]\s+/gm, '')           // - list
    .replace(/`([^`]+)`/g, '$1')          // `code`
    .trim()
}

// ===== 文本相似度去重 =====
/**
 * 计算两段文本的相似度（0-1），基于字符级 Jaccard
 */
export function textSimilarity(a: string, b: string): number {
  const sa = new Set((a || '').replace(/\s/g, '').split(''))
  const sb = new Set((b || '').replace(/\s/g, '').split(''))
  if (sa.size === 0 && sb.size === 0) return 1
  if (sa.size === 0 || sb.size === 0) return 0

  let intersection = 0
  sa.forEach((ch) => { if (sb.has(ch)) intersection += 1 })
  const union = sa.size + sb.size - intersection
  return union > 0 ? intersection / union : 0
}

/**
 * 从一组文本中去除相似度过高的重复项（保留第一个）
 */
export function dedupeTexts(texts: string[], threshold = 0.85): string[] {
  const result: string[] = []
  for (const text of texts) {
    const cleaned = (text || '').trim()
    if (!cleaned) continue
    const isDupe = result.some((kept) => textSimilarity(kept, cleaned) >= threshold)
    if (!isDupe) result.push(cleaned)
  }
  return result
}

// ===== Duration 校验 =====
/**
 * 校验并计算时长。优先用 end-start 计算，源值偏差>30min 用计算值，无结束时间返回 null
 * @returns 格式化的时长字符串，或 null（应隐藏）
 */
export function validateDuration(
  startTime: string | undefined,
  endTime: string | undefined,
  sourceDurationMin?: number | null,
): string | null {
  const start = parseTimeToMinutes(startTime)
  const end = parseTimeToMinutes(endTime)

  // 有起止时间 → 计算真实时长（最可信）
  if (start !== null && end !== null && end > start) {
    const calculated = end - start
    // 源值与计算值差 > 30min，用计算值（防止源值明显失真，如 1.5h 船程写成 5h）
    if (sourceDurationMin != null && Math.abs(sourceDurationMin - calculated) <= 30) {
      return formatDuration(sourceDurationMin)
    }
    return formatDuration(calculated)
  }

  // 无结束时间但正文里作者明确写了时长 → 用作者原文（note prose，非失真的结构化字段）
  // 只接受合理范围，过滤掉 note 里跨天/异常的数字
  if (sourceDurationMin != null && sourceDurationMin > 0 && sourceDurationMin <= 12 * 60) {
    return formatDuration(sourceDurationMin)
  }

  return null
}

function parseTimeToMinutes(time: string | undefined): number | null {
  if (!time) return null
  const match = time.match(/^(\d{1,2}):(\d{2})$/)
  if (!match) return null
  return Number(match[1]) * 60 + Number(match[2])
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return mins > 0 ? `${hours}h ${mins}min` : `${hours}h`
}

// ===== 隐私过滤（Field Whitelist）=====
// PRD 第 31 条：好友版用白名单机制
const PRIVATE_PATTERNS = [
  /admin/i,
  /payer|付款人|付款/,
  /creator|owner|创建者|编辑者/,
  /user_?id|member_?id|record_?id/i,
]

/**
 * 判断字符串是否含敏感信息（用户名/admin/付款人等）
 */
export function containsPrivateInfo(text: string): boolean {
  return PRIVATE_PATTERNS.some((p) => p.test(text || ''))
}

/**
 * 好友版：把成员姓名列表转成简单勾选（不暴露姓名）
 * @returns "✓" 表示已带，空表示未处理
 */
export function anonymizePackedStatus(packedBy: string[]): string {
  if (packedBy.length > 0) return '✓'
  return ''
}

// ===== Tips 原子化 =====
export type AtomicTip = {
  content: string
  level?: 'warning' | 'info'
}

/**
 * 将一个复合 Tip 拆分成原子 Tips（一个 Tip 一个主题）
 * 例如："MDAC 提前三天填好；亚庇机场不能带水" → 两条原子 Tip
 * 拆分规则：以 "；" / "\n" / "、同时" 等分隔符为边界
 */
export function atomizeTip(rawContent: string, level?: string): AtomicTip[] {
  const cleaned = stripMarkdown(rawContent).trim()
  if (!cleaned) return []

  // 按多种分隔符拆分（中文分号、换行、句号+换行）
  const segments = cleaned
    .split(/；|\n|。\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean)

  // 每段独立成 Tip，继承原 level
  return segments.map((content) => ({
    content,
    level: level === 'important' ? ('warning' as const) : level === 'notice' ? ('info' as const) : undefined,
  }))
}
