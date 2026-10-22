import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { paginateShare, type ShareSummary } from '../shareSummary'
import './GuideSharePreview.css'

function drawShareCards(summary: ShareSummary): HTMLCanvasElement[] {
  const pages = paginateShare(summary)
  return pages.map((days, index) => {
    const canvas = document.createElement('canvas'), measure = document.createElement('canvas').getContext('2d')!
    const labels: {text:string;x:number;y:number;size:number;bold:boolean;color:string}[] = [], rules:number[] = []
    let y = 36
    const text = (value:string, size:number, bold=false, x=36, width=488, color='#1a2433', gap=0) => {
      measure.font = `${bold ? 700 : 400} ${size}px -apple-system, BlinkMacSystemFont, "Noto Sans CJK SC", sans-serif`
      let row = ''
      for (const char of value) {
        if (char === '\n' || measure.measureText(row + char).width > width) {
          labels.push({text:row,x,y,size,bold,color}); y += size * 1.4; row = ''
          if (char === '\n') continue
        }
        row += char
      }
      labels.push({text:row,x,y,size,bold,color}); y += size * 1.4 + gap
    }
    text('17同游                                       TRAVEL NOTES',12,true,36,488,'#265cc7',38)
    text(summary.title,30,true,36,488,'#1a2433',14)
    text(summary.isItinerary ? `${summary.days.length} 天计划 · ${summary.days.reduce((n,d)=>n+d.stops.length,0)} 项安排` : '旅行笔记 · 随身简版',15,false,36,488,'#626b78',26)
    rules.push(y); y += 28
    days.forEach(day => {
      text(day.title,21,true,36,488,'#1a2433',19)
      if (!day.stops.length) text('这一天留给自由安排',18,false,36,488,'#626b78',12)
      day.stops.forEach(stop => {
        const rowY = y
        text(stop.name,21,false,36,350,'#1a2433',16)
        const endY = y
        if(stop.time) { y=rowY+3; text(stop.time,14,false,402,122,'#626b78'); y=Math.max(endY,y+16) }
      })
      y+=8;rules.push(y);y+=26
    })
    text('一起规划，一起出发',15,true,36,488,'#265cc7',8)
    text('简版计划 · 详细说明请查看完整攻略',12,false,36,488,'#626b78',8)
    text(`17tongyou.com                                      ${index+1} / ${pages.length}`,12,false,36,488,'#626b78',30)
    canvas.width=1120;canvas.height=Math.ceil(Math.max(y,640)*2)
    const ctx=canvas.getContext('2d');if(!ctx)throw new Error('图片画布不可用，请重试')
    ctx.scale(2,2);ctx.fillStyle='white';ctx.fillRect(0,0,560,canvas.height/2)
    const gradient=ctx.createLinearGradient(0,0,280,600);gradient.addColorStop(0,'#e0f2fa');gradient.addColorStop(1,'white');ctx.fillStyle=gradient;ctx.fillRect(0,0,560,canvas.height/2)
    ctx.strokeStyle='#265cc70c';ctx.lineWidth=20;ctx.beginPath();ctx.ellipse(455,178,175,130,0,0,Math.PI*2);ctx.stroke()
    ctx.textBaseline='top'
    labels.forEach(label=>{ctx.font=`${label.bold?700:400} ${label.size}px -apple-system, BlinkMacSystemFont, "Noto Sans CJK SC", sans-serif`;ctx.fillStyle=label.color;ctx.fillText(label.text,label.x,label.y)})
    ctx.setLineDash([2,4]);ctx.strokeStyle='#1a243340';ctx.lineWidth=1
    rules.forEach(y=>{ctx.beginPath();ctx.moveTo(36,y);ctx.lineTo(524,y);ctx.stroke()})
    return canvas
  })
}

function downloadShareFile(blob: Blob, name: string) {
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)
}

export default function GuideSharePreview({summary, fullText, onClose}: {summary:ShareSummary; fullText?:string; onClose:()=>void}) {
  const [images,setImages]=useState<string[]>([]),[page,setPage]=useState(0),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const canvases=useRef<HTMLCanvasElement[]>([]), close=useRef<HTMLButtonElement>(null)
  const signature=JSON.stringify(summary), onDismiss=useRef(onClose);onDismiss.current=onClose
  useEffect(()=>{
    const before=document.activeElement as HTMLElement|null
    close.current?.focus()
    let cancelled=false
    void document.fonts.ready.then(()=>{if(cancelled)return;try{canvases.current=drawShareCards(JSON.parse(signature) as ShareSummary);setImages(canvases.current.map(c=>c.toDataURL('image/png')))}catch(e){setError(e instanceof Error?e.message:'生成失败，请重试')}})
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')onDismiss.current();if(e.key==='Tab'){
      const buttons=Array.from(document.querySelectorAll<HTMLButtonElement>('.guide-share-dialog button:not(:disabled)'));const first=buttons[0],last=buttons.at(-1)
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
    }}
    document.addEventListener('keydown',key)
    return()=>{cancelled=true;document.removeEventListener('keydown',key);before?.focus()}
  },[signature])
  const save=async()=>{
    if(busy)return;setBusy(true);setError('')
    try{
      const canvas=canvases.current[page];if(!canvas)throw new Error('图片还未生成')
      const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('图片生成失败')),'image/png'))
      const name=`${summary.title.replace(/[/\\:*?"<>|]/g,'_').slice(0,40)}_计划单_${page+1}.png`
      if(window.tongyouAndroidDownload){const url=URL.createObjectURL(blob);await window.tongyouAndroidDownload(url,name);URL.revokeObjectURL(url)}
      else downloadShareFile(blob,name)
    }catch(e){setError(e instanceof Error?e.message:'保存失败，请重试')}finally{setBusy(false)}
  }
  return createPortal(<div className="guide-share-mask" onClick={onClose}>
    <section className="guide-share-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-share-title" onClick={e=>e.stopPropagation()}>
      <header><button ref={close} aria-label="关闭计划单" onClick={onClose}>关闭</button><h2 id="guide-share-title">分享计划单</h2><span>{page+1} / {images.length||1}</span></header>
      <div className="guide-share-scroll">
        <p>只带地点与时间，详细说明留在完整攻略里。{images.length>1&&`共 ${images.length} 张，全部日期都在。`}</p>
        {images[page]?<img data-testid="guide-share-image" src={images[page]} alt={`${summary.title}，第 ${page+1} 张`} />:<p role="status">{error?'': '正在整理计划单…'}</p>}
        {error&&<p role="alert">{error}</p>}
      </div>
      <footer>
        {images.length>1&&<nav aria-label="计划单翻页"><button disabled={!page} onClick={()=>setPage(page-1)}>上一张</button><span>{page+1} / {images.length}</span><button disabled={page===images.length-1} onClick={()=>setPage(page+1)}>下一张</button></nav>}
        <button className="guide-share-save" disabled={!images.length||busy} onClick={()=>void save()}>{busy?'生成中…':images.length>1?`保存 / 分享第 ${page+1} 张`:'保存 / 分享图片'}</button>
        {fullText&&<button className="guide-share-full" onClick={()=>downloadShareFile(new Blob([fullText],{type:'text/plain;charset=utf-8'}),`${summary.title.slice(0,40)}_完整攻略.txt`)}>下载完整文字</button>}
      </footer>
    </section>
  </div>,document.body)
}
