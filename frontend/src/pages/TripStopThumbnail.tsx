import { useEffect, useRef, useState } from 'react'
import { API, authFetch } from '../api'

/** Fetch only visible stops; a missing image stays a quiet location placeholder. */
export default function TripStopThumbnail({tripId,stopId,identity,index}:{tripId:string;stopId:string;identity:string;index:number}) {
 const ref=useRef<HTMLSpanElement>(null),[url,setUrl]=useState(''),[failed,setFailed]=useState(false)
 useEffect(()=>{const controller=new AbortController();let started=false;setUrl('');setFailed(false)
  const observer=new IntersectionObserver(entries=>{if(started||!entries.some(e=>e.isIntersecting))return;started=true;observer.disconnect()
   authFetch(`${API}/trips/${tripId}/stops/${stopId}/details`,{signal:controller.signal}).then(async r=>r.ok?r.json():null).then(data=>{if(!controller.signal.aborted)setUrl(data?.photos?.[0]?.url||'')}).catch(()=>{})
  },{root:ref.current?.closest('.trip-3col'),rootMargin:'60px'})
  if(ref.current)observer.observe(ref.current)
  return()=>{controller.abort();observer.disconnect()}
 },[tripId,stopId,identity])
 return <span ref={ref} className="trip-stop-thumbnail" aria-hidden="true">{url&&!failed?<img src={url.startsWith('/api/')?'/travel'+url:url} alt="" onError={()=>setFailed(true)}/>:<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/></svg>}<b>{index}</b></span>
}
