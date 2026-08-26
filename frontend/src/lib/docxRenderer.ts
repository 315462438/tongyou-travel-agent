/**
 * DOCX 渲染器
 * 将 ShareGuideSchema 转换为 DOCX Blob
 */

import type {
  ShareGuideSchema,
  CoverSection,
  OverviewSection,
  DaySection,
  DayHighlight,
  EventCard,
  Badge,
  TipCard,
  FoodSection,
  FoodCityGroup,
  RestaurantCard,
  StaySection,
  HotelCard,
  TipsSection,
  TipCategory,
  PackingSection,
  PackingGroup,
  BudgetSection,
} from './shareGuideSchema'
import { FONT_SIZES, SPACING, COLORS } from './guideStyles'

/**
 * 主函数：渲染 ShareGuideSchema 为 DOCX Blob
 */
export function renderShareGuideDocx(schema: ShareGuideSchema): Blob {
  const sections: string[] = []

  // Page 1：封面独占（PRD 第 8 条）
  sections.push(renderCover(schema.cover))
  sections.push(pageBreak())

  // Page 2：行程总览独占（PRD 第 9 条）
  sections.push(renderOverview(schema.overview))
  sections.push(pageBreak())

  // Page 3+：每日攻略。DayLabel 自带间距+keepNext 分隔，无需 divider（省空间）
  schema.days.forEach((day) => {
    sections.push(renderDay(day))
  })

  // 美食：新章节起页（美食是大板块，独立成页合理）
  if (schema.foods.cityGroups.length > 0) {
    sections.push(pageBreak())
    sections.push(renderFoods(schema.foods))
  }

  // 住宿：不强制分页，接美食后自然流动（PRD §39 动态布局）
  if (schema.stays.hotels.length > 0) {
    sections.push(divider())
    sections.push(renderStays(schema.stays))
  }

  // 避坑：不强制分页，自然流动
  if (schema.tips.categories.length > 0) {
    sections.push(divider())
    sections.push(renderTips(schema.tips))
  }

  // 行李：物品 <5 件不独占页面（PRD 第 30 条），跟在避坑后面用 divider 分隔
  if (schema.packing) {
    const itemCount = schema.packing.groups.reduce((sum, g) => sum + g.items.length, 0)
    sections.push(itemCount >= 5 ? pageBreak() : divider())
    sections.push(renderPacking(schema.packing))
  }

  // 预算：无数据（总额 0 且无明细）不渲染，避免空页
  if (schema.budget && ((schema.budget.total ?? 0) > 0 || (schema.budget.entries?.length ?? 0) > 0)) {
    sections.push(divider())
    sections.push(renderBudget(schema.budget))
  }

  return buildDocxBlob(sections.join(''))
}

// ===== 封面 =====
function renderCover(cover: CoverSection): string {
  return `
    ${p(cover.region, 'CoverLabel', { after: SPACING.sm })}
    ${p(cover.title, 'CoverTitle', { after: SPACING.md })}
    ${cover.subtitle ? p(cover.subtitle, 'CoverSubtitle', { after: SPACING.lg }) : ''}
    ${p(`${cover.days} DAYS · ${cover.nights} NIGHTS`, 'CoverMeta', { after: SPACING.sm })}
    ${p(cover.dateRange, 'CoverMeta', { after: SPACING.lg })}
    ${cover.tags.length > 0 ? p(cover.tags.join(' · '), 'CoverTags', { after: SPACING.xxl }) : ''}
  `
}

