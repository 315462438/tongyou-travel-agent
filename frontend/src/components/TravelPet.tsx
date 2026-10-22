import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { API, authFetch } from '../api'
import { useAndroidBack } from '../nativeAndroid'
import { addedPetMembers, nextPetAct, nextPetTip, petBubble, petActAllowed, petActDelay, petFlightFrames, readPetPreferences, petPreparation, PET_ACT_MS, type PetAct, type PetCheck, type PetTip, type PetPreferences, type PetTask, type PetTrip } from '../travelPet'
import './TravelPet.css'

export function usePetPreferences(username: string) {
  const key = `travel_pet_v1:${username}`
  const [preferences, setPreferences] = useState<PetPreferences>(() => {
    try { return readPetPreferences(localStorage.getItem(key)) } catch { return readPetPreferences(null) }
  })
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(preferences)) } catch { /* Private browsing may deny storage. */ } }, [key, preferences])
  return [preferences, setPreferences] as const
}

export function PetArt({ pose = 'idle', act }: { pose?: string; act?: PetAct | null }) {
  return <span className={`yp-art yp-${pose}${act ? ` yp-act-${act}` : ''}`} aria-hidden="true"><span className="yp-otter"><span className="yp-tail" /><span className="yp-pack" /><span className="yp-body" /><span className="yp-belly" /><span className="yp-foot yp-left" /><span className="yp-foot yp-right" /><span className="yp-ear yp-left" /><span className="yp-ear yp-right" /><span className="yp-head"><span className="yp-face" /><span className="yp-eye yp-left" /><span className="yp-eye yp-right" /><span className="yp-cheek yp-left" /><span className="yp-cheek yp-right" /><span className="yp-muzzle" /><span className="yp-nose" /><span className="yp-mouth" /></span><span className="yp-strap" /><span className="yp-map"><i /><i /><i /></span><span className="yp-paw yp-left" /><span className="yp-paw yp-right" /><span className="yp-heart">♥</span><span className="yp-mark" /></span></span>
}

export function PetTaskBadge({ task, quiet, onTools }: { task: PetTask; quiet: boolean; onTools: () => void }) {
  return <button className="pet-task-badge" data-quiet={quiet} onClick={onTools} aria-label={`游游，${task.label}，打开旅行工具`}><PetArt pose={task.phase} /><span><strong>游游 · 同游 AI</strong><small role="status">{task.detail || task.label}</small></span></button>
}

const motionOff = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * 问 AI 的衔接：克隆按钮里的游游，从停靠处跳进 AI 面板标题栏的小游游；面板同时从它的位置展开。
 * 在 setAiOpen 之前同步调用（此时按钮还在），落点在下一帧量——React 离散事件已同步提交、还没绘制。
 */
