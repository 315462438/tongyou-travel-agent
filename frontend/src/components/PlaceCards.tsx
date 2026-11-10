import { useState } from 'react'
import { API, authFetch } from '../api'
import { pickNavUrl, type NavLinks } from '../interaction'
import { useToast } from './toast-context'

export interface PlaceCard {
  name: string
  address: string
  photo: string
  location: string
  nav: NavLinks
}

interface TripRow { id: string; title: string; role: string }

/** 直答里提到的店/景点：图、导航、加入行程。把「聊到的地方」接到行程板，不用另外搜、另外记。 */
export function PlaceCards({ places }: { places: PlaceCard[] }) {
  const { notify } = useToast()
  const [picking, setPicking] = useState<PlaceCard | null>(null)
  const [trips, setTrips] = useState<TripRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [added, setAdded] = useState<Record<string, string>>({})

  const openPicker = async (place: PlaceCard) => {
    setPicking(place)
    setTrips(null)
    try {
      const res = await authFetch(`${API}/trips`)
      const rows: TripRow[] = res.ok ? await res.json() : []
      setTrips(rows.filter((t) => t.role !== 'viewer'))
    } catch {
      setTrips([])
    }
  }

  const addTo = async (trip: TripRow | null) => {
    if (!picking || busy) return
    setBusy(true)
    try {
      let target = trip
      if (!target) {
        const created = await authFetch(`${API}/trips`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: `${picking.name}之行`, destination: '', days: 1 }),
        })
        if (!created.ok) throw new Error('create')
        target = { id: (await created.json()).id, title: `${picking.name}之行`, role: 'owner' }
      }
      const res = await authFetch(`${API}/trips/${target.id}/stops`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ day: 1, name: picking.name, location: picking.location, note: picking.address }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        notify(body?.detail || '加入行程失败', 'error')
        return
      }
      setAdded((cur) => ({ ...cur, [picking.name]: target!.title }))
      notify(`已加入「${target.title}」，可在行程里调整到哪一天`, 'success')
      setPicking(null)
    } catch {
      notify('加入行程失败，请重试', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="place-cards" aria-label="回答里提到的地点">
      {places.map((p) => (
        <article className="place-card" key={p.name}>
          {p.photo
            ? <img src={p.photo} alt={p.name} loading="lazy" onError={(e) => { e.currentTarget.style.display = 'none' }} />
            : <span className="place-card-blank" aria-hidden>📍</span>}
          <div className="place-card-body">
            <strong>{p.name}</strong>
            {p.address && <small>{p.address}</small>}
            <div className="place-card-actions">
              <a href={pickNavUrl(p.nav, navigator.userAgent)} target="_blank" rel="noopener noreferrer">导航</a>
              <button disabled={!!added[p.name]} onClick={() => void openPicker(p)}>
                {added[p.name] ? '已加入' : '加入行程'}
              </button>
            </div>
          </div>
        </article>
      ))}
      {picking && (
        <div className="place-sheet-mask" onClick={() => !busy && setPicking(null)}>
          <div className="place-sheet" role="dialog" aria-label={`把 ${picking.name} 加入行程`} onClick={(e) => e.stopPropagation()}>
            <h3>把「{picking.name}」加入</h3>
            {trips === null && <p className="place-sheet-hint">正在读取你的行程…</p>}
            {trips?.map((t) => (
              <button key={t.id} disabled={busy} onClick={() => void addTo(t)}>{t.title}</button>
            ))}
            {trips !== null && (
              <button className="place-sheet-new" disabled={busy} onClick={() => void addTo(null)}>＋ 新建一个行程</button>
            )}
            <button className="place-sheet-cancel" disabled={busy} onClick={() => setPicking(null)}>取消</button>
          </div>
        </div>
      )}
    </div>
  )
}

/** 回答末尾的追问：点一下就发出去，手机上不用打字。只在最后一条回答下面出现。 */
export function Suggestions({ items, onPick }: { items: string[]; onPick: (text: string) => void }) {
  return (
    <div className="suggest-chips" aria-label="接着问">
      {items.map((text) => (
        <button key={text} onClick={() => onPick(text)}>{text}</button>
      ))}
    </div>
  )
}