// ===== 总览 =====
function renderOverview(overview: OverviewSection): string {
  const { timeline, stats } = overview

  const tableRows = timeline.map((day) => {
    return tableRow([
      { text: `Day ${day.day}`, style: 'TableCell' },
      { text: day.date, style: 'TableCell' },
      { text: day.weekday, style: 'TableCell' },
      { text: day.city, style: 'TableCell' },
      { text: day.theme, style: 'TableCell' },
      { text: day.hotel, style: 'TableCell' },
    ])
  })

  const statsText = [
    `${stats.totalDays} 天`,
    `${stats.cities.join('、')}`,
    `${stats.hotels} 家酒店`,
    stats.highlights.length > 0 ? stats.highlights.join('、') : '',
  ].filter(Boolean).join(' · ')

  return `
    ${p('行程总览', 'SectionTitle', { before: SPACING.lg, after: SPACING.lg })}
    ${table(
      [60, 60, 60, 80, 200, 120],
      tableRow([
        { text: 'Day', style: 'TableHeader' },
        { text: '日期', style: 'TableHeader' },
        { text: '星期', style: 'TableHeader' },
        { text: '城市', style: 'TableHeader' },
        { text: '今日主题', style: 'TableHeader' },
        { text: '住宿', style: 'TableHeader' },
      ]),
      ...tableRows
    )}
    ${p(statsText, 'BodySmall', { before: SPACING.lg })}
  `
}

// ===== 每日攻略 =====
function renderDay(day: DaySection): string {
  const route = day.route.length > 0 ? day.route.join(' → ') : ''
  const metaLine = [day.monthLabel, day.city].filter(Boolean).join('     ')

  // DayLabel keepNext 避免标题留页尾；缩小天间距让短天可与相邻天共页（PRD §39）
  return `
    ${p(`DAY ${String(day.day).padStart(2, '0')}`, 'DayLabel', { before: SPACING.md, after: SPACING.xs, keepNext: true })}
    ${metaLine ? p(metaLine, 'DayMeta', { after: SPACING.xs, keepNext: true }) : ''}
    ${p(day.theme, 'DayTitle', { after: SPACING.xs, keepNext: true })}
    ${day.dayTags.length ? p(day.dayTags.join('   '), 'DayMeta', { after: SPACING.sm }) : ''}
    ${route ? p(route, 'DayRoute', { after: SPACING.md }) : ''}
    ${day.highlight ? renderHighlightCard(day.highlight) : ''}
    ${day.events.map(renderEventCard).join('')}
  `
}

function renderHighlightCard(h: DayHighlight): string {
  const sub = [h.places.join(' / '), h.tags.join('  ')].filter(Boolean).join('\n')
  return `
    <w:p>
      <w:pPr>
        <w:shd w:fill="${COLORS.primaryLight}"/>
        <w:spacing w:before="${SPACING.sm}" w:after="0"/>
        <w:keepNext/>
      </w:pPr>
      <w:r><w:rPr><w:b/><w:color w:val="${COLORS.primaryDark}"/><w:sz w:val="${FONT_SIZES.placeName}"/></w:rPr><w:t>⭐ 今日重点：${escapeXml(h.title)}</w:t></w:r>
    </w:p>
    ${sub ? `<w:p><w:pPr><w:shd w:fill="${COLORS.primaryLight}"/><w:spacing w:before="0" w:after="${SPACING.md}"/></w:pPr><w:r><w:rPr><w:color w:val="${COLORS.textLight}"/><w:sz w:val="${FONT_SIZES.eventDesc}"/></w:rPr>${sub.split('\n').map((l, i) => `${i ? '<w:br/>' : ''}<w:t xml:space="preserve">${escapeXml(l)}</w:t>`).join('')}</w:r></w:p>` : ''}
  `
}

