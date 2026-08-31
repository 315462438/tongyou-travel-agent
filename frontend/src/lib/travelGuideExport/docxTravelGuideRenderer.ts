import type { GuideDay, TimelineItem, TravelGuideSchema } from './schema'
import type { GuideLayout, GuideLayoutBlock } from './layoutEngine'

const W = {
  page: 9600,
  time: 1180,
  main: 8420,
  half: 4800,
}

const COLOR = {
  ink: '10283B',
  body: '27364A',
  muted: '6E7F91',
  teal: '168C9C',
  tealDark: '0F4A5A',
  tealSoft: 'F0F8F9',
  tealSofter: 'F7FAFB',
  line: 'D8E8EC',
  green: '3E8B6E',
  greenSoft: 'EAF7F2',
  amber: 'C08A2E',
  amberSoft: 'FFF5DE',
  white: 'FFFFFF',
}

export function renderTravelGuideDocx(layout: GuideLayout): Blob {
  const body = layout.blocks.map((block, index) => renderBlock(block, index > 0)).join('')
  return buildDocxBlob(body, layout.blocks[0]?.kind === 'cover' ? (layout.blocks[0].guide.meta.subtitle || layout.blocks[0].guide.meta.title) : '旅行攻略')
}

function renderBlock(block: GuideLayoutBlock, pageBreak: boolean): string {
  const prefix = pageBreak ? pageBreakBefore() : ''
  switch (block.kind) {
    case 'cover': return prefix + CoverRenderer(block.guide)
    case 'overview': return prefix + OverviewRenderer(block.guide)
    case 'beforeDeparture': return prefix + BeforeDepartureRenderer(block.guide)
    case 'day': return prefix + DayRenderer(block.day)
    case 'foods': return prefix + FoodCollectionRenderer(block.guide)
    case 'hotels': return prefix + HotelCollectionRenderer(block.guide)
    case 'packing': return prefix + PackingRenderer(block.guide)
    case 'checklist': return prefix + ChecklistRenderer('出发前48小时 Checklist', block.guide.checklist48h)
    case 'notes': return prefix + NotesRenderer(block.guide)
  }
}

function CoverRenderer(guide: TravelGuideSchema): string {
  const meta = guide.meta
  return [
    p('TRAVEL BOOK / 2026', 'Kicker', { after: 220 }),
    p(meta.title, 'CoverTitle', { after: 140 }),
    p(meta.subtitle, 'CoverSubtitle', { after: 260 }),
    keyValueBand([
      ['日期', meta.dateRange],
      ['旅行关键词', meta.tags.join(' · ') || '旅行攻略'],
      ['旅行节奏', guide.summary.rhythm],
    ]),
    p(`${meta.days} DAYS · ${meta.nights} NIGHTS`, 'CoverMeta', { before: 360, after: 80 }),
    p(guide.summary.overview || '一份按时间线整理、到当地可以直接照着走的旅行手册', 'Body', { after: 0 }),
  ].join('')
}

function OverviewRenderer(guide: TravelGuideSchema): string {
  const rows = [
    tr([
      th('DAY', 980),
      th('日期', 1450),
      th('城市', 1500),
      th('当天主线', 3600),
      th('住宿', 2070),
    ], true),
    ...guide.days.map((day, idx) => tr([
      td(`DAY ${String(day.day).padStart(2, '0')}`, 980, { shade: idx % 2 ? COLOR.white : COLOR.tealSofter, bold: true, color: COLOR.tealDark }),
      td(shortDate(day.date), 1450, { shade: idx % 2 ? COLOR.white : COLOR.tealSofter }),
      td(day.city, 1500, { shade: idx % 2 ? COLOR.white : COLOR.tealSofter }),
      td(day.title, 3600, { shade: idx % 2 ? COLOR.white : COLOR.tealSofter }),
      td(day.hotel?.name || '-', 2070, { shade: idx % 2 ? COLOR.white : COLOR.tealSofter }),
    ])),
  ]
  return [
    p('OVERVIEW', 'Kicker', { after: 40 }),
    p('行程总览', 'SectionTitle', { after: 80 }),
    p('先看节奏，再看每天细节。航班日留出余量，体验日把安全和集合时间放在最前面。', 'Body', { after: 220 }),
    metricGrid(guide),
    table(rows, [980, 1450, 1500, 3600, 2070]),
    callout('这趟旅行的节奏', guide.summary.rhythm, COLOR.green, COLOR.greenSoft),
  ].join('')
}

