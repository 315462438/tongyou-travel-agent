import { useRef, useState, type CSSProperties } from 'react'
import { API, authFetch } from '../api'
import { shareAndroidLink } from '../nativeAndroid'
import './TripInvitationPanel.css'

export default function TripInvitationPanel({tripId,title,destination,days,stopCount,members,isOwner,username,onChanged}: {
  tripId:string;title:string;destination:string;days:number;stopCount:number
  members:{username:string;role:string;online?:boolean}[];isOwner:boolean;username:string;onChanged?:()=>void
}) {
  const [name,setName]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[error,setError]=useState(''),[link,setLink]=useState(''),[sent,setSent]=useState(0),[tilt,setTilt]=useState(0)
  const lock=useRef(false),pointer=useRef<number|null>(null)
  const act=async(operation:()=>Promise<void>)=>{
    if(lock.current)return;lock.current=true;setBusy(true);setNotice('');setError('')
    try{await operation()}catch(e){setError(e instanceof Error?e.message:'操作失败，请重试')}finally{lock.current=false;setBusy(false)}
  }
  const request=async(path:string,method:string,body?:object)=>{
    const r=await authFetch(`${API}/trips/${tripId}${path}`,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})})
    const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:'操作失败，请稍后重试');return data
  }
  const makeLink=async(share:boolean)=>{
    const data=await request('/share','POST',{reset:false})
    if(!/^[a-zA-Z0-9]{8}$/.test(data.short_code))throw new Error('邀请链接生成失败，请重试')
    const url=`https://17tongyou.com/t/${data.short_code}`;setLink(url)
    const text=`${username} 邀请你一起规划「${title}」 ${url}`
    if(share){
      if(shareAndroidLink('邀请加入协同行程',text))return
      if(navigator.share){try{await navigator.share({title:'邀请一起旅行',text});return}catch(e){if(e instanceof Error&&e.name==='AbortError')return;throw e}}
    }
    try{await navigator.clipboard.writeText(text)}catch{throw new Error('请长按下方链接复制')}
    setNotice('邀请已复制，发给同行的人吧。');setSent(n=>n+1)
  }
  const invite=()=>void act(async()=>{
    const target=name.trim();if(!target)throw new Error('请先填写对方的用户名')
    await request('/invite','POST',{username:target});setName('');setNotice(`已邀请 ${target}，等对方接受就能一起规划。`);setSent(n=>n+1);onChanged?.()
  })
  return <div className="trip-invitation-panel" data-testid="trip-invitation-panel">
    <div className="trip-invite-intro"><h3>{isOwner?'好风景，想和你一起。':'这趟旅行，一起完成。'}</h3><p>在同一份行程里，添上每个人的灵感。</p></div>
    <div className="trip-invite-ticket" data-testid="trip-invite-ticket" style={{'--ticket-tilt':`${tilt/12}deg`,'--ticket-shift':`${tilt/5}px`} as CSSProperties}
      onPointerDown={e=>{if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;pointer.current=e.clientX;e.currentTarget.setPointerCapture(e.pointerId)}}
      onPointerMove={e=>{if(pointer.current!==null)setTilt(Math.max(-60,Math.min(60,e.clientX-pointer.current)))}}
      onPointerUp={()=>{pointer.current=null;setTilt(0)}} onPointerCancel={()=>{pointer.current=null;setTilt(0)}}>
      <div className="trip-ticket-top"><span>17同游 / 同行邀请函</span><b key={sent} className={sent?'trip-ticket-sent':''} aria-hidden="true">{sent?'✓':'↗'}</b></div>
      <strong>{title}</strong><p>{destination||'目的地待定'} · {days} 天 · {stopCount} 个地点</p>
      <div className="trip-ticket-bottom"><span className="trip-ticket-avatars">{members.slice(0,4).map(m=><i key={m.username} aria-label={m.username}>{m.username[0]?.toUpperCase()}</i>)}</span><span>下一位，是你呀</span></div>
    </div>
    {isOwner&&<>
      <div className="trip-invite-actions"><button disabled={busy} onClick={()=>void act(()=>makeLink(false))}>复制邀请链接</button><button className="primary" disabled={busy} onClick={()=>void act(()=>makeLink(true))}>分享给朋友 <span aria-hidden="true">↗</span></button></div>
      <p className="trip-invite-permission">持有链接的人可以加入并编辑行程。请只发给同行的人；可随时关闭。</p>
      {link&&<input className="trip-invite-link" aria-label="邀请链接" value={link} readOnly onFocus={e=>e.target.select()} />}
      <form className="trip-invite-username" onSubmit={e=>{e.preventDefault();invite()}}><label htmlFor={`trip-invite-${tripId}`}>也可以按用户名邀请</label><div><input id={`trip-invite-${tripId}`} placeholder="对方的用户名" value={name} onChange={e=>setName(e.target.value)} autoCapitalize="none" autoCorrect="off" /><button disabled={busy||!name.trim()} aria-label="发送邀请">{busy?'…':'↑'}</button></div><small>对方接受后，就能共同编辑。</small></form>
    </>}
    {notice&&<p role="status" className="trip-invite-success" key={sent}>✓ {notice}</p>}
    {error&&<p role="alert" className="trip-invite-error">{error}</p>}
    <section className="trip-invite-people"><h4>同行的人 · {members.length}</h4>{members.map(m=><p key={m.username}><strong>{m.username}</strong><span>{m.role==='owner'?'创建者':'协作成员'} · {m.online?'在线':'离线'}</span></p>)}</section>
    {isOwner&&<button className="trip-invite-disable" disabled={busy} onClick={()=>{if(window.confirm('关闭邀请链接？已加入的成员会保留。'))void act(async()=>{await request('/share','DELETE');setLink('');setNotice('邀请链接已关闭，已加入成员不受影响。')})}}>关闭链接邀请</button>}
  </div>
}