function renderEventCard(event: EventCard): string {
  const timeCol = event.time ? `
    <w:tc>
      <w:tcPr><w:tcW w:w="1200" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>
      ${p(event.time, 'EventTime')}
    </w:tc>
  ` : ''

  const mainCol = `
    <w:tc>
      <w:tcPr><w:tcW w:w="${event.time ? '7800' : '9000'}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>
      ${p(event.place, 'PlaceName', { after: SPACING.xs })}
      ${event.description ? p(event.description, 'EventDesc', { after: SPACING.xs }) : ''}
      ${event.badges.length > 0 ? renderBadges(event.badges) : ''}
      ${event.tips ? event.tips.map(renderTipCard).join('') : ''}
    </w:tc>
  `

  return `
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="9000" w:type="dxa"/>
        <w:tblBorders>
          <w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/>
          <w:insideH w:val="none"/><w:insideV w:val="none"/>
        </w:tblBorders>
        <w:tblCellMar>
          <w:top w:w="0" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>
          <w:bottom w:w="${SPACING.md}" w:type="dxa"/><w:right w:w="0" w:type="dxa"/>
        </w:tblCellMar>
      </w:tblPr>
      <w:tblGrid>
        ${event.time ? '<w:gridCol w:w="1200"/>' : ''}
        <w:gridCol w:w="${event.time ? '7800' : '9000'}"/>
      </w:tblGrid>
      <w:tr>
        ${timeCol}
        ${mainCol}
      </w:tr>
    </w:tbl>
  `
}

function renderBadges(badges: Badge[]): string {
  const separator = `<w:r><w:rPr><w:sz w:val="${FONT_SIZES.badge}"/></w:rPr><w:t xml:space="preserve">    </w:t></w:r>`
  const badgeRuns = badges.map((badge) => {
    const color = badge.type === 'cost' ? COLORS.primary : COLORS.muted
    return `<w:r>
      <w:rPr><w:color w:val="${color}"/><w:sz w:val="${FONT_SIZES.badge}"/></w:rPr>
      <w:t xml:space="preserve">${badge.icon} ${escapeXml(badge.label)}</w:t>
    </w:r>`
  }).join(separator)

  return `<w:p><w:pPr><w:spacing w:after="${SPACING.sm}"/></w:pPr>${badgeRuns}</w:p>`
}

function renderTipCard(tip: TipCard): string {
  const bgColor = tip.level === 'warning' ? COLORS.bgWarn : tip.level === 'info' ? COLORS.bgInfo : COLORS.bg
  const textColor = tip.level === 'warning' ? COLORS.textWarn : tip.level === 'info' ? COLORS.textInfo : COLORS.text

  // title 与 content 高度相似时只显示 title（避免"MDAC提前3天 / MDAC提前3天"重复）
  const showContent = tip.content && !tipTextsAlike(tip.title, tip.content)

  return `
    <w:p>
      <w:pPr>
        <w:shd w:fill="${bgColor}"/>
        <w:spacing w:before="${SPACING.sm}" w:after="${SPACING.xs}"/>
        <w:ind w:left="${SPACING.lg}" w:right="${SPACING.lg}"/>
        ${showContent ? '<w:keepNext/>' : ''}
      </w:pPr>
      <w:r>
        <w:rPr><w:color w:val="${textColor}"/><w:sz w:val="${FONT_SIZES.tipTitle}"/><w:b/></w:rPr>
        <w:t>${tip.icon} ${escapeXml(tip.title)}</w:t>
      </w:r>
    </w:p>
    ${showContent ? `<w:p>
      <w:pPr>
        <w:shd w:fill="${bgColor}"/>
        <w:spacing w:after="${SPACING.sm}"/>
        <w:ind w:left="${SPACING.lg}" w:right="${SPACING.lg}"/>
      </w:pPr>
      <w:r>
        <w:rPr><w:color w:val="${COLORS.text}"/><w:sz w:val="${FONT_SIZES.tipContent}"/></w:rPr>
        ${textWithBreaks(tip.content)}
      </w:r>
    </w:p>` : ''}
  `
}

/** 两段文本是否高度相似（字符级 Jaccard > 0.85），用于隐藏与标题重复的正文 */
function tipTextsAlike(a: string, b: string): boolean {
  const sa = new Set((a || '').replace(/\s/g, '').split(''))
  const sb = new Set((b || '').replace(/\s/g, '').split(''))
  if (sa.size === 0 || sb.size === 0) return false
  let inter = 0
  sa.forEach((c) => { if (sb.has(c)) inter += 1 })
  return inter / (sa.size + sb.size - inter) > 0.85
}

