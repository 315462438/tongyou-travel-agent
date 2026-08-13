/** 协同行程规划板（Phase 35-63）：三栏 = Timeline | 每日地图 | AI Copilot。
 * 协同 = 2.5s 轮询（顺带上报 presence）+ 行程群聊；AI 一律提案制（Preview→采纳/拒绝/恢复）。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChatBody, ChatInput } from '../components/ChatInput'
import Iridescence from '../components/Iridescence'
import TripMap from '../components/TripMap'
import { useToast } from '../components/toast-context'
import { API, authFetch } from '../api'
import { formatTripTimeRange, prepareMarkdown } from '../interaction'

interface TripSummary {
  id: string
  title: string
  destination: string
  days: number
  role: string
  updated_at: string
}

interface TripStop {
  id: string
  day: number
  order_no: number
  name: string
  note: string
  location: string
  start_time: string
  stay_min: number | null
  transport: string
  ticket_price: number | null
  tags: string[]
}

interface TripMember {
  username: string
  role: string
  online: boolean
  editing_day: number | null
}

interface TripDetail {
  id: string
  title: string
  destination: string
  days: number
  budget: number | null
  budget_breakdown?: Record<string, number>
  day_plans?: { day: number; type: string; overnight_required: boolean; overnight_city: string }[]
  hotel_recommendations?: { city: string; hotel: string; price: number | null; source: string; note: string }[]
  start_date: string
  source_conversation_id: string
  ai_status: string | null
  ai_review: string
  updated_at: string
  members: TripMember[]
  stops: TripStop[]
}

interface TripIssue {
  level: 'warn' | 'info'
  kind: string
  day?: number
  stop_id?: string
  text: string
  detail?: string
  action?: 'repair_geocode'
}

interface ChangeOp {
  op: string
  stop_id: string
  day: number
  name: string
  note: string
  reason: string
}

interface Suggestion {
  id: string
  prompt: string
  reply: string
  status: string
  changes: ChangeOp[]
  created_at: string
}

interface TripComment {
  id: string
  stop_id: string
  username: string
  content: string
  mine: boolean
}

interface TripChatMessage {
  id: string
  username: string
  content: string
  mine: boolean
  created_at: string
}

interface SourceGuide {
  title: string
  content: string
  sources: { title: string; url: string }[]
  can_open_conversation: boolean
  conversation_id: string
}

interface Expense {
  id: string
  amount: number
  title: string
  category: string
  payer: string
  participants: string[]
  mine: boolean
  spent_at: string
}

interface ExpenseSummary {
  total: number
  count: number
  by_category: Record<string, number>
  per_person: { username: string; paid: number; share: number; balance: number }[]
  transfers: { from: string; to: string; amount: number }[]
  text: string
}

interface Segment {
  from_id: string
  to_id: string
  minutes: number | null
  km: number | null
  mode: string
  estimated?: boolean
  note?: string
}

/** http（IP 访问）下 navigator.clipboard 不存在，静默失败会让用户复制到旧剪贴板内容
 * （踩坑：复制出上一张截图）——降级用 execCommand。 */
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // HTTP/IP 部署下 Clipboard API 可能存在但会拒绝，继续走兼容路径。
    }
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(ta)
  return ok
}

const DAY_COLORS = ['#FF5A5F', '#2EC4B6', '#3D5AFE', '#FF9F1C', '#9B5DE5', '#00B894']
const TRANSPORTS = ['', '步行', '公交', '地铁', '打车', '驾车', '骑行']
const COPILOT_CHIPS = ['减少步行', '预算降一点', '调成亲子路线', '加点美食', '加个夜景']
const OP_LABEL: Record<string, string> = { add: '＋新增', update: '✎修改', delete: '－删除' }
// Phase 87：按 PRD《好友协同旅游》4.3 的「先规划、后协同、再收尾」重排。
// Day 标签与这些功能标签同栏横向滚动（见 trip-workspace-tabs）。
// 群聊不在此列——它是带未读徽标的抽屉（Phase 61），做成标签会丢掉红点提醒，
// 保留在头部入口；PRD 建议的「跳微信群」对本项目是倒退，不采纳。
const TRIP_TOOL_TABS = [
  { id: 'food', icon: '🍜', label: '美食' },
  { id: 'stay', icon: '🏨', label: '住宿' },
  { id: 'money', icon: '💰', label: '记账' },
  { id: 'packing', icon: '🧳', label: '行李' },
  { id: 'tips', icon: '⚠️', label: '避坑' },
  { id: 'assistant', icon: '✦', label: '助手' },
  { id: 'log', icon: '◷', label: '动态' },
] as const

type TripToolTab = (typeof TRIP_TOOL_TABS)[number]['id']

// PRD 4.5 情境化悬浮按钮：按当前标签变文案
const FAB_BY_TAB: Partial<Record<TripToolTab, string>> = {
  food: '+ 加美食',
  packing: '+ 加物品',
  tips: '+ 加提醒',
  money: '+ 记一笔',
}

/** 行程状态（PRD 4.2 头部状态角标）。无出发日期时按「未开始」处理。 */
function tripStatus(startDate: string, days: number): { key: string; label: string } {
  if (!startDate) return { key: 'draft', label: '未定日期' }
  const start = new Date(`${startDate}T00:00:00`)
  if (Number.isNaN(start.getTime())) return { key: 'draft', label: '未定日期' }
  const end = new Date(start)
  end.setDate(end.getDate() + Math.max(1, days) - 1)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  if (today < start) return { key: 'upcoming', label: '未开始' }
  if (today > end) return { key: 'archived', label: '已结束' }
  return { key: 'ongoing', label: '进行中' }
}
// Phase 51 计划预算类别展示顺序（与后端 normalize_budget_category 一致）
const BUDGET_CAT_ORDER = ['住宿', '大交通', '交通', '餐饮', '门票', '其他']

