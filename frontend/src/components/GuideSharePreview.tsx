import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { paginateShare, type ShareSummary } from '../shareSummary'
import { isAndroidApp, shareAndroidImages } from '../nativeAndroid'
import './GuideSharePreview.css'

// 一张长图的上限：iOS Safari 画布面积约 1678 万像素，宽 560 逻辑像素时 2 倍图最多约 7490 高，超了就降倍率。
const MAX_CANVAS_AREA = 16_000_000

/** book=true：整份行程画成一张「旅行手册」长图；否则按页切成卡片。 */
function drawShareCards(summary: ShareSummary, book = false): HTMLCanvasElement[] {
  const pages = book ? [summary.days] : paginateShare(summary)
  return pages.map((days, index) => {
    const canvas = document.createElement('canvas'), measure = document.createElement('canvas').getContext('2d')!
    const labels: {text:string;x:number;y:number;size:number;bold:boolean;color:string;align?:CanvasTextAlign}[] = [], rules:number[] = [], bands:{y:number;h:number}[] = []
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
    // 两端对齐的一行：右侧真正右对齐，不靠一串空格去凑（空格宽度随字体变，会停在半路）。
    const edges = (left:string, right:string, size:number, bold:boolean, color:string, gap:number) => {
      labels.push({text:right,x:524,y,size,bold,color,align:'right'}); text(left,size,bold,36,488,color,gap)
    }
    edges('17同游',book ? 'TRAVEL HANDBOOK' : 'TRAVEL NOTES',12,true,'#265cc7',38)
    text(summary.title,30,true,36,488,'#1a2433',14)
    text(summary.isItinerary ? `${summary.days.length} 天计划 · ${summary.days.reduce((n,d)=>n+d.stops.length,0)} 项安排` : '旅行笔记 · 随身简版',15,false,36,488,'#626b78',26)
    rules.push(y); y += 28
    if (book && summary.isItinerary && days.length > 1) {
      text('行程一览',14,true,36,488,'#265cc7',8)
      days.forEach((day, i) => text(`${String(i+1).padStart(2,'0')}  ${day.title}`,15,false,36,488,'#3b4656',4))
      y += 18; rules.push(y); y += 28
    }
    days.forEach(day => {
      if (book) { const top = y - 10; text(day.title,21,true,48,464,'#1a2433',0); bands.push({y:top,h:y-top+8}); y += 22 }
      else text(day.title,21,true,36,488,'#1a2433',19)
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
    edges('17tongyou.com',book ? '旅行手册' : `${index+1} / ${pages.length}`,12,false,'#626b78',30)
    const height=Math.max(y,640), scale=Math.min(2, Math.sqrt(MAX_CANVAS_AREA/(560*height)))
    canvas.width=Math.round(560*scale);canvas.height=Math.ceil(height*scale)
    const ctx=canvas.getContext('2d');if(!ctx)throw new Error('图片画布不可用，请重试')
    ctx.scale(scale,scale);ctx.fillStyle='white';ctx.fillRect(0,0,560,height)
    const gradient=ctx.createLinearGradient(0,0,280,600);gradient.addColorStop(0,'#e0f2fa');gradient.addColorStop(1,'white');ctx.fillStyle=gradient;ctx.fillRect(0,0,560,height)
    ctx.strokeStyle='#265cc70c';ctx.lineWidth=20;ctx.beginPath();ctx.ellipse(455,178,175,130,0,0,Math.PI*2);ctx.stroke()
    ctx.fillStyle='#265cc712';bands.forEach(b=>{ctx.beginPath();ctx.roundRect(36,b.y,488,b.h,10);ctx.fill()})
    ctx.fillStyle='#265cc7';bands.forEach(b=>{ctx.beginPath();ctx.roundRect(36,b.y+8,4,b.h-16,2);ctx.fill()})
    ctx.textBaseline='top'
    labels.forEach(label=>{ctx.textAlign=label.align||'left';ctx.font=`${label.bold?700:400} ${label.size}px -apple-system, BlinkMacSystemFont, "Noto Sans CJK SC", sans-serif`;ctx.fillStyle=label.color;ctx.fillText(label.text,label.x,label.y)})
    ctx.setLineDash([2,4]);ctx.strokeStyle='#1a243340';ctx.lineWidth=1
    rules.forEach(y=>{ctx.beginPath();ctx.moveTo(36,y);ctx.lineTo(524,y);ctx.stroke()})
    return canvas
  })
}

const toBlob=(canvas:HTMLCanvasElement)=>new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('图片生成失败')),'image/png'))

function downloadShareFile(blob: Blob, name: string) {
  const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)
}