function BeforeDepartureRenderer(guide: TravelGuideSchema): string {
  const items = guide.beforeDeparture.length ? guide.beforeDeparture : guide.importantNotes
  return [
    p('BEFORE YOU GO', 'Kicker', { after: 40 }),
    p('出发前速查', 'SectionTitle', { after: 80 }),
    p('把容易忘、但会直接影响行程的事项集中到一页。', 'Body', { after: 180 }),
    twoColumnCards(items.slice(0, 8).map((item) => ({ title: inferNoteTitle(item), body: item }))),
    callout('两个需要提前记住的时间点', guide.importantNotes.slice(0, 3).join('；') || '核对集合时间、预约信息和酒店入住安排。', COLOR.amber, COLOR.amberSoft),
  ].join('')
}

function DayRenderer(day: GuideDay): string {
  return [
    DayHeaderRenderer(day),
    HighlightCardRenderer(day),
    routeLine(day.route),
    TimelineRenderer(day.timeline),
    day.food.length ? FoodCardRenderer(day.food) : '',
    day.outfit ? OutfitCardRenderer(day.outfit) : '',
    day.tips.length ? TipCardRenderer('今日提醒', day.tips.join('；')) : '',
    day.warnings.length ? WarningCardRenderer('当天小提醒', day.warnings.join('；')) : '',
    day.hotel ? HotelCardRenderer(day.hotel.name, [day.hotel.city, day.hotel.note].filter(Boolean).join(' · ')) : '',
  ].join('')
}

function DayHeaderRenderer(day: GuideDay): string {
  return [
    p(`DAY ${String(day.day).padStart(2, '0')} · ${monthLabel(day.date)}`, 'DayKicker', { after: 40, keepNext: true }),
    p(day.title, 'DayTitle', { after: 60, keepNext: true }),
    p([day.date, day.city, day.subtitle].filter(Boolean).join(' | '), 'DaySub', { after: 120 }),
    tagLine(day.tags),
  ].join('')
}

function HighlightCardRenderer(day: GuideDay): string {
  return infoPairTable([
    ['今日重点', day.highlight || day.title],
    ['今晚住宿', day.hotel?.name || '按当天安排确认'],
  ])
}

function TimelineRenderer(items: TimelineItem[]): string {
  if (!items.length) return callout('时间轴', '暂无时间线安排。', COLOR.teal, COLOR.tealSoft)
  return table(items.map((item, idx) => tr([
    td(item.time || '', W.time, { shade: COLOR.tealSoft, color: COLOR.teal, bold: true, vAlign: 'top' }),
    td(timelineText(item), W.main, { shade: idx % 2 ? COLOR.white : COLOR.tealSofter, vAlign: 'top' }),
  ], false, true)), [W.time, W.main], { top: COLOR.line, insideH: COLOR.line, insideV: COLOR.line })
}

function FoodCardRenderer(items: string[]): string {
  return twoColumnCards([{ title: '美食推荐', body: items.join('、') }], COLOR.greenSoft)
}

function OutfitCardRenderer(text: string): string {
  return twoColumnCards([{ title: '穿搭建议', body: text }], COLOR.tealSoft)
}

function TipCardRenderer(title: string, text: string): string {
  return callout(title, text, COLOR.teal, COLOR.tealSoft)
}

function WarningCardRenderer(title: string, text: string): string {
  return callout(title, text, COLOR.amber, COLOR.amberSoft)
}

function HotelCardRenderer(title: string, text: string): string {
  return callout(title, text || '当天落脚点', COLOR.teal, COLOR.tealSoft)
}

function FoodCollectionRenderer(guide: TravelGuideSchema): string {
  return [
    p('COLLECTION', 'Kicker', { after: 40 }),
    p('美食收藏', 'SectionTitle', { after: 160 }),
    twoColumnCards(guide.foodRecommendations.map((food) => ({
      title: food.name,
      body: [food.city, food.category, food.mealType, food.price, food.rating ? `评分 ${food.rating}` : '', food.recommendation].filter(Boolean).join(' · '),
    }))),
  ].join('')
}

function HotelCollectionRenderer(guide: TravelGuideSchema): string {
  return [
    p('STAYS', 'Kicker', { after: 40 }),
    p('住宿安排', 'SectionTitle', { after: 160 }),
    twoColumnCards(guide.hotels.map((hotel) => ({
      title: hotel.name,
      body: [hotel.city, hotel.checkIn && hotel.checkOut ? `${hotel.checkIn} - ${hotel.checkOut}` : '', hotel.nights ? `${hotel.nights} 晚` : '', hotel.note].filter(Boolean).join(' · '),
    }))),
  ].join('')
}

