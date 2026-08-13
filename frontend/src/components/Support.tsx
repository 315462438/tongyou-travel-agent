/**
 * 客服会话（Phase 73）。
 *
 * 用户端：一条常驻会话，向管理员汇报问题。
 * 管理员端：会话列表 + 逐个回复，带未读徽标与在线圆点。
 *
 * 轮询而非推送，与全站其余对话流一致：抽屉打开时 3s，关闭时 30s 只查未读数。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { API, authFetch } from '../api'
import { ChatBody, ChatInput } from './ChatInput'
import { formatLastSeen } from '../interaction'

export interface SupportMessage {
  id: string
  sender: 'user' | 'admin'
  content: string
  created_at: string | null
  read: boolean
}

export interface SupportThread {
  user_id: string
  username: string
  online: boolean
  last_seen_at: string | null
  total: number
  unread: number
  last_at: string | null
  last_sender: 'user' | 'admin' | null
  last_excerpt: string
}

const OPEN_POLL_MS = 3000
const IDLE_POLL_MS = 30000

/** 未读轮询：关闭时低频查数字，用于侧边栏红点。 */
export function useSupportUnread(enabled: boolean, paused: boolean): number {
  const [unread, setUnread] = useState(0)
  useEffect(() => {
    if (!enabled || paused) return
    let alive = true
    const tick = async () => {
      try {
        const res = await authFetch(`${API}/support/unread`)
        if (!res.ok) return
        const data = await res.json()
        if (alive) setUnread(data.unread || 0)
      } catch {
        /* 红点拿不到不影响主流程 */
      }
    }
    tick()
    const timer = window.setInterval(tick, IDLE_POLL_MS)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [enabled, paused])
  return unread
}

function MessageList({ messages, mineIs, empty }: {
  messages: SupportMessage[]
  mineIs: 'user' | 'admin'
  empty: React.ReactNode
}) {
  const listRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  useEffect(() => {
    if (!stickRef.current) return
    const el = listRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages])
  return (
    <div
      className="support-messages"
      ref={listRef}
      onScroll={(e) => {
        const el = e.currentTarget
        stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}
    >
      {messages.length === 0 ? <div className="support-empty">{empty}</div> : null}
      {messages.map((m) => (
        <div key={m.id} className={`support-msg ${m.sender === mineIs ? 'mine' : 'theirs'}`}>
          <div className="support-bubble"><ChatBody content={m.content} /></div>
          <time>{m.created_at ? new Date(m.created_at).toLocaleString('zh-CN', { hour12: false }) : ''}</time>
        </div>
      ))}
    </div>
  )
}

/** 用户端：联系客服抽屉。 */
export function SupportChat({ open, onClose }: {
  open: boolean
  onClose: () => void
}) {
  const [messages, setMessages] = useState<SupportMessage[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/support/messages`)
      if (!res.ok) throw new Error()
      const data = await res.json()
      setMessages(data.messages || [])
      setError('')
    } catch {
      setError('消息加载失败，请稍后重试')
    }
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const timer = window.setInterval(load, OPEN_POLL_MS)
    return () => window.clearInterval(timer)
  }, [open, load])

  const send = async (content: string) => {
    try {
      const res = await authFetch(`${API}/support/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      if (!res.ok) throw new Error()
      load()
    } catch {
      setError('发送失败，请稍后重试')
    }
  }

  if (!open) return null
  return (
    <div className="modal-mask panel-mask" onClick={onClose}>
      <div className="modal side-panel support-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>联系客服</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-sub">遇到问题、有建议，都可以在这里告诉我们，管理员会尽快回复。</div>
        {error && <div className="support-error">{error}</div>}
        <MessageList
          messages={messages}
          mineIs="user"
          empty={<><span aria-hidden>💬</span><p>还没有消息。描述你遇到的问题，越具体越好（在哪个页面、什么操作、大概什么时间）。</p></>}
        />
        <ChatInput onSend={send} onError={setError}
          placeholder="描述你遇到的问题…（可粘贴截图，Enter 发送）" />
      </div>
    </div>
  )
}

/** 管理员端：客服会话列表 + 回复。嵌在用户管理面板的标签页里。 */
export function AdminSupport() {
  const [threads, setThreads] = useState<SupportThread[]>([])
  const [active, setActive] = useState<SupportThread | null>(null)
  const [messages, setMessages] = useState<SupportMessage[]>([])
  const [now, setNow] = useState(() => Date.now())

  const loadThreads = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/admin/support/threads`)
      if (!res.ok) return
      const data = await res.json()
      setThreads(data.threads || [])
      setNow(Date.now())
    } catch {
      /* 列表拿不到不影响已打开的会话 */
    }
  }, [])

  const loadMessages = useCallback(async (userId: string) => {
    try {
      const res = await authFetch(`${API}/admin/support/${userId}/messages`)
      if (!res.ok) return
      const data = await res.json()
      setMessages(data.messages || [])
    } catch {
      /* 忽略单次失败，下一轮轮询会补上 */
    }
  }, [])

  useEffect(() => {
    loadThreads()
    const timer = window.setInterval(loadThreads, OPEN_POLL_MS)
    return () => window.clearInterval(timer)
  }, [loadThreads])

  useEffect(() => {
    if (!active) return
    loadMessages(active.user_id)
    const timer = window.setInterval(() => loadMessages(active.user_id), OPEN_POLL_MS)
    return () => window.clearInterval(timer)
  }, [active, loadMessages])

  const reply = async (content: string) => {
    if (!active) return
    await authFetch(`${API}/admin/support/${active.user_id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    loadMessages(active.user_id)
    loadThreads()
  }

  if (active) {
    return (
      <div className="admin-support-thread">
        <div className="admin-support-back">
          <button onClick={() => { setActive(null); loadThreads() }}>← 全部会话</button>
          <span className={`online-dot ${active.online ? 'on' : ''}`} aria-hidden />
          <strong>{active.username}</strong>
          <small>{active.online ? '在线' : formatLastSeen(active.last_seen_at, now)}</small>
        </div>
        <MessageList
          messages={messages}
          mineIs="admin"
          empty={<p>这位用户还没有留言。</p>}
        />
        <ChatInput onSend={reply} placeholder="回复用户…（可粘贴截图，Enter 发送）" />
      </div>
    )
  }

  return (
    <div className="modal-body">
      {threads.length === 0 && <div className="support-empty"><p>还没有用户发起客服会话。</p></div>}
      {threads.map((t) => (
        <button key={t.user_id} className="admin-thread-row" onClick={() => setActive(t)}>
          <span className={`online-dot ${t.online ? 'on' : ''}`} aria-hidden />
          <span className="admin-thread-main">
            <span className="admin-thread-name">
              {t.username}
              {t.unread > 0 && <b className="support-badge">{t.unread}</b>}
            </span>
            <small className="admin-thread-excerpt">
              {t.last_sender === 'admin' ? '我：' : ''}{t.last_excerpt}
            </small>
          </span>
          <small className="admin-thread-time">{formatLastSeen(t.last_at, now)}</small>
        </button>
      ))}
    </div>
  )
}
