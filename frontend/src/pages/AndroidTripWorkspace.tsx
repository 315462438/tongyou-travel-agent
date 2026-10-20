import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { formatTripTimeRange, pickNavUrl } from '../interaction'
import type { TripDetail, TripStop } from './Trips'
import './AndroidTripWorkspace.css'

export function AndroidTripToolbar({title, onBack, onMore, chat}: {title: string; onBack: () => void; onMore: () => void; chat: ReactNode}) {
  return <header className="android-trip-toolbar">
    <button aria-label="返回行程列表" onClick={onBack}><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m14 5-7 7 7 7" /></svg></button>
    <strong>{title}</strong>{chat}
    <button aria-label="行程更多操作" aria-haspopup="dialog" onClick={onMore}>···</button>
  </header>
}

export function AndroidTripOverview({trip, days, day, dateControl, status, title, date, count, located, aiBusy, onDay, onAdd, onAI, onTitle, view, onView, onMembers}: {
  trip: TripDetail; days: number[]; day: number; dateControl: ReactNode; status: ReactNode; title: string; date: string; count: number; located: number; aiBusy: boolean;
  onDay: (day: number) => void; onAdd: () => void; onAI: () => void; onTitle: () => void; onMembers: () => void;
  view: 'timeline' | 'map' | 'assistant'; onView: (view: 'timeline' | 'map') => void;
}) {
  const selected = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    // Scroll only the date strip; scrollIntoView would also jump the entire page.
    const el=selected.current, strip=el?.parentElement
    if(el && strip) strip.scrollTo({left: el.offsetLeft-(strip.clientWidth-el.offsetWidth)/2, behavior:'auto'})
  },[day])
  return <>
    <section className="android-trip-intro">
      <p>一起规划 · 一起出发</p><h1>{trip.title}</h1>
      <div className="android-trip-facts"><span>{trip.destination || '目的地待定'}</span><span>{trip.days} 天</span>{dateControl}{trip.budget != null && <span>预算 ¥{trip.budget.toLocaleString()}</span>}</div>
      <button className="android-trip-members" onClick={onMembers} aria-label="查看同行成员">
        <span aria-hidden="true">{trip.members.slice(0,5).map(m=><i key={m.username}>{m.username.slice(0,1)}</i>)}</span>
        {trip.members.length} 人同行 <b aria-hidden="true">›</b>
      </button>
    </section>
    {status}
    <nav className="android-trip-days" role="tablist" aria-label="选择行程日期">{days.map(d=><button key={d} ref={d===day?selected:undefined} role="tab" aria-selected={d===day} onClick={()=>onDay(d)}><b>Day {d}</b><small>{trip.day_titles?.[String(d)] || `第 ${d} 天`}</small></button>)}</nav>
    <section className="android-trip-day-card">
      <button className="android-trip-day-title" onClick={onTitle} aria-label="修改当天标题"><h2>{title}</h2><span aria-hidden="true">✎</span></button>
      <p>{count} 项安排 · {located} 处已定位{date && <small>{date}</small>}</p>
      <div><button className="primary" onClick={onAdd} disabled={trip.ai_status==='seeding'}>＋ 添加地点</button><button onClick={onAI} disabled={aiBusy}>✦ AI 调整</button></div>
    </section>
    <div className="android-trip-segments" role="tablist" aria-label="当天视图">
      <button role="tab" aria-selected={view==='timeline'} onClick={()=>onView('timeline')}>当天行程</button>
      <button role="tab" aria-selected={view==='map'} onClick={()=>onView('map')}>路线地图</button>
    </div>
  </>
}