function PackingRenderer(guide: TravelGuideSchema): string {
  return [
    p('PACKING', 'Kicker', { after: 40 }),
    p('行李清单', 'SectionTitle', { after: 160 }),
    ...guide.packingList.map((group) => ChecklistRenderer(group.category, group.items, false)),
  ].join('')
}

function NotesRenderer(guide: TravelGuideSchema): string {
  const issueNotes = guide.issues.map((issue) => `${issue.day ? `Day ${issue.day}：` : ''}${issue.message}`)
  return [
    p('NOTES', 'Kicker', { after: 40 }),
    p('重要注意事项', 'SectionTitle', { after: 160 }),
    ...guide.importantNotes.map((note) => callout(inferNoteTitle(note), note, COLOR.amber, COLOR.amberSoft)),
    issueNotes.length ? ChecklistRenderer('数据核对', issueNotes, false) : '',
  ].join('')
}

function ChecklistRenderer(title: string, items: string[], sectionTitle = true): string {
  const rows = items.map((item) => tr([
    td('□', 520, { color: COLOR.teal, bold: true }),
    td(item, 9080),
  ], false, true))
  return [
    sectionTitle ? p(title, 'SectionTitleSmall', { before: 80, after: 120 }) : p(title, 'CardTitle', { before: 120, after: 70 }),
    table(rows, [520, 9080], { top: COLOR.line, insideH: COLOR.line }),
  ].join('')
}

function keyValueBand(rows: Array<[string, string]>): string {
  return table(rows.map(([key, value], idx) => tr([
    td(key, 1500, { shade: idx % 2 ? COLOR.tealSofter : COLOR.tealSoft, color: COLOR.tealDark, bold: true }),
    td(value, 8100, { shade: idx % 2 ? COLOR.tealSofter : COLOR.tealSoft }),
  ], false, true)), [1500, 8100], { top: COLOR.line, insideH: COLOR.line, insideV: COLOR.line })
}

function metricGrid(guide: TravelGuideSchema): string {
  const metrics = [
    ['旅行天数', `${guide.meta.days} 天 ${guide.meta.nights} 晚\n${guide.meta.dateRange}`],
    ['城市', `${guide.summary.cities.length} 站\n${guide.summary.cities.join(' / ') || guide.meta.destination}`],
    ['住宿', `${guide.hotels.length} 家\n${guide.hotels[0]?.name || '按每日安排确认'}`],
    ['核心体验', guide.summary.highlights.join(' + ') || guide.meta.tags.join(' + ')],
  ]
  return table([
    tr(metrics.map(([k, v]) => td(`${k}\n${v}`, 2400, { shade: COLOR.tealSoft, bold: true })), false, true),
  ], [2400, 2400, 2400, 2400], { top: COLOR.line, insideV: COLOR.line })
}

function infoPairTable(rows: Array<[string, string]>): string {
  return table([tr(rows.map(([k, v]) => td(`${k}\n${v}`, W.half, { shade: COLOR.tealSoft, bold: true })), false, true)], [W.half, W.half], { top: COLOR.line, insideV: COLOR.line })
}

function twoColumnCards(cards: Array<{ title: string; body: string }>, shade = COLOR.tealSofter): string {
  const rows: string[] = []
  for (let i = 0; i < cards.length; i += 2) {
    rows.push(tr([
      td(`${cards[i].title}\n${cards[i].body}`, W.half, { shade, bold: true, vAlign: 'top' }),
      td(cards[i + 1] ? `${cards[i + 1].title}\n${cards[i + 1].body}` : '', W.half, { shade: cards[i + 1] ? shade : COLOR.white, bold: true, vAlign: 'top' }),
    ], false, true))
  }
  return table(rows, [W.half, W.half], { top: COLOR.line, insideH: COLOR.line, insideV: COLOR.line })
}

function callout(title: string, text: string, accent: string, shade: string): string {
  return table([tr([
    td('', 90, { shade: accent }),
    td(`${title}\n${text}`, W.page - 90, { shade, bold: true }),
  ], false, true)], [90, W.page - 90], { top: shade, insideV: shade })
}

function routeLine(route: string[]): string {
  if (!route.length) return ''
  return p(`路线  ${route.join(' → ')}`, 'Route', { before: 120, after: 160 })
}

function tagLine(tags: string[]): string {
  if (!tags.length) return ''
  return p(tags.join(' / '), 'Tags', { after: 150 })
}