export default function GuideSharePreview({summary, onClose}: {summary:ShareSummary; onClose:()=>void}) {
  const [images,setImages]=useState<string[]>([]),[page,setPage]=useState(0),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  // 默认整合成一张旅行手册（发给朋友只有一张图）；分页卡片留作备选，适合发朋友圈九宫格。
  const [mode,setMode]=useState<'book'|'cards'>('book')
  const canvases=useRef<HTMLCanvasElement[]>([]), close=useRef<HTMLButtonElement>(null)
  const signature=JSON.stringify(summary), onDismiss=useRef(onClose);onDismiss.current=onClose
  useEffect(()=>{
    const before=document.activeElement as HTMLElement|null
    close.current?.focus()
    let cancelled=false
    setImages([]);setPage(0);setError('')
    void document.fonts.ready.then(()=>{if(cancelled)return;try{canvases.current=drawShareCards(JSON.parse(signature) as ShareSummary,mode==='book');setImages(canvases.current.map(c=>c.toDataURL('image/png')))}catch(e){setError(e instanceof Error?e.message:'生成失败，请重试')}})
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')onDismiss.current();if(e.key==='Tab'){
      const buttons=Array.from(document.querySelectorAll<HTMLButtonElement>('.guide-share-dialog button:not(:disabled)'));const first=buttons[0],last=buttons.at(-1)
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
    }}
    document.addEventListener('keydown',key)
    return()=>{cancelled=true;document.removeEventListener('keydown',key);before?.focus()}
  },[signature,mode])
  const fileName=(index:number)=>`${summary.title.replace(/[/\\:*?"<>|]/g,'_').slice(0,40)}_${mode==='book'?'旅行手册':`计划单_${index+1}`}.png`
  // 一次全部：手机浏览器走系统分享（一次带上所有图，可直接发微信）；App 交给原生「全部存相册 / 一起分享」；其余逐张下载。
  const saveAll=async()=>{
    if(busy||!canvases.current.length)return;setBusy(true);setError('')
    try{
      const blobs=await Promise.all(canvases.current.map(toBlob))
      if(isAndroidApp()){shareAndroidImages(images.map((data,i)=>({name:fileName(i),data})));return}
      const files=blobs.map((blob,i)=>new File([blob],fileName(i),{type:'image/png'}))
      // 系统分享只在触屏设备用（桌面 Chrome/Safari 也支持，但电脑上用户要的是文件落到下载目录）。
      if(matchMedia('(pointer: coarse)').matches&&navigator.canShare?.({files})){
        try{await navigator.share({files,title:summary.title})}catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))throw e}
        return
      }
      for(const [i,blob] of blobs.entries()){downloadShareFile(blob,fileName(i));await new Promise(r=>setTimeout(r,250))}
    }catch(e){setError(e instanceof Error?e.message:'保存失败，请重试')}finally{setBusy(false)}
  }
  const save=async()=>{
    if(busy)return;setBusy(true);setError('')
    try{
      const canvas=canvases.current[page];if(!canvas)throw new Error('图片还未生成')
      const blob=await toBlob(canvas)
      const name=fileName(page)
      // 手册只有一张：手机浏览器直接走系统分享，能一步发到微信。
      const file=new File([blob],name,{type:'image/png'})
      if(!window.tongyouAndroidDownload&&matchMedia('(pointer: coarse)').matches&&navigator.canShare?.({files:[file]})){
        try{await navigator.share({files:[file],title:summary.title})}catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))throw e}
        return
      }
      if(window.tongyouAndroidDownload){const url=URL.createObjectURL(blob);await window.tongyouAndroidDownload(url,name);URL.revokeObjectURL(url)}
      else downloadShareFile(blob,name)
    }catch(e){setError(e instanceof Error?e.message:'保存失败，请重试')}finally{setBusy(false)}
  }
  return createPortal(<div className="guide-share-mask" onClick={onClose}>
    <section className="guide-share-dialog" role="dialog" aria-modal="true" aria-labelledby="guide-share-title" onClick={e=>e.stopPropagation()}>
      <header><button ref={close} aria-label="关闭计划单" onClick={onClose}>关闭</button><h2 id="guide-share-title">分享计划单</h2><span>{mode==='book'?'手册':`${page+1} / ${images.length||1}`}</span></header>
      <div className="guide-share-scroll">
        {summary.days.length>1&&<div className="guide-share-mode" role="radiogroup" aria-label="分享样式">
          <button role="radio" aria-checked={mode==='book'} disabled={busy} onClick={()=>setMode('book')}>旅行手册 · 1 张长图</button>
          <button role="radio" aria-checked={mode==='cards'} disabled={busy} onClick={()=>setMode('cards')}>分页卡片</button>
        </div>}
        <p>只带地点与时间，详细说明留在完整攻略里。{mode==='book'?'全部日期整合在一张图里，发给朋友只有一张。':images.length>1&&`共 ${images.length} 张，全部日期都在。`}</p>
        {images[page]?<img data-testid="guide-share-image" src={images[page]} alt={`${summary.title}，第 ${page+1} 张`} />:<p role="status">{error?'': '正在整理计划单…'}</p>}
        {error&&<p role="alert">{error}</p>}
      </div>
      <footer>
        {images.length>1&&<nav aria-label="计划单翻页"><button disabled={!page} onClick={()=>setPage(page-1)}>上一张</button><button className="guide-share-one" disabled={busy} onClick={()=>void save()}>只存第 {page+1} 张</button><button disabled={page===images.length-1} onClick={()=>setPage(page+1)}>下一张</button></nav>}
        <button className="guide-share-save" disabled={!images.length||busy} onClick={()=>void (images.length>1?saveAll():save())}>{busy?'生成中…':images.length>1?`全部保存 / 分享（${images.length} 张）`:mode==='book'?'保存 / 分享旅行手册':'保存 / 分享图片'}</button>
      </footer>
    </section>
  </div>,document.body)
}