function tripDayDate(startDate: string, day: number): string {
  if (!startDate) return ''
  const date = new Date(`${startDate}T00:00:00`)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + day - 1)
  const WEEK = ['日', '一', '二', '三', '四', '五', '六']
  // 展示完整年月日 + 星期：多天行程里只有「8月13日」很难对上真实日程
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 周${WEEK[date.getDay()]}`
}

export default function TripsOverlay({
  username, layoutMode = 'desktop', initialBoardId = null, onBoardChange, onClose, onOpenConversation, onAskInChat,
}: {
  username: string
  layoutMode?: 'desktop' | 'mobile'
  initialBoardId?: string | null
  onBoardChange?: (id: string | null) => void
  onClose: () => void
  onOpenConversation?: (cid: string) => void
  onAskInChat?: (text: string) => void
}) {
  const [boardId, setBoardId] = useState<string | null>(initialBoardId)
  // 把当前 board 同步给父组件（写进 URL hash），刷新后可恢复到具体这块板
  useEffect(() => {
    onBoardChange?.(boardId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boardId])
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !document.querySelector('.trip-chat-panel, .trip-source-panel')) onClose()
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])
  return (
    <div className={`trips-overlay${layoutMode === 'mobile' ? ' mobile-layout' : ''}`}>
      <div className="trips-backdrop">
        <Iridescence color={[0.62, 0.78, 0.98]} speed={0.35} amplitude={0.04} />
      </div>
      <div className="trips-head">
        <strong>🗺️ 协同行程</strong>
        <span className="trips-hint">邀请同伴一起规划，AI 的每个改动都由你们决定采纳与否</span>
        <button className="modal-close" onClick={onClose}>✕</button>
      </div>
      {boardId === null ? (
        <TripList onOpen={setBoardId} />
      ) : (
        <TripBoard tripId={boardId} username={username} onBack={() => setBoardId(null)} onOpenConversation={onOpenConversation} onAskInChat={onAskInChat} />
      )}
    </div>
  )
}

function TripList({ onOpen }: { onOpen: (id: string) => void }) {
  const [trips, setTrips] = useState<TripSummary[] | null>(null)
  const [title, setTitle] = useState('')
  const [dest, setDest] = useState('')
  const [seedPrompt, setSeedPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const { notify } = useToast()

  useEffect(() => {
    authFetch(`${API}/trips`)
      .then(async (r) => {
        if (!r.ok) throw new Error()
        setTrips(await r.json())
      })
      .catch(() => {
        setTrips([])
        notify('行程列表加载失败，请稍后重试', 'error')
      })
  }, [notify])

  const removeTrip = async (t: TripSummary) => {
    if (!window.confirm(`删除行程「${t.title}」？此操作不可恢复。`)) return
    const res = await authFetch(`${API}/trips/${t.id}`, { method: 'DELETE' })
    if (res.ok) {
      setTrips((list) => (list || []).filter((x) => x.id !== t.id))
      notify('行程已删除', 'success')
    } else {
      const body = await res.json().catch(() => null)
      notify(body?.detail || '删除失败', 'error')
    }
  }

  const create = async () => {
    if (busy) return
    setBusy(true)
    try {
      const res = await authFetch(`${API}/trips`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title || (dest ? `${dest}之行` : '新行程'), destination: dest, days: 2 }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        notify(body?.detail || '创建行程失败', 'error')
        return
      }
      const { id } = await res.json()
      if (seedPrompt.trim()) {
        await authFetch(`${API}/trips/${id}/ai/seed`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: seedPrompt.trim() }),
        })
      }
      onOpen(id)
      notify(seedPrompt.trim() ? '行程已创建，AI 正在起草' : '空白行程已创建', 'success')
    } catch {
      notify('创建行程失败，请检查网络', 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="trips-list">
      <div className="trip-create">
        <div className="trip-create-row">
          <input placeholder="行程名（可空）" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input placeholder="目的地，如 开封" value={dest} onChange={(e) => setDest(e.target.value)} />
        </div>
        <textarea
          placeholder="（可选）让 AI 先起草一版：例如「开封两日游，喜欢历史和小吃，节奏轻松」——建好后可随意编辑"
          value={seedPrompt}
          onChange={(e) => setSeedPrompt(e.target.value)}
          rows={2}
        />
        <button className="trip-btn primary" onClick={create} disabled={busy}>
          {seedPrompt.trim() ? '✨ AI 起草并创建' : '＋ 创建空白行程'}
        </button>
      </div>
      {trips === null && <div className="modal-empty">加载中…</div>}
      {trips?.length === 0 && <div className="modal-empty">还没有行程，创建一个开始吧</div>}
      <div className="trip-cards">
        {trips?.map((t) => (
          <div key={t.id} className="trip-card" role="button" tabIndex={0}
            onClick={() => onOpen(t.id)}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onOpen(t.id)}>
            <div className="trip-card-title">{t.title}</div>
            <div className="trip-card-sub">
              {t.destination || '未定目的地'} · {t.days} 天 · {t.role === 'owner' ? '我创建的' : '受邀协作'}
            </div>
            {t.role === 'owner' && (
              <button className="trip-card-del" title="删除行程"
                onClick={(e) => { e.stopPropagation(); removeTrip(t) }}>✕</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function TripChat({
  tripId,
  tripTitle,
  members,
}: {
  tripId: string
  tripTitle: string
  members: TripMember[]
}) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<TripChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [unread, setUnread] = useState(0)
  const messagesRef = useRef<TripChatMessage[]>([])
  const hydratedRef = useRef(false)
  const openRef = useRef(false)
  const nearBottomRef = useRef(true)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    openRef.current = open
    if (open) {
      setUnread(0)
      nearBottomRef.current = true
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])

  const loadChat = useCallback(async () => {
    try {
      const previous = messagesRef.current
      const incremental = openRef.current && previous.length > 0
      const after = incremental ? previous[previous.length - 1].id : ''
      let response = await authFetch(
        `${API}/trips/${tripId}/chat${after ? `?after=${encodeURIComponent(after)}` : ''}`,
      )
      // 另一个标签页删除了游标消息时，回退完整窗口恢复，不让轮询永久卡在 400。
      if (!response.ok && after) {
        response = await authFetch(`${API}/trips/${tripId}/chat`)
      }
      if (!response.ok) return
      const incoming: TripChatMessage[] = await response.json()
      const next = incremental && after && response.url.includes('after=')
        ? [
            ...previous,
            ...incoming.filter((message) => !previous.some((item) => item.id === message.id)),
          ].slice(-100)
        : incoming
      if (hydratedRef.current && !openRef.current) {
        const known = new Set(previous.map((message) => message.id))
        const fresh = next.filter((message) => !known.has(message.id)).length
        if (fresh > 0) setUnread((count) => Math.min(99, count + fresh))
      }
      hydratedRef.current = true
      messagesRef.current = next
      setMessages(next)
    } catch {
      // 群聊轮询失败不影响行程板；用户主动发送时再给明确错误。
    }
  }, [tripId])

  useEffect(() => {
    hydratedRef.current = false
    messagesRef.current = []
    setMessages([])
    setUnread(0)
    loadChat()
  }, [tripId, loadChat])

  useEffect(() => {
    const timer = window.setInterval(loadChat, open ? 2500 : 8000)
    return () => window.clearInterval(timer)
  }, [loadChat, open])

  useEffect(() => {
    if (!open || !nearBottomRef.current) return
    const list = listRef.current
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' })
  }, [messages, open])

  const openChat = () => {
    openRef.current = true
    setOpen(true)
    setUnread(0)
    nearBottomRef.current = true
    loadChat()
  }

  const send = async (raw?: string) => {
    const content = (raw ?? input).trim()
    if (!content || sending) return
    setSending(true)
    setError('')
    try {
      const response = await authFetch(`${API}/trips/${tripId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(body?.detail || '消息发送失败')
      }
      const message: TripChatMessage = await response.json()
      const next = [...messagesRef.current.filter((item) => item.id !== message.id), message]
      messagesRef.current = next
      setMessages(next)
      setInput('')
      nearBottomRef.current = true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '消息发送失败，请稍后重试')
    } finally {
      setSending(false)
    }
  }

  const remove = async (messageId: string) => {
    const response = await authFetch(`${API}/trips/${tripId}/chat/${messageId}`, { method: 'DELETE' })
    if (!response.ok) {
      setError('删除失败，请稍后重试')
      return
    }
    const next = messagesRef.current.filter((message) => message.id !== messageId)
    messagesRef.current = next
    setMessages(next)
  }

  const timeLabel = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }

  const dayLabel = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return ''
    const today = new Date()
    const sameDay = date.toDateString() === today.toDateString()
    if (sameDay) return '今天'
    return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
  }

  const panel = open ? createPortal(
    <div className="trip-chat-mask" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setOpen(false)
    }}>
      <aside className="trip-chat-panel" role="dialog" aria-modal="true" aria-label={`${tripTitle}群聊`}>
        <header className="trip-chat-head">
          <div className="trip-chat-head-copy">
            <span className="trip-chat-head-icon" aria-hidden>💬</span>
            <span>
              <strong>同行群聊</strong>
              <small>{tripTitle} · {members.length} 位同行者</small>
            </span>
          </div>
          <div className="trip-chat-head-members" aria-label="群聊成员">
            {members.slice(0, 5).map((member) => (
              <i key={member.username} title={member.username}>
                {member.username[0]?.toUpperCase()}
              </i>
            ))}
            {members.length > 5 && <b>+{members.length - 5}</b>}
          </div>
          <button className="trip-chat-close" onClick={() => setOpen(false)} aria-label="关闭群聊">✕</button>
        </header>

        <div
          className="trip-chat-messages"
          ref={listRef}
          onScroll={(event) => {
            const target = event.currentTarget
            nearBottomRef.current = target.scrollHeight - target.scrollTop - target.clientHeight < 100
          }}
        >
          {messages.length === 0 && (
            <div className="trip-chat-empty">
              <span aria-hidden>🧭</span>
              <strong>把整体安排放在这里聊</strong>
              <p>集合时间、预算取舍、临时变更都可以告诉同行者；具体地点仍可使用地点留言。</p>
            </div>
          )}
          {messages.map((message, index) => {
            const previous = messages[index - 1]
            const showDay = !previous || dayLabel(previous.created_at) !== dayLabel(message.created_at)
            const showAuthor = !previous
              || previous.username !== message.username
              || previous.mine !== message.mine
              || showDay
            return (
              <div key={message.id}>
                {showDay && <div className="trip-chat-day"><span>{dayLabel(message.created_at)}</span></div>}
                <div className={`trip-chat-message${message.mine ? ' mine' : ''}${showAuthor ? ' with-author' : ''}`}>
                  {!message.mine && (
                    <span className="trip-chat-avatar" aria-hidden>{message.username[0]?.toUpperCase()}</span>
                  )}
                  <div className="trip-chat-message-main">
                    {showAuthor && (
                      <div className="trip-chat-author">
                        <b>{message.mine ? '我' : message.username}</b>
                        <time>{timeLabel(message.created_at)}</time>
                      </div>
                    )}
                    <div className="trip-chat-bubble"><ChatBody content={message.content} /></div>
                    {message.mine && (
                      <button className="trip-chat-delete" onClick={() => remove(message.id)}>删除</button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <footer className="trip-chat-composer">
          {error && <div className="trip-chat-error" role="alert">{error}</div>}
          <ChatInput
            onSend={send}
            onError={setError}
            disabled={sending}
            placeholder={`发消息给 ${members.length} 位同行者…（可粘贴截图）`}
          />
          <div className="trip-chat-input-meta">
            <span><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行</span>
          </div>
        </footer>
      </aside>
    </div>,
    document.body,
  ) : null

  return (
    <>
      <button className={`trip-chat-trigger${unread ? ' has-unread' : ''}`} onClick={openChat}>
        <span className="trip-chat-trigger-icon" aria-hidden>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z" />
          </svg>
        </span>
        <span className="trip-chat-trigger-label">群聊</span>
        {unread > 0 && <b aria-label={`${unread} 条未读消息`}>{unread > 9 ? '9+' : unread}</b>}
      </button>
      {panel}
    </>
  )
}

function SourceGuideDrawer({
  tripId, tripTitle, onClose, onOpenConversation,
}: {
  tripId: string
  tripTitle: string
  onClose: () => void
  onOpenConversation?: (cid: string) => void
}) {
  const [guide, setGuide] = useState<SourceGuide | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    authFetch(`${API}/trips/${tripId}/source-guide`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || '原攻略加载失败')
        }
        const data: SourceGuide = await res.json()
        if (alive) setGuide(data)
      })
      .catch((reason) => alive && setError(reason instanceof Error ? reason.message : '原攻略加载失败'))
    return () => { alive = false }
  }, [tripId])

  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])

  return createPortal(
    <div className="trip-source-mask" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <aside className="trip-source-panel" role="dialog" aria-modal="true" aria-label={`${tripTitle}原攻略`}>
        <header className="trip-source-head">
          <span>
            <small>协同行程 · 只读原文</small>
            <strong>📄 {guide?.title || tripTitle}</strong>
          </span>
          <div className="trip-source-head-actions">
            {guide?.can_open_conversation && guide.conversation_id && onOpenConversation && (
              <button onClick={() => onOpenConversation(guide.conversation_id)}>回到我的原对话 ↗</button>
            )}
            <button className="trip-chat-close" onClick={onClose} aria-label="关闭原攻略">✕</button>
          </div>
        </header>
        <div className="trip-source-body">
          {!guide && !error && <div className="trip-source-loading"><span className="spinner" /> 正在加载原攻略…</div>}
          {error && <div className="trip-source-error">⚠️ {error}</div>}
          {guide && (
            <>
              <div className="md trip-source-markdown">
                <ReactMarkdown
                  remarkPlugins={[[remarkGfm, { singleTilde: false }]]}
                  components={{
                    a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a>,
                    img: ({ alt, ...props }) => <img {...props} alt={alt || '攻略配图'} loading="lazy" />,
                  }}
                >{prepareMarkdown(guide.content)}</ReactMarkdown>
              </div>
              {guide.sources.length > 0 && (
                <section className="trip-source-links">
                  <strong>参考来源</strong>
                  {guide.sources.map((source, index) => (
                    <a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noreferrer">
                      <b>{index + 1}</b><span>{source.title}</span><i>打开 ↗</i>
                    </a>
                  ))}
                </section>
              )}
            </>
          )}
        </div>
      </aside>
    </div>,
    document.body,
  )
}

