/**
 * HTML 渲染器
 * 将 ShareGuideSchema 转换为 HTML（用于浏览器打印成 PDF）
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

/**
 * 主函数：渲染 ShareGuideSchema 为 HTML 字符串
 */
export function renderShareGuideHtml(schema: ShareGuideSchema): string {
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(schema.cover.title)} - 旅行攻略</title>
  <style>${buildStyles()}</style>
</head>
<body>
  ${renderCover(schema.cover)}
  ${renderOverview(schema.overview)}
  ${schema.days.map(renderDay).join('')}
  ${schema.foods.cityGroups.length > 0 ? renderFoods(schema.foods) : ''}
  ${schema.stays.hotels.length > 0 ? renderStays(schema.stays) : ''}
  ${schema.tips.categories.length > 0 ? renderTips(schema.tips) : ''}
  ${schema.packing ? renderPacking(schema.packing) : ''}
  ${schema.budget ? renderBudget(schema.budget) : ''}
  <script>
    // 打印预览准备就绪后自动打开打印对话框
    window.addEventListener('load', () => {
      setTimeout(() => window.print(), 300)
    })
  </script>
</body>
</html>`
}

// ===== 样式 =====
function buildStyles(): string {
  return `
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: "PingFang SC", "Microsoft YaHei", -apple-system, BlinkMacSystemFont, sans-serif;
      font-size: 10.5pt;
      line-height: 1.5;
      color: #27272a;
      background: #fff;
      padding: 32pt;
    }

    /* 分页控制 */
    .page-break { page-break-before: always; }
    .keep-together { break-inside: avoid; page-break-inside: avoid; }

    /* 封面 */
    .cover {
      margin-bottom: 48pt;
      break-after: page;
      page-break-after: always;
    }
    .cover-label {
      font-size: 10pt;
      color: #71717a;
      margin-bottom: 6pt;
    }
    .cover-title {
      font-size: 28pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 8pt;
      line-height: 1.2;
    }
    .cover-subtitle {
      font-size: 14pt;
      color: #27272a;
      margin-bottom: 12pt;
    }
    .cover-meta {
      font-size: 10pt;
      color: #71717a;
      margin-bottom: 6pt;
    }
    .cover-tags {
      font-size: 9.5pt;
      color: #3155c6;
      margin-top: 12pt;
    }

    /* 总览 */
    .section-title {
      font-size: 22pt;
      font-weight: 700;
      color: #18181b;
      margin-top: 24pt;
      margin-bottom: 16pt;
      break-after: avoid;
      page-break-after: avoid;
    }
    .overview-table {
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 16pt;
      font-size: 10pt;
    }
    .overview-table th {
      background: #fafafa;
      border: 1px solid #e4e4e7;
      padding: 6pt 8pt;
      text-align: left;
      font-weight: 700;
      color: #71717a;
      font-size: 9.5pt;
    }
    .overview-table td {
      border: 1px solid #f4f4f5;
      padding: 6pt 8pt;
      color: #27272a;
    }
    .overview-stats {
      font-size: 10pt;
      color: #3f3f46;
      margin-top: 16pt;
    }

    /* 每日攻略 */
    .day-section {
      margin-top: 24pt;
      margin-bottom: 24pt;
      border-top: 1px solid #f4f4f5;
      padding-top: 20pt;
    }
    .day-label {
      font-size: 11pt;
      font-weight: 700;
      color: #3155c6;
      margin-bottom: 4pt;
    }
    .day-meta {
      font-size: 11pt;
      color: #71717a;
      margin-bottom: 4pt;
    }
    .day-title {
      font-size: 20pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 8pt;
      line-height: 1.3;
    }
    .day-route {
      font-size: 9.5pt;
      color: #3f3f46;
      margin-bottom: 16pt;
    }
    .day-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6pt;
      margin-bottom: 12pt;
    }
    .day-tag {
      font-size: 9pt;
      padding: 2pt 8pt;
      border-radius: 10pt;
      background: #eef2ff;
      color: #3155c6;
    }
    .highlight-card {
      background: #eef2ff;
      border-radius: 8pt;
      padding: 10pt 12pt;
      margin-bottom: 14pt;
    }
    .highlight-title {
      font-size: 11pt;
      font-weight: 700;
      color: #1e40af;
      margin-bottom: 4pt;
    }
    .highlight-sub {
      font-size: 9.5pt;
      color: #3f3f46;
      margin-top: 2pt;
    }

    /* Event Card */
    .event-card {
      display: grid;
      grid-template-columns: 60pt 1fr;
      gap: 14pt;
      margin-bottom: 16pt;
      break-inside: avoid;
      page-break-inside: avoid;
    }
    .event-time {
      font-size: 11pt;
      font-weight: 700;
      color: #3155c6;
      font-variant-numeric: tabular-nums;
    }
    .event-main {}
    .event-place {
      font-size: 12.5pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 4pt;
    }
    .event-desc {
      font-size: 10pt;
      color: #3f3f46;
      line-height: 1.55;
      margin-bottom: 6pt;
    }
    .event-badges {
      display: flex;
      flex-wrap: wrap;
      gap: 8pt;
      margin-bottom: 8pt;
    }
    .badge {
      font-size: 9.5pt;
      padding: 2pt 8pt;
      border-radius: 12pt;
      background: #f4f4f5;
      color: #71717a;
      white-space: nowrap;
    }
    .badge-cost {
      background: #dbeafe;
      color: #3155c6;
      font-weight: 650;
    }

    /* Tip Card */
    .tip-card {
      background: #f9fafb;
      border-left: 3pt solid #e4e4e7;
      padding: 8pt 12pt;
      margin-top: 8pt;
      border-radius: 4pt;
      break-inside: avoid;
      page-break-inside: avoid;
    }
    .tip-card.warning {
      background: #fef3c7;
      border-left-color: #d97706;
    }
    .tip-card.info {
      background: #dbeafe;
      border-left-color: #2563eb;
    }
    .tip-title {
      font-size: 10.5pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 4pt;
    }
    .tip-content {
      font-size: 10pt;
      color: #27272a;
      line-height: 1.5;
    }

    /* 美食 */
    .city-label {
      font-size: 18pt;
      font-weight: 700;
      color: #18181b;
      margin-top: 20pt;
      margin-bottom: 12pt;
      break-after: avoid;
      page-break-after: avoid;
    }
    .restaurant-card {
      margin-bottom: 12pt;
      break-inside: avoid;
      page-break-inside: avoid;
    }
    .restaurant-name {
      font-size: 12.5pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 4pt;
    }
    .restaurant-name.more {
      font-size: 10pt;
      font-weight: 600;
    }
    .restaurant-meta {
      font-size: 9.5pt;
      color: #71717a;
      margin-bottom: 4pt;
    }
    .restaurant-dishes {
      font-size: 10pt;
      color: #3f3f46;
      margin-bottom: 4pt;
    }
    .restaurant-reason {
      font-size: 10pt;
      color: #3f3f46;
      font-style: italic;
    }
    .more-label {
      font-size: 10pt;
      color: #71717a;
      margin-top: 12pt;
      margin-bottom: 8pt;
    }

    /* 双栏卡片网格 */
    .card-grid-2col {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10pt;
      margin-bottom: 8pt;
    }
    .card-grid-2col .restaurant-card,
    .card-grid-2col .hotel-card {
      border: 1px solid #e4e4e7;
      border-radius: 8pt;
      padding: 10pt 12pt;
      background: #fafafa;
      margin-bottom: 0;
    }

    /* 住宿 */
    .hotel-card {
      margin-bottom: 12pt;
      break-inside: avoid;
      page-break-inside: avoid;
    }
    .hotel-name {
      font-size: 12pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 4pt;
    }
    .hotel-meta {
      font-size: 9.5pt;
      color: #71717a;
      margin-bottom: 4pt;
    }
    .hotel-note {
      font-size: 10pt;
      color: #3f3f46;
    }

    /* 避坑 */
    .tip-category {
      margin-top: 16pt;
      margin-bottom: 12pt;
    }
    .category-label {
      font-size: 14pt;
      font-weight: 700;
      color: #27272a;
      margin-bottom: 8pt;
      break-after: avoid;
      page-break-after: avoid;
    }

    /* 预算 */
    .budget-total {
      font-size: 10.5pt;
      font-weight: 700;
      color: #18181b;
      margin-bottom: 6pt;
    }
    .budget-table {
      width: 60%;
      border-collapse: collapse;
      margin-top: 16pt;
      font-size: 10pt;
    }
    .budget-table th {
      background: #fafafa;
      border: 1px solid #e4e4e7;
      padding: 6pt 8pt;
      text-align: left;
      font-weight: 700;
      color: #71717a;
      font-size: 9.5pt;
    }
    .budget-table td {
      border: 1px solid #f4f4f5;
      padding: 6pt 8pt;
      color: #27272a;
    }

    /* 打印样式 */
    @media print {
      body { padding: 0; }
      .cover { page-break-after: always; }
      .section-title { page-break-after: avoid; }
      .keep-together { page-break-inside: avoid; }
    }
  `
}

// ===== 封面 =====
function renderCover(cover: CoverSection): string {
  return `
    <div class="cover">
      <div class="cover-label">${escapeHtml(cover.region)}</div>
      <div class="cover-title">${escapeHtml(cover.title)}</div>
      ${cover.subtitle ? `<div class="cover-subtitle">${escapeHtml(cover.subtitle)}</div>` : ''}
      <div class="cover-meta">${cover.days} DAYS · ${cover.nights} NIGHTS</div>
      <div class="cover-meta">${escapeHtml(cover.dateRange)}</div>
      ${cover.tags.length > 0 ? `<div class="cover-tags">${cover.tags.join(' · ')}</div>` : ''}
    </div>
  `
}

// ===== 总览 =====
function renderOverview(overview: OverviewSection): string {
  const { timeline, stats } = overview

  const rows = timeline.map((day) => `
    <tr>
      <td>Day ${day.day}</td>
      <td>${escapeHtml(day.date)}</td>
      <td>${escapeHtml(day.weekday)}</td>
      <td>${escapeHtml(day.city)}</td>
      <td>${escapeHtml(day.theme)}</td>
      <td>${escapeHtml(day.hotel)}</td>
    </tr>
  `).join('')

  const statsText = [
    `${stats.totalDays} 天`,
    stats.cities.join('、'),
    `${stats.hotels} 家酒店`,
    stats.highlights.length > 0 ? stats.highlights.join('、') : '',
  ].filter(Boolean).join(' · ')

  // 总览独占一页：内容后强制分页，让 Day 1 从第 3 页开始
  return `
    <section style="break-after: page; page-break-after: always;">
      <div class="section-title">行程总览</div>
      <table class="overview-table">
        <thead>
          <tr>
            <th>Day</th>
            <th>日期</th>
            <th>星期</th>
            <th>城市</th>
            <th>今日主题</th>
            <th>住宿</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
      <div class="overview-stats">${escapeHtml(statsText)}</div>
    </section>
  `
}

// ===== 每日攻略 =====
function renderDay(day: DaySection): string {
  const route = day.route.length > 0 ? day.route.join(' → ') : ''
  const metaLine = [day.monthLabel, day.city].filter(Boolean).join('     ')

  return `
    <div class="day-section">
      <div class="day-label">DAY ${String(day.day).padStart(2, '0')}</div>
      ${metaLine ? `<div class="day-meta">${escapeHtml(metaLine)}</div>` : ''}
      <div class="day-title">${escapeHtml(day.theme)}</div>
      ${day.dayTags.length ? `<div class="day-tags">${day.dayTags.map((t) => `<span class="day-tag">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
      ${route ? `<div class="day-route">${escapeHtml(route)}</div>` : ''}
      ${day.highlight ? renderHighlightCard(day.highlight) : ''}
      ${day.events.map(renderEventCard).join('')}
    </div>
  `
}

function renderHighlightCard(h: DayHighlight): string {
  const places = h.places.length ? h.places.join(' / ') : ''
  const tags = h.tags.length ? h.tags.join('  ') : ''
  return `
    <div class="highlight-card keep-together">
      <div class="highlight-title">⭐ 今日重点：${escapeHtml(h.title)}</div>
      ${places ? `<div class="highlight-sub">${escapeHtml(places)}</div>` : ''}
      ${tags ? `<div class="highlight-sub">${escapeHtml(tags)}</div>` : ''}
    </div>
  `
}

function renderEventCard(event: EventCard): string {
  return `
    <div class="event-card">
      ${event.time ? `<div class="event-time">${escapeHtml(event.time)}</div>` : '<div></div>'}
      <div class="event-main">
        <div class="event-place">${escapeHtml(event.place)}</div>
        ${event.description ? `<div class="event-desc">${escapeHtml(event.description)}</div>` : ''}
        ${event.badges.length > 0 ? renderBadges(event.badges) : ''}
        ${event.tips ? event.tips.map(renderTipCard).join('') : ''}
      </div>
    </div>
  `
}

function renderBadges(badges: Badge[]): string {
  const badgeHtml = badges.map((badge) => {
    const className = badge.type === 'cost' ? 'badge badge-cost' : 'badge'
    return `<span class="${className}">${badge.icon} ${escapeHtml(badge.label)}</span>`
  }).join('')

  return `<div class="event-badges">${badgeHtml}</div>`
}

function renderTipCard(tip: TipCard): string {
  const levelClass = tip.level ? ` ${tip.level}` : ''
  // title 与 content 高度相似时只显示 title（避免重复）
  const showContent = tip.content && !tipTextsAlike(tip.title, tip.content)
  return `
    <div class="tip-card keep-together${levelClass}">
      <div class="tip-title">${tip.icon} ${escapeHtml(tip.title)}</div>
      ${showContent ? `<div class="tip-content">${escapeHtml(tip.content)}</div>` : ''}
    </div>
  `
}

/** 两段文本是否高度相似（字符级 Jaccard > 0.85） */
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
    <div class="page-break"></div>
    <div class="section-title">美食推荐</div>
    ${foods.cityGroups.map(renderFoodCityGroup).join('')}
  `
}

