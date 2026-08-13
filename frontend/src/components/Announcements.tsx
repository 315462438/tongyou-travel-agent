/**
 * 公告（Phase 74）：管理员一键推送，用户顶栏喇叭查看。
 *
 * 未读是**推导**出来的（有公告 && 我没有已读行），发布一条公告只写 1 行，
 * 不给每个用户复制一份。
 */
import { useCallback, useEffect, useState } from 'react'
import { API, authFetch } from '../api'
import { formatLastSeen } from '../interaction'

export interface Announcement {
  id: string
  title: string
  content: string
  created_at: string | null
  read: boolean
  author: string
}

const POLL_MS = 60000

export function useAnnouncementUnread(paused: boolean): [number, () => void] {
  const [unread, setUnread] = useState(0)
  const refresh = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/announcements/unread`)
      if (res.ok) setUnread((await res.json()).unread || 0)
    } catch {
      /* 红点拿不到不影响主流程 */
    }
  }, [])
  useEffect(() => {
    if (paused) return
    refresh()
    const timer = window.setInterval(refresh, POLL_MS)
    return () => window.clearInterval(timer)
  }, [paused, refresh])
  return [unread, refresh]
}

export function AnnouncementPanel({ open, onClose, onRead }: {
  open: boolean
  onClose: () => void
  onRead: () => void
}) {
  const [items, setItems] = useState<Announcement[] | null>(null)
  const [now] = useState(() => Date.now())

  useEffect(() => {
    if (!open) return
    let alive = true
    ;(async () => {
      try {
        const res = await authFetch(`${API}/announcements`)
        if (!res.ok) throw new Error()
        const data = await res.json()
        if (!alive) return
        const list: Announcement[] = data.announcements || []
        setItems(list)
        // 打开即全部标记已读——公告是「看过就行」的东西，不值得再点一次
        await Promise.all(
          list.filter((a) => !a.read).map((a) =>
            authFetch(`${API}/announcements/${a.id}/read`, { method: 'POST' })),
        )
        onRead()
      } catch {
        if (alive) setItems([])
      }
    })()
    return () => { alive = false }
  }, [open, onRead])

  if (!open) return null
  return (
    <div className="modal-mask panel-mask" onClick={onClose}>
      <div className="modal side-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>公告</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {items === null && <div className="support-empty"><p>加载中…</p></div>}
          {items?.length === 0 && (
            <div className="support-empty"><span aria-hidden>📣</span><p>还没有公告。</p></div>
          )}
          {items?.map((a) => (
            <article key={a.id} className={`ann-item${a.read ? '' : ' unread'}`}>
              <header>
                <strong>{a.title}</strong>
                <small>{formatLastSeen(a.created_at, now)}</small>
              </header>
              <p>{a.content}</p>
              <footer>—— {a.author}</footer>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}

/** 管理员：发布 / 撤下公告。嵌在用户管理面板的标签页里。 */
export function AdminAnnouncements() {
  const [items, setItems] = useState<Announcement[]>([])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/announcements`)
      if (res.ok) setItems((await res.json()).announcements || [])
    } catch {
      /* 忽略 */
    }
  }, [])
  useEffect(() => { load() }, [load])

  const publish = async () => {
    if (!title.trim() || !content.trim() || busy) return
    setBusy(true)
    try {
      const res = await authFetch(`${API}/admin/announcements`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content }),
      })
      if (!res.ok) throw new Error()
      setTitle('')
      setContent('')
      setMsg('已推送给全部账号')
      load()
    } catch {
      setMsg('推送失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  const withdraw = async (id: string) => {
    if (!window.confirm('撤下这条公告？所有用户都将不再看到。')) return
    await authFetch(`${API}/admin/announcements/${id}`, { method: 'DELETE' })
    load()
  }

  return (
    <div className="modal-body">
      <div className="admin-form">
        <input
          value={title}
          maxLength={128}
          placeholder="公告标题，例如：手账海报功能上线"
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          value={content}
          rows={4}
          placeholder="公告内容…"
          onChange={(e) => setContent(e.target.value)}
        />
        <div className="admin-form-actions">
          {msg && <small>{msg}</small>}
          <button onClick={publish} disabled={busy || !title.trim() || !content.trim()}>
            {busy ? '推送中…' : '📣 推送给所有账号'}
          </button>
        </div>
      </div>
      {items.map((a) => (
        <div key={a.id} className="admin-row">
          <span className="admin-name">{a.title}</span>
          <span className="admin-stat">
            <button className="link-danger" onClick={() => withdraw(a.id)}>撤下</button>
          </span>
        </div>
      ))}
    </div>
  )
}

/**
 * 新公告弹窗（Phase 74.1）：红点太弱，用户发现不了 —— 首次进来直接弹。
 *
 * 与铃铛抽屉的**关键区别**：抽屉是「打开即已读」（用户主动点开 = 看到了），
 * 弹窗是**点「我知道了」才已读**。弹窗可能在用户不在电脑前时自动出现，
 * 若一显示就标已读，这条公告会永远消失。没确认就下次继续弹。
 */
export function AnnouncementModal({ open, onAcknowledged, onDismiss }: {
  open: boolean
  onAcknowledged: () => void
  onDismiss: () => void
}) {
  const [items, setItems] = useState<Announcement[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    let alive = true
    ;(async () => {
      try {
        const res = await authFetch(`${API}/announcements`)
        if (!res.ok) return
        const data = await res.json()
        const unread = (data.announcements || []).filter((a: Announcement) => !a.read)
        // 新注册用户的未读是「全部历史公告」，一次弹二十条是灾难 —— 只展示最新 5 条，
        // 确认时仍把**全部**标记已读，不留下清不掉的红点。
        if (alive) setItems(unread.slice(0, 5))
      } catch {
        /* 拿不到就不弹，绝不因为公告挡住主界面 */
      }
    })()
    return () => { alive = false }
  }, [open])

  const acknowledge = async () => {
    if (busy) return
    setBusy(true)
    try {
      const res = await authFetch(`${API}/announcements`)
      const all: Announcement[] = res.ok ? (await res.json()).announcements || [] : []
      await Promise.all(
        all.filter((a) => !a.read).map((a) =>
          authFetch(`${API}/announcements/${a.id}/read`, { method: 'POST' })),
      )
    } catch {
      /* 标记失败下次会再弹，不算坏事 */
    } finally {
      setBusy(false)
      onAcknowledged()
    }
  }

  if (!open || items.length === 0) return null
  return (
    <div className="modal-mask ann-modal-mask">
      <div className="ann-modal" role="dialog" aria-modal="true" aria-label="新公告">
        <div className="ann-modal-head">
          <span className="ann-modal-icon" aria-hidden>📣</span>
          <strong>{items.length > 1 ? `${items.length} 条新公告` : '新公告'}</strong>
          <button className="modal-close" aria-label="稍后再看" onClick={onDismiss}>✕</button>
        </div>
        <div className="ann-modal-body">
          {items.map((a) => (
            <article key={a.id}>
              <h4>{a.title}</h4>
              <p>{a.content}</p>
            </article>
          ))}
        </div>
        <div className="ann-modal-foot">
          <small>稍后可在右上角 🔔 再看</small>
          <button onClick={acknowledge} disabled={busy}>我知道了</button>
        </div>
      </div>
    </div>
  )
}
