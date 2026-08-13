import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { API, authFetch } from '../api'

interface ImmersiveChoice {
  id: 'canyon' | 'summit'
  label: string
  hint: string
  energy_delta: number
}

interface ImmersiveVariant {
  title?: string
  narration?: string
  energy_delta?: number
}

interface ImmersiveScene {
  id: string
  chapter: string
  title: string
  location: string
  poi_name: string
  time: string
  atmosphere: string
  narration: string
  image: string
  energy_delta: number
  cost: number
  choices?: ImmersiveChoice[]
  variants?: Partial<Record<'canyon' | 'summit', ImmersiveVariant>>
}

interface ImmersivePayload {
  destination: string
  title: string
  subtitle: string
  disclaimer: string
  scenes: ImmersiveScene[]
  has_images: boolean
}

type RouteChoice = 'canyon' | 'summit'

const HOLD_DURATION_MS = 900
const CINEMATIC_IMAGE = `${import.meta.env.BASE_URL}immersive/tiantangzhai-cinematic.webp`

const ROUTE_COPY: Record<RouteChoice, { label: string; summary: string }> = {
  canyon: { label: '峡谷慢行线', summary: '沿水而行，给瀑布、拍照和停留留出更多时间' },
  summit: { label: '主峰挑战线', summary: '投入更多体力，换取爬升和更开阔的山脊视野' },
}

function resolveScene(scene: ImmersiveScene, route: RouteChoice | null): ImmersiveScene {
  const variant = route ? scene.variants?.[route] : null
  return variant ? { ...scene, ...variant } : scene
}

function clampEnergy(value: number): number {
  return Math.max(8, Math.min(100, value))
}

