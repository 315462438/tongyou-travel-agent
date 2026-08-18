import { useCallback, useEffect, useState } from 'react'

import { API, authFetch } from '../api'
import { formatLastSeen } from '../interaction'

export interface ProductNotification {
  id: string
  type: 'friend_request' | 'friend_accepted' | 'relay_reaction' | 'trip_chat' | string
  title: string
  body: string
  target_kind: 'friends' | 'relay' | 'trip' | string
  target_id: string
  meta: { destination?: string; reaction?: string; tab?: string; trip_id?: string; trip_title?: string; count?: number }
  read: boolean
  created_at: string | null
  actor: { id: string; username: string; display_name: string; avatar_url: string }
}

function NotificationAvatar({ item }: { item: ProductNotification }) {
  return (
    <span className={`notification-avatar type-${item.type}`} aria-hidden>
      {item.actor.avatar_url
        ? <img src={item.actor.avatar_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} />
        : <b>{(item.actor.display_name || item.actor.username || '旅')[0].toUpperCase()}</b>}
      <i>{item.type === 'trip_chat' ? '💬'
        : item.type === 'relay_reaction' ? '♥'
        : item.type === 'friend_accepted' ? '✓' : '+'}</i>
    </span>
  )
}

export function NotificationPanel({
  open,
  onClose,
  announcementUnread,
  onOpenAnnouncements,
  onNavigate,
  onUnreadChange,
}: {
  open: boolean
  onClose: () => void
  announcementUnread: number
  onOpenAnnouncements: () => void
  onNavigate: (item: ProductNotification) => void
  onUnreadChange: () => void
}) {
  const [items, setItems] = useState<ProductNotification[] | null>(null)
  const [unread, setUnread] = useState(0)
  const [now, setNow] = useState(() => Date.now())

  const load = useCallback(async () => {
    try {
      const response = await authFetch(`${API}/notifications`)
      if (!response.ok) throw new Error()
      const data = await response.json()
      setItems(data.notifications || [])
      setUnread(data.unread || 0)
      setNow(Date.now())
    } catch {
      setItems([])
      setUnread(0)
    }
  }, [])

  useEffect(() => { if (open) void load() }, [load, open])

  const readOne = async (item: ProductNotification) => {
    if (!item.read) {
      const response = await authFetch(`${API}/notifications/${item.id}/read`, { method: 'POST' })
      if (!response.ok) return
      setItems((current) => current?.map((row) => row.id === item.id ? { ...row, read: true } : row) || [])
      setUnread((value) => Math.max(0, value - 1))
      onUnreadChange()
    }
    onClose()
    onNavigate(item)
  }

  const readAll = async () => {
    if (!unread) return
    const response = await authFetch(`${API}/notifications/read-all`, { method: 'POST' })
    if (!response.ok) return
    setItems((current) => current?.map((item) => ({ ...item, read: true })) || [])
    setUnread(0)
    onUnreadChange()
  }

  if (!open) return null
  return (
    <div className="notification-mask" onClick={onClose}>
      <section className="notification-panel" role="dialog" aria-modal="true" aria-label="通知中心" onClick={(event) => event.stopPropagation()}>
        <header>
          <div><small>17同游</small><h2>通知</h2></div>
          <div>{unread > 0 && <button onClick={readAll}>全部已读</button>}<button className="notification-close" onClick={onClose} aria-label="关闭通知">×</button></div>
        </header>
        <div className="notification-list">
          {items === null && <div className="notification-empty"><span className="spinner" /><p>正在查看新消息…</p></div>}
          {items?.length === 0 && <div className="notification-empty"><span>✓</span><b>暂时没有新通知</b><p>好友申请、接力反馈和同行群聊会出现在这里。</p></div>}
          {items?.map((item) => (
            <button className={`notification-item${item.read ? '' : ' unread'}`} key={item.id} onClick={() => readOne(item)}>
              <NotificationAvatar item={item} />
              <span className="notification-copy">
                <b>{item.title}{(item.meta.count ?? 0) > 1 && <em className="notification-count">等 {item.meta.count} 条</em>}</b>
                <span>{item.body}</span>
                <small>{formatLastSeen(item.created_at, now)}</small>
              </span>
              {!item.read && <i className="notification-unread" aria-label="未读" />}
            </button>
          ))}
        </div>
        <footer>
          <button onClick={() => { onClose(); onOpenAnnouncements() }}><span>📣</span><b>平台公告</b><small>{announcementUnread > 0 ? `${announcementUnread} 条未读` : '查看功能更新与平台消息'}</small><i>→</i></button>
        </footer>
      </section>
    </div>
  )
}
