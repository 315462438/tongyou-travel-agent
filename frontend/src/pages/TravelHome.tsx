import { useEffect, useState } from 'react'
import { API, authFetch } from '../api'

import { pickNavUrl, type NavLinks } from '../interaction'

interface Trip { id: string; title: string; destination: string; days: number; role: string }
interface TodayTrip {
  id: string; title: string; destination: string; days: number
  day?: number; day_title?: string; starts_in?: number
  stops?: { id: string; name: string; start_time: string; note: string; nav: NavLinks | null }[]
}
const localDate = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
export default function TravelHome({ name, cities, covers, unread, onTrip, onAll, onCreate, onAsk, onNotifications }: {
  name: string; unread: number; cities: string[]; covers: Record<string, string>
  onTrip: (id: string) => void; onAll: () => void; onCreate: () => void
  onAsk: (prompt?: string) => void; onNotifications: () => void
}) {
  const [trips, setTrips] = useState<Trip[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [retry, setRetry] = useState(0)
  // 出行期间（或临出发）首页先给今天的安排，不用再去翻行程
  const [today, setToday] = useState<TodayTrip | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    authFetch(`${API}/trips/today?date=${localDate()}`, { signal: controller.signal })
      .then(async r => { if (r.ok) setToday((await r.json()).trip) }).catch(() => {})
    return () => controller.abort()
  }, [retry])
  useEffect(() => {
    const controller = new AbortController()
    setState('loading')
    authFetch(`${API}/trips`, { signal: controller.signal }).then(async r => {
      if (!r.ok) throw new Error('trips')
      const data = await r.json()
      if (!controller.signal.aborted) { setTrips(data); setState('ready') }
    }).catch(() => { if (!controller.signal.aborted) setState('error') })
    return () => controller.abort()
  }, [retry])
  return <section className="travel-home" aria-label="旅行首页">
    <header className="travel-toolbar"><span className="travel-wordmark">17同游<span>一起出发</span></span><button onClick={onNotifications} aria-label={unread ? `通知，${unread} 条未读` : "通知"}><svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M5 16V10a7 7 0 0 1 14 0v6l2 2H3l2-2ZM9 21h6" /></svg>{unread > 0 && <span className="travel-unread">{unread > 99 ? "99+" : unread}</span>}</button></header>
    <div className="travel-welcome"><p>{name}，下一站去哪儿？</p><h1>把期待，<br />变成一段旅行。</h1></div>
    {today && <section className="travel-today" aria-label={today.day ? '今天的行程' : '即将出发'}>
      <button className="travel-today-head" onClick={() => onTrip(today.id)}>
        <span><small>{today.day ? `今天 · 第 ${today.day} / ${today.days} 天` : today.starts_in === 1 ? '明天出发' : `还有 ${today.starts_in} 天出发`}</small><strong>{today.day_title || today.title}</strong></span>
        <i aria-hidden>打开行程 ↗</i>
      </button>
      {today.day && !today.stops?.length && <p className="travel-today-empty">今天还没有安排，打开行程加几个地点。</p>}
      {!!today.stops?.length && <ol>{today.stops.slice(0, 5).map(stop => <li key={stop.id}>
        <span>{stop.start_time && <time>{stop.start_time}</time>}<b>{stop.name}</b></span>
        {stop.nav && <a href={pickNavUrl(stop.nav, navigator.userAgent)} target="_blank" rel="noopener noreferrer" aria-label={`导航到 ${stop.name}`}>导航</a>}
      </li>)}{today.stops.length > 5 && <li className="more"><span>还有 {today.stops.length - 5} 个地点</span></li>}</ol>}
    </section>}
    <div className="travel-primary-actions"><button className="travel-primary" onClick={onCreate}><span aria-hidden>＋</span> 新建旅行</button><button className="travel-secondary" onClick={() => onAsk('帮我把这篇攻略整理成行程：')}><span aria-hidden>↗</span> 导入攻略</button></div>
    <section className="travel-library" aria-labelledby="my-travel-title">
      <div className="travel-section-head"><h2 id="my-travel-title">我的旅行</h2><button onClick={onAll}>全部行程 <span aria-hidden>↗</span></button></div>
      {state === 'loading' && <div className="travel-loading" role="status">正在打开旅行册…</div>}
      {state === 'error' && <div className="travel-empty" role="alert"><p>暂时没能加载行程</p><button onClick={() => setRetry(v => v + 1)}>重新加载</button></div>}
      {state === 'ready' && !trips.length && <div className="travel-empty"><div className="travel-paper-art" aria-hidden><span>出发</span><i>下一站</i></div><h3>第一本旅行册，等你翻开</h3><p>先选一个目的地，慢慢安排每一天。</p><button onClick={() => onAsk('帮我规划一次轻松的周末旅行')}>一起想想去哪儿 <span aria-hidden>↗</span></button></div>}
      {state === 'ready' && trips.length > 0 && <div className="travel-book-grid">{trips.slice(0, 4).map((trip, i) => <button key={trip.id} className={`travel-book travel-tone-${i % 4}`} onClick={() => onTrip(trip.id)} aria-label={`打开行程 ${trip.title}`}>
        <span className="travel-book-spine" aria-hidden />
        <span className="travel-book-top"><span>{trip.destination || '目的地待定'}</span><span>{trip.days} 天</span></span>
        <span className="travel-book-art" aria-hidden><svg viewBox="0 0 260 90" fill="none"><path d="M10 68C45-10 65 110 115 45S185 25 247 15" stroke="currentColor" strokeWidth="2" strokeDasharray="4 6"/><circle cx="12" cy="65" r="5" fill="currentColor"/><path d="m236 8 14 6-11 10" stroke="currentColor" strokeWidth="2"/></svg></span>
        <strong>{trip.title}</strong><span className="travel-book-footer">{trip.role === 'owner' ? '我的行程' : '一起规划'}<span aria-hidden>打开 ↗</span></span>
      </button>)}</div>}
    </section>
    {!!cities.length && <section className="travel-inspiration" aria-labelledby="travel-inspiration-title"><div className="travel-section-head"><h2 id="travel-inspiration-title">下一站灵感</h2><span>选个地方，聊聊怎么玩</span></div><div className="travel-destinations">{cities.slice(0, 4).map((city, i) => <button key={city} className={`travel-destination travel-tone-${i % 4}`} onClick={() => onAsk(`我想去${city}，帮我规划一次旅行`)} aria-label={`聊聊${city}`}>
      {covers[city] && <img src={`${API}/img?u=${encodeURIComponent(covers[city])}`} alt="" loading="lazy" onError={e => { e.currentTarget.hidden = true }} />}
      <span className="travel-destination-mark" aria-hidden>↗</span><strong>{city}</strong><small>留一点时间，去看看</small>
    </button>)}</div></section>}
  </section>
}
