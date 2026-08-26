/**
 * 验收脚本：读真实 fixture → Composer → DOCX Renderer → 写文件
 * 用法：npx tsx scripts/gen-guide-docx.mts <mode: friend|personal> <out.docx>
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { composeShareGuide } from '../src/lib/guideComposer'
import { renderShareGuideDocx } from '../src/lib/docxRenderer'

const raw = JSON.parse(readFileSync('/tmp/trip_fixture.json', 'utf8'))
const mode = (process.argv[2] || 'friend') as 'friend' | 'personal'
const out = process.argv[3] || '/tmp/guide.docx'

// 映射 fixture → 前端类型
const trip = {
  id: raw.trip.id,
  title: raw.trip.title,
  destination: raw.trip.destination || '',
  start_date: raw.trip.start_date || '',
  days: raw.trip.days,
  day_titles: raw.trip.day_titles_json ? JSON.parse(raw.trip.day_titles_json) : {},
  stops: raw.stops.map((s: any) => ({
    id: s.id,
    day: s.day,
    order_no: s.order_no,
    name: s.name || '',
    note: s.note || '',
    location: s.location || '',
    start_time: s.start_time || '',
    transport: s.transport || '',
    ticket_price: s.ticket_price,
    tags: s.tags ? String(s.tags).split(/[\s,]+/).filter(Boolean) : [],
  })),
}

const foods = raw.foods.map((f: any) => ({
  id: f.id,
  name: f.name || '',
  city: f.city || '',
  category: f.category || '',
  meal_type: f.meal_type || '待定',
  price: f.price,
  rating: f.rating,
  address: f.address || '',
  recommend_food: f.recommend_food_json ? JSON.parse(f.recommend_food_json) : [],
  business_hours: f.business_hours || '',
  note: f.note || '',
  day: f.day,
  is_favorite: !!f.is_favorite,
  checked_in: !!f.checked_in,
}))

const tips = raw.tips.map((t: any) => ({ id: t.id, content: t.content || '', level: t.level || '' }))
const packing = { members: ['陈莉莉', 'admin'], items: [{ name: '身份证', category: '证件', states: { '陈莉莉': 'packed', 'admin': 'packed' } }] }
const expenses = (raw.expenses || []).map((e: any) => ({ title: e.title, category: e.category, amount: e.amount, payer: e.payer }))

const schema = composeShareGuide(trip as any, foods as any, tips as any, packing as any, expenses as any, {
  includePacking: true,
  includeBudget: true,
  exportMode: mode,
})

console.log('=== Schema 概览 ===')
console.log('封面标题:', schema.cover.title)
console.log('封面副标题:', schema.cover.subtitle)
console.log('封面标签:', schema.cover.tags)
console.log('天数:', schema.days.length)
console.log('酒店数(merge后):', schema.stays.hotels.length)
console.log('酒店列表:', schema.stays.hotels.map((h) => `${h.name}(${h.nights}晚)`))
console.log('美食城市组:', schema.foods.cityGroups.map((g) => `${g.city}:top${g.top.length}+more${g.more.length}`))
console.log('Tips分类:', schema.tips.categories.map((c) => `${c.title}(${c.tips.length})`))
console.log('预算总额:', schema.budget?.total, '明细条数:', schema.budget?.entries?.length ?? 0)
console.log('Overview城市:', schema.overview.stats.cities, '酒店数:', schema.overview.stats.hotels)

// Day 路线检查
schema.days.forEach((d) => {
  console.log(`  Day${d.day} [${d.city}] route: ${d.route.join(' → ')}`)
})

const blob = renderShareGuideDocx(schema)
const buf = Buffer.from(await blob.arrayBuffer())
writeFileSync(out, buf)
console.log('\n已写入', out, buf.length, 'bytes')