export default function ImmersivePreview({
  destination,
  onClose,
  onCreatePlan,
}: {
  destination: string
  onClose: () => void
  onCreatePlan: (prompt: string) => void
}) {
  const [payload, setPayload] = useState<ImmersivePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sceneIndex, setSceneIndex] = useState(0)
  const [route, setRoute] = useState<RouteChoice | null>(null)
  const [finished, setFinished] = useState(false)
  const [retryKey, setRetryKey] = useState(0)
  const [holdProgress, setHoldProgress] = useState(0)
  const [showInfo, setShowInfo] = useState(false)
  const overlayRef = useRef<HTMLDivElement>(null)
  const holdFrameRef = useRef<number | null>(null)
  const holdStartRef = useRef(0)
  const holdTriggeredRef = useRef(false)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    authFetch(`${API}/immersive/preview?destination=${encodeURIComponent(destination)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error('场景暂时没有准备好')
        return response.json()
      })
      .then((data) => {
        if (!active) return
        setPayload(data)
        setSceneIndex(0)
        setRoute(null)
        setFinished(false)
      })
      .catch((reason) => { if (active) setError(reason?.message || '加载失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [destination, retryKey])

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previous }
  }, [])

  const baseScene = payload?.scenes[sceneIndex]
  const scene = baseScene ? resolveScene(baseScene, route) : null
  const routeChoiceEnergy = route && sceneIndex >= 1
    ? (payload?.scenes[1]?.choices?.find((choice) => choice.id === route)?.energy_delta || 0)
    : 0
  const metrics = useMemo(() => {
    if (!payload) return { energy: 100, cost: 0 }
    const visited = payload.scenes.slice(0, sceneIndex + 1)
    const energy = visited.reduce((sum, item) => sum + resolveScene(item, route).energy_delta, 100) + routeChoiceEnergy
    const cost = visited.reduce((sum, item) => sum + item.cost, 0)
    return { energy: clampEnergy(energy), cost }
  }, [payload, route, routeChoiceEnergy, sceneIndex])

  useEffect(() => {
    const next = payload?.scenes[sceneIndex + 1]?.image
    if (!next) return
    const image = new Image()
    image.src = `${API}/img?u=${encodeURIComponent(next)}`
  }, [payload, sceneIndex])

  const continueScene = useCallback(() => {
    if (!payload) return
    setHoldProgress(0)
    if (sceneIndex >= payload.scenes.length - 1) setFinished(true)
    else setSceneIndex((current) => current + 1)
  }, [payload, sceneIndex])

  const cancelHold = useCallback(() => {
    if (holdFrameRef.current !== null) cancelAnimationFrame(holdFrameRef.current)
    holdFrameRef.current = null
    holdStartRef.current = 0
    if (!holdTriggeredRef.current) setHoldProgress(0)
  }, [])

  const beginHold = useCallback(() => {
    if (!payload || holdFrameRef.current !== null) return
    holdTriggeredRef.current = false
    holdStartRef.current = performance.now()
    const tick = (now: number) => {
      const progress = Math.min(1, (now - holdStartRef.current) / HOLD_DURATION_MS)
      setHoldProgress(progress)
      if (progress >= 1) {
        holdFrameRef.current = null
        holdTriggeredRef.current = true
        continueScene()
        return
      }
      holdFrameRef.current = requestAnimationFrame(tick)
    }
    holdFrameRef.current = requestAnimationFrame(tick)
  }, [continueScene, payload])

  useEffect(() => () => cancelHold(), [cancelHold])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.code === 'Space' && !finished && !scene?.choices?.length && !event.repeat) {
        event.preventDefault()
        beginHold()
      }
    }
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space') cancelHold()
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [beginHold, cancelHold, finished, onClose, scene?.choices?.length])

  const moveScene = (clientX: number, clientY: number) => {
    const root = overlayRef.current
    if (!root || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const x = ((clientX / window.innerWidth) - 0.5) * 2
    const y = ((clientY / window.innerHeight) - 0.5) * 2
    root.style.setProperty('--look-x', `${x.toFixed(3)}`)
    root.style.setProperty('--look-y', `${y.toFixed(3)}`)
  }

  const resetSceneLook = () => {
    overlayRef.current?.style.setProperty('--look-x', '0')
    overlayRef.current?.style.setProperty('--look-y', '0')
  }

  const chooseRoute = (choice: ImmersiveChoice) => {
    setRoute(choice.id)
    setSceneIndex((current) => Math.min(current + 1, (payload?.scenes.length || 1) - 1))
  }

  const createPlan = () => {
    if (!payload || !route) return
    const places = Array.from(new Set(payload.scenes.map((item) => item.location))).join('、')
    const routeCopy = ROUTE_COPY[route]
    onCreatePlan(
      `我刚完成了${payload.destination}的第一视角旅行预演，选择了「${routeCopy.label}」（${routeCopy.summary}）。` +
      `体验经过：${places}。请把这段体验变成现实可执行的3天行程：从交通抵达开始，按我的路线偏好安排每日时间、步行/爬升强度、休息点、餐饮、预算和雨天备选；` +
      `请核实真实开放信息，不要把体验中的模拟时间、体力或花费当成实时数据。`,
    )
  }

  const isCinematicScene = destination.includes('天堂寨') && sceneIndex === 0
  const realImage = scene?.image ? `${API}/img?u=${encodeURIComponent(scene.image)}` : ''
  const foregroundImage = isCinematicScene ? CINEMATIC_IMAGE : realImage || CINEMATIC_IMAGE
  const backdropImage = realImage || CINEMATIC_IMAGE
  const displayProgress = payload ? ((sceneIndex + 1) / payload.scenes.length) * 100 : 0

  return (
    <div
      ref={overlayRef}
      className="immersive-overlay immersive-film"
      role="dialog"
      aria-modal="true"
      aria-label={`${destination}互动旅行电影`}
      onPointerMove={(event) => moveScene(event.clientX, event.clientY)}
      onPointerLeave={resetSceneLook}
    >
      {scene && (
        <div className="immersive-scene" key={`${scene.id}-${route || 'start'}`}>
          <div className="immersive-environment" style={{ backgroundImage: `url("${backdropImage}")` }} aria-hidden />
          <div className="immersive-light immersive-light-one" aria-hidden />
          <div className="immersive-light immersive-light-two" aria-hidden />
          <div className="immersive-film-frame">
            <img
              className="immersive-film-image"
              src={foregroundImage}
              alt=""
              onError={(event) => { event.currentTarget.src = CINEMATIC_IMAGE }}
            />
            <div className="immersive-film-grade" aria-hidden />
            <div className="immersive-film-grain" aria-hidden />
            <div className="immersive-frame-label">
              <span>{isCinematicScene ? '氛围演绎' : '真实地点参考'}</span>
              <b>{scene.poi_name || scene.location}</b>
            </div>
          </div>
        </div>
      )}

      <header className="immersive-header">
        <div className="immersive-brand"><span>17</span><b>同游</b><i>旅行电影</i></div>
        <div className="immersive-progress" aria-label={`体验进度 ${sceneIndex + 1}/${payload?.scenes.length || 6}`}>
          <span>{String(sceneIndex + 1).padStart(2, '0')}</span>
          <div><i style={{ width: `${displayProgress}%` }} /></div>
          <span>{String(payload?.scenes.length || 6).padStart(2, '0')}</span>
        </div>
        <button className="immersive-close" type="button" onClick={onClose} aria-label="退出互动旅行电影">退出 <b>×</b></button>
      </header>

      {loading && (
        <div className="immersive-loading" role="status">
          <div className="immersive-loading-orbit"><span>17</span></div>
          <h2>正在打开天堂寨的山门</h2>
          <p>连接真实地点，准备一段互动旅行电影…</p>
        </div>
      )}

      {!loading && error && (
        <div className="immersive-loading error" role="alert">
          <h2>山里的信号暂时断了</h2>
          <p>{error}</p>
          <div><button onClick={() => setRetryKey((key) => key + 1)}>重新进入</button><button onClick={onClose}>返回首页</button></div>
        </div>
      )}

      {!loading && !error && scene && payload && !finished && (
        <main className="immersive-story">
          <div className="immersive-scene-meta">
            <span>{scene.chapter}</span><i />
            <span>{scene.time}</span><i />
            <span>{scene.atmosphere}</span>
          </div>
          <h2>{scene.title}</h2>
          <p>{scene.narration}</p>

          {scene.choices?.length && !route ? (
            <div className="immersive-choices" aria-label="选择接下来的路线">
              {scene.choices.map((choice) => (
                <button key={choice.id} onClick={() => chooseRoute(choice)}>
                  <span>{choice.id === 'canyon' ? '沿水' : '登高'}</span>
                  <b>{choice.label}</b>
                  <small>{choice.hint}</small>
                  <em>{Math.abs(choice.energy_delta)} 点体力 · 进入这条路 →</em>
                </button>
              ))}
            </div>
          ) : (
            <button
              className={`immersive-hold ${holdProgress > 0 ? 'holding' : ''}`}
              type="button"
              onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); beginHold() }}
              onPointerUp={cancelHold}
              onPointerCancel={cancelHold}
              onContextMenu={(event) => event.preventDefault()}
              aria-label={sceneIndex === payload.scenes.length - 1 ? '按住查看旅程结果' : '按住继续前行'}
            >
              <span className="immersive-hold-track"><i style={{ width: `${holdProgress * 100}%` }} /></span>
              <b>{holdProgress > 0 ? '别松手，脚步正在向前…' : sceneIndex === payload.scenes.length - 1 ? '按住，完成这段旅程' : '按住，沿着步道向前'}</b>
              <small>也可以按住空格键</small>
            </button>
          )}
        </main>
      )}

      {!loading && !error && scene && payload && !finished && (
        <div className="immersive-journey-note">
          <button type="button" onClick={() => setShowInfo((value) => !value)} aria-expanded={showInfo}>
            <span>行程感受</span><b>{metrics.energy}%</b><i style={{ width: `${metrics.energy}%` }} />
          </button>
          {showInfo && <div><span>模拟体力 {metrics.energy}%</span><span>体验花费 ¥{metrics.cost}</span><small>仅用于体验节奏，不代表实时数据</small></div>}
        </div>
      )}

      {!loading && !error && payload && finished && route && (
        <main className="immersive-finish">
          <span className="immersive-finish-kicker">你的选择已经成为路线</span>
          <h2>{payload.destination} · {ROUTE_COPY[route].label}</h2>
          <p>{ROUTE_COPY[route].summary}</p>
          <div className="immersive-finish-stats">
            <div><small>经过场景</small><strong>{payload.scenes.length} 幕</strong></div>
            <div><small>体验体力</small><strong>{metrics.energy}%</strong></div>
            <div><small>体验花费</small><strong>¥{metrics.cost}</strong></div>
          </div>
          <div className="immersive-finish-route">
            {payload.scenes.map((item, index) => <span key={item.id}><i>{index + 1}</i>{item.location}</span>)}
          </div>
          <div className="immersive-finish-actions">
            <button className="secondary" onClick={() => { setSceneIndex(0); setRoute(null); setFinished(false) }}>重新体验</button>
            <button className="primary" onClick={createPlan}>把这段体验变成真实行程 <span>→</span></button>
          </div>
          <small>{payload.disclaimer}</small>
        </main>
      )}
    </div>
  )
}
