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