// ===== 美食 =====
function renderFoods(foods: FoodSection): string {
  return `
    ${p('美食推荐', 'SectionTitle', { before: SPACING.lg, after: SPACING.lg })}
    ${foods.cityGroups.map(renderFoodCityGroup).join('')}
  `
}

function renderFoodCityGroup(group: FoodCityGroup): string {
  return `
    ${p(group.city, 'CityLabel', { before: SPACING.lg, after: SPACING.md })}
    ${twoColumnGrid(group.top.map((r) => renderRestaurantCard(r, true)))}
    ${group.more.length > 0 ? p(`其他收藏 (${group.more.length})`, 'BodySmall', { before: SPACING.md, after: SPACING.sm }) : ''}
    ${group.more.length > 0 ? twoColumnGrid(group.more.map((r) => renderRestaurantCard(r, false))) : ''}
  `
}

function renderRestaurantCard(card: RestaurantCard, isTop: boolean): string {
  const meta = [
    card.category,
    card.pricePerPerson ? `人均 ¥${card.pricePerPerson}` : '',
    card.rating ? `⭐ ${card.rating}` : '',
  ].filter(Boolean).join(' · ')

  const dishes = card.dishes?.length ? card.dishes.join('、') : ''
  const reason = card.reason || ''
  // Top 餐厅字号更大更突出，more 收藏用小一号
  const nameSize = isTop ? FONT_SIZES.restaurantName : FONT_SIZES.hotelMeta

  return `
    <w:p>
      <w:pPr>
        <w:spacing w:before="${SPACING.md}" w:after="${SPACING.xs}"/>
        <w:keepNext/>
      </w:pPr>
      <w:r>
        <w:rPr><w:color w:val="${COLORS.ink}"/><w:sz w:val="${nameSize}"/><w:b/></w:rPr>
        <w:t>${escapeXml(card.name)}</w:t>
      </w:r>
    </w:p>
    ${meta ? p(meta, 'RestaurantMeta', { after: SPACING.xs }) : ''}
    ${isTop && dishes ? p(`推荐：${dishes}`, 'BodySmall', { after: SPACING.xs }) : ''}
    ${isTop && reason ? p(reason, 'BodySmall', { after: SPACING.sm }) : ''}
  `
}

// ===== 住宿 =====
function renderStays(stays: StaySection): string {
  return `
    ${p('住宿安排', 'SectionTitle', { before: SPACING.lg, after: SPACING.lg })}
    ${twoColumnGrid(stays.hotels.map(renderHotelCard))}
  `
}

function renderHotelCard(card: HotelCard): string {
  const meta = [
    card.city,
    `${card.checkIn} - ${card.checkOut}`,
    `${card.nights} 晚`,
    card.pricePerNight ? `¥${card.pricePerNight}/晚` : '',
  ].filter(Boolean).join(' · ')

  return `
    <w:p>
      <w:pPr>
        <w:spacing w:before="${SPACING.md}" w:after="${SPACING.xs}"/>
        <w:keepNext/>
      </w:pPr>
      <w:r>
        <w:rPr><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.hotelName}"/><w:b/></w:rPr>
        <w:t>${escapeXml(card.name)}</w:t>
      </w:r>
    </w:p>
    ${p(meta, 'HotelMeta', { after: SPACING.sm })}
    ${card.note ? p(card.note, 'BodySmall', { after: SPACING.sm }) : ''}
  `
}

// ===== 避坑 =====
function renderTips(tips: TipsSection): string {
  return `
    ${p('出发前一定要看', 'SectionTitle', { before: SPACING.lg, after: SPACING.lg })}
    ${tips.categories.map(renderTipCategory).join('')}
  `
}

