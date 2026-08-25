/** 高德 JS 互动地图（Phase 40）：编号 marker + 路线 polyline + 双向联动。
 *
 * 凭据一律从 Vite 环境变量读，源码里不留真值（见 `frontend/.env.example`）。两个值的
 * 性质不同，别一起对待：
 *   - **key**（Web端/JS API）本质公开——必须下发到每个访客浏览器才能加载地图，F12 就能看到。
 *     从源码挪走不是为了保密，是为了别人 fork 之后默认用自己的 key、不蹭本站配额；
 *     真正的防护是高德控制台的域名白名单。
 *   - **安全密钥** 才是真密钥。生产**永远**走 nginx `_AMapService` 代理由服务端注入 jscode
 *     （官方代理模式），前端只在 dev 分支内联，该分支在生产构建中被摇树剔除。
 *
 * ⚠️ key 缺失时不静默白屏：立刻 onFail 让父组件回退静态图，并在控制台留话——
 * 否则「构建时忘了注入」和「高德挂了」现象一模一样，没法排查。 */
import { useEffect, useRef, useState } from 'react'
import AMapLoader from '@amap/amap-jsapi-loader'

const AMAP_JS_KEY = import.meta.env.VITE_AMAP_JS_KEY ?? ''

declare global {
  interface Window {
    _AMapSecurityConfig?: { serviceHost?: string; securityJsCode?: string }
  }
}

if (import.meta.env.DEV) {
  // 本地开发直连高德，需要明文安全密钥；没配就不设，交给下面的加载失败回退
  const jsCode = import.meta.env.VITE_AMAP_JS_SECURITY_CODE ?? ''
  if (jsCode) window._AMapSecurityConfig = { securityJsCode: jsCode }
} else {
  window._AMapSecurityConfig = { serviceHost: `${window.location.origin}/_AMapService` }
}

export interface MapStop {
  id: string
  name: string
  location: string // "lng,lat"
  idx: number // 天内序号（1 起）
}

export default function TripMap({
  stops, color, focusId, onMarkerClick, onFail,
}: {
  stops: MapStop[]
  color: string
  focusId: string | null
  onMarkerClick: (stopId: string) => void
  onFail: () => void
}) {
  const divRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const amapRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const overlaysRef = useRef<any[]>([])
  const clickRef = useRef(onMarkerClick)
  clickRef.current = onMarkerClick
  // 父组件每次渲染都新建 stops 数组；这里用 ref 读最新值，effect 只按内容签名触发
  const stopsRef = useRef(stops)
  stopsRef.current = stops
  const [mapReady, setMapReady] = useState(0)

  // 初始化地图（一次）
  useEffect(() => {
    if (!AMAP_JS_KEY) {
      console.error(
        '[TripMap] 缺少 VITE_AMAP_JS_KEY，互动地图不可用，已回退静态图。'
        + '构建/开发前请按 frontend/.env.example 配置。',
      )
      onFail()
      return
    }
    let disposed = false
    AMapLoader.load({ key: AMAP_JS_KEY, version: '2.0', plugins: [] })
      .then((AMap) => {
        if (disposed || !divRef.current) return
        amapRef.current = AMap
        mapRef.current = new AMap.Map(divRef.current, {
          viewMode: '2D',
          zoom: 12,
          mapStyle: 'amap://styles/whitesmoke', // 素雅底图，配流光背景
        })
        setMapReady((n) => n + 1) // 地图就绪 → 触发首次绘制
      })
      .catch(() => onFail())
    return () => {
      disposed = true
      mapRef.current?.destroy?.()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 内容签名：只在「点位/顺序/颜色」真正变化时重绘（避免父组件每次渲染都刷新→抖动）
  const sig = stops.map((s) => `${s.id}@${s.location}`).join('|') + '#' + color

  useEffect(() => {
    const AMap = amapRef.current
    const map = mapRef.current
    if (!AMap || !map) return
    const cur = stopsRef.current
    map.remove(overlaysRef.current)
    overlaysRef.current = []
    const path = cur.map((s) => s.location.split(',').map(Number))
    if (path.length >= 2) {
      const line = new AMap.Polyline({
        path, strokeColor: color, strokeWeight: 5, strokeOpacity: 0.85,
        showDir: true, lineJoin: 'round',
      })
      map.add(line)
      overlaysRef.current.push(line)
    }
    for (const s of cur) {
      const marker = new AMap.Marker({
        position: s.location.split(',').map(Number),
        title: s.name,
        content: `<div class="trip-jsmarker" style="background:${color}">${s.idx}</div>`,
        offset: new AMap.Pixel(-13, -13),
      })
      marker.on('click', () => clickRef.current(s.id))
      map.add(marker)
      overlaysRef.current.push(marker)
    }
    // immediately=true：瞬时定位不做动画，避免每次重绘的缩放动画互相打架造成抖动
    if (path.length) map.setFitView(overlaysRef.current, true, [60, 60, 60, 60])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, mapReady])

  // 点卡片 → 地图平滑移过去（只在 focusId 变化时，不随父组件重渲染反复触发）
  useEffect(() => {
    const map = mapRef.current
    if (!map || !focusId) return
    const s = stopsRef.current.find((x) => x.id === focusId)
    if (s) map.setZoomAndCenter(15, s.location.split(',').map(Number), false, 500)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId])

  return <div ref={divRef} className="trip-jsmap" />
}