function TripBoard({
  tripId, username, onBack, onOpenConversation, onAskInChat,
}: {
  tripId: string
  username: string
  onBack: () => void
  onOpenConversation?: (cid: string) => void
  onAskInChat?: (text: string) => void
}) {
  const [trip, setTrip] = useState<TripDetail | null>(null)
  const [issues, setIssues] = useState<TripIssue[]>([])
  const [ticketTotal, setTicketTotal] = useState(0)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [comments, setComments] = useState<TripComment[]>([])
  const [segments, setSegments] = useState<Segment[]>([])
  const [events, setEvents] = useState<{ username: string; action: string; created_at: string }[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [invite, setInvite] = useState('')
  const [msg, setMsg] = useState('')
  const [copilotInput, setCopilotInput] = useState('')
  const [retrying, setRetrying] = useState(false)
  const [selectedDay, setSelectedDay] = useState(1)
  const [flashId, setFlashId] = useState<string | null>(null)
  const [editing, setEditing] = useState<TripStop | null>(null)
  const [openComments, setOpenComments] = useState<string | null>(null)
  const [mapFailed, setMapFailed] = useState(false)  // JS 地图挂了回退静态图
  const [focusStop, setFocusStop] = useState<string | null>(null)
  const [repairingLocations, setRepairingLocations] = useState(false)
  const [sourceGuideOpen, setSourceGuideOpen] = useState(false)
  const [mobilePane, setMobilePane] = useState<'timeline' | 'map' | 'assistant'>('timeline')
  const [workspaceView, setWorkspaceView] = useState<'day' | 'tool'>('day')
  // Phase 47：右栏从「6 面板堆叠」改标签页，按用户心智分四块（一次只显一块）
  const [aiTab, setAiTab] = useState<TripToolTab>('assistant')
  // Phase 48：每天过夜城市（逆地理编码）+ 受控酒店搜索城市
  const [dayCities, setDayCities] = useState<Record<string, string>>({})
  const [dayOvernight, setDayOvernight] = useState<Record<string, boolean>>({})
  const [hotelCity, setHotelCity] = useState('')
  const { notify } = useToast()
  const dragIdRef = useRef<string | null>(null)
  const updatedRef = useRef('')
  const aiStatusRef = useRef<string | null>(null)
  const dayRef = useRef(1)
  const stopRefs = useRef(new Map<string, HTMLDivElement>())
  const tripUpdatedAt = trip?.updated_at
  dayRef.current = selectedDay

  const load = useCallback(async () => {
    const res = await authFetch(`${API}/trips/${tripId}?editing_day=${dayRef.current}`)
    if (!res.ok) return
    const data: TripDetail = await res.json()
    const wasCopilot = aiStatusRef.current === 'copilot'
    aiStatusRef.current = data.ai_status
    if (data.updated_at !== updatedRef.current) {
      updatedRef.current = data.updated_at
      setTrip(data)
      authFetch(`${API}/trips/${tripId}/issues`).then(async (r) => {
        if (r.ok) {
          const b = await r.json()
          setIssues(b.issues)
          setTicketTotal(b.ticket_total)
        }
      }).catch(() => {})
      authFetch(`${API}/trips/${tripId}/suggestions`).then(async (r) => r.ok && setSuggestions(await r.json())).catch(() => {})
      authFetch(`${API}/trips/${tripId}/comments`).then(async (r) => r.ok && setComments(await r.json())).catch(() => {})
      authFetch(`${API}/trips/${tripId}/expenses`).then(async (r) => r.ok && setExpenses(await r.json())).catch(() => {})
    } else {
      setTrip((cur) => (cur ? { ...cur, ai_status: data.ai_status, members: data.members } : data))
      if (data.ai_status === null && wasCopilot) {
        authFetch(`${API}/trips/${tripId}/suggestions`).then(async (r) => r.ok && setSuggestions(await r.json())).catch(() => {})
      }
    }
  }, [tripId])

  useEffect(() => {
    load()
    const timer = window.setInterval(load, 2500)
    return () => window.clearInterval(timer)
  }, [load])

  // Phase 39：选中天的真实交通时间
  useEffect(() => {
    if (!tripUpdatedAt) return
    authFetch(`${API}/trips/${tripId}/segment-times?day=${selectedDay}`)
      .then(async (r) => r.ok && setSegments((await r.json()).segments))
      .catch(() => setSegments([]))
  }, [tripId, selectedDay, tripUpdatedAt])

  useEffect(() => {
    if (aiTab === 'log') {
      authFetch(`${API}/trips/${tripId}/events`).then(async (r) => r.ok && setEvents(await r.json())).catch(() => {})
    }
  }, [aiTab, tripId, trip?.updated_at])

  // Phase 48：住宿 tab 打开时拉每天过夜城市；初始化酒店搜索城市为目的地
  useEffect(() => {
    if (aiTab !== 'stay') return
    authFetch(`${API}/trips/${tripId}/day-cities`).then(async (r) => {
      if (!r.ok) return
      const body = await r.json()
      setDayCities(body.cities || {})
      setDayOvernight(body.overnight || {})
      setHotelCity((c) => c || body.default || '')
    }).catch(() => {})
  }, [aiTab, tripId, trip?.updated_at])

  // Phase 51 批6：首次载入把当前日定位到「第一个有坐标的日」，避免开局地图空白/居中在别处
  const didInitDay = useRef('')
  useEffect(() => {
    if (!trip || didInitDay.current === tripId) return
    const first = trip.stops.filter((s) => s.location)
      .sort((a, b) => a.day - b.day || a.order_no - b.order_no)[0]
    if (first) {
      setSelectedDay(first.day)
      didInitDay.current = tripId
    }
  }, [trip, tripId])

  const call = useCallback(async (path: string, method: string, body?: unknown) => {
    const res = await authFetch(`${API}/trips/${tripId}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!res.ok) {
      try {
        setMsg((await res.json()).detail || '操作失败')
      } catch {
        setMsg('操作失败')
      }
      window.setTimeout(() => setMsg(''), 3000)
    }
    updatedRef.current = ''
    await load()
    return res.ok
  }, [tripId, load])

  if (trip === null) return <div className="modal-empty">加载中…</div>

  const isOwner = trip.members.some((m) => m.username === username && m.role === 'owner')
  const status = tripStatus(trip.start_date, trip.days)
  // PRD 4.5：悬浮按钮的文案跟着当前标签走；行程表视图下是「新增地点」
  const fabLabel = workspaceView === 'day' ? '+ 加地点' : FAB_BY_TAB[aiTab]
  const days = Array.from(
    new Set([...Array.from({ length: trip.days }, (_, i) => i + 1), ...trip.stops.map((s) => s.day)]),
  ).sort((a, b) => a - b)
  const stopsOf = (d: number) => trip.stops.filter((s) => s.day === d).sort((a, b) => a.order_no - b.order_no)
  const isStay = (s: TripStop) => (s.note || '').includes('🏨') || (s.note || '').includes('住宿')
  // 「已加入」按**当前选中天**判定（去掉 🏨 前缀）：从真实 stops 派生，删除即复原；
  // 不同天可重复加同一家酒店（切天后该家又显示「加入」）——只避免同一天重复添加。
  const addedHotelNames = new Set(
    stopsOf(selectedDay).filter(isStay).map((s) => s.name.replace(/^🏨\s*/, '')),
  )
  const commentsOf = (sid: string) => comments.filter((c) => c.stop_id === sid)
  const segAfter = (sid: string) => segments.find((sg) => sg.from_id === sid)

  const locate = (day?: number, stopId?: string) => {
    if (day) setSelectedDay(day)
    if (stopId) {
      setWorkspaceView('day')
      setMobilePane('timeline')
      setFlashId(stopId)
      window.setTimeout(() => setFlashId(null), 2200)
      window.setTimeout(() => stopRefs.current.get(stopId)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 60)
    }
  }

  const repairLocations = async () => {
    if (repairingLocations) return
    setRepairingLocations(true)
    try {
      const res = await authFetch(`${API}/trips/${tripId}/geocode/repair`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setMsg(body.detail || '重新定位失败')
        return
      }
      const body = await res.json()
      const unresolved = Array.isArray(body.unresolved) ? body.unresolved.length : 0
      setMsg(`坐标修复完成：更新 ${body.updated} 个，清除错误 ${body.cleared} 个${unresolved ? `，${unresolved} 个仍未找到` : ''}`)
      updatedRef.current = ''
      await load()
    } catch {
      setMsg('重新定位失败，请稍后重试')
    } finally {
      setRepairingLocations(false)
      window.setTimeout(() => setMsg(''), 7000)
    }
  }

  const move = async (stop: TripStop, dir: -1 | 1) => {
    const siblings = stopsOf(stop.day)
    const idx = siblings.findIndex((s) => s.id === stop.id)
    const target = siblings[idx + dir]
    if (!target) return
    await call(`/stops/${stop.id}`, 'PATCH', { order_no: target.order_no })
    await call(`/stops/${target.id}`, 'PATCH', { order_no: stop.order_no })
  }

  const dropOn = async (dragId: string, day: number, beforeId: string | null) => {
    const siblings = stopsOf(day).map((x) => x.id).filter((id) => id !== dragId)
    const idx = beforeId ? siblings.indexOf(beforeId) : siblings.length
    siblings.splice(idx < 0 ? siblings.length : idx, 0, dragId)
    await call('/stops/reorder', 'POST', { day, ordered_ids: siblings })
  }

  // 只有「进行中」状态锁输入；failed 是终态，必须允许重发以恢复（否则卡死无法自愈）
  const aiBusy = ['seeding', 'copilot', 'reviewing'].includes(trip.ai_status || '')
  const sendCopilot = async (prompt: string) => {
    if (!prompt.trim() || aiBusy) return
    setCopilotInput('')
    await call('/ai/copilot', 'POST', { prompt: prompt.trim() })
  }

  const retryImport = async () => {
    if (retrying) return
    setRetrying(true)
    try {
      const res = await authFetch(`${API}/trips/${tripId}/import/retry`, { method: 'POST' })
      const body = await res.json().catch(() => null)
      if (!res.ok) {
        notify(body?.detail || '重试失败', 'error')
        return
      }
      const days: number[] = body?.retry_days || []
      notify(days.length ? `正在重试第 ${days.join('、')} 天` : '正在重新解析攻略', 'success')
      await load()
    } finally {
      setRetrying(false)
    }
  }

  const deleteDraft = async () => {
    if (!window.confirm('删除这份导入草稿？攻略本身不受影响，之后可以重新导入。')) return
    const res = await authFetch(`${API}/trips/${tripId}`, { method: 'DELETE' })
    if (res.ok) {
      notify('草稿已删除', 'success')
      onBack()
    } else {
      notify('删除失败', 'error')
    }
  }

  const mapStops = stopsOf(selectedDay).filter((s) => s.location)
  const actualTotal = expenses.reduce((sum, expense) => sum + expense.amount, 0)
  const plannedTotal = trip.budget || Object.values(trip.budget_breakdown || {}).reduce((sum, value) => sum + value, 0)
  const budgetPercent = plannedTotal > 0 ? Math.min(100, Math.round((actualTotal / plannedTotal) * 100)) : 0
  const mapUrl = mapStops.length
    ? `${API}/staticmap?pts=${mapStops.map((s) => s.location).join(';')}` +
      `&labels=${mapStops.map((_, i) => i + 1).join(',')}` +
      `&days=${mapStops.map(() => selectedDay).join(',')}&size=600*600`
    : null

  const optimizeRoute = async () => {
    const res = await authFetch(`${API}/trips/${tripId}/ai/order`, { method: 'POST' })
    if (!res.ok) return
    const result = await res.json()
    setMsg(`已串好路线：${result.km_before}km → ${result.km_after}km${result.unlocated.length ? `（${result.unlocated.join('、')} 无坐标已跳过）` : ''}`)
    window.setTimeout(() => setMsg(''), 6000)
    updatedRef.current = ''
    load()
  }

  return (
    <div className="trip-board">
      <div className="trip-board-head">
        <button className="trip-btn" onClick={onBack}>← 返回</button>
        <span className="trip-title-stack">
          <strong className="trip-board-title">
            {trip.title}
            {/* PRD 4.2：行程状态角标。没填出发日期时显示「未定日期」而不是硬猜一个状态 */}
            <i className={`trip-status-badge status-${status.key}`}>{status.label}</i>
          </strong>
          <span className="trip-board-sub">
            {trip.destination || '未定目的地'} · {trip.days} 天{trip.start_date ? ` · ${trip.start_date} 出发` : ''}
          </span>
        </span>
        {trip.ai_status && (
          <span className="trip-ai-status">
            {trip.ai_status === 'seeding' ? `✨ ${trip.ai_review || 'AI 起草中…'}`
              : trip.ai_status === 'copilot' ? '🤖 AI 思考中…'
                : trip.ai_status === 'reviewing' ? '🔍 AI 检查中…'
                  : `⚠️ ${trip.ai_review || '上次 AI 任务失败'}`}
            {/* 导入失败/部分成功必须给出恢复入口——此前只有一句「请重试」，
                页面上却没有任何可点的东西，用户只能回对话重导，于是堆出重复空行程。 */}
            {['failed', 'partial'].includes(trip.ai_status) && (
              <>
                <button className="trip-btn tiny" onClick={retryImport} disabled={retrying}>
                  {retrying ? '重试中…' : '继续重试'}
                </button>
                <button className="trip-btn tiny ghost" onClick={deleteDraft}>删除草稿</button>
              </>
            )}
          </span>
        )}
        {msg && <span className="trip-msg">{msg}</span>}
        <span className="trip-members">
          {trip.members.map((m) => (
            <i key={m.username} className={`trip-avatar${m.online ? ' online' : ''}`}
              title={`${m.username}${m.online ? (m.editing_day ? ` · 在看 Day${m.editing_day}` : ' · 在线') : ''}`}>
              {m.username[0]?.toUpperCase()}
              {m.online && m.editing_day ? <b className="trip-avatar-day">D{m.editing_day}</b> : null}
            </i>
          ))}
        </span>
        <TripChat
          tripId={tripId}
          tripTitle={trip.title}
          members={trip.members}
        />
        {(isOwner || trip.source_conversation_id) && (
          <details className="trip-actions-menu">
            <summary aria-label="行程操作">••• <span>行程操作</span></summary>
            <div className="trip-actions-popover">
              {trip.source_conversation_id && (
                <button className="trip-action-row" onClick={() => setSourceGuideOpen(true)}>
                  <span>📄</span><b>查看原攻略</b><small>所有已加入成员都可只读查看</small>
                </button>
              )}
              {isOwner && <ShareButton tripId={tripId} tripTitle={trip.title} destination={trip.destination} username={username} />}
              {isOwner && (
                <div className="trip-invite">
                  <label>邀请同行者</label>
                  <span>
                    <input placeholder="输入用户名" value={invite} onChange={(e) => setInvite(e.target.value)} />
                    <button className="trip-btn primary" onClick={async () => {
                      if (invite.trim() && (await call('/invite', 'POST', { username: invite.trim() }))) {
                        setInvite('')
                        setMsg('已发出邀请，等待对方接受')
                        window.setTimeout(() => setMsg(''), 4000)
                      }
                    }}>
                      邀请
                    </button>
                  </span>
                </div>
              )}
            </div>
          </details>
        )}
      </div>

      <nav className="trip-workspace-tabs" aria-label="行程日期与工具导航">
        <div className="trip-day-nav" role="tablist" aria-label="选择行程日期">
          {days.map((d) => (
            <button
              key={d}
              role="tab"
              aria-selected={workspaceView === 'day' && selectedDay === d}
              className={workspaceView === 'day' && selectedDay === d ? 'active' : ''}
              onClick={() => {
                setSelectedDay(d)
                setWorkspaceView('day')
              }}
            >
              Day {d}
              <small>{stopsOf(d).length}</small>
            </button>
          ))}
        </div>
        <i className="trip-tabs-divider" aria-hidden="true" />
        <div className="trip-feature-nav" role="tablist" aria-label="行程工具">
          {TRIP_TOOL_TABS.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={workspaceView === 'tool' && aiTab === tab.id}
              className={workspaceView === 'tool' && aiTab === tab.id ? 'active' : ''}
              onClick={() => {
                setAiTab(tab.id)
                setWorkspaceView('tool')
              }}
            >
              <span aria-hidden="true">{tab.icon}</span>{tab.label}
              {tab.id === 'assistant' && issues.length > 0 ? <small>{issues.length}</small> : null}
            </button>
          ))}
        </div>
      </nav>

      <div className="trip-mobile-tabs" role="tablist" aria-label="行程板块">
        <button role="tab" aria-selected={mobilePane === 'timeline'} className={mobilePane === 'timeline' ? 'active' : ''} onClick={() => setMobilePane('timeline')}>
          🗓️ 行程
        </button>
        <button role="tab" aria-selected={mobilePane === 'map'} className={mobilePane === 'map' ? 'active' : ''} onClick={() => setMobilePane('map')}>
          🗺️ 地图
        </button>
        <button role="tab" aria-selected={mobilePane === 'assistant'} className={mobilePane === 'assistant' ? 'active' : ''} onClick={() => setMobilePane('assistant')}>
          ✨ 助手{issues.length > 0 ? ` · ${issues.length}` : ''}
        </button>
      </div>

      <div className={`trip-3col trip-view-${workspaceView}`}>
        {/* 左：预算概览 + 每天导航（与参考 HTML 一致） */}
        <aside className="trip-day-sidebar" aria-label="预算与行程天数">
          <section className="trip-budget-summary">
            <span>总预算 {plannedTotal > 0 ? `¥${plannedTotal.toLocaleString()} / 人` : '未设置'}</span>
            <strong>已花费 ¥{actualTotal.toLocaleString()}</strong>
            <div className="trip-budget-progress" aria-label={`预算已使用 ${budgetPercent}%`}>
              <i style={{ width: `${budgetPercent}%` }} />
            </div>
            <small>{plannedTotal > 0 ? `已使用 ${budgetPercent}%` : '可在「费用」中设置预算'}</small>
          </section>
          <div className="trip-sidebar-label">行程天数</div>
          <nav className="trip-sidebar-days">
            {days.map((d) => (
              <button
                key={d}
                className={workspaceView === 'day' && selectedDay === d ? 'active' : ''}
                onClick={() => { setSelectedDay(d); setWorkspaceView('day') }}
              >
                <span><b>Day {d}</b><small>{tripDayDate(trip.start_date, d) || `${stopsOf(d).length} 个事件`}</small></span>
                <i>{stopsOf(d).length}</i>
              </button>
            ))}
          </nav>
        </aside>

        {/* 中：当前日事件时间线 */}
        <div className={`trip-col-timeline${mobilePane === 'timeline' ? ' mobile-active' : ''}`}>
          <header className="trip-day-overview">
            <h2>Day {selectedDay} · {trip.destination || trip.title}</h2>
            <p>{[tripDayDate(trip.start_date, selectedDay), `${stopsOf(selectedDay).length} 个事件`].filter(Boolean).join(' · ')}</p>
          </header>
          <section className="trip-route-summary">
            <div className="trip-route-summary-head">
              <strong>📍 今日路线</strong>
              <button className="trip-btn primary" onClick={optimizeRoute}>✦ AI 优化路线</button>
            </div>
            <div className="trip-route-points">
              {stopsOf(selectedDay).length
                ? stopsOf(selectedDay).map((stop) => stop.name.replace(/^🏨\s*/, '')).join('　→　')
                : '添加事件后，这里会自动形成当天路线'}
            </div>
          </section>
          {days.filter((d) => d === selectedDay).map((d) => (
            <div
              key={d}
              className={`trip-day-section${selectedDay === d ? ' active' : ''}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault()
                if (dragIdRef.current) dropOn(dragIdRef.current, d, null)
                dragIdRef.current = null
              }}
            >
              {/* Phase 51 批6：长行程导航——只展开当前日，其余折叠成日头（点击展开），拖拽仍可落到折叠日 */}
              {selectedDay === d && (<>
              {stopsOf(d).map((s, i, arr) => (
                <div key={s.id} className="trip-event-item">
                  <div
                    ref={(el) => { if (el) stopRefs.current.set(s.id, el) }}
                    className={`trip-stop${flashId === s.id ? ' flash' : ''}${isStay(s) ? ' is-stay' : ''}`}
                    onClick={() => { setSelectedDay(d); setFocusStop(s.id) }}
                    draggable
                    onDragStart={(e) => { dragIdRef.current = s.id; e.dataTransfer.effectAllowed = 'move' }}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      if (dragIdRef.current && dragIdRef.current !== s.id) dropOn(dragIdRef.current, d, s.id)
                      dragIdRef.current = null
                    }}
                  >
                    <div className="trip-stop-time-row">
                      <span className="trip-stop-time">
                        {formatTripTimeRange(s.start_time, s.stay_min, arr[i + 1]?.start_time)}
                      </span>
                    </div>
                    <div className="trip-stop-main">
                      <span className="trip-stop-no" style={{ background: DAY_COLORS[(d - 1) % DAY_COLORS.length] }}>{i + 1}</span>
                      <span className="trip-stop-name" title={s.location ? '已定位' : '未找到坐标，串路线时会跳过'}>
                        {s.name} {!s.location && <em className="trip-noloc">?</em>}
                      </span>
                    </div>
                    <div className="trip-stop-badges">
                      {s.stay_min ? <span>⏱ {s.stay_min}min</span> : null}
                      {s.transport && <span>🚶 {s.transport}</span>}
                      {s.ticket_price ? <span>🎫 ¥{s.ticket_price}</span> : null}
                      {s.tags.map((t) => <span key={t} className="trip-tag">#{t}</span>)}
                    </div>
                    {s.note && <div className="trip-stop-note">{s.note}</div>}
                    <div className="trip-stop-ops">
                      <button aria-label={`上移 ${s.name}`} disabled={i === 0} onClick={(e) => { e.stopPropagation(); move(s, -1) }} title="上移">↑</button>
                      <button aria-label={`下移 ${s.name}`} disabled={i === arr.length - 1} onClick={(e) => { e.stopPropagation(); move(s, 1) }} title="下移">↓</button>
                      <button onClick={(e) => {
                        e.stopPropagation()
                        const nd = window.prompt('移到第几天？', String(s.day === days[days.length - 1] ? 1 : s.day + 1))
                        const n = Number(nd)
                        if (n >= 1 && n <= 15) call(`/stops/${s.id}`, 'PATCH', { day: n })
                      }} aria-label={`移动 ${s.name} 到其他天`} title="换天">⇄</button>
                      <button aria-label={`编辑 ${s.name}`} onClick={(e) => { e.stopPropagation(); setEditing(s) }} title="编辑详情">✎</button>
                      <button
                        className={commentsOf(s.id).length ? 'has-comments' : ''}
                        onClick={(e) => { e.stopPropagation(); setOpenComments(openComments === s.id ? null : s.id) }}
                        title="评论"
                        aria-label={`${s.name} 的评论`}
                      >
                        💬{commentsOf(s.id).length || ''}
                      </button>
                      <button onClick={(e) => {
                        e.stopPropagation()
                        if (!window.confirm(`删除「${s.name}」？此操作无法撤销。`)) return
                        call(`/stops/${s.id}`, 'DELETE').then((ok) => {
                          if (ok) notify(`已删除「${s.name}」`, 'success')
                        })
                      }} aria-label={`删除 ${s.name}`} title="删除">✕</button>
                    </div>
                    {openComments === s.id && (
                      <CommentThread
                        comments={commentsOf(s.id)}
                        onAdd={(text) => call(`/stops/${s.id}/comments`, 'POST', { content: text })}
                        onDelete={(id) => call(`/comments/${id}`, 'DELETE')}
                      />
                    )}
                  </div>
                  {selectedDay === d && i < arr.length - 1 && segAfter(s.id)?.minutes != null && (
                    <div className="trip-segment">
                      ↓ {segAfter(s.id)!.mode} {segAfter(s.id)!.minutes} 分钟 · {segAfter(s.id)!.km}km
                      {segAfter(s.id)!.estimated ? <em title={segAfter(s.id)!.note || '距离与时间为估算'}>估算</em> : null}
                    </div>
                  )}
                </div>
              ))}
              <AddStop onAdd={(name) => call('/stops', 'POST', { day: d, name })} />
              </>)}
            </div>
          ))}
        </div>

        {/* 右：每日地图（桌面固定，参考 HTML 的地图侧栏） */}
        <div className={`trip-col-map${mobilePane === 'map' ? ' mobile-active' : ''}`}>
          <div className="trip-map-card-head">
            <strong>📍 今日路线地图</strong>
            <span>{mapStops.length} 个地点</span>
          </div>
          <div className="trip-map-tabs">
            {days.map((d) => (
              <button key={d} className={`trip-map-tab${selectedDay === d ? ' active' : ''}`}
                style={selectedDay === d ? { borderColor: DAY_COLORS[(d - 1) % DAY_COLORS.length] } : undefined}
                onClick={() => setSelectedDay(d)}>
                Day {d}
              </button>
            ))}
          </div>
          {!mapFailed ? (
            <TripMap
              stops={mapStops.map((s, i) => ({ id: s.id, name: s.name, location: s.location, idx: i + 1 }))}
              color={DAY_COLORS[(selectedDay - 1) % DAY_COLORS.length]}
              focusId={focusStop}
              onMarkerClick={(id) => {
                const st = trip.stops.find((x) => x.id === id)
                locate(st?.day, id)
              }}
              onFail={() => setMapFailed(true)}
            />
          ) : mapUrl ? (
            <img className="trip-map-img" src={mapUrl} alt={`Day${selectedDay} 路线图`} />
          ) : (
            <div className="trip-map-empty">Day {selectedDay} 还没有带坐标的地点<br />添加地点后自动出图</div>
          )}
          {!mapFailed && mapStops.length === 0 && (
            <div className="trip-map-hint">Day {selectedDay} 还没有带坐标的地点，添加后自动上图</div>
          )}
          <div className="trip-map-tools">
            <button className="trip-btn trip-repair-btn" disabled={repairingLocations} onClick={repairLocations}
              title="按每天所在城市重新搜索坐标，修复海外或同名地点误定位">
              {repairingLocations ? '🌐 正在重新定位…' : '🌐 重新定位'}
            </button>
          </div>
          <small className="trip-geocode-credit">海外坐标数据 © OpenStreetMap contributors</small>
        </div>

        {/* 左侧功能视图：由顶部功能胶囊替换事件列表，地图始终留在右侧 */}
        <div className={`trip-col-ai${mobilePane === 'assistant' ? ' mobile-active' : ''}`}>
          <button className="trip-return-timeline" onClick={() => setWorkspaceView('day')}>
            ← 返回 Day {selectedDay} 行程
          </button>
          {/* Phase 87：这里原本还有一套驱动同一个 aiTab 的标签栏，与顶部 trip-workspace-tabs
              完全重复（同样的四个标签、同样的 setAiTab）。删掉，只保留顶部那一套。 */}

          {aiTab === 'food' && <FoodPanel tripId={tripId} active />}
          {aiTab === 'packing' && (
            <PackingPanel tripId={tripId} active username={username}
              members={trip.members} isOwner={isOwner}
              onInvite={(n) => call('/invite', 'POST', { username: n }).then((r) => !!r)} />
          )}
          {aiTab === 'tips' && <TipsPanel tripId={tripId} active />}

          {/* ---- 住宿 tab：每晚住哪汇总 + 酒店推荐 ---- */}
          {aiTab === 'stay' && (
            <>
              <div className="trip-panel">
                <div className="trip-panel-head">🛏 每晚住哪 <span className="trip-day-km">点「查酒店」按天订</span></div>
                {days.map((d) => {
                  const stays = stopsOf(d).filter(isStay)
                  const city = dayCities[String(d)] || trip.destination
                  // Phase 51 批4：返程日（overnight=false）当晚回家，不提示订房
                  const noStay = dayOvernight[String(d)] === false
                  return (
                    <div key={d} className="trip-stay-row">
                      <span className="trip-stay-day" style={{ background: DAY_COLORS[(d - 1) % DAY_COLORS.length] }}>D{d}</span>
                      {noStay && !stays.length ? (
                        <span className="trip-stay-name trip-stay-return">返程日 · 无需住宿</span>
                      ) : stays.length ? (
                        <span className="trip-stay-name" onClick={() => { setSelectedDay(d); locate(d, stays[0].id) }}>
                          {stays.map((s) => s.name.replace(/^🏨\s*/, '')).join('、')}
                          {stays.some((s) => s.ticket_price) && (
                            <b className="trip-stay-price">
                              ¥{stays.reduce((a, s) => a + (s.ticket_price || 0), 0).toFixed(0)}/晚
                            </b>
                          )}
                        </span>
                      ) : (
                        <>
                          <span className="trip-stay-name trip-stay-city">{city || '未知城市'}</span>
                          <button
                            className="trip-btn trip-stay-book"
                            disabled={!city}
                            onClick={() => { setSelectedDay(d); setHotelCity(city) }}
                            title={`查 ${city} 的酒店并加到 Day${d}`}
                          >
                            查酒店
                          </button>
                        </>
                      )}
                    </div>
                  )
                })}
              </div>
              {!!trip.hotel_recommendations?.length && (
                <div className="trip-panel trip-imported-hotels">
                  <div className="trip-panel-head">
                    🧳 攻略推荐酒店
                    <span className="trip-day-km">候选 · 尚未预订</span>
                  </div>
                  {trip.hotel_recommendations.map((hotel) => (
                    <div className="trip-imported-hotel" key={`${hotel.city}-${hotel.hotel}`}>
                      <div>
                        <b>{hotel.hotel}</b>
                        <span>{[hotel.city, hotel.source].filter(Boolean).join(' · ')}</span>
                        {hotel.note && <small>{hotel.note}</small>}
                      </div>
                      {hotel.price ? <strong>¥{hotel.price.toFixed(0)}/晚</strong> : null}
                      <button
                        className="trip-btn"
                        disabled={addedHotelNames.has(hotel.hotel)}
                        onClick={() => call('/stops', 'POST', {
                          day: selectedDay,
                          name: `🏨 ${hotel.hotel}`,
                          note: `住宿${hotel.source ? ` · ${hotel.source}` : ''}`,
                          ticket_price: hotel.price,
                        })}
                      >
                        {addedHotelNames.has(hotel.hotel) ? `已加入 Day${selectedDay} ✓` : `加入 Day${selectedDay}`}
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="trip-hotel-day-hint">正在为 <b>Day{selectedDay}</b> 挑酒店 · 加入的酒店会挂到这一天</div>
              <HotelPanel
                tripId={tripId}
                city={hotelCity}
                addedNames={addedHotelNames}
                onCityChange={setHotelCity}
                onAdd={(name, loc) => call('/stops', 'POST', { day: selectedDay, name, note: '🏨 住宿', location: loc })}
                onCtripPrice={onAskInChat ? (c) => onAskInChat(`查一下${c}的酒店，要携程实时价格和房态，帮我推荐几家性价比高的`) : undefined}
              />
            </>
          )}

          {/* ---- 费用 tab：预算 + 记账 ---- */}
          {aiTab === 'money' && (
            <>
              <div className="trip-panel">
                <div className="trip-panel-head">💰 预算</div>
                <div className="trip-budget-row">
                  <span>景点票价已录入 <b>¥{ticketTotal.toFixed(0)}</b></span>
                  <span className={trip.budget && ticketTotal > trip.budget ? 'trip-over' : ''}>
                    预算 <input className="trip-budget-input" defaultValue={trip.budget ?? ''} placeholder="未设"
                      key={`b${trip.updated_at}`}
                      onBlur={(e) => {
                        const v = Number(e.target.value)
                        if (e.target.value !== String(trip.budget ?? '')) call('', 'PATCH', { budget: v > 0 ? v : 0 })
                      }} />
                  </span>
                </div>
                {trip.budget_breakdown && Object.keys(trip.budget_breakdown).length > 0 && (
                  <div className="trip-budget-breakdown">
                    <div className="trip-budget-bd-head">计划预算（按类别）</div>
                    {BUDGET_CAT_ORDER.filter((c) => trip.budget_breakdown![c] > 0).map((c) => (
                      <div key={c} className="trip-budget-bd-row">
                        <span>{c}</span><b>¥{trip.budget_breakdown![c].toFixed(0)}</b>
                      </div>
                    ))}
                    <div className="trip-budget-bd-row trip-budget-bd-total">
                      <span>合计</span>
                      <b>¥{Object.values(trip.budget_breakdown).reduce((a, v) => a + v, 0).toFixed(0)}</b>
                    </div>
                  </div>
                )}
                <div className="trip-budget-row">
                  <span>已记账实际支出</span>
                  <b className={trip.budget && expenses.reduce((a, e) => a + e.amount, 0) > trip.budget ? 'trip-over' : ''}>
                    ¥{expenses.reduce((a, e) => a + e.amount, 0).toFixed(0)}
                  </b>
                </div>
                <div className="trip-budget-row">
                  <span>出发日期</span>
                  <input type="date" className="trip-budget-input wide" defaultValue={trip.start_date} key={`d${trip.updated_at}`}
                    onBlur={(e) => { if (e.target.value !== trip.start_date) call('', 'PATCH', { start_date: e.target.value }) }} />
                </div>
              </div>
              <LedgerPanel
                expenses={expenses}
                members={trip.members.map((m) => m.username)}
                tripId={tripId}
                username={username}
                onChanged={() => { updatedRef.current = ''; load() }}
              />
            </>
          )}

          {/* ---- 助手 tab：检查中心 + Copilot ---- */}
          {aiTab === 'assistant' && (
            <>
          <div className="trip-panel">
            <div className="trip-panel-head">🩺 检查中心 <span className="trip-issue-count">{issues.length}</span></div>
            {issues.length === 0 && <div className="trip-panel-empty">没有发现问题 ✓</div>}
            {issues.map((iss, i) => (
              <button key={i} className={`trip-issue ${iss.level}`} onClick={() => {
                if (iss.action === 'repair_geocode') repairLocations()
                else locate(iss.day, iss.stop_id)
              }}>
                <span>{iss.level === 'warn' ? '⚠' : 'ℹ'} {iss.text}</span>
                {iss.detail && <span className="trip-issue-detail">{iss.detail}</span>}
              </button>
            ))}
          </div>

          <div className="trip-panel">
            <div className="trip-panel-head">🤖 AI Copilot</div>
            <div className="trip-chips">
              {COPILOT_CHIPS.map((c) => (
                <button key={c} className="trip-chip" disabled={aiBusy} onClick={() => sendCopilot(c)}>{c}</button>
              ))}
            </div>
            <div className="trip-copilot-input">
              <input
                placeholder="问问题或下指令，如「Day2 太赶了」"
                value={copilotInput}
                disabled={aiBusy}
                onChange={(e) => setCopilotInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendCopilot(copilotInput)}
              />
              <button className="trip-btn primary" disabled={aiBusy || !copilotInput.trim()} onClick={() => sendCopilot(copilotInput)}>
                发送
              </button>
            </div>
            {suggestions.map((sg) => (
              <div key={sg.id} className={`trip-suggestion ${sg.status}`}>
                <div className="trip-sg-prompt">🙋 {sg.prompt}</div>
                <div className="trip-sg-reply"><ReactMarkdown remarkPlugins={[[remarkGfm, { singleTilde: false }]]}>{prepareMarkdown(sg.reply)}</ReactMarkdown></div>
                {sg.changes.length > 0 && (
                  <div className="trip-sg-changes">
                    {sg.changes.map((ch, i) => (
                      <div key={i} className="trip-sg-change" onClick={() => ch.stop_id && locate(undefined, ch.stop_id)}>
                        <span className={`trip-op ${ch.op}`}>{OP_LABEL[ch.op] || ch.op}</span>
                        <span className="trip-sg-target">{ch.name || nameOf(trip, ch.stop_id)}</span>
                        {ch.reason && <span className="trip-sg-reason">— {ch.reason}</span>}
                      </div>
                    ))}
                  </div>
                )}
                <div className="trip-sg-ops">
                  {sg.status === 'pending' && (
                    <>
                      <button className="trip-btn primary" onClick={() => call(`/suggestions/${sg.id}/apply`, 'POST')}>采纳</button>
                      <button className="trip-btn" onClick={() => call(`/suggestions/${sg.id}/reject`, 'POST')}>拒绝</button>
                    </>
                  )}
                  {sg.status === 'applied' && (
                    <>
                      <span className="trip-sg-state ok">已采纳</span>
                      <button className="trip-btn" onClick={() => call(`/suggestions/${sg.id}/revert`, 'POST')}>恢复原样</button>
                    </>
                  )}
                  {sg.status === 'rejected' && <span className="trip-sg-state">已拒绝</span>}
                  {sg.status === 'reverted' && <span className="trip-sg-state">已恢复</span>}
                </div>
              </div>
            ))}
          </div>
            </>
          )}

          {/* ---- 动态 tab：修改记录 ---- */}
          {aiTab === 'log' && (
            <div className="trip-panel">
              <div className="trip-panel-head">🕘 修改记录</div>
              {events.map((e, i) => (
                <div key={i} className="trip-event">
                  <b>{e.username}</b> {e.action}
                  <span className="trip-event-time">{e.created_at.slice(5, 16).replace('T', ' ')}</span>
                </div>
              ))}
              {events.length === 0 && <div className="trip-panel-empty">还没有记录</div>}
            </div>
          )}
        </div>
      </div>

      {/* PRD 4.5 情境化悬浮按钮：不重复实现新增逻辑，只把当前面板的输入框聚焦过去，
          这样各面板的校验/提示仍然只有一处。找不到输入框（如动态、助手）就不显示。 */}
      {fabLabel && (
        <button className="trip-fab" onClick={() => {
          const scope = document.querySelector(
            workspaceView === 'day' ? '.trip-col-timeline' : '.trip-col-ai',
          )
          const input = scope?.querySelector<HTMLInputElement>(
            '.trip-module-add input, .trip-add-stop input, .trip-expense-form input',
          )
          input?.scrollIntoView({ block: 'center', behavior: 'smooth' })
          input?.focus()
        }}>{fabLabel}</button>
      )}

      {editing && (
        <EditStopModal
          stop={editing}
          onClose={() => setEditing(null)}
          onSave={async (patch) => {
            await call(`/stops/${editing.id}`, 'PATCH', patch)
            setEditing(null)
          }}
        />
      )}
      {sourceGuideOpen && (
        <SourceGuideDrawer
          tripId={tripId}
          tripTitle={trip.title}
          onClose={() => setSourceGuideOpen(false)}
          onOpenConversation={onOpenConversation}
        />
      )}
    </div>
  )
}

function ShareButton({
  tripId, tripTitle, destination, username,
}: { tripId: string; tripTitle: string; destination: string; username: string }) {
  const [open, setOpen] = useState(false)
  const [shortCode, setShortCode] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const { notify } = useToast()

  const ensure = async (reset = false) => {
    const res = await authFetch(`${API}/trips/${tripId}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reset }),
    })
    if (res.ok) {
      setShortCode((await res.json()).short_code)
    } else {
      notify('分享链接生成失败', 'error')
    }
  }

  // 短链：/t/{8位码}，经 nginx 302 到完整 join 链接（Phase 42.1）
  const link = shortCode ? `${window.location.origin}/t/${shortCode}` : ''
  // 一句话 + 短链（用户拍板的形态），目的地优先、标题兜底
  const what = destination ? `${destination}之行` : `《${tripTitle}》`
  const shareText = `${username} 邀请你一起规划${what}，点开加入 👉 ${link}`

  return (
    <>
      <button className="trip-btn" onClick={() => { setOpen(true); ensure() }}>🔗 分享</button>
      {open && createPortal(
        <div className="modal-mask share-mask" onClick={() => setOpen(false)}>
          <div className="modal trip-share-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>🔗 分享协同行程</strong>
              <button className="modal-close" onClick={() => setOpen(false)}>✕</button>
            </div>
            <div className="trip-share-tip">
              把链接发到微信，对方点开注册后<b>自动加入</b>这个规划板一起编辑。
              拿到链接的人都能加入，介意的话随时可以重置或关闭。
            </div>
            {shortCode && <div className="trip-share-link">{link}</div>}
            <div className="trip-edit-ops">
              <button className="trip-btn" onClick={() => {
                if (window.confirm('重置后旧链接会立即失效，继续吗？')) ensure(true)
              }}>♻️ 重置链接</button>
              <button className="trip-btn danger" onClick={async () => {
                if (!window.confirm('关闭后，当前分享链接将无法再加入行程。继续吗？')) return
                const res = await authFetch(`${API}/trips/${tripId}/share`, { method: 'DELETE' })
                if (res.ok) {
                  setShortCode(null)
                  setOpen(false)
                  notify('分享已关闭', 'success')
                } else {
                  notify('关闭分享失败', 'error')
                }
              }}>关闭分享</button>
              <button className="trip-btn primary" disabled={!shortCode} onClick={async () => {
                if (await copyText(shareText)) {
                  setCopied(true)
                  notify('微信邀请文案已复制', 'success')
                  window.setTimeout(() => setCopied(false), 2000)
                } else {
                  notify('复制失败，请手动选择链接', 'error')
                }
              }}>
                {copied ? '已复制 ✓' : '📋 复制微信文案'}
              </button>
            </div>
            {shortCode && <div className="trip-share-preview">{shareText}</div>}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

const EXPENSE_CATS = ['餐饮', '交通', '门票', '住宿', '购物', '其他']

interface Hotel { name: string; rating: string; address: string; location: string }

function HotelPanel({
  tripId, city, addedNames, onCityChange, onAdd, onCtripPrice,
}: {
  tripId: string
  city: string  // Phase 48：受控——父组件按天订房时切城市
  addedNames: Set<string>  // 当前选中天已加入的住宿名（父组件从真实 stops 派生，增删自愈）
  onCityChange: (city: string) => void
  onAdd: (name: string, location: string) => void
  onCtripPrice?: (city: string) => void
}) {
  const [hotels, setHotels] = useState<Hotel[] | null>(null)
  const [loading, setLoading] = useState(false)

  const search = useCallback(async (target: string) => {
    const q = target.trim()
    if (!q) return
    setLoading(true)
    setHotels(null)
    try {
      const res = await authFetch(`${API}/trips/${tripId}/hotels?city=${encodeURIComponent(q)}`)
      if (res.ok) setHotels((await res.json()).hotels)
      else setHotels([])
    } catch {
      setHotels([])
    } finally {
      setLoading(false)
    }
  }, [tripId])

  // 受控 city 变化即自动搜（父组件点某天「查酒店」会切 city）
  useEffect(() => {
    if (city) search(city)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [city])

  return (
    <div className="trip-panel">
      <div className="trip-panel-head">🏨 酒店推荐 <span className="trip-day-km">高德实时 POI</span></div>
      <div className="trip-hotel-search">
        <input
          value={city}
          placeholder="城市，如 拉萨 / 成都"
          onChange={(e) => onCityChange(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search(city)}
        />
        <button className="trip-btn primary" onClick={() => search(city)} disabled={loading}>
          {loading ? '查询中…' : '查酒店'}
        </button>
      </div>
      {loading && <div className="trip-panel-empty">正在查「{city}」的酒店…</div>}
      {hotels !== null && hotels.length === 0 && !loading && (
        <div className="trip-panel-empty">没查到「{city}」的酒店，换个城市名试试</div>
      )}
      {hotels && hotels.length > 0 && (
        <>
          <div className="trip-hotel-list">
            {hotels.map((h) => (
              <div key={h.name} className="trip-hotel">
                <div className="trip-hotel-main">
                  <span className="trip-hotel-name">{h.name}</span>
                  {h.rating && <span className="trip-hotel-rating">⭐{h.rating}</span>}
                </div>
                {h.address && <div className="trip-hotel-addr">{h.address}</div>}
                <button
                  className="trip-btn"
                  disabled={addedNames.has(h.name)}
                  onClick={() => onAdd(h.name, h.location)}
                >
                  {addedNames.has(h.name) ? '已加入 ✓' : '＋ 加入行程'}
                </button>
              </div>
            ))}
          </div>
          <div className="trip-hotel-tip">高德 POI 无实时价格/房态</div>
        </>
      )}
      {onCtripPrice && (
        <button className="trip-ctrip-btn" onClick={() => onCtripPrice(city)}>
          <span className="trip-ctrip-title">💰 去对话核实携程实价</span>
          <span className="trip-ctrip-sub">另开对话，不回板</span>
        </button>
      )}
    </div>
  )
}

function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface ExpenseDraft {
  id?: string
  amount: string
  title: string
  category: string
  payer: string
  spent_at: string
  parts: string[]   // 空 = 全员平摊
}

/** 记账弹窗（新增 / 修改共用一个表单）。 */
function ExpenseModal({
  draft, members, onClose, onSubmit,
}: {
  draft: ExpenseDraft
  members: string[]
  onClose: () => void
  onSubmit: (d: ExpenseDraft) => Promise<boolean>
}) {
  const [d, setD] = useState<ExpenseDraft>(draft)
  const [busy, setBusy] = useState(false)
  const set = (patch: Partial<ExpenseDraft>) => setD((cur) => ({ ...cur, ...patch }))
  const valid = Number(d.amount) > 0 && d.title.trim().length > 0

  return createPortal(
    <div className="modal-mask" onClick={onClose}>
      <div className="modal trip-expense-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>{d.id ? '修改账目' : '记一笔'}</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="trip-expense-form">
          <label>
            <span>谁付的</span>
            <select value={d.payer} onChange={(e) => set({ payer: e.target.value })}>
              {members.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label>
            <span>类别</span>
            <select value={d.category} onChange={(e) => set({ category: e.target.value })}>
              {EXPENSE_CATS.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>
            <span>事项</span>
            <input placeholder="花在哪了，如 晚餐" value={d.title}
              onChange={(e) => set({ title: e.target.value })} />
          </label>
          <label>
            <span>金额</span>
            <input type="number" min="0" step="0.01" placeholder="0.00" value={d.amount}
              onChange={(e) => set({ amount: e.target.value })} />
          </label>
          <label>
            <span>日期</span>
            {/* 花费日期与记账时间分开：补记昨天的账很常见 */}
            <input type="date" value={d.spent_at} onChange={(e) => set({ spent_at: e.target.value })} />
          </label>
          <div className="trip-expense-parts">
            <span>分摊</span>
            <div>
              {members.map((m) => {
                const on = d.parts.length === 0 || d.parts.includes(m)
                return (
                  <button key={m} className={`trip-chip${on ? ' on' : ''}`} onClick={() => {
                    const base = d.parts.length === 0 ? [...members] : [...d.parts]
                    const next = base.includes(m) ? base.filter((x) => x !== m) : [...base, m]
                    set({ parts: next.length === members.length ? [] : next })
                  }}>{m}</button>
                )
              })}
              <small>{d.parts.length === 0 ? '全员平摊' : `${d.parts.length} 人分摊`}</small>
            </div>
          </div>
        </div>
        <div className="trip-expense-modal-foot">
          <button className="trip-btn" onClick={onClose}>取消</button>
          <button className="trip-btn primary" disabled={!valid || busy} onClick={async () => {
            setBusy(true)
            const ok = await onSubmit(d)
            setBusy(false)
            if (ok) onClose()
          }}>{busy ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function LedgerPanel({
  expenses, members, tripId, username, onChanged,
}: {
  expenses: Expense[]; members: string[]; tripId: string; username: string; onChanged: () => void
}) {
  const [summary, setSummary] = useState<ExpenseSummary | null>(null)
  const [perPerson, setPerPerson] = useState<ExpenseSummary['per_person']>([])
  const [editing, setEditing] = useState<ExpenseDraft | null>(null)
  const [copied, setCopied] = useState(false)
  const [filter, setFilter] = useState('全部')
  const { notify } = useToast()

  // 每人总支出常驻展示（不用点「一键结算」才看得到）
  const loadPerPerson = useCallback(async () => {
    const r = await authFetch(`${API}/trips/${tripId}/expenses/summary`)
    if (r.ok) setPerPerson((await r.json()).per_person || [])
  }, [tripId])
  useEffect(() => { loadPerPerson() }, [loadPerPerson, expenses.length])

  const submit = async (d: ExpenseDraft): Promise<boolean> => {
    const body = {
      amount: Number(d.amount), title: d.title.trim(), category: d.category,
      payer: d.payer, spent_at: d.spent_at,
      participant_usernames: d.parts.length ? d.parts : [],
    }
    const r = await authFetch(
      `${API}/trips/${tripId}/expenses${d.id ? `/${d.id}` : ''}`,
      { method: d.id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
    )
    if (!r.ok) { notify('保存失败，请检查金额和分摊成员', 'error'); return false }
    onChanged()
    loadPerPerson()
    notify(d.id ? '账目已更新' : '账目已添加', 'success')
    return true
  }

  const remove = async (e: Expense) => {
    if (!window.confirm(`删除「${e.title}」？`)) return
    const r = await authFetch(`${API}/trips/${tripId}/expenses/${e.id}`, { method: 'DELETE' })
    if (r.ok) { onChanged(); loadPerPerson() } else notify('删除失败，请重试', 'error')
  }

  const settle = async () => {
    const res = await authFetch(`${API}/trips/${tripId}/expenses/summary`)
    if (res.ok) setSummary(await res.json())
  }

  const cats = ['全部', ...EXPENSE_CATS.filter((c) => expenses.some((e) => e.category === c))]
  const shown = filter === '全部' ? expenses : expenses.filter((e) => e.category === filter)
  const total = expenses.reduce((a, e) => a + e.amount, 0)

  return (
    <div className="trip-panel trip-module">
      <div className="trip-panel-head">🧾 记账本 <span className="trip-day-km">{expenses.length} 笔 · 共 ¥{total.toFixed(0)}</span></div>

      {/* 每人总支出：常驻，一眼看到谁垫得多 */}
      {perPerson.length > 0 && (
        <div className="trip-ledger-people">
          {perPerson.map((p) => (
            <div key={p.username} className="trip-ledger-person">
              <b>{p.username}{p.username === username ? '（我）' : ''}</b>
              <span>垫付 ¥{p.paid.toFixed(0)}</span>
              <small className={p.balance >= 0 ? 'pos' : 'neg'}>
                {p.balance >= 0 ? '应收' : '应付'} ¥{Math.abs(p.balance).toFixed(0)}
              </small>
            </div>
          ))}
        </div>
      )}

      <div className="trip-module-toolbar">
        <button className="trip-btn primary" onClick={() => setEditing({
          amount: '', title: '', category: '餐饮', payer: username,
          spent_at: todayStr(), parts: [],
        })}>+ 记一笔</button>
        {expenses.length > 0 && <button className="trip-btn" onClick={settle}>💰 一键结算</button>}
      </div>

      {cats.length > 1 && (
        <div className="trip-module-filters">
          {cats.map((c) => (
            <button key={c} className={filter === c ? 'active' : ''} onClick={() => setFilter(c)}>{c}</button>
          ))}
        </div>
      )}

      {shown.length === 0 && <p className="trip-module-empty">还没有账目，点「记一笔」开始。</p>}
      <ul className="trip-module-list trip-ledger-list">
        {shown.map((e) => (
          <li key={e.id}>
            <span className="trip-module-main">
              <b>{e.title}</b>
              <small>
                {e.payer} 付 · {e.category}
                {e.spent_at ? ` · ${e.spent_at}` : ''}
              </small>
            </span>
            <b className="trip-ledger-amount-cell">¥{e.amount.toFixed(2)}</b>
            {/* 任何成员都能改删：记错的账往往是别人先发现的 */}
            <button className="trip-btn tiny" onClick={() => setEditing({
              id: e.id, amount: String(e.amount), title: e.title, category: e.category,
              payer: e.payer, spent_at: e.spent_at || '', parts: [],
            })}>修改</button>
            <button className="trip-module-del" onClick={() => remove(e)} aria-label="删除">×</button>
          </li>
        ))}
      </ul>

      {editing && (
        <ExpenseModal draft={editing} members={members}
          onClose={() => setEditing(null)} onSubmit={submit} />
      )}

      {summary && (
        <div className="modal-mask" onClick={() => setSummary(null)}>
          <div className="modal trip-settle-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>💰 结算 · 共 {summary.count} 笔 ¥{summary.total.toFixed(2)}</strong>
              <button className="modal-close" onClick={() => setSummary(null)}>✕</button>
            </div>
            <table className="trip-settle-table">
              <thead><tr><th>成员</th><th>垫付</th><th>应摊</th><th>结果</th></tr></thead>
              <tbody>
                {summary.per_person.map((p) => (
                  <tr key={p.username}>
                    <td>{p.username}</td>
                    <td>¥{p.paid.toFixed(2)}</td>
                    <td>¥{p.share.toFixed(2)}</td>
                    <td className={p.balance >= 0 ? 'pos' : 'neg'}>
                      {p.balance >= 0 ? '应收' : '应付'} ¥{Math.abs(p.balance).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="trip-settle-transfers">
              {summary.transfers.length === 0 && <div className="trip-panel-empty">已两清，无需转账 🎉</div>}
              {summary.transfers.map((t, i) => (
                <div key={i} className="trip-transfer">💸 <b>{t.from}</b> → <b>{t.to}</b>　¥{t.amount.toFixed(2)}</div>
              ))}
            </div>
            <button className="trip-btn primary" onClick={async () => {
              if (await copyText(summary.text)) {
                setCopied(true)
                notify('结算账单已复制', 'success')
                window.setTimeout(() => setCopied(false), 2000)
              } else {
                notify('复制失败，请手动选择账单文字', 'error')
              }
            }}>
              {copied ? '已复制 ✓' : '📋 复制文字账单'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function nameOf(trip: TripDetail, stopId: string): string {
  return trip.stops.find((s) => s.id === stopId)?.name || '（条目）'
}

function CommentThread({
  comments, onAdd, onDelete,
}: { comments: TripComment[]; onAdd: (text: string) => void; onDelete: (id: string) => void }) {
  const [text, setText] = useState('')
  return (
    <div className="trip-comments" onClick={(e) => e.stopPropagation()}>
      {comments.map((c) => (
        <div key={c.id} className="trip-comment">
          <b>{c.username}</b>：{c.content}
          {c.mine && <button className="trip-comment-del" onClick={() => onDelete(c.id)}>✕</button>}
        </div>
      ))}
      <input
        placeholder="写评论，回车发送"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && text.trim()) {
            onAdd(text.trim())
            setText('')
          }
        }}
      />
    </div>
  )
}

function EditStopModal({
  stop, onClose, onSave,
}: { stop: TripStop; onClose: () => void; onSave: (patch: Record<string, unknown>) => void }) {
  const [name, setName] = useState(stop.name)
  const [time, setTime] = useState(stop.start_time)
  const [stay, setStay] = useState(stop.stay_min ? String(stop.stay_min) : '')
  const [transport, setTransport] = useState(stop.transport)
  const [ticket, setTicket] = useState(stop.ticket_price ? String(stop.ticket_price) : '')
  const [tags, setTags] = useState(stop.tags.join(','))
  const [note, setNote] = useState(stop.note)
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal trip-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>编辑地点</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="trip-edit-grid">
          <label>名称<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label>到达时间<input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
          <label>停留(分钟)<input type="number" min="0" value={stay} onChange={(e) => setStay(e.target.value)} /></label>
          <label>交通方式
            <select value={transport} onChange={(e) => setTransport(e.target.value)}>
              {TRANSPORTS.map((t) => <option key={t} value={t}>{t || '未填'}</option>)}
            </select>
          </label>
          <label>门票(元)<input type="number" min="0" value={ticket} onChange={(e) => setTicket(e.target.value)} /></label>
          <label>标签(逗号分隔)<input value={tags} placeholder="美食,拍照" onChange={(e) => setTags(e.target.value)} /></label>
          <label className="trip-edit-full">备注<textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        </div>
        <div className="trip-edit-ops">
          <button className="trip-btn" onClick={onClose}>取消</button>
          <button className="trip-btn primary" onClick={() => onSave({
            name: name.trim() || undefined,
            start_time: time,
            stay_min: stay === '' ? 0 : Math.max(0, Number(stay) || 0),
            transport,
            ticket_price: ticket === '' ? 0 : Math.max(0, Number(ticket) || 0),
            tags: tags.split(/[,，]/).map((t) => t.trim()).filter(Boolean),
            note,
          })}>
            保存
          </button>
        </div>
      </div>
    </div>
  )
}

function AddStop({ onAdd }: { onAdd: (name: string) => void }) {
  const [name, setName] = useState('')
  return (
    <div className="trip-add-stop">
      <input
        placeholder="+ 添加地点"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && name.trim()) {
            onAdd(name.trim())
            setName('')
          }
        }}
      />
    </div>
  )
}


/* ==========================================================================
 * Phase 87 — PRD 模块 2/5/6/7：美食 / 任务分工 / 行李 / 避坑
 * 四个面板共用一套轻量增删改模式：进入标签时拉一次，写操作后就地刷新。
 * 不接入 2.5s 主轮询——这些数据变更频率远低于行程条目，跟着主轮询拉是浪费。
 * ========================================================================== */

/** 面板通用：加载 + 错误提示 + 空态。抽出来避免四个面板各写一遍。 */
function useModuleData<T>(tripId: string, path: string, active: boolean, initial: T) {
  const [data, setData] = useState<T>(initial)
  const [loading, setLoading] = useState(false)
  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const r = await authFetch(`${API}/trips/${tripId}/${path}`)
      if (r.ok) setData(await r.json())
    } finally {
      setLoading(false)
    }
  }, [tripId, path])
  useEffect(() => {
    if (active) reload()
  }, [active, reload])
  return { data, loading, reload }
}

interface FoodItem {
  id: string; name: string; category: string; city: string
  price: number | null; note: string; is_top: boolean; created_by: string
}

const FOOD_CATS = ['小吃', '正餐', '甜点', '饮品', '其他']

function FoodPanel({ tripId, active }: { tripId: string; active: boolean }) {
  const { data, reload } = useModuleData<FoodItem[]>(tripId, 'foods', active, [])
  const [name, setName] = useState('')
  const [cat, setCat] = useState('正餐')
  const [filter, setFilter] = useState('全部')
  const { notify } = useToast()

  const add = async () => {
    if (!name.trim()) return
    const r = await authFetch(`${API}/trips/${tripId}/foods`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), category: cat }),
    })
    if (r.ok) { setName(''); reload() } else notify('添加失败，请重试')
  }
  const toggleTop = async (f: FoodItem) => {
    const r = await authFetch(`${API}/trips/${tripId}/foods/${f.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...f, is_top: !f.is_top }),
    })
    if (r.ok) reload()
  }
  const remove = async (id: string) => {
    const r = await authFetch(`${API}/trips/${tripId}/foods/${id}`, { method: 'DELETE' })
    if (r.ok) reload()
  }

  const cats = ['全部', ...FOOD_CATS.filter((c) => data.some((f) => f.category === c))]
  const shown = filter === '全部' ? data : data.filter((f) => f.category === filter)

  return (
    <div className="trip-panel trip-module">
      <div className="trip-panel-head">🍜 美食清单 <span className="trip-day-km">TOP 会置顶</span></div>
      {cats.length > 1 && (
        <div className="trip-module-filters">
          {cats.map((c) => (
            <button key={c} className={filter === c ? 'active' : ''} onClick={() => setFilter(c)}>{c}</button>
          ))}
        </div>
      )}
      {shown.length === 0 && <p className="trip-module-empty">还没记录，先加一家想吃的。</p>}
      <ul className="trip-module-list">
        {shown.map((f) => (
          <li key={f.id} className={f.is_top ? 'top' : ''}>
            <button className="trip-module-star" title={f.is_top ? '取消 TOP' : '设为 TOP'}
              onClick={() => toggleTop(f)}>{f.is_top ? '★' : '☆'}</button>
            <span className="trip-module-main">
              <b>{f.name}</b>
              <small>{f.category}{f.price ? ` · 人均 ¥${f.price}` : ''}{f.note ? ` · ${f.note}` : ''}</small>
            </span>
            <button className="trip-module-del" onClick={() => remove(f.id)} aria-label="删除">×</button>
          </li>
        ))}
      </ul>
      <div className="trip-module-add">
        <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="类型">
          {FOOD_CATS.map((c) => <option key={c}>{c}</option>)}
        </select>
        <input placeholder="店名或菜名" value={name} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button className="trip-btn primary" onClick={add}>添加</button>
      </div>
    </div>
  )
}

interface PackingData {
  members: string[]
  items: {
    id: string; name: string; category: string
    states: Record<string, string>
    marked_by: Record<string, string>  // 被代勾的格子：成员名 → 是谁代勾的
  }[]
  templates: string[]
}

// 三态循环：未设置 → 已带 → 没带 → 未设置
const PACK_NEXT: Record<string, string> = { na: 'packed', packed: 'unpacked', unpacked: 'na' }
const PACK_GLYPH: Record<string, string> = { packed: '✓', unpacked: '✗', na: '–' }

function PackingPanel({
  tripId, active, username, members, isOwner, onInvite,
}: {
  tripId: string; active: boolean; username: string
  members: { username: string; role: string }[]
  isOwner: boolean
  onInvite: (name: string) => Promise<boolean>
}) {
  const { data, reload } = useModuleData<PackingData>(
    tripId, 'packing', active, { members: [], items: [], templates: [] })
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [cat, setCat] = useState('通用')
  const [manageCats, setManageCats] = useState(false)
  const [managePeople, setManagePeople] = useState(false)
  const [invite, setInvite] = useState('')
  const { notify } = useToast()

  const add = async (text: string, category = '通用') => {
    if (!text.trim()) return
    const r = await authFetch(`${API}/trips/${tripId}/packing`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: text.trim(), category }),
    })
    if (r.ok) { setName(''); setAdding(false); reload() } else notify('添加失败，请重试', 'error')
  }
  const cycle = async (itemId: string, cur: string, member: string) => {
    const r = await authFetch(`${API}/trips/${tripId}/packing/${itemId}/state`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: PACK_NEXT[cur] || 'packed', member }),
    })
    if (r.ok) reload()
  }
  const remove = async (id: string, itemName: string) => {
    if (!window.confirm(`删除「${itemName}」？`)) return
    const r = await authFetch(`${API}/trips/${tripId}/packing/${id}`, { method: 'DELETE' })
    // 失败必须说出来——原来静默失败，用户只看到「点了没反应」
    if (r.ok) reload()
    else notify('删除失败，请重试', 'error')
  }
  const recategorize = async (itemId: string, category: string) => {
    const r = await authFetch(`${API}/trips/${tripId}/packing/${itemId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category }),
    })
    if (r.ok) reload()
  }

  const cats = Array.from(new Set(data.items.map((i) => i.category || '通用')))
  const grouped = cats.map((c) => ({ cat: c, items: data.items.filter((i) => (i.category || '通用') === c) }))
  const unused = data.templates.filter((t) => !data.items.some((i) => i.name === t))

  const renderRows = (items: PackingData['items']) => items.map((it) => (
    <tr key={it.id}>
      <td className="trip-packing-name">{it.name}</td>
      {data.members.map((m) => {
        const st = it.states[m] || 'na'
        const mine = m === username
        const by = it.marked_by?.[m]
        return (
          <td key={m}>
            <button className={`trip-pack-cell ${st}${mine ? ' mine' : ''}${by ? ' proxied' : ''}`}
              title={`${mine ? '我' : m}：点击切换 已带 / 没带 / 未设置${by ? `（由 ${by} 代勾）` : ''}`}
              onClick={() => cycle(it.id, st, mine ? '' : m)}>
              {PACK_GLYPH[st]}
              {by && <i className="trip-pack-proxy" aria-hidden="true">{by[0]?.toUpperCase()}</i>}
            </button>
          </td>
        )
      })}
      <td className="trip-packing-ops">
        <button className="trip-module-del" onClick={() => remove(it.id, it.name)} aria-label="删除">×</button>
      </td>
    </tr>
  ))

  return (
    <div className="trip-panel trip-module">
      <div className="trip-panel-head">🧳 行李清单 <span className="trip-day-km">可以替同伴勾，会记下是谁勾的</span></div>

      <div className="trip-module-toolbar">
        <button className="trip-btn primary" onClick={() => setAdding(true)}>+ 添加物品</button>
        <button className="trip-btn" onClick={() => setManageCats(true)} disabled={data.items.length === 0}>
          🏷 管理分类
        </button>
        <button className="trip-btn" onClick={() => setManagePeople(true)}>👥 人员管理</button>
      </div>

      {adding && (
        <div className="trip-module-add">
          <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="分类">
            {Array.from(new Set(['通用', ...cats])).map((c) => <option key={c}>{c}</option>)}
          </select>
          <input autoFocus placeholder="物品名" value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add(name, cat)} />
          <button className="trip-btn primary" onClick={() => add(name, cat)}>确定</button>
          <button className="trip-btn" onClick={() => { setAdding(false); setName('') }}>取消</button>
        </div>
      )}

      {data.items.length === 0 && <p className="trip-module-empty">还没有物品，用下面的常见清单或「添加物品」加起。</p>}

      {/* 按分类分组展示：物品一多，一张平表根本找不到东西 */}
      {grouped.map((g) => (
        <div key={g.cat} className="trip-packing-group">
          <div className="trip-packing-group-head">{g.cat} <small>{g.items.length}</small></div>
          <div className="trip-packing-scroll">
            <table className="trip-packing-table">
              <thead>
                <tr>
                  <th>物品</th>
                  {data.members.map((m) => (
                    <th key={m} className={m === username ? 'me' : ''}>{m === username ? '我' : m}</th>
                  ))}
                  <th aria-label="操作" />
                </tr>
              </thead>
              <tbody>{renderRows(g.items)}</tbody>
            </table>
          </div>
        </div>
      ))}

      {unused.length > 0 && (
        <div className="trip-module-templates">
          <small>常见物品：</small>
          {unused.map((t) => (
            <button key={t} className="trip-btn tiny ghost" onClick={() => add(t)}>+ {t}</button>
          ))}
        </div>
      )}

      {manageCats && createPortal(
        <div className="modal-mask" onClick={() => setManageCats(false)}>
          <div className="modal trip-manage-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>🏷 管理分类</strong>
              <button className="modal-close" onClick={() => setManageCats(false)}>✕</button>
            </div>
            <p className="trip-module-empty">给每件物品选一个分类，清单会按分类分组显示。</p>
            <ul className="trip-module-list">
              {data.items.map((it) => (
                <li key={it.id}>
                  <span className="trip-module-main"><b>{it.name}</b></span>
                  <input className="trip-cat-input" defaultValue={it.category || '通用'}
                    aria-label={`${it.name} 的分类`}
                    onBlur={(e) => {
                      const v = e.target.value.trim()
                      if (v && v !== (it.category || '通用')) recategorize(it.id, v)
                    }} />
                </li>
              ))}
            </ul>
          </div>
        </div>, document.body)}

      {managePeople && createPortal(
        <div className="modal-mask" onClick={() => setManagePeople(false)}>
          <div className="modal trip-manage-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>👥 人员管理</strong>
              <button className="modal-close" onClick={() => setManagePeople(false)}>✕</button>
            </div>
            <p className="trip-module-empty">
              行李清单的列 = 行程成员。人员是行程级数据，在这里加人对所有模块都生效。
            </p>
            <ul className="trip-module-list">
              {members.map((m) => (
                <li key={m.username}>
                  <span className="trip-module-main">
                    <b>{m.username}{m.username === username ? '（我）' : ''}</b>
                    <small>{m.role === 'owner' ? '创建者' : '协作者'}</small>
                  </span>
                </li>
              ))}
            </ul>
            {isOwner ? (
              <div className="trip-module-add">
                <input placeholder="输入用户名邀请" value={invite}
                  onChange={(e) => setInvite(e.target.value)} />
                <button className="trip-btn primary" onClick={async () => {
                  if (!invite.trim()) return
                  if (await onInvite(invite.trim())) { setInvite(''); notify('已发出邀请', 'success') }
                  else notify('邀请失败，请检查用户名', 'error')
                }}>邀请</button>
              </div>
            ) : (
              <p className="trip-module-empty">只有行程创建者能邀请新成员。</p>
            )}
          </div>
        </div>, document.body)}
    </div>
  )
}

interface TipItem { id: string; content: string; level: string; created_by: string }

function TipsPanel({ tripId, active }: { tripId: string; active: boolean }) {
  const { data, reload } = useModuleData<TipItem[]>(tripId, 'tips', active, [])
  const [content, setContent] = useState('')
  const [level, setLevel] = useState('notice')
  const { notify } = useToast()

  const add = async () => {
    if (!content.trim()) return
    const r = await authFetch(`${API}/trips/${tripId}/tips`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: content.trim(), level }),
    })
    if (r.ok) { setContent(''); reload() } else notify('添加失败，请重试')
  }
  const remove = async (id: string) => {
    const r = await authFetch(`${API}/trips/${tripId}/tips/${id}`, { method: 'DELETE' })
    if (r.ok) reload()
  }

  return (
    <div className="trip-panel trip-module">
      <div className="trip-panel-head">⚠️ 避坑提醒 <span className="trip-day-km">重要的会排在前面</span></div>
      {data.length === 0 && <p className="trip-module-empty">还没有提醒。踩过的坑记下来，同行的人就不用再踩。</p>}
      <ul className="trip-module-list trip-tip-list">
        {data.map((t) => (
          <li key={t.id} className={`level-${t.level}`}>
            <span className="trip-tip-badge">{t.level === 'important' ? '重要' : '提醒'}</span>
            <span className="trip-module-main"><b>{t.content}</b>{t.created_by && <small>{t.created_by}</small>}</span>
            <button className="trip-module-del" onClick={() => remove(t.id)} aria-label="删除">×</button>
          </li>
        ))}
      </ul>
      <div className="trip-module-add">
        <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="级别">
          <option value="notice">提醒</option>
          <option value="important">重要</option>
        </select>
        <input placeholder="如「清明上河园周一闭园」" value={content}
          onChange={(e) => setContent(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button className="trip-btn primary" onClick={add}>添加</button>
      </div>
    </div>
  )
}