function renderTipCategory(category: TipCategory): string {
  // 分类标题 keepNext：不让标题留在页尾、内容掉下一页
  return `
    ${p(`${category.icon} ${category.title}`, 'CategoryLabel', { before: SPACING.lg, after: SPACING.md, keepNext: true })}
    ${category.tips.map(renderTipCard).join('')}
  `
}

// ===== 行李 =====
function renderPacking(packing: PackingSection): string {
  return `
    ${p('行李清单', 'SectionTitle', { before: SPACING.lg, after: SPACING.lg })}
    ${packing.groups.map(renderPackingGroup).join('')}
  `
}

function renderPackingGroup(group: PackingGroup): string {
  const rows = group.items.map((item) => {
    const status = renderPackStatus(item.packedBy, item.unpackedBy)
    return tableRow([
      { text: item.name, style: 'TableCell' },
      { text: status, style: 'TableCell' },
    ])
  })

  return `
    ${p(`${group.category}（共 ${group.items.length} 件）`, 'CategoryLabel', { before: SPACING.lg, after: SPACING.md })}
    ${table(
      [300, 260],
      tableRow([
        { text: '物品', style: 'TableHeader' },
        { text: '状态', style: 'TableHeader' },
      ]),
      ...rows
    )}
  `
}

function renderPackStatus(packedBy: string[], unpackedBy: string[]): string {
  // 好友版：packedBy = ['✓'] 表示已带但不暴露姓名
  if (packedBy.length === 1 && packedBy[0] === '✓') return '✓'
  // 个人完整版：显示成员姓名
  if (packedBy.length > 0) return `已带：${packedBy.join('、')}`
  if (unpackedBy.length > 0) return `未带：${unpackedBy.join('、')}`
  return '—'
}

// ===== 预算 =====
function renderBudget(budget: BudgetSection): string {
  const breakdownRows = budget.breakdown.map((item) => {
    return tableRow([
      { text: item.category, style: 'TableCell' },
      { text: `¥${item.amount}`, style: 'TableCell' },
      { text: `${item.percentage}%`, style: 'TableCell' },
    ])
  })

  // 详细记账条目
  const entriesTable = budget.entries && budget.entries.length > 0 ? `
    ${p('详细记账', 'CategoryLabel', { before: SPACING.xl, after: SPACING.md })}
    ${table(
      [240, 100, 100, 120],
      tableRow([
        { text: '项目', style: 'TableHeader' },
        { text: '分类', style: 'TableHeader' },
        { text: '金额', style: 'TableHeader' },
        { text: '付款人', style: 'TableHeader' },
      ]),
      ...budget.entries.map((entry) =>
        tableRow([
          { text: entry.title, style: 'TableCell' },
          { text: entry.category, style: 'TableCell' },
          { text: `¥${entry.amount}`, style: 'TableCell' },
          { text: entry.payer || '—', style: 'TableCell' },
        ])
      )
    )}
  ` : ''

  return `
    ${p('预算概览', 'SectionTitle', { before: SPACING.lg, after: SPACING.lg })}
    ${budget.total ? p(`总预算：¥${budget.total}`, 'BudgetTotal', { after: SPACING.sm }) : ''}
    ${budget.perPerson ? p(`人均：¥${budget.perPerson}`, 'BudgetTotal', { after: SPACING.lg }) : ''}
    ${table(
      [200, 150, 100],
      tableRow([
        { text: '分类', style: 'TableHeader' },
        { text: '金额', style: 'TableHeader' },
        { text: '占比', style: 'TableHeader' },
      ]),
      ...breakdownRows
    )}
    ${entriesTable}
  `
}

