import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { API, authFetch } from '../api'
import { useAndroidBack } from '../nativeAndroid'
import { pickNavUrl } from '../interaction'
import { AndroidTripSheet } from './AndroidTripWorkspace'
import type { TripStop } from './Trips'
import './PlaceDetails.css'

type Details = { status: string; description: string; description_source: string; guide_excerpt: string; photos: {url:string;source:string}[]; facts: {label:string;value:string;source:string}[]; source_url?:string }
function Photo({url,source,name}:{url:string;source:string;name:string}) {
 const [failed,setFailed]=useState(false)
 return <figure>{failed?<div className="place-photo-empty">照片暂时无法加载</div>:<img src={url.startsWith('/api/')?'/travel'+url:url} alt={name+'实景'} onError={()=>setFailed(true)}/>}<figcaption>{source}</figcaption></figure>
}
export default function PlaceDetails({tripId,stop,onClose,onEdit}:{tripId:string;stop:TripStop;onClose:()=>void;onEdit:()=>void}) {
 const [data,setData]=useState<Details|null>(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0),[loading,setLoading]=useState(true)
 useAndroidBack(()=>{onClose();return true},36)
 useEffect(()=>{const abort=new AbortController();setLoading(true);setError('');setData(null)
  authFetch(`${API}/trips/${tripId}/stops/${stop.id}/details`,{signal:abort.signal}).then(async r=>{if(!r.ok)throw new Error('地点资料暂时未能加载');return r.json()}).then(d=>{if(!abort.signal.aborted)setData(d)}).catch(e=>{if(!abort.signal.aborted)setError(e.message)}).finally(()=>{if(!abort.signal.aborted)setLoading(false)})
  return()=>abort.abort()
 },[tripId,stop.id,attempt])
 return <AndroidTripSheet title={stop.name} onClose={onClose}><div className="place-detail" data-testid="place-detail">
  <div className="place-tags"><span>Day {stop.day}</span>{stop.start_time&&<span>{stop.start_time}</span>}{stop.stay_min!=null&&<span>停留 {stop.stay_min} 分钟</span>}</div>
  {loading?<div className="place-photo-empty" role="status">正在整理地点资料…</div>:data?.photos?.length?<div className="place-gallery" aria-label="景点照片">{data.photos.map(p=><Photo key={p.url} {...p} name={stop.name}/>)}</div>:<div className="place-photo-empty">暂无可靠实景照片</div>}
  {(error||data?.status==='temporary_error')&&<div className="place-error" role="status">{error||'地图资料暂时不可用'}<button onClick={()=>setAttempt(x=>x+1)}>重试</button></div>}
  <section><h3>行程介绍 <small>{data?.description_source||'行程说明'}</small></h3>{(data?.description||stop.note)?<ReactMarkdown>{data?.description||stop.note}</ReactMarkdown>:<p className="place-muted">还没有地点介绍，可以编辑补充你的安排。</p>}</section>
  {data?.guide_excerpt&&data.guide_excerpt!==data.description&&<section><h3>原攻略节选</h3><ReactMarkdown>{data.guide_excerpt}</ReactMarkdown></section>}
  {!!data?.facts?.length&&<section><h3>地点信息 <small>高德地图</small></h3><dl>{data.facts.map(f=><div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl></section>}
  {stop.ticket_price!=null&&<p className="place-muted">行程记录的参考费用：¥{stop.ticket_price}，以现场信息为准。</p>}
  {data?.source_url&&<a className="place-source" href={data.source_url} target="_blank" rel="noopener noreferrer">在高德地图查看资料 ↗</a>}
  <footer>{stop.nav?<a href={pickNavUrl(stop.nav,navigator.userAgent)} target="_blank" rel="noopener noreferrer">↗ 导航</a>:<span>位置待补充</span>}<button onClick={onEdit}>编辑安排</button></footer>
 </div></AndroidTripSheet>
}