function timelineText(item: TimelineItem): string {
  const meta = [item.duration, item.price, item.transport].filter(Boolean).join(' · ')
  return [item.title, item.description, meta].filter(Boolean).join('\n')
}

function table(rows: string[], widths: number[], border: { top?: string; insideH?: string; insideV?: string } = {}): string {
  return `
    <w:tbl>
      <w:tblPr>
        <w:tblW w:w="${W.page}" w:type="dxa"/>
        <w:tblLayout w:type="fixed"/>
        <w:tblBorders>
          <w:top w:val="single" w:sz="4" w:color="${border.top || COLOR.line}"/>
          <w:left w:val="single" w:sz="4" w:color="${border.top || COLOR.line}"/>
          <w:bottom w:val="single" w:sz="4" w:color="${border.top || COLOR.line}"/>
          <w:right w:val="single" w:sz="4" w:color="${border.top || COLOR.line}"/>
          <w:insideH w:val="single" w:sz="4" w:color="${border.insideH || COLOR.line}"/>
          <w:insideV w:val="single" w:sz="4" w:color="${border.insideV || COLOR.line}"/>
        </w:tblBorders>
        <w:tblCellMar><w:top w:w="120" w:type="dxa"/><w:left w:w="140" w:type="dxa"/><w:bottom w:w="120" w:type="dxa"/><w:right w:w="140" w:type="dxa"/></w:tblCellMar>
      </w:tblPr>
      <w:tblGrid>${widths.map((width) => `<w:gridCol w:w="${width}"/>`).join('')}</w:tblGrid>
      ${rows.join('')}
    </w:tbl>
    ${p('', 'Body', { after: 140 })}
  `
}

function tr(cells: string[], header = false, cantSplit = false): string {
  return `<w:tr><w:trPr>${header ? '<w:tblHeader/>' : ''}${cantSplit ? '<w:cantSplit/>' : ''}</w:trPr>${cells.join('')}</w:tr>`
}

function th(text: string, width: number): string {
  return td(text, width, { shade: COLOR.tealDark, color: COLOR.white, bold: true })
}

function td(text: string, width: number, opts: { shade?: string; color?: string; bold?: boolean; vAlign?: 'top' | 'center' } = {}): string {
  return `
    <w:tc>
      <w:tcPr>
        <w:tcW w:w="${width}" w:type="dxa"/>
        <w:vAlign w:val="${opts.vAlign || 'center'}"/>
        ${opts.shade ? `<w:shd w:val="clear" w:color="auto" w:fill="${opts.shade}"/>` : ''}
      </w:tcPr>
      ${String(text || '').split('\n').map((line, idx) => p(line, idx === 0 && opts.bold ? 'CardTitle' : 'TableText', { after: idx === 0 ? 35 : 0, color: opts.color, bold: idx === 0 && opts.bold })).join('')}
    </w:tc>
  `
}

function p(text: string, style: string, opts: { before?: number; after?: number; keepNext?: boolean; color?: string; bold?: boolean } = {}): string {
  return `
    <w:p>
      <w:pPr>
        <w:pStyle w:val="${style}"/>
        <w:spacing w:before="${opts.before ?? 0}" w:after="${opts.after ?? 80}" w:line="276" w:lineRule="auto"/>
        ${opts.keepNext ? '<w:keepNext/>' : ''}
      </w:pPr>
      <w:r>
        <w:rPr>${opts.bold ? '<w:b/>' : ''}${opts.color ? `<w:color w:val="${opts.color}"/>` : ''}</w:rPr>
        <w:t xml:space="preserve">${escapeXml(text)}</w:t>
      </w:r>
    </w:p>
  `
}

function pageBreakBefore(): string {
  return '<w:p><w:pPr><w:pageBreakBefore/></w:pPr></w:p>'
}

function shortDate(value: string): string {
  return value.replace(/^\d{4}年/, '').replace(/日\s*/, ' · ')
}

function monthLabel(value: string): string {
  const match = value.match(/(\d{1,2})月(\d{1,2})日/)
  if (!match) return ''
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return `${months[Number(match[1]) - 1] || ''} ${String(Number(match[2])).padStart(2, '0')}`
}

function inferNoteTitle(text: string): string {
  if (/护照|签证|MDAC|入境/.test(text)) return '证件 / 入境'
  if (/机场|航班|值机|安检/.test(text)) return '机场 / 转场'
  if (/船|码头|跳岛|浮潜|晕船/.test(text)) return '海岛 / 船程'
  if (/现金|支付|马币|银行卡/.test(text)) return '现金 / 支付'
  if (/防晒|泳衣|外套|装备/.test(text)) return '装备 / 穿搭'
  return '提醒'
}