// ===== 工具函数 =====
function p(text: string, style: string, spacing?: { before?: number; after?: number; keepNext?: boolean }): string {
  const beforeAttr = spacing?.before ? `w:before="${spacing.before}"` : ''
  const afterAttr = spacing?.after ? `w:after="${spacing.after}"` : ''
  const spacingTag = beforeAttr || afterAttr ? `<w:spacing ${beforeAttr} ${afterAttr}/>` : ''
  const keepNextTag = spacing?.keepNext ? '<w:keepNext/>' : ''

  return `
    <w:p>
      <w:pPr>
        <w:pStyle w:val="${style}"/>
        ${spacingTag}
        ${keepNextTag}
      </w:pPr>
      <w:r><w:t xml:space="preserve">${escapeXml(text)}</w:t></w:r>
    </w:p>
  `
}

function table(widths: number[], ...rows: string[]): string {
  return `
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="5000" w:type="pct"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="6" w:color="${COLORS.border}"/>
          <w:left w:val="single" w:sz="6" w:color="${COLORS.border}"/>
          <w:bottom w:val="single" w:sz="6" w:color="${COLORS.border}"/>
          <w:right w:val="single" w:sz="6" w:color="${COLORS.border}"/>
          <w:insideH w:val="single" w:sz="4" w:color="${COLORS.borderLight}"/>
          <w:insideV w:val="single" w:sz="4" w:color="${COLORS.borderLight}"/>
        </w:tblBorders>
      </w:tblPr>
      <w:tblGrid>${widths.map((w) => `<w:gridCol w:w="${w}"/>`).join('')}</w:tblGrid>
      ${rows.join('')}
    </w:tbl>
  `
}

function tableRow(cells: Array<{ text: string; style: string }>): string {
  return `
    <w:tr>
      ${cells.map((cell) => `
        <w:tc>
          <w:tcPr><w:tcMar><w:top w:w="${SPACING.xs}" w:type="dxa"/><w:left w:w="${SPACING.sm}" w:type="dxa"/><w:bottom w:w="${SPACING.xs}" w:type="dxa"/><w:right w:w="${SPACING.sm}" w:type="dxa"/></w:tcMar></w:tcPr>
          ${p(cell.text, cell.style)}
        </w:tc>
      `).join('')}
    </w:tr>
  `
}

function divider(): string {
  return `
    <w:p>
      <w:pPr>
        <w:pBdr><w:top w:val="single" w:sz="6" w:space="8" w:color="${COLORS.borderLight}"/></w:pBdr>
        <w:spacing w:before="${SPACING.lg}" w:after="${SPACING.md}"/>
      </w:pPr>
    </w:p>
  `
}

function pageBreak(): string {
  return `<w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p>`
}

/**
 * 把一组卡片内容（每个是若干 w:p）两两排进一个无边框 2 列表格，实现双栏布局
 */
function twoColumnGrid(cards: string[]): string {
  if (cards.length === 0) return ''
  const rows: string[] = []
  for (let i = 0; i < cards.length; i += 2) {
    const left = cards[i]
    const right = cards[i + 1] || ''
    rows.push(`
      <w:tr>
        <w:tc>
          <w:tcPr><w:tcW w:w="4400" w:type="dxa"/><w:tcMar><w:right w:w="160" w:type="dxa"/></w:tcMar></w:tcPr>
          ${left}
        </w:tc>
        <w:tc>
          <w:tcPr><w:tcW w:w="4400" w:type="dxa"/><w:tcMar><w:left w:w="160" w:type="dxa"/></w:tcMar></w:tcPr>
          ${right || '<w:p/>'}
        </w:tc>
      </w:tr>
    `)
  }
  return `
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="8800" w:type="dxa"/>
        <w:tblBorders>
          <w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/>
          <w:insideH w:val="none"/><w:insideV w:val="none"/>
        </w:tblBorders>
      </w:tblPr>
      <w:tblGrid><w:gridCol w:w="4400"/><w:gridCol w:w="4400"/></w:tblGrid>
      ${rows.join('')}
    </w:tbl>
  `
}

function escapeXml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function textWithBreaks(value: unknown): string {
  const lines = String(value ?? '').split(/\r\n|\r|\n/)
  return lines.map((line, idx) => `${idx ? '<w:br/>' : ''}<w:t xml:space="preserve">${escapeXml(line)}</w:t>`).join('')
}