export function flyPetToAI(source: HTMLElement | null | undefined, quiet: boolean) {
  if (!source || quiet || motionOff() || typeof source.animate !== 'function') return
  const from = source.getBoundingClientRect()
  if (!from.width) return
  const ghost = source.cloneNode(true) as HTMLElement
  ghost.className = 'yp-art yp-launch pet-flight'
  Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px` })
  const ox = from.left + from.width / 2, oy = from.top + from.height / 2
  requestAnimationFrame(() => {
    const panel = document.querySelector<HTMLElement>('.ai-workspace')
    if (panel && !panel.hidden) {
      panel.style.setProperty('--pet-ox', `${Math.round(ox)}px`)
      panel.style.setProperty('--pet-oy', `${Math.round(oy)}px`)
      // 揭开动画顶替了面板自带的淡入；结束时不能只摘掉类名——那会让淡入从透明重播一遍，整屏闪一下。
      // 换成 ai-pet-opened（animation:none）停住，面板收起时再摘掉，下次别的入口打开照常淡入。
      panel.classList.remove('ai-pet-opened')
      panel.classList.add('ai-from-pet')
      const settle = () => {
        if (!panel.classList.contains('ai-from-pet')) return
        panel.classList.add('ai-pet-opened'); panel.classList.remove('ai-from-pet')
        const closed = new MutationObserver(() => { if (panel.hidden) { panel.classList.remove('ai-pet-opened'); closed.disconnect() } })
        closed.observe(panel, { attributes: true, attributeFilter: ['hidden'] })
      }
      const done = (event: AnimationEvent) => { if (event.target === panel) { panel.removeEventListener('animationend', done); settle() } }
      panel.addEventListener('animationend', done)
      window.setTimeout(settle, 900)
    }
    const target = document.querySelector<HTMLElement>('.ai-workspace:not([hidden]) .journey-ai-header .pet-task-badge .yp-art')
    const to = target?.getBoundingClientRect()
    document.body.appendChild(ghost)
    const restore = () => { ghost.remove(); if (target) target.style.visibility = '' }
    if (!target || !to?.width) {
      ghost.animate([{ opacity: 1, transform: 'scale(1)' }, { opacity: 0, transform: 'translateY(-40px) scale(.7)' }], { duration: 320, easing: 'ease-out' }).finished.then(restore, restore)
      return
    }
    target.style.visibility = 'hidden'
    const flight = ghost.animate(petFlightFrames(from, to), { duration: 560, easing: 'cubic-bezier(.45,0,.25,1)', fill: 'forwards' })
    const safety = window.setTimeout(restore, 1200)
    flight.finished.then(() => {
      window.clearTimeout(safety); restore()
      target.classList.add('yp-landed')
      window.setTimeout(() => target.classList.remove('yp-landed'), 520)
    }, () => { window.clearTimeout(safety); restore() })
  })
}

/** 待机小动作：只在空闲/完成、可见、未减少动态、页面在前台时随机播放，播完隔 6–12 秒再来。 */
function usePetAct(enabled: boolean) {
  const [act, setAct] = useState<PetAct | null>(null)
  useEffect(() => {
    if (!enabled || motionOff()) { setAct(null); return }
    let last: PetAct | null = null
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      timer = setTimeout(() => {
        if (document.visibilityState === 'visible') {
          last = nextPetAct(last); setAct(last)
          timer = setTimeout(() => { setAct(null); schedule() }, PET_ACT_MS)
        } else schedule()
      }, petActDelay())
    }
    schedule()
    return () => { clearTimeout(timer); setAct(null) }
  }, [enabled])
  return act
}

// 指引一次会话只说一句，组件重挂载（切页面）也不重复。
let tipShownThisSession = false

/** 空闲 6 秒后说一句还没说过的指引，9 秒后自己收起。 */
function usePetTip(enabled: boolean, phase: PetTask['phase'], seen: readonly string[] | undefined, onSeen: (id: string) => void) {
  const [tip, setTip] = useState<PetTip | null>(null)
  const latest = useRef({ seen, onSeen, phase })
  latest.current = { seen, onSeen, phase }
  useEffect(() => {
    if (!enabled || tipShownThisSession) return
    const show = setTimeout(() => {
      const next = nextPetTip(latest.current.seen, latest.current.phase)
      if (!next || tipShownThisSession) return
      tipShownThisSession = true
      setTip(next); latest.current.onSeen(next.id)
    }, 6000)
    return () => clearTimeout(show)
  }, [enabled])
  useEffect(() => { if (!tip) return; const hide = setTimeout(() => setTip(null), 9000); return () => clearTimeout(hide) }, [tip])
  useEffect(() => { if (!enabled) setTip(null) }, [enabled])
  return [tip, setTip] as const
}

export default function TravelPet({ task, conversation, title, preferences, hidden, onAsk, onTools, onTipSeen }: {
  task: PetTask; conversation: string | null; title?: string; preferences: PetPreferences; hidden: boolean
  /** toTask=true：点的是进度/完成提醒，要回到游游正在跟的那个对话。 */
  onAsk: (from?: HTMLElement | null, toTask?: boolean) => void; onTools: () => void; onTipSeen: (id: string) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const gesture = useRef<{ x: number; y: number; moved: boolean; long: boolean } | null>(null)
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const liveTurn = useRef<{ conversation: string; turn: string } | null>(null)
  const [finished, setFinished] = useState(false)
  const [cheer, setCheer] = useState(0)
  const act = usePetAct(preferences.visible && !preferences.quiet && !hidden && petActAllowed(task.phase) && !finished)
  const [tip, setTip] = usePetTip(preferences.visible && !hidden && petActAllowed(task.phase) && !finished, task.phase, preferences.tipsSeen, onTipSeen)
  const bubble = preferences.visible ? petBubble(task, finished, tip, title) : null
  const art = () => host.current?.querySelector<HTMLElement>('.travel-pet-fab .yp-art')
  const tapBubble = () => {
    if (bubble?.kind === 'tip') {
      setTip(null)
      if (bubble.tip.action === 'ask') onAsk(art())
      else if (bubble.tip.action === 'tools') onTools()
      return
    }
    setFinished(false)
    onAsk(art(), true)
  }
  const [side, setSide] = useState(preferences.side)
  useEffect(() => setSide(preferences.side), [preferences.side])
  useEffect(() => {
    if (task.phase === 'working' || task.phase === 'waiting') liveTurn.current = { conversation: conversation || '', turn: task.turn }
    else {
      const previous = liveTurn.current
      liveTurn.current = null
      if (task.phase === 'ready' && previous && previous.conversation === conversation && previous.turn === task.turn) { setFinished(true); setCheer(count => count + 1) }
    }
    // 完成提醒一直留着，直到点开、点✕或开始下一轮。
    if (task.phase === 'working' || task.phase === 'waiting') setFinished(false)
  }, [conversation, task.phase, task.turn])
  const clearPress = () => { if (pressTimer.current) clearTimeout(pressTimer.current); pressTimer.current = null }
  useEffect(() => () => { if (pressTimer.current) clearTimeout(pressTimer.current) }, [])
  const suppressed = useRef(false)
  const down = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 || !preferences.visible) return
    clearPress()
    gesture.current = { x: event.clientX, y: event.clientY, moved: false, long: false }
    event.currentTarget.setPointerCapture(event.pointerId)
    pressTimer.current = setTimeout(() => { if (gesture.current && !gesture.current.moved) { gesture.current.long = true; suppressed.current = true; onTools() } }, 550)
  }
  const move = (event: PointerEvent<HTMLButtonElement>) => {
    const start = gesture.current
    if (!start || start.long) return
    const dx = event.clientX - start.x
    if (Math.hypot(dx, event.clientY - start.y) > 8) { start.moved = true; clearPress() }
    if (start.moved && host.current) {
      const rect = host.current.getBoundingClientRect()
      const current = Number(host.current.dataset.drag || 0)
      const delta = Math.max(10 - (rect.left - current), Math.min(innerWidth - 10 - (rect.right - current), dx))
      host.current.style.translate = `${delta}px 0`
      host.current.dataset.lean = delta - current < -1 ? 'left' : delta - current > 1 ? 'right' : host.current.dataset.lean || ''
      host.current.dataset.drag = String(delta)
    }
  }
  const up = (event: PointerEvent<HTMLButtonElement>) => {
    clearPress()
    const start = gesture.current
    gesture.current = null
    if (host.current) { host.current.style.translate = ''; delete host.current.dataset.drag; delete host.current.dataset.lean }
    if (start?.moved) {
      suppressed.current = true
      const next = event.clientX < innerWidth / 2 ? 'left' : 'right'
      setSide(next)
      // The parent owns the persisted preference and navigation clearance.
      window.dispatchEvent(new CustomEvent('tongyou:pet-side', { detail: next }))
    }
  }
  return <div ref={host} className="travel-pet-dock" data-side={side} data-quiet={preferences.quiet} hidden={hidden}>
    {cheer > 0 && !preferences.quiet && preferences.visible && <span key={cheer} className="pet-cheer" aria-hidden="true">{['🎉', '✨', '💙', '👏', '🌟'].map(emoji => <i key={emoji}>{emoji}</i>)}</span>}
    {bubble && <div className="travel-pet-bubble" data-kind={bubble.kind} aria-live="polite">
      <button key={bubble.text} className="pet-bubble-main" onClick={tapBubble}>{bubble.kind === 'progress' && <i aria-hidden="true" />}{bubble.kind === 'done' && <b aria-hidden="true">✓</b>}{bubble.text}</button>
      {(bubble.kind === 'tip' || bubble.kind === 'done') && <button className="pet-bubble-close" aria-label="收起提示" onClick={() => { setTip(null); setFinished(false) }}>✕</button>}
    </div>}
    <button className={`journey-ai-fab${preferences.visible ? ' travel-pet-fab' : ''}`} data-no-press={preferences.visible || undefined} aria-label={task.phase === 'working' || task.phase === 'waiting' ? '问 AI，正在生成' : '问 AI'}
      aria-description={preferences.visible ? '游游旅行搭子，长按打开旅行工具，拖动到左右两侧' : undefined}
      onClick={event => { if (suppressed.current) { suppressed.current = false; return } onAsk(event.currentTarget.querySelector<HTMLElement>('.yp-art'), finished || !petActAllowed(task.phase)) }}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => { clearPress(); gesture.current = null; if (host.current) { host.current.style.translate = ''; delete host.current.dataset.drag; delete host.current.dataset.lean } }}
      onContextMenu={event => { event.preventDefault(); if (preferences.visible) onTools() }}>
      {preferences.visible ? <PetArt pose={finished ? 'happy' : task.phase} act={act} /> : <span aria-hidden="true">✦</span>}
      <span>{task.phase === 'working' || task.phase === 'waiting' ? '生成中' : '问 AI'}</span>
    </button>
  </div>
}

export function PetTools({ preferences, onChange, onClose, onAsk, onTrip }: {
  preferences: PetPreferences; onChange: (next: PetPreferences) => void; onClose: () => void
  onAsk: () => void; onTrip: (id: string) => void
}) {
  const panel = useRef<HTMLElement>(null)
  const [pat, setPat] = useState(false)
  const [checking, setChecking] = useState(false)
  const [trips, setTrips] = useState<{ id: string; title: string }[] | null>(null)
  const [selected, setSelected] = useState('')
  const [checks, setChecks] = useState<PetCheck[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useAndroidBack(() => { onClose(); return true }, 95)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const app = document.querySelector<HTMLElement>('.journey-shell')
    const wasInert = app?.inert
    if (app) app.inert = true
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus()
    return () => { if (app) app.inert = !!wasInert; if (previous?.isConnected) previous.focus() }
  }, [])
  useEffect(() => { if (!pat) return; const timer = setTimeout(() => setPat(false), 1500); return () => clearTimeout(timer) }, [pat])
  useEffect(() => {
    if (!checking) return
    const controller = new AbortController()
    setBusy(true); setError(''); setChecks(null)
    const load = async () => {
      try {
        if (!selected) {
          const response = await authFetch(`${API}/trips`, { signal: controller.signal })
          if (!response.ok) throw new Error()
          const list = await response.json() as { id: string; title: string }[]
          if (controller.signal.aborted) return
          setTrips(list)
          if (list.length) setSelected(list[0].id)
        } else {
          const [detail, issues] = await Promise.all([
            authFetch(`${API}/trips/${encodeURIComponent(selected)}`, { signal: controller.signal }),
            authFetch(`${API}/trips/${encodeURIComponent(selected)}/issues`, { signal: controller.signal }),
          ])
          if (!detail.ok || !issues.ok) throw new Error()
          const trip = await detail.json() as PetTrip
          const result = await issues.json() as { issues: PetCheck[] }
          if (!Array.isArray(trip.stops) || !Array.isArray(result.issues)) throw new Error()
          if (!controller.signal.aborted) setChecks(petPreparation(trip, result.issues))
        }
      } catch { if (!controller.signal.aborted) setError('暂时没能完成检查，请重试') }
      finally { if (!controller.signal.aborted) setBusy(false) }
    }
    void load()
    return () => controller.abort()
  }, [checking, selected, retry])
  return createPortal(<div className="pet-tools-mask" onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <section ref={panel} className="pet-tools" data-pet-dialog data-quiet={preferences.quiet} role="dialog" aria-modal="true" aria-labelledby="pet-tools-title" onKeyDown={event => {
      if (event.key === 'Escape') { event.stopPropagation(); onClose() }
      if (event.key === 'Tab') {
        const controls = [...(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input, select') || [])].filter(el => el.getClientRects().length)
        const first = controls[0], last = controls.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }}>
      <header><h2 id="pet-tools-title">游游 · 旅行搭子</h2><button onClick={onClose} aria-label="关闭游游旅行工具">✕</button></header>
      <div className="pet-tools-intro"><button className="pet-pat" onClick={() => setPat(true)} aria-label="摸摸游游"><PetArt pose={pat ? 'pat' : 'idle'} /></button><p role="status">{pat ? '咕噜～这趟也一起走。' : '地图我带着，好心情你带着。'}</p></div>
      <div className="pet-tools-actions"><button onClick={() => { onClose(); onAsk() }}>一起问 AI ↗</button><button aria-pressed={checking} onClick={() => setChecking(value => !value)}>出发检查</button></div>
      {checking && <section className="pet-preparation" aria-label="出发准备检查">
        <h3>看看哪份行程？</h3>
        {trips && trips.length > 0 && <select aria-label="待检查的行程" value={selected} onChange={event => { setSelected(event.target.value); setChecks(null); setError('') }}>{trips.map(trip => <option key={trip.id} value={trip.id}>{trip.title}</option>)}</select>}
        {busy && <p role="status">正在查看行程资料…</p>}
        {error && <div role="alert"><p>{error}</p><button onClick={() => setRetry(value => value + 1)}>重新检查</button></div>}
        {!busy && !error && trips?.length === 0 && <p>还没有行程，先一起想想去哪儿。</p>}
        {!busy && !error && checks && <><p role="status">{checks.length ? `有 ${checks.length} 项信息可以再确认` : '行程基础信息已填好'}</p>{checks.length > 0 && <ul>{checks.map((check, index) => <li key={index} data-level={check.level}>{check.text}</li>)}</ul>}<button onClick={() => { onClose(); onTrip(selected) }}>打开这份行程 ↗</button></>}
        <small>检查出发日期、地点和时间安排。</small>
      </section>}
      <div className="pet-preferences"><label><input type="checkbox" checked={preferences.visible} onChange={event => onChange({ ...preferences, visible: event.target.checked })} />在界面显示游游</label><label><input type="checkbox" checked={preferences.quiet} onChange={event => onChange({ ...preferences, quiet: event.target.checked })} />减少动态效果</label><label>停在哪一侧<select aria-label="游游停靠位置" value={preferences.side} onChange={event => onChange({ ...preferences, side: event.target.value === 'left' ? 'left' : 'right' })}><option value="left">左侧</option><option value="right">右侧</option></select></label><small>收起游游后，问 AI 入口仍然保留。</small></div>
    </section>
  </div>, document.body)
}

/** Same snapshot, changed presence is not a join. Baselines are scoped to the current trip. */
export function PetMemberWelcome({ tripId, members, username }: { tripId: string; members: readonly { username: string }[]; username: string }) {
  const previous = useRef<{ id: string; names: string[] } | null>(null)
  const [welcome, setWelcome] = useState('')
  const [preferences] = usePetPreferences(username)
  const names = members.map(member => member.username).sort().join('\u0000')
  useEffect(() => {
    const current = names ? names.split('\u0000') : []
    const baseline = previous.current?.id === tripId ? previous.current.names : null
    const added = addedPetMembers(baseline, current, username)
    previous.current = { id: tripId, names: current }
    setWelcome(added.length ? `${added.slice(0, 2).join('、')}${added.length > 2 ? '等搭子' : ''} 加入啦，一起出发！` : '')
  }, [names, tripId, username])
  useEffect(() => { if (!welcome) return; const timer = setTimeout(() => setWelcome(''), 4500); return () => clearTimeout(timer) }, [welcome])
  if (!welcome || !preferences.visible) return null
  return <div className="pet-member-welcome" data-quiet={preferences.quiet} role="status"><PetArt pose="wave" /><span>{welcome}</span><button onClick={() => setWelcome('')} aria-label="收起同行欢迎">✕</button></div>
}
