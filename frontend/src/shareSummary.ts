export interface ShareStop { name: string; time: string }
export interface ShareDay { title: string; stops: ShareStop[] }
export interface ShareSummary { title: string; days: ShareDay[]; isItinerary: boolean }

export function sharePlain(value: string): string {
  return value.replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '').replace(/[*_`#]/g, '').trim()
}

/** Copy the guide's itinerary, without an extra model request or invented opening times. */
export function parseShareSummary(markdown: string, fallback = '我的旅行计划'): ShareSummary {
  const title = sharePlain(markdown.split('\n').slice(0, 8).find(l => /^#{1,6}\s/.test(l)) || fallback) || '我的旅行计划'
  const days: ShareDay[] = [], notes: ShareStop[] = []
  let current: ShareDay | undefined, header: string[] = [], code = false
  const flush = () => { if (current) days.push(current); current = undefined }
  const add = (value: string, time = '') => {
    const stop = {name: sharePlain(value), time: sharePlain(time)}
    if (!stop.name) return
    const target = current?.stops || notes, last = target.at(-1)
    if (last?.name !== stop.name || last.time !== stop.time) target.push(stop)
  }
  for (const raw of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const line = raw.trim(), text = sharePlain(line)
    if (line.startsWith('```')) { code = !code; continue }
    if (code || !line || line.startsWith('![') || line.startsWith('[[img:')) continue
    const heading = line.startsWith('#') || /^\*\*.+\*\*$/.test(line)
    if (!line.startsWith('|') && !/^[-*•]\s/.test(line) && (heading || text.length < 95) && (/(?:^|[\s·｜|])(?:day\s*\d+|第[一二三四五六七八九十\d]+[天日])/i.test(text) || /^\d{1,2}[月./]\d{1,2}(?:日|\s|[｜|·：:]|$)/.test(text))) {
      flush(); current = {title: text, stops: []}; header = []; continue
    }
    if (heading) {
      if (/预算|费用|住宿推荐|酒店推荐|美食推荐|注意事项|旅行贴士|行前|行李|总结|参考来源/.test(text)) flush()
      header = []
      if (!current && text !== title) notes.push({name: text, time: ''})
      continue
    }
    if (line.startsWith('|')) {
      const cells = line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(sharePlain)
      if (cells.every(c => /^[-: ]*$/.test(c))) continue
      if (!header.length) { header = cells; continue }
      const place = header.findIndex(c => /地点|景点|安排|活动|行程|项目|去哪里/.test(c)), time = header.findIndex(c => /时间|时段/.test(c))
      if (place >= 0 && place < cells.length) add(cells[place], cells[time] || '')
      else if (current) add(cells.filter((_, i) => i !== time).join(' · '), cells[time] || '')
      continue
    }
    header = []
    if (/^(---|\*\*\*|___)$/.test(line) || line.startsWith('>')) continue
    const stripped = text.replace(/^(?:[-+•]\s*|\d+[.、)]\s*)/, '')
    if (current) {
      if (stripped.includes('→')) stripped.split('→').forEach(s => add(s))
      else {
        const time = /^(?:[0-2]?\d[:：][0-5]\d(?:\s*[-–—~～至]\s*[0-2]?\d[:：][0-5]\d)?|上午|中午|下午|傍晚|晚上|早餐|午餐|晚餐)/.exec(stripped)
        if (time) add(stripped.slice(time[0].length).replace(/^[ ：:·｜|\-–—]+/, '') || stripped, time[0])
        else if (/^[-*•]/.test(line) || stripped !== text || (!/[：。]/.test(stripped) && stripped.length < 65)) add(stripped)
      }
    } else if (stripped) notes.push({name: stripped, time: ''})
  }
  flush()
  const isItinerary = days.some(d => d.stops.length)
  return {title, isItinerary, days: isItinerary ? days : [{title:'旅行笔记', stops:notes.length ? notes : [{name:sharePlain(markdown) || '暂无可分享的内容',time:''}]}]}
}

/** Bound each card while keeping every extracted stop, including the final day. */
export function paginateShare(summary: ShareSummary, maxUnits = 24): ShareDay[][] {
  const pages: ShareDay[][] = []
  let page: ShareDay[] = [], units = 0
  const flush = () => { if (page.length) pages.push(page); page = []; units = 0 }
  for (const day of summary.days) {
    let continuation = false
    const rows = day.stops.flatMap(stop => {
      const chars = Array.from(stop.name)
      return Array.from({length:Math.max(1, Math.ceil(chars.length / 100))}, (_, i) => ({name:chars.slice(i*100, (i+1)*100).join(''),time:i ? '续' : stop.time}))
    })
    if (!rows.length) {
      if (units + 3 > maxUnits) flush()
      page.push({title:day.title, stops:[]}); units += 3
    }
    for (const stop of rows) {
      const cost = Math.max(1, Math.ceil(Array.from(stop.name).length / 19)) + 1
      if (units + cost + (page.at(-1)?.title === day.title ? 0 : 2) > maxUnits) { flush(); continuation = true }
      const title = day.title + (continuation ? ' · 续' : '')
      if (page.at(-1)?.title !== title) { page.push({title, stops:[]}); units += 2 }
      page.at(-1)!.stops.push(stop); units += cost
    }
  }
  flush()
  return pages
}

export function summaryFromTrip(trip: {title:string; days:number; start_date:string; day_titles?:Record<string,string>; stops:{day:number; order_no:number; name:string; start_time:string}[]}): ShareSummary {
  const last = Math.max(trip.days, ...trip.stops.map(s => s.day), 1)
  return {title:trip.title, isItinerary:true, days:Array.from({length:last}, (_, i) => {
    const day = i + 1
    const start = /^\d{4}-\d{2}-\d{2}$/.test(trip.start_date) ? new Date(trip.start_date + 'T00:00:00Z') : null
    if (start) start.setUTCDate(start.getUTCDate() + i)
    const date = start && Number.isFinite(start.getTime()) ? `${start.getUTCMonth()+1}.${String(start.getUTCDate()).padStart(2,'0')} / 周${'日一二三四五六'[start.getUTCDay()]}` : `Day ${day}`
    return {title:date + (trip.day_titles?.[String(day)] ? ' · ' + trip.day_titles[String(day)] : ''),stops:trip.stops.filter(s => s.day === day).sort((a,b) => a.order_no-b.order_no).map(s => ({name:s.name,time:s.start_time || ''}))}
  })}
}