// ===== DOCX ZIP 打包 =====
function buildDocxBlob(content: string): Blob {
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        ${content}
        <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>
      </w:body>
    </w:document>`

  const stylesXml = buildStylesXml()

  return createZipBlob([
    { name: '[Content_Types].xml', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>' },
    { name: '_rels/.rels', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>' },
    { name: 'word/_rels/document.xml.rels', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' },
    { name: 'word/document.xml', content: documentXml },
    { name: 'word/styles.xml', content: stylesXml },
  ], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
}

function buildStylesXml(): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:docDefaults>
        <w:rPrDefault><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:hAnsi="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:color w:val="${COLORS.text}"/><w:sz w:val="${FONT_SIZES.body}"/></w:rPr></w:rPrDefault>
        <w:pPrDefault><w:pPr><w:widowControl/></w:pPr></w:pPrDefault>
      </w:docDefaults>

      <w:style w:type="paragraph" w:styleId="CoverLabel"><w:name w:val="Cover Label"/><w:rPr><w:color w:val="${COLORS.muted}"/><w:sz w:val="${FONT_SIZES.coverMeta}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="CoverTitle"><w:name w:val="Cover Title"/><w:rPr><w:b/><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.coverTitle}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="CoverSubtitle"><w:name w:val="Cover Subtitle"/><w:rPr><w:color w:val="${COLORS.text}"/><w:sz w:val="${FONT_SIZES.coverSubtitle}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="CoverMeta"><w:name w:val="Cover Meta"/><w:rPr><w:color w:val="${COLORS.muted}"/><w:sz w:val="${FONT_SIZES.coverMeta}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="CoverTags"><w:name w:val="Cover Tags"/><w:rPr><w:color w:val="${COLORS.primary}"/><w:sz w:val="${FONT_SIZES.coverStats}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="SectionTitle"><w:name w:val="Section Title"/><w:rPr><w:b/><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.sectionTitle}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="DayLabel"><w:name w:val="Day Label"/><w:rPr><w:b/><w:color w:val="${COLORS.primary}"/><w:sz w:val="${FONT_SIZES.dayLabel}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="DayMeta"><w:name w:val="Day Meta"/><w:rPr><w:color w:val="${COLORS.muted}"/><w:sz w:val="${FONT_SIZES.dayLabel}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="DayTitle"><w:name w:val="Day Title"/><w:rPr><w:b/><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.dayTitle}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="DayRoute"><w:name w:val="Day Route"/><w:rPr><w:color w:val="${COLORS.textLight}"/><w:sz w:val="${FONT_SIZES.dayRoute}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="EventTime"><w:name w:val="Event Time"/><w:rPr><w:b/><w:color w:val="${COLORS.primary}"/><w:sz w:val="${FONT_SIZES.eventTime}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="PlaceName"><w:name w:val="Place Name"/><w:rPr><w:b/><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.placeName}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="EventDesc"><w:name w:val="Event Desc"/><w:rPr><w:color w:val="${COLORS.textLight}"/><w:sz w:val="${FONT_SIZES.eventDesc}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="CityLabel"><w:name w:val="City Label"/><w:rPr><w:b/><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.sectionTitle}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="RestaurantMeta"><w:name w:val="Restaurant Meta"/><w:rPr><w:color w:val="${COLORS.muted}"/><w:sz w:val="${FONT_SIZES.restaurantMeta}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="HotelMeta"><w:name w:val="Hotel Meta"/><w:rPr><w:color w:val="${COLORS.muted}"/><w:sz w:val="${FONT_SIZES.hotelMeta}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="CategoryLabel"><w:name w:val="Category Label"/><w:rPr><w:b/><w:color w:val="${COLORS.text}"/><w:sz w:val="${FONT_SIZES.body}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="BudgetTotal"><w:name w:val="Budget Total"/><w:rPr><w:b/><w:color w:val="${COLORS.ink}"/><w:sz w:val="${FONT_SIZES.body}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="TableHeader"><w:name w:val="Table Header"/><w:rPr><w:b/><w:color w:val="${COLORS.muted}"/><w:sz w:val="${FONT_SIZES.tableHeader}"/></w:rPr></w:style>
      <w:style w:type="paragraph" w:styleId="TableCell"><w:name w:val="Table Cell"/><w:rPr><w:color w:val="${COLORS.text}"/><w:sz w:val="${FONT_SIZES.tableCell}"/></w:rPr></w:style>

      <w:style w:type="paragraph" w:styleId="BodySmall"><w:name w:val="Body Small"/><w:rPr><w:color w:val="${COLORS.textLight}"/><w:sz w:val="${FONT_SIZES.bodySmall}"/></w:rPr></w:style>
    </w:styles>`
}