function escapeXml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

function buildDocxBlob(content: string, title: string): Blob {
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        ${content}
        <w:sectPr>
          <w:pgSz w:w="11906" w:h="16838"/>
          <w:pgMar w:top="1080" w:right="1134" w:bottom="1080" w:left="1134" w:header="720" w:footer="720"/>
          <w:footerReference w:type="default" r:id="rId2" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>
        </w:sectPr>
      </w:body>
    </w:document>`
  return createZipBlob([
    { name: '[Content_Types].xml', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>' },
    { name: '_rels/.rels', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>' },
    { name: 'word/_rels/document.xml.rels', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>' },
    { name: 'word/document.xml', content: documentXml },
    { name: 'word/styles.xml', content: stylesXml() },
    { name: 'word/footer1.xml', content: footerXml() },
    { name: 'docProps/core.xml', content: coreXml(title) },
    { name: 'docProps/app.xml', content: '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>17同游</Application></Properties>' },
  ], 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
}

function stylesXml(): string {
  const style = (id: string, size: number, color = COLOR.body, bold = false, font = 'Noto Sans CJK SC') =>
    `<w:style w:type="paragraph" w:styleId="${id}"><w:name w:val="${id}"/><w:rPr><w:rFonts w:ascii="${font}" w:hAnsi="${font}" w:eastAsia="${font}"/>${bold ? '<w:b/>' : ''}<w:color w:val="${color}"/><w:sz w:val="${size}"/></w:rPr></w:style>`
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Noto Sans CJK SC" w:hAnsi="Noto Sans CJK SC" w:eastAsia="Noto Sans CJK SC"/><w:color w:val="${COLOR.body}"/><w:sz w:val="20"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:widowControl/></w:pPr></w:pPrDefault></w:docDefaults>
      ${style('Kicker', 20, COLOR.teal, true)}
      ${style('CoverTitle', 62, COLOR.ink, true)}
      ${style('CoverSubtitle', 30, COLOR.ink, true)}
      ${style('CoverMeta', 22, COLOR.muted, true)}
      ${style('SectionTitle', 42, COLOR.ink, true)}
      ${style('SectionTitleSmall', 32, COLOR.ink, true)}
      ${style('DayKicker', 21, COLOR.teal, true)}
      ${style('DayTitle', 52, COLOR.ink, true)}
      ${style('DaySub', 21, COLOR.muted)}
      ${style('Tags', 19, COLOR.teal)}
      ${style('Route', 20, COLOR.tealDark, true)}
      ${style('CardTitle', 22, COLOR.tealDark, true)}
      ${style('TableText', 19, COLOR.body)}
      ${style('Body', 21, COLOR.body)}
      ${style('Footer', 17, '90A0AE')}
    </w:styles>`
}

function footerXml(): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr><w:r><w:t>17同游 · 精致攻略</w:t></w:r></w:p></w:ftr>`
}

function coreXml(title: string): string {
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>${escapeXml(title)}</dc:title><dc:creator>17同游</dc:creator><dc:description>generated by TravelGuideExportPipeline</dc:description><dcterms:created xsi:type="dcterms:W3CDTF">${new Date().toISOString()}</dcterms:created></cp:coreProperties>`
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
    const local = new Uint8Array(30 + nameBytes.length)
    const localView = new DataView(local.buffer)
    write32(localView, 0, 0x04034b50)
    write16(localView, 4, 20)
    write16(localView, 8, 0)
    write16(localView, 10, dosTime)
    write16(localView, 12, dosDate)
    write32(localView, 14, crc)
    write32(localView, 18, data.length)
    write32(localView, 22, data.length)
    write16(localView, 26, nameBytes.length)
    local.set(nameBytes, 30)
    chunks.push(local, data)
    const dir = new Uint8Array(46 + nameBytes.length)
    const dirView = new DataView(dir.buffer)
    write32(dirView, 0, 0x02014b50)
    write16(dirView, 4, 20)
    write16(dirView, 6, 20)
    write16(dirView, 12, dosTime)
    write16(dirView, 14, dosDate)
    write32(dirView, 16, crc)
    write32(dirView, 20, data.length)
    write32(dirView, 24, data.length)
    write16(dirView, 28, nameBytes.length)
    write32(dirView, 42, offset)
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