export function AndroidTripTimeline({stops, locating, onEdit, onMove, onDelete, onMap, onAdd, stopRef}: {
  stops: TripStop[]; locating: boolean; onEdit: (stop: TripStop) => void; onMove: (stop: TripStop, direction: -1 | 1) => void;
  onDelete: (stop: TripStop) => void; onMap: (stop: TripStop) => void; onAdd: () => void; stopRef: (id: string, el: HTMLDivElement | null) => void;
}) {
  return <section className="android-trip-timeline" aria-label="当天地点安排">
    {!stops.length && <div className="android-trip-empty"><strong>这一天还没有安排</strong><p>添加一个地点，或者让 AI 帮你规划。</p></div>}
    {stops.map((stop,i)=><div className="android-trip-stop" key={stop.id} ref={el=>stopRef(stop.id,el)}>
      <div className="android-trip-rail" aria-hidden="true"><b>{i+1}</b>{i<stops.length-1 && <i/>}</div>
      <article>
        <header><h3>{stop.name}</h3>{stop.start_time && <time>{stop.start_time}</time>}</header>
        {stop.note && <p className="android-trip-note">{stop.note}</p>}
        <div className="android-trip-stop-facts">
          {stop.stay_min != null && stop.stay_min>0 && <span>{stop.stay_min>=60?`${Math.floor(stop.stay_min/60)}小时${stop.stay_min%60?`${stop.stay_min%60}分`:''}`:`${stop.stay_min}分钟`}</span>}
          {stop.transport && <span>{stop.transport}</span>}
          <span>{stop.ticket_price==null?'费用待补充':`参考 ¥${stop.ticket_price}`}</span>
          {!stop.location && !stop.tags?.includes('no_location') && <span>{locating?'位置补充中':'暂未定位'}</span>}
        </div>
        {stop.start_time && <small className="android-trip-time-range">{formatTripTimeRange(stop.start_time,stop.stay_min,stops[i+1]?.start_time)}</small>}
        <div className="android-trip-stop-actions">
          <button onClick={()=>onEdit(stop)} aria-label={`编辑 ${stop.name}`}>编辑</button>
          {stop.nav && <a href={pickNavUrl(stop.nav,navigator.userAgent)} target="_blank" rel="noopener noreferrer" aria-label={`导航到 ${stop.name}`}>导航</a>}
          <details><summary aria-label={`更多操作 ${stop.name}`}>更多</summary><div onClick={e=>e.currentTarget.parentElement?.removeAttribute('open')}>
            <button onClick={()=>onMap(stop)}>在地图上看</button>
            <button disabled={i===0} onClick={()=>onMove(stop,-1)} aria-label={`上移 ${stop.name}`}>上移</button>
            <button disabled={i===stops.length-1} onClick={()=>onMove(stop,1)} aria-label={`下移 ${stop.name}`}>下移</button>
            <button className="danger" onClick={()=>onDelete(stop)} aria-label={`删除 ${stop.name}`}>删除地点</button>
          </div></details>
        </div>
      </article>
    </div>)}
    <button className="android-trip-add" onClick={onAdd}>＋ 继续添加</button>
  </section>
}

export function AndroidTripSheet({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}) {
  const panel=useRef<HTMLElement>(null)
  const close=useRef(onClose);close.current=onClose
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus()
    const key=(e:KeyboardEvent)=>{
      const top=[...document.querySelectorAll('[role=dialog],.modal-mask')].filter(el=>el.getClientRects().length).at(-1)
      if(top && top!==panel.current && !panel.current?.contains(top)) return
      if(e.key==='Escape'){e.stopPropagation();close.current()}if(e.key==='Tab'){
      const all=[...panel.current!.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href]')].filter(x=>x.getClientRects().length)
      if(!all.length)return
      if(e.shiftKey&&document.activeElement===all[0]){e.preventDefault();all.at(-1)?.focus()}
      else if(!e.shiftKey&&document.activeElement===all.at(-1)){e.preventDefault();all[0].focus()}
    }}
    document.addEventListener('keydown',key,true)
    return()=>{document.removeEventListener('keydown',key,true);previous?.focus({preventScroll:true})}
  },[])
  return createPortal(<div className="android-trip-sheet-mask" onClick={onClose}><section ref={panel} className="android-trip-sheet" role="dialog" aria-modal="true" aria-label={title} onClick={e=>e.stopPropagation()}><header><h2>{title}</h2><button onClick={onClose} aria-label="关闭行程操作">完成</button></header>{children}</section></div>,document.body)
}