function createCrcTable(): number[] {
  return Array.from({ length: 256 }, (_, n) => {
    let c = n
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    return c >>> 0
  })
}

const ZIP_CRC_TABLE = createCrcTable()

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff
  bytes.forEach((byte) => { crc = ZIP_CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8) })
  return (crc ^ 0xffffffff) >>> 0
}

function createZipBlob(files: { name: string; content: string }[], type: string): Blob {
  const encoder = new TextEncoder()
  const chunks: Uint8Array[] = []
  const central: Uint8Array[] = []
  let offset = 0
  const now = new Date()
  const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2)
  const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate()

  const write16 = (view: DataView, pos: number, val: number) => view.setUint16(pos, val, true)
  const write32 = (view: DataView, pos: number, val: number) => view.setUint32(pos, val, true)

  files.forEach(({ name, content }) => {
    const nameBytes = encoder.encode(name)
    const data = encoder.encode(content)
    const crc = crc32(data)
    // ZIP local file header：偏移必须严格按规范，写错一个字段整个包就打不开
    const local = new Uint8Array(30 + nameBytes.length)
    const localView = new DataView(local.buffer)
    write32(localView, 0, 0x04034b50)   // 签名
    write16(localView, 4, 20)           // version needed
    write16(localView, 8, 0)            // 压缩方法：0 = stored
    write16(localView, 10, dosTime)
    write16(localView, 12, dosDate)
    write32(localView, 14, crc)
    write32(localView, 18, data.length) // 压缩后大小
    write32(localView, 22, data.length) // 原始大小
    write16(localView, 26, nameBytes.length)
    local.set(nameBytes, 30)
    chunks.push(local, data)

    const dir = new Uint8Array(46 + nameBytes.length)
    const dirView = new DataView(dir.buffer)
    write32(dirView, 0, 0x02014b50)
    write16(dirView, 4, 20)             // version made by
    write16(dirView, 6, 20)             // version needed
    write16(dirView, 12, dosTime)       // offset 10 是压缩方法，留 0
    write16(dirView, 14, dosDate)
    write32(dirView, 16, crc)
    write32(dirView, 20, data.length)
    write32(dirView, 24, data.length)
    write16(dirView, 28, nameBytes.length)
    write32(dirView, 42, offset)        // 对应 local header 的偏移
    dir.set(nameBytes, 46)
    central.push(dir)
    offset += local.length + data.length
  })

  const centralSize = central.reduce((sum, item) => sum + item.length, 0)
  const end = new Uint8Array(22)
  const endView = new DataView(end.buffer)
  write32(endView, 0, 0x06054b50)
  write16(endView, 8, files.length)
  write16(endView, 10, files.length)
  write32(endView, 12, centralSize)
  write32(endView, 16, offset)
  const parts = [...chunks, ...central, end].map((part) => part.buffer.slice(part.byteOffset, part.byteOffset + part.byteLength) as ArrayBuffer)
  return new Blob(parts, { type })
}