function renderFoodCityGroup(group: FoodCityGroup): string {
  return `
    <div class="city-label">${escapeHtml(group.city)}</div>
    <div class="card-grid-2col">
      ${group.top.map((r) => renderRestaurantCard(r, true)).join('')}
    </div>
    ${group.more.length > 0 ? `<div class="more-label">其他收藏 (${group.more.length})</div>` : ''}
    ${group.more.length > 0 ? `<div class="card-grid-2col">${group.more.map((r) => renderRestaurantCard(r, false)).join('')}</div>` : ''}
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
  const nameClass = isTop ? 'restaurant-name' : 'restaurant-name more'

  return `
    <div class="restaurant-card keep-together">
      <div class="${nameClass}">${escapeHtml(card.name)}</div>
      ${meta ? `<div class="restaurant-meta">${escapeHtml(meta)}</div>` : ''}
      ${isTop && dishes ? `<div class="restaurant-dishes">推荐：${escapeHtml(dishes)}</div>` : ''}
      ${isTop && reason ? `<div class="restaurant-reason">${escapeHtml(reason)}</div>` : ''}
    </div>
  `
}

// ===== 住宿 =====
function renderStays(stays: StaySection): string {
  return `
    <div class="page-break"></div>
    <div class="section-title">住宿安排</div>
    <div class="card-grid-2col">
      ${stays.hotels.map(renderHotelCard).join('')}
    </div>
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
    <div class="hotel-card keep-together">
      <div class="hotel-name">${escapeHtml(card.name)}</div>
      <div class="hotel-meta">${escapeHtml(meta)}</div>
      ${card.note ? `<div class="hotel-note">${escapeHtml(card.note)}</div>` : ''}
    </div>
  `
}

// ===== 避坑 =====
function renderTips(tips: TipsSection): string {
  return `
    <div class="page-break"></div>
    <div class="section-title">出发前一定要看</div>
    ${tips.categories.map(renderTipCategory).join('')}
  `
}

function renderTipCategory(category: TipCategory): string {
  return `
    <div class="tip-category">
      <div class="category-label">${category.icon} ${escapeHtml(category.title)}</div>
      ${category.tips.map(renderTipCard).join('')}
    </div>
  `
}

// ===== 行李 =====
function renderPacking(packing: PackingSection): string {
  // 物品 <5 件不独占页面（PRD 第 30 条），不加 page-break
  const itemCount = packing.groups.reduce((sum, g) => sum + g.items.length, 0)
  const pageBreak = itemCount >= 5 ? '<div class="page-break"></div>' : ''
  return `
    ${pageBreak}
    <div class="section-title">行李清单</div>
    ${packing.groups.map(renderPackingGroup).join('')}
  `
}

function renderPackingGroup(group: PackingGroup): string {
  const rows = group.items.map((item) => {
    const status = renderPackStatus(item.packedBy, item.unpackedBy)
    return `
      <tr>
        <td>${escapeHtml(item.name)}</td>
        <td>${escapeHtml(status)}</td>
      </tr>
    `
  }).join('')

  return `
    <div class="category-label">${escapeHtml(group.category)}（共 ${group.items.length} 件）</div>
    <table class="overview-table">
      <thead>
        <tr>
          <th>物品</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  `
}

function renderPackStatus(packedBy: string[], unpackedBy: string[]): string {
  // 好友版：packedBy = ['✓'] 表示已带但不暴露姓名
  if (packedBy.length === 1 && packedBy[0] === '✓') return '✓'
  if (packedBy.length > 0) return `已带：${packedBy.join('、')}`
  if (unpackedBy.length > 0) return `未带：${unpackedBy.join('、')}`
  return '—'
}

// ===== 预算 =====
function renderBudget(budget: BudgetSection): string {
  const breakdownRows = budget.breakdown.map((item) => `
    <tr>
      <td>${escapeHtml(item.category)}</td>
      <td>¥${item.amount}</td>
      <td>${item.percentage}%</td>
    </tr>
  `).join('')

  const entriesTable = budget.entries && budget.entries.length > 0 ? `
    <div class="category-label" style="margin-top: 24pt;">详细记账</div>
    <table class="budget-table" style="width: 100%;">
      <thead>
        <tr>
          <th>项目</th>
          <th>分类</th>
          <th>金额</th>
          <th>付款人</th>
        </tr>
      </thead>
      <tbody>
        ${budget.entries.map((entry) => `
          <tr>
            <td>${escapeHtml(entry.title)}</td>
            <td>${escapeHtml(entry.category)}</td>
            <td>¥${entry.amount}</td>
            <td>${escapeHtml(entry.payer || '—')}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  ` : ''

  return `
    <div class="page-break"></div>
    <div class="section-title">预算概览</div>
    ${budget.total ? `<div class="budget-total">总预算：¥${budget.total}</div>` : ''}
    ${budget.perPerson ? `<div class="budget-total">人均：¥${budget.perPerson}</div>` : ''}
    <table class="budget-table">
      <thead>
        <tr>
          <th>分类</th>
          <th>金额</th>
          <th>占比</th>
        </tr>
      </thead>
      <tbody>
        ${breakdownRows}
      </tbody>
    </table>
    ${entriesTable}
  `
}

// ===== 工具函数 =====
function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
