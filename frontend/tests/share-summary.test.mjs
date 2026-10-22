import test from 'node:test'
import assert from 'node:assert/strict'
import {parseShareSummary,paginateShare,summaryFromTrip} from '../src/shareSummary.ts'

test('share plan extracts table places without squeezing notes or inventing time',()=>{
  const summary=parseShareSummary('# 周末旅行\n## Day 1 · 老城\n### 当天路线\n| 时间 | 行程安排 | 费用 | 备注 |\n| --- | --- | --- | --- |\n| 09:00 | **森林公园** | ¥20 | 不进入卡片 |\n| 下午 | [半边街](https://example.com) | 待定 | |\n## Day 2\n- 08:30 湖边\n- 植物园\n![图](https://example.com/a.png)\n## 预算\n不作为地点。')
  assert.equal(summary.title,'周末旅行');assert.equal(summary.days.length,2)
  assert.deepEqual(summary.days[0].stops,[{name:'森林公园',time:'09:00'},{name:'半边街',time:'下午'}])
  assert.deepEqual(summary.days[1].stops,[{name:'湖边',time:'08:30'},{name:'植物园',time:''}])
})
test('Chinese days, date headings and route arrows survive',()=>{
  const s=parseShareSummary('## 第一天\n西湖 → 灵隐寺\n## 第二天\n- 河坊街')
  assert.equal(s.days.length,2);assert.equal(s.days[0].stops.length,2)
  assert.equal(parseShareSummary('## 10.24 周六\n- 森林公园\n## 10.25 周日\n- 植物园').days.length,2)
})
test('long plans paginate with every final-day stop intact and in order',()=>{
  const days=Array.from({length:7},(_,i)=>({title:`Day ${i+1}`,stops:Array.from({length:8},(_,j)=>({name:`第${i+1}天地点${j+1}`,time:''}))}))
  const pages=paginateShare({title:'七天',days,isItinerary:true})
  assert.ok(pages.length>1);assert.deepEqual(pages.flat().flatMap(d=>d.stops),days.flatMap(d=>d.stops))
  const markdown=days.map(day=>`## ${day.title}\n| 时间 | 地点 |\n| --- | --- |\n`+day.stops.map(s=>`| 09:00 | ${s.name} |`).join('\n')).join('\n')
  const parsed=parseShareSummary(markdown)
  assert.equal(parsed.days.length,7)
  assert.equal(paginateShare(parsed).flat().flatMap(d=>d.stops).at(-1).name,'第7天地点8')
  assert.equal(parsed.days.flatMap(d=>d.stops).length,56)
  assert.equal(parseShareSummary('**Day 1**\n- 西湖').days[0].stops[0].name,'西湖')
})
test('unstructured and huge notes remain available, bounded rows never clip the tail',()=>{
  const s=parseShareSummary('带雨伞。\n留足休息。');assert.equal(s.isItinerary,false);assert.equal(s.days[0].stops.length,2)
  const name='内容'.repeat(300)+'最后一句',long={title:'笔记',days:[{title:'笔记',stops:[{name,time:''}]}],isItinerary:false}
  assert.equal(paginateShare(long).flat().flatMap(d=>d.stops).map(s=>s.name).join(''),name)
})
test('trip export keeps empty days, actual dates, order and missing times',()=>{
  const s=summaryFromTrip({title:'合肥',days:3,start_date:'2026-10-24',stops:[{day:1,order_no:1,name:'古镇',start_time:''},{day:1,order_no:0,name:'森林',start_time:'09:00'},{day:3,order_no:0,name:'最后地点',start_time:'10:00'}]})
  assert.equal(s.days[0].title,'10.24 / 周六');assert.deepEqual(s.days[0].stops,[{name:'森林',time:'09:00'},{name:'古镇',time:''}])
  assert.equal(s.days[1].stops.length,0);assert.equal(s.days[2].stops[0].name,'最后地点')
})

// 后端 ITINERARY 提示词规定的真实格式：每天先「今日路线：A → B」，再四列表格，表后几条提示。
const REAL = `# 杭州2日\n\n> **行程速览**：西湖+灵隐。\n\n## Day 1 · 西湖经典\n**今日路线**：断桥 → 白堤 → 雷峰塔\n\n| 时段 | 地点与体验 | 交通与停留 | 参考花费 |\n| --- | --- | --- | --- |\n| 09:00-11:00 | 断桥残雪、白堤 | 步行 | 0 |\n| 17:30 | 雷峰塔 | 地铁 | 40元 |\n\n- **小贴士**：西湖周边周末限行，建议地铁出行。\n\n## Day 2 · 只有路线\n**今日路线**：灵隐寺 → 飞来峰\n\n- 提前预约灵隐寺门票，节假日人多。\n\n## 💰 预算参考\n| 项目 | 人均 |\n| --- | --- |\n| 住宿 | 500 |`

test('real guide format: each place once, table wins over route line and tips',()=>{
  const s=parseShareSummary(REAL)
  assert.deepEqual(s.days[0].stops,[{name:'断桥残雪、白堤',time:'09:00-11:00'},{name:'雷峰塔',time:'17:30'}])
})

test('real guide format: route line alone is used, without its label',()=>{
  const s=parseShareSummary(REAL)
  assert.deepEqual(s.days[1].stops.map(x=>x.name),['灵隐寺','飞来峰'])
  assert.equal(s.days.length,2,'budget section is not a day')
})
