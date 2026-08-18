/** 协同行程规划板（Phase 35-63）：三栏 = Timeline | 每日地图 | AI Copilot。
 * 协同 = 2.5s 轮询（顺带上报 presence）+ 行程群聊；AI 一律提案制（Preview→采纳/拒绝/恢复）。 */
import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import html2canvas from 'html2canvas'
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
  day_titles?: Record<string, string>
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
  packing: '',
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

function tripDayDateFromTitle(title: string, day: number): string {
  const match = title.match(/(\d{1,2})[./月](\d{1,2})(?:日)?\s*[—–-]\s*(\d{1,2})[./月](\d{1,2})/)
  if (!match) return ''
  const startMonth = Number(match[1])
  const startDay = Number(match[2])
  if (!startMonth || !startDay) return ''
  const date = new Date(2024, startMonth - 1, startDay)
  if (Number.isNaN(date.getTime())) return ''
  date.setDate(date.getDate() + day - 1)
  return `${date.getMonth() + 1}.${date.getDate()}`
}

function displayTripDayDate(trip: TripDetail, day: number): string {
  return tripDayDate(trip.start_date, day) || tripDayDateFromTitle(trip.title, day)
}

export default function TripsOverlay({
  username, layoutMode = 'desktop', initialBoardId = null, openChatSignal = 0, onChatRead,
  onBoardChange, onClose, onOpenConversation, onAskInChat,
}: {
  username: string
  layoutMode?: 'desktop' | 'mobile'
  initialBoardId?: string | null
  /** 自增序号：变化即请求展开群聊抽屉（从主页群聊通知点进来时用） */
  openChatSignal?: number
  /** 群聊已读上报后回调，让主页铃铛立刻掉未读 */
  onChatRead?: () => void
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
      if (event.key !== 'Escape') return
      if (document.querySelector('.trip-chat-panel, .trip-source-panel')) return
      if (document.querySelector('.modal-mask, .trip-actions-menu[open]')) return
      // 行程页是一个工作台，Esc 只交给当前打开的小弹窗/抽屉处理，避免误退出整页。
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
        <TripBoard
          tripId={boardId}
          username={username}
          onBack={() => setBoardId(null)}
          onOpenConversation={onOpenConversation}
          onAskInChat={onAskInChat}
          openChatSignal={openChatSignal}
          onChatRead={onChatRead}
        />
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
  openSignal = 0,
  onRead,
}: {
  tripId: string
  tripTitle: string
  members: TripMember[]
  /** 自增序号：变化即展开抽屉（从主页群聊通知点进来） */
  openSignal?: number
  /** 已读上报后回调，让主页铃铛立刻掉未读，而不用等下一轮 30s 轮询 */
  onRead?: () => void
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

  const openChat = useCallback(() => {
    openRef.current = true
    setOpen(true)
    setUnread(0)
    nearBottomRef.current = true
    loadChat()
    // Phase 97：把主页铃铛上那条群聊通知置为已读。失败静默——已读上报不该打扰用户，
    // 下次打开会再试一次。
    authFetch(`${API}/trips/${tripId}/chat/read`, { method: 'POST' })
      .then(() => onRead?.())
      .catch(() => {})
  }, [loadChat, onRead, tripId])

  // 从主页群聊通知点进来：序号一变就展开抽屉（初始 0 不触发）
  useEffect(() => {
    if (openSignal > 0) openChat()
  }, [openSignal, openChat])

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
  tripId, username, onBack, onOpenConversation, onAskInChat, openChatSignal = 0, onChatRead,
}: {
  tripId: string
  username: string
  onBack: () => void
  onOpenConversation?: (cid: string) => void
  onAskInChat?: (text: string) => void
  openChatSignal?: number
  onChatRead?: () => void
}) {
  const [trip, setTrip] = useState<TripDetail | null>(null)
  const [issues, setIssues] = useState<TripIssue[]>([])
  const [ticketTotal, setTicketTotal] = useState(0)
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [comments, setComments] = useState<TripComment[]>([])
  const [events, setEvents] = useState<{ username: string; action: string; created_at: string }[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [invite, setInvite] = useState('')
  const [msg, setMsg] = useState('')
  const [copilotInput, setCopilotInput] = useState('')
  const [retrying, setRetrying] = useState(false)
  const [selectedDay, setSelectedDay] = useState(1)
  const [flashId, setFlashId] = useState<string | null>(null)
  const [editing, setEditing] = useState<TripStop | null>(null)
  const [addingStopDay, setAddingStopDay] = useState<number | null>(null)
  const [dragOverStopId, setDragOverStopId] = useState<string | null>(null)
  const [editingDayTitle, setEditingDayTitle] = useState<number | null>(null)
  const [dayTitleInput, setDayTitleInput] = useState('')
  const [openComments] = useState<string | null>(null)
  const [mapFailed, setMapFailed] = useState(false)  // JS 地图挂了回退静态图
  const [focusStop, setFocusStop] = useState<string | null>(null)
  const [repairingLocations, setRepairingLocations] = useState(false)
  const [optimizingRoute, setOptimizingRoute] = useState(false)
  const [sourceGuideOpen, setSourceGuideOpen] = useState(false)
  const [mobilePane, setMobilePane] = useState<'timeline' | 'map' | 'assistant'>('timeline')
  const [workspaceView, setWorkspaceView] = useState<'day' | 'tool'>('day')
  const [mapCollapsed, setMapCollapsed] = useState(false)
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
  dayRef.current = selectedDay

  const load = useCallback(async () => {
    const res = await authFetch(`${API}/trips/${tripId}?editing_day=${dayRef.current}`)
    if (!res.ok) {
      // 404 = 行程不存在（可能已被删除），跳转回首页
      if (res.status === 404) {
        notify('行程不存在或已被删除')
        window.location.href = '/travel/'
      }
      return
    }
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

  const saveDayTitle = async (day: number, title: string) => {
    if (!trip) return
    const newTitles = { ...(trip.day_titles || {}), [day]: title.trim() }
    const res = await authFetch(`${API}/trips/${tripId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ day_titles: newTitles })
    })
    if (res.ok) {
      setTrip({ ...trip, day_titles: newTitles })
      setEditingDayTitle(null)
      notify('标题已更新')
    } else {
      notify('更新失败，请重试')
    }
  }

  const getDayTitle = (day: number) => {
    return trip?.day_titles?.[day] || trip?.destination || trip?.title || ''
  }

  const formatDayTitle = (day: number) => {
    const title = getDayTitle(day).trim()
    if (!title) return `Day ${day}`
    return /^Day\s*\d{1,2}\b/i.test(title) ? title : `Day ${day} · ${title}`
  }

  const changeDays = async (newDays: number) => {
    if (!trip || newDays < 1 || newDays > 30) return
    const res = await authFetch(`${API}/trips/${tripId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: newDays })
    })
    if (res.ok) {
      await load()
      if (selectedDay > newDays) {
        setSelectedDay(newDays)
      }
      notify(`行程已调整为 ${newDays} 天`)
    } else {
      notify('调整失败，请重试')
    }
  }

  const exportToImage = async () => {
    if (!trip) return
    notify('正在生成长图，请稍候...')

    try {
      // 获取所有模块数据
      const [foodsRes, tipsRes, packingRes] = await Promise.all([
        authFetch(`${API}/trips/${tripId}/foods`),
        authFetch(`${API}/trips/${tripId}/tips`),
        authFetch(`${API}/trips/${tripId}/packing`)
      ])

      const foods: FoodItem[] = foodsRes.ok ? await foodsRes.json() : []
      const tips: TipItem[] = tipsRes.ok ? await tipsRes.json() : []
      const packingData: PackingData = packingRes.ok ? await packingRes.json() : { members: [], items: [], templates: [] }

      // 时间计算辅助函数
      const formatTimeRange = (startTime: string, stayMin: number | null, nextStartTime?: string) => {
        const parseTime = (time: string): number | null => {
          const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim())
          if (!match) return null
          const hours = Number(match[1])
          const minutes = Number(match[2])
          if (hours > 23 || minutes > 59) return null
          return hours * 60 + minutes
        }

        const formatTime = (totalMinutes: number): string => {
          const normalized = ((totalMinutes % 1440) + 1440) % 1440
          return `${String(Math.floor(normalized / 60)).padStart(2, '0')}:${String(normalized % 60).padStart(2, '0')}`
        }

        const start = parseTime(startTime)
        if (start === null) return '时间待定'

        if (stayMin !== null && Number.isFinite(stayMin) && stayMin > 0) {
          const end = start + stayMin
          const dayPrefix = end >= 1440 ? '次日 ' : ''
          return `${formatTime(start)} – ${dayPrefix}${formatTime(end)}`
        }

        if (nextStartTime) {
          const next = parseTime(nextStartTime)
          if (next !== null) {
            return `${formatTime(start)} – ${formatTime(next)}`
          }
        }

        return `${formatTime(start)} 开始`
      }

      // 创建一个临时容器来渲染完整行程
      const container = document.createElement('div')
      container.style.cssText = `
        position: fixed;
        left: -9999px;
        top: 0;
        width: 900px;
        background: white;
        padding: 50px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      `
      document.body.appendChild(container)

      // 渲染行程标题
      const titleSection = document.createElement('div')
      titleSection.style.cssText = 'margin-bottom: 40px; border-bottom: 3px solid #5b8ff9; padding-bottom: 25px;'
      titleSection.innerHTML = `
        <h1 style="margin: 0 0 12px 0; font-size: 32px; color: #1a1a1a; font-weight: 700;">${trip.title}</h1>
        <div style="display: flex; gap: 20px; flex-wrap: wrap; align-items: center;">
          <span style="color: #666; font-size: 18px; display: flex; align-items: center; gap: 6px;">
            <span style="font-weight: 600;">📍</span>${trip.destination}
          </span>
          <span style="color: #666; font-size: 18px; display: flex; align-items: center; gap: 6px;">
            <span style="font-weight: 600;">📅</span>${trip.days} 天
          </span>
          ${trip.start_date ? `
            <span style="color: #666; font-size: 18px; display: flex; align-items: center; gap: 6px;">
              <span style="font-weight: 600;">🚀</span>${trip.start_date} 出发
            </span>
          ` : ''}
          ${trip.budget ? `
            <span style="color: #5b8ff9; font-size: 18px; font-weight: 600; display: flex; align-items: center; gap: 6px;">
              <span>💰</span>¥${trip.budget.toLocaleString()} / 人
            </span>
          ` : ''}
        </div>
      `
      container.appendChild(titleSection)

      // 渲染每一天的内容
      const days = Array.from({ length: trip.days }, (_, i) => i + 1)
      for (const day of days) {
        const dayStops = stopsOf(day)
        const dayTitle = getDayTitle(day)
        const dayDate = tripDayDate(trip.start_date, day)

        const daySection = document.createElement('div')
        daySection.style.cssText = 'margin-bottom: 45px; page-break-inside: avoid;'

        // Day 标题
        daySection.innerHTML = `
          <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 18px 24px; border-radius: 12px 12px 0 0; margin-bottom: 0;">
            <h2 style="margin: 0; font-size: 24px; color: white; font-weight: 700;">
              Day ${day} · ${dayTitle}
            </h2>
            <div style="color: rgba(255,255,255,0.9); margin-top: 6px; font-size: 15px;">
              ${dayDate ? `📅 ${dayDate}` : ''}
              ${dayDate && dayStops.length > 0 ? ' · ' : ''}
              ${dayStops.length > 0 ? `${dayStops.length} 个事件` : '暂无安排'}
            </div>
          </div>
        `

        // 路线概览
        if (dayStops.length > 0) {
          const route = dayStops.map(s => s.name.replace(/^🏨\s*/, '')).join(' → ')
          daySection.innerHTML += `
            <div style="background: #f8f9ff; padding: 16px 24px; border-left: 4px solid #667eea; margin-bottom: 0; font-size: 15px; color: #333; line-height: 1.8;">
              <strong style="color: #667eea; margin-right: 8px;">📍 今日路线</strong>${route}
            </div>
          `
        }

        // 事件列表容器
        const eventsContainer = document.createElement('div')
        eventsContainer.style.cssText = 'background: #fafbfc; padding: 20px 24px 24px 24px; border-radius: 0 0 12px 12px;'

        // 渲染每个事件
        dayStops.forEach((stop, idx) => {
          const isStay = stop.name.startsWith('🏨')
          const nextStop = dayStops[idx + 1]
          const timeRange = stop.start_time ? formatTimeRange(stop.start_time, stop.stay_min, nextStop?.start_time) : ''

          const details = []
          if (stop.transport) details.push(`🚗 ${stop.transport}`)
          if (stop.ticket_price) details.push(`💰 ¥${stop.ticket_price}`)
          if (stop.tags && stop.tags.length > 0) details.push(`🏷️ ${stop.tags.join(', ')}`)

          eventsContainer.innerHTML += `
            <div style="
              margin-bottom: 16px;
              padding: 20px;
              border-left: 4px solid ${isStay ? '#faad14' : '#5b8ff9'};
              border-radius: 8px;
              ${isStay ? 'background: linear-gradient(to right, #fffbf0, #ffffff);' : 'background: white;'}
              box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            ">
              <div style="display: flex; align-items: flex-start; gap: 16px;">
                <div style="
                  min-width: 36px;
                  height: 36px;
                  border-radius: 50%;
                  background: ${isStay ? '#faad14' : '#5b8ff9'};
                  color: white;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  font-weight: bold;
                  font-size: 16px;
                  flex-shrink: 0;
                ">${idx + 1}</div>
                <div style="flex: 1;">
                  <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                    <h3 style="margin: 0; font-size: 18px; color: #1a1a1a; font-weight: 600; line-height: 1.4;">${stop.name}</h3>
                    ${timeRange ? `
                      <span style="
                        background: #e6f7ff;
                        color: #1890ff;
                        padding: 4px 12px;
                        border-radius: 12px;
                        font-size: 14px;
                        font-weight: 600;
                        white-space: nowrap;
                        margin-left: 12px;
                      ">⏰ ${timeRange}</span>
                    ` : ''}
                  </div>
                  ${stop.note ? `
                    <p style="margin: 0 0 10px 0; color: #555; font-size: 15px; line-height: 1.7;">
                      ${stop.note}
                    </p>
                  ` : ''}
                  ${details.length > 0 ? `
                    <div style="display: flex; flex-wrap: wrap; gap: 12px; font-size: 14px; color: #666;">
                      ${details.map(d => `<span>${d}</span>`).join('')}
                    </div>
                  ` : ''}
                </div>
              </div>
            </div>
          `
        })

        daySection.appendChild(eventsContainer)
        container.appendChild(daySection)
      }

      // 渲染注意事项
      if (tips.length > 0) {
        const tipsSection = document.createElement('div')
        tipsSection.style.cssText = 'margin-top: 50px; page-break-before: avoid;'
        tipsSection.innerHTML = `
          <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 18px 24px; border-radius: 12px 12px 0 0;">
            <h2 style="margin: 0; font-size: 24px; color: white; font-weight: 700; display: flex; align-items: center; gap: 10px;">
              ⚠️ 注意事项
            </h2>
          </div>
          <div style="background: #fafbfc; padding: 20px 24px; border-radius: 0 0 12px 12px;">
        `

        tips.forEach(tip => {
          const levelConfig = {
            warning: { color: '#ff4d4f', icon: '⚠️', bg: '#fff1f0' },
            info: { color: '#1890ff', icon: 'ℹ️', bg: '#e6f7ff' },
            tip: { color: '#52c41a', icon: '💡', bg: '#f6ffed' }
          }
          const config = levelConfig[tip.level as keyof typeof levelConfig] || levelConfig.info

          tipsSection.innerHTML += `
            <div style="
              margin-bottom: 12px;
              padding: 14px 18px;
              border-left: 4px solid ${config.color};
              background: ${config.bg};
              border-radius: 6px;
            ">
              <span style="font-size: 18px; margin-right: 10px;">${config.icon}</span>
              <span style="color: #333; font-size: 15px; line-height: 1.7;">${tip.content}</span>
            </div>
          `
        })

        tipsSection.innerHTML += `</div>`
        container.appendChild(tipsSection)
      }

      // 渲染美食推荐
      if (foods.length > 0) {
        const foodSection = document.createElement('div')
        foodSection.style.cssText = 'margin-top: 50px; page-break-before: avoid;'
        foodSection.innerHTML = `
          <div style="background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); padding: 18px 24px; border-radius: 12px 12px 0 0;">
            <h2 style="margin: 0; font-size: 24px; color: white; font-weight: 700; display: flex; align-items: center; gap: 10px;">
              🍜 美食推荐
            </h2>
          </div>
          <div style="background: #fafbfc; padding: 20px 24px; border-radius: 0 0 12px 12px;">
        `

        const FOOD_CATS = ['小吃', '正餐', '甜点', '饮品', '其他']
        FOOD_CATS.forEach(cat => {
          const catFoods = foods.filter(f => f.category === cat)
          if (catFoods.length === 0) return

          foodSection.innerHTML += `
            <h3 style="margin: 20px 0 12px 0; font-size: 18px; color: #333; font-weight: 600;">${cat}</h3>
          `

          catFoods.forEach(food => {
            const priceText = food.price ? `¥${food.price}` : ''
            const cityText = food.city ? `📍 ${food.city}` : ''
            const isTop = food.is_top

            foodSection.innerHTML += `
              <div style="
                margin-bottom: 12px;
                padding: 14px 18px;
                background: white;
                border: 1px solid #e8e8e8;
                border-radius: 8px;
                ${isTop ? 'border-left: 4px solid #faad14; background: linear-gradient(to right, #fffbf0, #ffffff);' : ''}
              ">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                  <div style="flex: 1;">
                    <div style="font-weight: 600; color: #1a1a1a; font-size: 16px; margin-bottom: 6px;">
                      ${isTop ? '<span style="color: #faad14; margin-right: 6px;">⭐</span>' : ''}${food.name}
                    </div>
                    ${food.note ? `
                      <p style="margin: 0 0 6px 0; color: #666; font-size: 14px; line-height: 1.6;">${food.note}</p>
                    ` : ''}
                    ${(cityText || priceText) ? `
                      <div style="font-size: 13px; color: #999;">
                        ${[cityText, priceText].filter(Boolean).join(' · ')}
                      </div>
                    ` : ''}
                  </div>
                </div>
              </div>
            `
          })
        })

        foodSection.innerHTML += `</div>`
        container.appendChild(foodSection)
      }

      // 渲染行李清单
      if (packingData.items.length > 0) {
        const packingSection = document.createElement('div')
        packingSection.style.cssText = 'margin-top: 50px; page-break-before: avoid;'
        packingSection.innerHTML = `
          <div style="background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%); padding: 18px 24px; border-radius: 12px 12px 0 0;">
            <h2 style="margin: 0; font-size: 24px; color: #333; font-weight: 700; display: flex; align-items: center; gap: 10px;">
              🧳 行李清单
            </h2>
          </div>
          <div style="background: #fafbfc; padding: 20px 24px; border-radius: 0 0 12px 12px;">
        `

        const categories = [...new Set(packingData.items.map(i => i.category))]
        categories.forEach(cat => {
          const catItems = packingData.items.filter(i => i.category === cat)
          if (catItems.length === 0) return

          packingSection.innerHTML += `
            <h3 style="margin: 20px 0 12px 0; font-size: 18px; color: #333; font-weight: 600;">${cat}</h3>
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px;">
          `

          catItems.forEach(item => {
            const states = Object.values(item.states)
            const packedCount = states.filter(s => s === 'packed').length
            const totalCount = states.length
            const allPacked = packedCount === totalCount
            const somePacked = packedCount > 0 && packedCount < totalCount

            const statusIcon = allPacked ? '✓' : somePacked ? '◐' : '○'
            const statusColor = allPacked ? '#52c41a' : somePacked ? '#faad14' : '#d9d9d9'

            packingSection.innerHTML += `
              <div style="
                padding: 10px 14px;
                background: white;
                border: 1px solid #e8e8e8;
                border-radius: 6px;
                display: flex;
                align-items: center;
                gap: 10px;
              ">
                <span style="
                  font-size: 18px;
                  color: ${statusColor};
                  font-weight: bold;
                  flex-shrink: 0;
                ">${statusIcon}</span>
                <span style="color: #333; font-size: 15px; flex: 1;">${item.name}</span>
                ${totalCount > 1 ? `
                  <span style="color: #999; font-size: 13px; white-space: nowrap;">${packedCount}/${totalCount}</span>
                ` : ''}
              </div>
            `
          })

          packingSection.innerHTML += `</div>`
        })

        packingSection.innerHTML += `</div>`
        container.appendChild(packingSection)
      }

      // 添加页脚
      const footer = document.createElement('div')
      footer.style.cssText = 'margin-top: 60px; padding-top: 30px; border-top: 2px solid #e8e8e8; text-align: center;'
      footer.innerHTML = `
        <div style="color: #999; font-size: 14px; line-height: 1.8;">
          <div style="font-weight: 600; color: #666; margin-bottom: 8px;">✨ 由 17同游 生成</div>
          <div>${new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' })}</div>
        </div>
      `
      container.appendChild(footer)

      // 使用 html2canvas 生成图片
      const canvas = await html2canvas(container, {
        scale: 2,
        backgroundColor: '#ffffff',
        logging: false,
        useCORS: true,
        windowWidth: 900
      })

      // 下载图片
      canvas.toBlob((blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url
          a.download = `${trip.title.replace(/[^\w一-龥]/g, '_')}_行程单.png`
          a.click()
          URL.revokeObjectURL(url)
          notify('长图已生成并下载')
        }
      })

      // 清理临时容器
      document.body.removeChild(container)
    } catch (error) {
      console.error('导出失败:', error)
      notify('导出失败，请重试')
    }
  }

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
  // 工具页按模块保留快捷入口；日程页的添加入口放在表格内，避免右下角重复悬浮按钮遮挡地图。
  const fabLabel = workspaceView === 'tool' ? FAB_BY_TAB[aiTab] : ''
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

  const dropOn = async (dragId: string, day: number, beforeId: string | null) => {
    const siblings = stopsOf(day).map((x) => x.id).filter((id) => id !== dragId)
    const idx = beforeId ? siblings.indexOf(beforeId) : siblings.length
    siblings.splice(idx < 0 ? siblings.length : idx, 0, dragId)

    // 乐观更新：立即本地重排，后台异步调接口，失败时才 reload
    const dragged = trip.stops.find((s) => s.id === dragId)
    if (dragged && dragged.day !== day) {
      // 跨天拖拽，更新 day
      setTrip((prev) => prev ? {
        ...prev,
        stops: prev.stops.map((s) => s.id === dragId ? { ...s, day } : s)
      } : prev)
    }
    setTrip((prev) => prev ? {
      ...prev,
      stops: prev.stops.map((s) => {
        if (s.id === dragId) {
          const orderNo = siblings.indexOf(s.id)
          return { ...s, day, order_no: orderNo >= 0 ? orderNo : s.order_no }
        }
        if (s.day !== day) return s
        const orderNo = siblings.indexOf(s.id)
        return orderNo >= 0 ? { ...s, order_no: orderNo } : s
      }),
    } : prev)

    const res = await authFetch(`${API}/trips/${tripId}/stops/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ day, ordered_ids: siblings }),
    })
    if (!res.ok) {
      setMsg('调整顺序失败，已恢复最新数据')
      window.setTimeout(() => setMsg(''), 3000)
      await load()
    }
  }

  const moveStop = async (stop: TripStop, direction: -1 | 1) => {
    const current = stopsOf(stop.day)
    const from = current.findIndex((s) => s.id === stop.id)
    const to = from + direction
    if (from < 0 || to < 0 || to >= current.length) return

    const next = [...current]
    const [picked] = next.splice(from, 1)
    next.splice(to, 0, picked)
    const orderedIds = next.map((s) => s.id)

    setTrip((prev) => prev ? {
      ...prev,
      stops: prev.stops.map((s) => {
        if (s.day !== stop.day) return s
        const orderNo = orderedIds.indexOf(s.id)
        return orderNo >= 0 ? { ...s, order_no: orderNo } : s
      }),
    } : prev)

    try {
      const res = await authFetch(`${API}/trips/${tripId}/stops/reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ day: stop.day, ordered_ids: orderedIds }),
      })
      if (!res.ok) await load()
    } catch {
      await load()
    }
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
  const mapStopIndexById = new Map(mapStops.map((s, i) => [s.id, i + 1]))
  const actualTotal = expenses.reduce((sum, expense) => sum + expense.amount, 0)
  const plannedTotal = trip.budget || Object.values(trip.budget_breakdown || {}).reduce((sum, value) => sum + value, 0)
  const budgetPercent = plannedTotal > 0 ? Math.min(100, Math.round((actualTotal / plannedTotal) * 100)) : 0
  const mapUrl = mapStops.length
    ? `${API}/staticmap?pts=${mapStops.map((s) => s.location).join(';')}` +
      `&labels=${mapStops.map((_, i) => i + 1).join(',')}` +
      `&days=${mapStops.map(() => selectedDay).join(',')}&size=600*600`
    : null

  const optimizeRoute = async () => {
    if (optimizingRoute) return
    if (stopsOf(selectedDay).length < 2) {
      setMsg('当天至少需要 2 个行程点才能优化路线')
      window.setTimeout(() => setMsg(''), 3500)
      return
    }
    setOptimizingRoute(true)
    setMsg('正在优化路线…')
    try {
      const res = await authFetch(`${API}/trips/${tripId}/ai/order`, { method: 'POST' })
      const result = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMsg(result.detail || '路线优化失败，请稍后重试')
        return
      }
      setMsg(`已串好路线：${result.km_before}km → ${result.km_after}km${result.unlocated?.length ? `（${result.unlocated.join('、')} 无坐标已跳过）` : ''}`)
      updatedRef.current = ''
      await load()
    } catch {
      setMsg('路线优化失败，请检查网络或稍后重试')
    } finally {
      setOptimizingRoute(false)
      window.setTimeout(() => setMsg(''), 6000)
    }
  }

  return (
    <div className="trip-board">
      <div className="trip-board-head">
        <button className="trip-btn" onClick={onBack}>← 返回</button>
        <button className="trip-btn" onClick={exportToImage} style={{ marginLeft: '8px' }}>📸 导出长图</button>
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
          openSignal={openChatSignal}
          onRead={onChatRead}
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

      <div className={`trip-3col trip-view-${workspaceView}${mapCollapsed ? ' trip-map-collapsed' : ''}`}>
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
          <div className="trip-sidebar-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>行程天数</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              <button
                className="trip-btn tiny"
                onClick={() => changeDays(trip.days - 1)}
                disabled={trip.days <= 1}
                title="减少一天"
                style={{ padding: '2px 6px', fontSize: '12px' }}
              >
                −
              </button>
              <button
                className="trip-btn tiny"
                onClick={() => changeDays(trip.days + 1)}
                disabled={trip.days >= 30}
                title="增加一天"
                style={{ padding: '2px 6px', fontSize: '12px' }}
              >
                +
              </button>
            </div>
          </div>
          <nav className="trip-sidebar-days">
            {days.map((d) => (
              <button
                key={d}
                className={workspaceView === 'day' && selectedDay === d ? 'active' : ''}
                onClick={() => { setSelectedDay(d); setWorkspaceView('day') }}
              >
                <span><b>Day {d}</b><small>{displayTripDayDate(trip, d) || `${stopsOf(d).length} 个事件`}</small></span>
                <i>{stopsOf(d).length}</i>
              </button>
            ))}
          </nav>
        </aside>

        {/* 中：当前日事件时间线 */}
        <div className={`trip-col-timeline${mobilePane === 'timeline' ? ' mobile-active' : ''}`}>
          <header className="trip-day-overview">
            {editingDayTitle === selectedDay ? (
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                Day {selectedDay} ·
                <input
                  type="text"
                  value={dayTitleInput}
                  onChange={(e) => setDayTitleInput(e.target.value)}
                  onBlur={() => {
                    if (dayTitleInput.trim()) {
                      saveDayTitle(selectedDay, dayTitleInput)
                    } else {
                      setEditingDayTitle(null)
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      if (dayTitleInput.trim()) {
                        saveDayTitle(selectedDay, dayTitleInput)
                      }
                    } else if (e.key === 'Escape') {
                      setEditingDayTitle(null)
                    }
                  }}
                  autoFocus
                  style={{
                    flex: 1,
                    fontSize: 'inherit',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    padding: '4px 8px'
                  }}
                />
              </h2>
            ) : (
              <h2
                style={{ cursor: 'pointer' }}
                onClick={() => {
                  setEditingDayTitle(selectedDay)
                  setDayTitleInput(getDayTitle(selectedDay))
                }}
                title="点击编辑标题"
              >
                {formatDayTitle(selectedDay)}
              </h2>
            )}
            <p>{[displayTripDayDate(trip, selectedDay), `${stopsOf(selectedDay).length} 个事件`].filter(Boolean).join(' · ')}</p>
          </header>
          <section className="trip-route-summary">
            <div className="trip-route-summary-head">
              <strong>📍 今日路线</strong>
              <span className="trip-route-actions">
                <span className="trip-route-plan" title="按当天有坐标的地点计算直线距离，用最近邻把每一天内部重排；无坐标地点会跳过并排在后面。">
                  当前方案：按坐标距离最短重排
                </span>
                <button className="trip-btn primary" onClick={optimizeRoute} disabled={optimizingRoute}>
                  {optimizingRoute ? '优化中…' : '✦ AI 优化路线'}
                </button>
              </span>
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
              {/* 表格式行程展示 */}
              {selectedDay === d && (
                <div className="trip-table-shell">
                  <div className="trip-table">
                    <div className="trip-table-header">
                      <div className="trip-table-col-time">时段</div>
                      <div className="trip-table-col-activity">地点与活动</div>
                      <div className="trip-table-col-transport">交通/备注</div>
                      <div className="trip-table-col-price">参考花费</div>
                      <div className="trip-table-col-ops">操作</div>
                    </div>
                    {stopsOf(d).length === 0 ? (
                      <div className="trip-table-empty">暂无行程</div>
                    ) : (
                      stopsOf(d).map((s, i, arr) => (
                        <div
                          key={s.id}
                          ref={(el) => { if (el) stopRefs.current.set(s.id, el) }}
                          className={`trip-table-row${flashId === s.id ? ' flash' : ''}${isStay(s) ? ' is-stay' : ''}${dragOverStopId === s.id ? ' drag-over' : ''}`}
                          draggable
                          onDragStart={(e) => { dragIdRef.current = s.id; e.dataTransfer.effectAllowed = 'move' }}
                          onDragEnter={() => {
                            if (dragIdRef.current && dragIdRef.current !== s.id) setDragOverStopId(s.id)
                          }}
                          onDragLeave={(e) => {
                            if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOverStopId(null)
                          }}
                          onDragOver={(e) => {
                            e.preventDefault()
                            if (dragIdRef.current && dragIdRef.current !== s.id) setDragOverStopId(s.id)
                          }}
                          onDrop={(e) => {
                            e.preventDefault()
                            e.stopPropagation()
                            if (dragIdRef.current && dragIdRef.current !== s.id) dropOn(dragIdRef.current, d, s.id)
                            dragIdRef.current = null
                            setDragOverStopId(null)
                          }}
                          onDragEnd={() => setDragOverStopId(null)}
                        >
                          <div className="trip-table-col-time">
                            {formatTripTimeRange(s.start_time, s.stay_min, arr[i + 1]?.start_time)}
                          </div>
                          <div className="trip-table-col-activity" onClick={() => { setSelectedDay(d); setFocusStop(s.id) }}>
                            <div className="trip-activity-title">
                              {mapStopIndexById.has(s.id) && (
                                <i className="trip-stop-map-index">{mapStopIndexById.get(s.id)}</i>
                              )}
                              <span>{s.name}</span>
                            </div>
                            {s.note && (
                              <div className="trip-activity-desc">{s.note}</div>
                            )}
                          </div>
                          <div className="trip-table-col-transport">
                            {s.transport || '—'}
                          </div>
                          <div className="trip-table-col-price">
                            {s.ticket_price ? `¥${s.ticket_price}${s.ticket_price < 1000 ? '/人' : ''}` : '免费'}
                          </div>
                          <div className="trip-table-col-ops">
                            <button
                              className="trip-table-btn-move"
                              onClick={(e) => { e.stopPropagation(); moveStop(s, -1) }}
                              aria-label={`上移 ${s.name}`}
                              title="上移"
                              disabled={i === 0}
                            >↑</button>
                            <button
                              className="trip-table-btn-move"
                              onClick={(e) => { e.stopPropagation(); moveStop(s, 1) }}
                              aria-label={`下移 ${s.name}`}
                              title="下移"
                              disabled={i === arr.length - 1}
                            >↓</button>
                            <button
                              className="trip-table-btn-edit"
                              aria-label={`编辑 ${s.name}`}
                              onClick={(e) => { e.stopPropagation(); setEditing(s) }}
                              title="编辑"
                            >✏️</button>
                            <button
                              className="trip-table-btn-delete"
                              onClick={(e) => {
                                e.stopPropagation()
                                if (!window.confirm(`删除「${s.name}」？此操作无法撤销。`)) return
                                call(`/stops/${s.id}`, 'DELETE').then((ok) => {
                                  if (ok) notify(`已删除「${s.name}」`, 'success')
                                })
                              }}
                              aria-label={`删除 ${s.name}`}
                              title="删除"
                            >🗑️</button>
                          </div>
                          {openComments === s.id && (
                            <div className="trip-table-comments">
                              <CommentThread
                                comments={commentsOf(s.id)}
                                onAdd={(text) => call(`/stops/${s.id}/comments`, 'POST', { content: text })}
                                onDelete={(id) => call(`/comments/${id}`, 'DELETE')}
                              />
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                  <AddStop onAdd={() => setAddingStopDay(d)} />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* 右：每日地图（桌面固定，参考 HTML 的地图侧栏） */}
        <div className={`trip-col-map${mobilePane === 'map' ? ' mobile-active' : ''}`}>
          <div className="trip-map-card-head">
            <span>
              <strong>📍 今日路线地图</strong>
              <small>{mapStops.length} 个地点</small>
            </span>
            <button className="trip-map-toggle" onClick={() => setMapCollapsed((v) => !v)}>
              {mapCollapsed ? '展开' : '收起'}
            </button>
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

          {aiTab === 'food' && (
            <FoodPanel
              tripId={tripId}
              active
              days={days}
              stopsOf={stopsOf}
              onAddToDay={(day, name) => call('/stops', 'POST', { day, name, note: '美食', tags: ['food'] })}
              onEditStop={setEditing}
              onDeleteStop={(stop) => call(`/stops/${stop.id}`, 'DELETE')}
            />
          )}
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
                        <span className="trip-stay-name trip-stay-with-actions">
                          <button className="trip-stay-link" onClick={() => { setSelectedDay(d); locate(d, stays[0].id) }}>
                            {stays.map((s) => s.name.replace(/^🏨\s*/, '')).join('、')}
                            {stays.some((s) => s.ticket_price) && (
                              <b className="trip-stay-price">
                                ¥{stays.reduce((a, s) => a + (s.ticket_price || 0), 0).toFixed(0)}/晚
                              </b>
                            )}
                          </button>
                          <button className="trip-mini-action" onClick={() => setEditing(stays[0])}>编辑</button>
                          <button className="trip-mini-action danger" onClick={() => {
                            if (!window.confirm(`删除 Day${d} 住宿？`)) return
                            call(`/stops/${stays[0].id}`, 'DELETE')
                          }}>删除</button>
                        </span>
                      ) : (
                        <>
                          <span className="trip-stay-name trip-stay-city">{city || '未知城市'}</span>
                          <button
                            className="trip-btn trip-stay-book"
                            onClick={() => call('/stops', 'POST', { day: d, name: '🏨 待定住宿', note: '住宿' })}
                          >
                            添加住宿
                          </button>
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
            const optimisticPatch = { ...patch }
            if ('no_location' in patch) {
              const prevTags = editing.tags || []
              optimisticPatch.tags = patch.no_location
                ? Array.from(new Set([...prevTags, 'no_location']))
                : prevTags.filter((tag) => tag !== 'no_location')
            }
            delete optimisticPatch.location
            delete optimisticPatch.no_location
            setTrip((prev) => prev ? {
              ...prev,
              stops: prev.stops.map((s) => s.id === editing.id ? { ...s, ...optimisticPatch } : s)
            } : prev)
            setEditing(null)
            call(`/stops/${editing.id}`, 'PATCH', patch).catch(() => load())
          }}
        />
      )}
      {addingStopDay !== null && (
        <AddStopModal
          day={addingStopDay}
          onClose={() => setAddingStopDay(null)}
          onSave={async (patch) => {
            setAddingStopDay(null)
            await call('/stops', 'POST', { day: addingStopDay, ...patch })
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
          <div className="trip-expense-topline">
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
          </div>
          <label className="trip-expense-title-field">
            <span>事项</span>
            <input placeholder="花在哪了，如 晚餐" value={d.title}
              onChange={(e) => set({ title: e.target.value })} />
          </label>
          <div className="trip-expense-money-row">
            <label className="trip-expense-amount-field">
              <span>金额</span>
              <i>¥</i>
              <input type="number" min="0" step="0.01" placeholder="0.00" value={d.amount}
                onChange={(e) => set({ amount: e.target.value })} />
            </label>
            <label>
              <span>日期</span>
              {/* 花费日期与记账时间分开：补记昨天的账很常见 */}
              <input type="date" value={d.spent_at} onChange={(e) => set({ spent_at: e.target.value })} />
            </label>
          </div>
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
    if (!r.ok) {
      notify('保存失败，请检查金额和分摊成员', 'error')
      return false
    }
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
  const [startTime, setStartTime] = useState(stop.start_time)
  // 从 start_time + stay_min 反推结束时间（用于初始化）
  const calcEndTime = (start: string, stayMin: number) => {
    if (!start || !stayMin) return ''
    const [h, m] = start.split(':').map(Number)
    if (isNaN(h) || isNaN(m)) return ''
    const endMin = h * 60 + m + stayMin
    return `${String(Math.floor(endMin / 60)).padStart(2, '0')}:${String(endMin % 60).padStart(2, '0')}`
  }
  const [endTime, setEndTime] = useState(calcEndTime(stop.start_time, stop.stay_min || 0))
  const initialNoLocation = stop.tags?.includes('no_location') || false
  const [locationText, setLocationText] = useState(stop.name.replace(/^🏨\s*/, ''))
  const [description, setDescription] = useState(stop.note || '')
  const [noLocation, setNoLocation] = useState(initialNoLocation)
  const [transport, setTransport] = useState(stop.transport)
  const [ticket, setTicket] = useState(stop.ticket_price ? String(stop.ticket_price) : '')
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal trip-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>编辑行程</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="trip-edit-context">
          <span>📅 Day {stop.day}</span>
          <b>{name || '未命名行程'}</b>
        </div>
        <div className="trip-edit-grid">
          <div className="trip-edit-section trip-edit-full">
            <b>基础信息</b>
            <small>活动名用于行程展示，地图关键词只负责定位。</small>
          </div>
          <label className="trip-edit-full">活动名称<input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：双子塔（KLCC）" /></label>
          <label>开始时间<input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} /></label>
          <label>结束时间<input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} /></label>
          <label>交通方式<input value={transport} onChange={(e) => setTransport(e.target.value)} placeholder="步行/打车/地铁/飞机" /></label>
          <label>花费<input type="number" min="0" value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder="免费" /></label>
          <div className="trip-edit-section trip-edit-full">
            <b>地图定位</b>
            <small>开启后会参与右侧地图序号和路线展示；飞行/跨城交通可关闭。</small>
          </div>
          <div className="trip-edit-full trip-location-field">
            <div className="trip-location-head">
              <div>
                <b>{noLocation ? '不显示在地图上' : '显示在地图上'}</b>
                <small>{noLocation ? '飞行、跨城交通等无需地图定位' : '开启后可在地图上显示该行程位置'}</small>
              </div>
              <label className={`trip-map-switch ${noLocation ? '' : 'on'}`}>
                <input type="checkbox" checked={!noLocation} onChange={(e) => setNoLocation(!e.target.checked)} />
                <span className="trip-map-switch-track" />
                <span>{noLocation ? '关闭' : '开启'}</span>
              </label>
            </div>
            {noLocation ? (
              <div className="trip-map-disabled-note">开启后可填写定位关键词，并在今日路线地图上显示序号。</div>
            ) : (
              <label className="trip-location-keyword">地图定位关键词<input value={locationText} onChange={(e) => setLocationText(e.target.value)} placeholder="如：Petronas Twin Towers / Suria KLCC" /></label>
            )}
          </div>
          <div className="trip-edit-section trip-edit-full">
            <b>补充信息</b>
          </div>
          <label className="trip-edit-full">描述/备注<textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="参观博物馆，逛街购物；预约、门票、注意事项等" /></label>
        </div>
        <div className="trip-edit-ops">
          <button className="trip-btn" onClick={onClose}>取消</button>
          <button className="trip-btn primary" onClick={() => {
            // 从开始、结束时间计算停留分钟数
            let stayMin = 0
            if (startTime && endTime) {
              const [sh, sm] = startTime.split(':').map(Number)
              const [eh, em] = endTime.split(':').map(Number)
              if (!isNaN(sh) && !isNaN(sm) && !isNaN(eh) && !isNaN(em)) {
                stayMin = Math.max(0, (eh * 60 + em) - (sh * 60 + sm))
              }
            }
            onSave({
              name: name.trim() || undefined,
              start_time: startTime,
              stay_min: stayMin,
              transport: transport.trim() || '',
              ticket_price: ticket === '' ? 0 : Math.max(0, Number(ticket) || 0),
              no_location: noLocation,
              location: noLocation ? '' : locationText.trim(),
              note: description.trim(),
            })
          }}>
            保存
          </button>
        </div>
      </div>
    </div>
  )
}

function AddStopModal({
  day, onClose, onSave,
}: { day: number; onClose: () => void; onSave: (patch: Record<string, unknown>) => void }) {
  const [name, setName] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [locationText, setLocationText] = useState('')
  const [description, setDescription] = useState('')
  const [transport, setTransport] = useState('')
  const [ticket, setTicket] = useState('')
  const [noLocation, setNoLocation] = useState(false)
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose])
  const save = () => {
    if (!name.trim()) return
    let stayMin = 0
    if (startTime && endTime) {
      const [sh, sm] = startTime.split(':').map(Number)
      const [eh, em] = endTime.split(':').map(Number)
      if (!isNaN(sh) && !isNaN(sm) && !isNaN(eh) && !isNaN(em)) {
        stayMin = Math.max(0, (eh * 60 + em) - (sh * 60 + sm))
      }
    }
    onSave({
      name: name.trim(),
      start_time: startTime,
      stay_min: stayMin,
      transport: transport.trim(),
      ticket_price: ticket === '' ? 0 : Math.max(0, Number(ticket) || 0),
      no_location: noLocation,
      location: noLocation ? '' : locationText.trim(),
      note: description.trim(),
    })
  }
  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal trip-edit-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>添加 Day {day} 地点</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="trip-edit-context">
          <span>📅 Day {day}</span>
          <b>{name || '新行程'}</b>
        </div>
        <div className="trip-edit-grid">
          <div className="trip-edit-section trip-edit-full">
            <b>基础信息</b>
            <small>活动名用于行程展示，地图关键词只负责定位。</small>
          </div>
          <label className="trip-edit-full">活动名称<input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="如：双子塔夜景" /></label>
          <label>开始时间<input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} /></label>
          <label>结束时间<input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} /></label>
          <label>交通方式<input value={transport} onChange={(e) => setTransport(e.target.value)} placeholder="步行/打车/地铁/飞机" /></label>
          <label>花费<input type="number" min="0" value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder="免费" /></label>
          <div className="trip-edit-section trip-edit-full">
            <b>地图定位</b>
            <small>开启后会参与右侧地图序号和路线展示；飞行/跨城交通可关闭。</small>
          </div>
          <div className="trip-edit-full trip-location-field">
            <div className="trip-location-head">
              <div>
                <b>{noLocation ? '不显示在地图上' : '显示在地图上'}</b>
                <small>{noLocation ? '飞行、跨城交通等无需地图定位' : '开启后可在地图上显示该行程位置'}</small>
              </div>
              <label className={`trip-map-switch ${noLocation ? '' : 'on'}`}>
                <input type="checkbox" checked={!noLocation} onChange={(e) => setNoLocation(!e.target.checked)} />
                <span className="trip-map-switch-track" />
                <span>{noLocation ? '关闭' : '开启'}</span>
              </label>
            </div>
            {noLocation ? (
              <div className="trip-map-disabled-note">开启后可填写定位关键词，并在今日路线地图上显示序号。</div>
            ) : (
              <label className="trip-location-keyword">地图定位关键词<input value={locationText} onChange={(e) => setLocationText(e.target.value)} placeholder="详细地址或地点名，如：Petronas Twin Towers" /></label>
            )}
          </div>
          <div className="trip-edit-section trip-edit-full">
            <b>补充信息</b>
          </div>
          <label className="trip-edit-full">描述/备注<textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="补充说明、注意事项" /></label>
        </div>
        <div className="trip-edit-ops">
          <button className="trip-btn" onClick={onClose}>取消</button>
          <button className="trip-btn primary" onClick={save} disabled={!name.trim()}>保存</button>
        </div>
      </div>
    </div>
  )
}

function AddStop({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="trip-add-stop">
      <button type="button" onClick={onAdd}>+ 添加地点</button>
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
  return { data, setData, loading, reload }
}

interface FoodItem {
  id: string; name: string; category: string; city: string
  price: number | null; note: string; is_top: boolean; created_by: string
}

const FOOD_CATS = ['小吃', '正餐', '甜点', '饮品', '其他']

function FoodPanel({
  tripId, active, days, stopsOf, onAddToDay, onEditStop, onDeleteStop,
}: {
  tripId: string
  active: boolean
  days: number[]
  stopsOf: (day: number) => TripStop[]
  onAddToDay: (day: number, name: string) => Promise<unknown>
  onEditStop: (stop: TripStop) => void
  onDeleteStop: (stop: TripStop) => Promise<unknown>
}) {
  const { data, reload } = useModuleData<FoodItem[]>(tripId, 'foods', active, [])
  const [name, setName] = useState('')
  const [dayFoodName, setDayFoodName] = useState<Record<number, string>>({})
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
  const foodStopsOf = (day: number) => stopsOf(day).filter((s) => (
    s.tags?.includes('food') || (s.note || '').includes('美食') || /餐|咖啡|小吃|饭|食|甜品|早餐|午餐|晚餐/.test(s.name)
  ))

  return (
    <div className="trip-panel trip-module">
      <div className="trip-panel-head">🍜 按天美食 <span className="trip-day-km">会同步到对应 Day 行程</span></div>
      <div className="trip-day-foods">
        {days.map((d) => {
          const dayFoods = foodStopsOf(d)
          return (
            <section key={d} className={`trip-day-food-card${dayFoods.length ? '' : ' empty'}`}>
              <div className="trip-day-food-head">
                <b>Day {d}</b>
                <small>{dayFoods.length} 项</small>
              </div>
              {dayFoods.length ? (
                <ul className="trip-day-food-list">
                  {dayFoods.map((s) => (
                    <li key={s.id}>
                      <span>
                        <b>{s.name}</b>
                        {s.note && <small>{s.note.replace(/^美食\s*/, '')}</small>}
                      </span>
                      <button className="trip-mini-action" onClick={() => onEditStop(s)}>编辑</button>
                      <button className="trip-mini-action danger" onClick={() => {
                        if (window.confirm(`删除「${s.name}」？`)) onDeleteStop(s)
                      }}>删除</button>
                    </li>
                  ))}
                </ul>
              ) : <p className="trip-module-empty">暂无美食安排</p>}
              <div className="trip-module-add compact">
                <input
                  placeholder="添加这天的美食"
                  value={dayFoodName[d] || ''}
                  onChange={(e) => setDayFoodName((prev) => ({ ...prev, [d]: e.target.value }))}
                  onKeyDown={async (e) => {
                    const value = (dayFoodName[d] || '').trim()
                    if (e.key === 'Enter' && value) {
                      await onAddToDay(d, value)
                      setDayFoodName((prev) => ({ ...prev, [d]: '' }))
                    }
                  }}
                />
                <button className="trip-btn primary" onClick={async () => {
                  const value = (dayFoodName[d] || '').trim()
                  if (!value) return
                  await onAddToDay(d, value)
                  setDayFoodName((prev) => ({ ...prev, [d]: '' }))
                }}>添加</button>
              </div>
            </section>
          )
        })}
      </div>

      <div className="trip-panel-head trip-sub-panel-head">攻略推荐美食 <span className="trip-day-km">未分天，可手动加入上面某天</span></div>
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

function PackingPanel({
  tripId, active, username, members, isOwner, onInvite,
}: {
  tripId: string; active: boolean; username: string
  members: { username: string; role: string }[]
  isOwner: boolean
  onInvite: (name: string) => Promise<boolean>
}) {
  const { data, setData, reload } = useModuleData<PackingData>(
    tripId, 'packing', active, { members: [], items: [], templates: [] })
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [cat, setCat] = useState('通用')
  const [categoryName, setCategoryName] = useState('')
  const [editingCategoryName, setEditingCategoryName] = useState('')
  const [editingCategoryValue, setEditingCategoryValue] = useState('')
  const [customCats, setCustomCats] = useState<string[]>([])
  const [manageCats, setManageCats] = useState(false)
  const [managePeople, setManagePeople] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchRows, setBatchRows] = useState([{ name: '', category: '通用' }])
  const [bulkCat, setBulkCat] = useState('通用')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [editingItem, setEditingItem] = useState<PackingData['items'][number] | null>(null)
  const [editingName, setEditingName] = useState('')
  const [editingCat, setEditingCat] = useState('通用')
  const [invite, setInvite] = useState('')
  const [filterCat, setFilterCat] = useState('全部')
  const { notify } = useToast()

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopImmediatePropagation()
      if (editingItem) setEditingItem(null)
      else if (batchOpen) setBatchOpen(false)
      else if (manageCats) setManageCats(false)
      else if (managePeople) setManagePeople(false)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [batchOpen, editingItem, manageCats, managePeople])

  const add = async (text: string, category = '通用') => {
    if (!text.trim()) return
    const r = await authFetch(`${API}/trips/${tripId}/packing`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: text.trim(), category }),
    })
    if (r.ok) { setName(''); setAdding(false); reload() } else notify('添加失败，请重试', 'error')
  }
  const cycle = async (itemId: string, cur: string, member: string) => {
    const nextState = PACK_NEXT[cur] || 'packed'
    const targetMember = member || username
    setData((prev) => ({
      ...prev,
      items: prev.items.map((it) => it.id === itemId ? {
        ...it,
        states: { ...it.states, [targetMember]: nextState },
        marked_by: (() => {
          const nextMarked = { ...it.marked_by }
          if (member && member !== username) {
            if (nextState === 'na') delete nextMarked[targetMember]
            else nextMarked[targetMember] = username
          }
          return nextMarked
        })(),
      } : it),
    }))
    const r = await authFetch(`${API}/trips/${tripId}/packing/${itemId}/state`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: nextState, member }),
    })
    if (!r.ok) {
      notify('勾选失败，请重试', 'error')
      reload()
    }
  }
  const updateItem = async (itemId: string, patch: { name?: string; category?: string }, reloadAfter = false) => {
    const r = await authFetch(`${API}/trips/${tripId}/packing/${itemId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!r.ok) {
      notify('修改失败，请重试', 'error')
      return false
    }
    setData((prev) => ({
      ...prev,
      items: prev.items.map((item) => item.id === itemId ? { ...item, ...patch } : item),
    }))
    if (reloadAfter) reload()
    return true
  }
  const remove = async (id: string, itemName: string) => {
    if (!window.confirm(`删除「${itemName}」？`)) return
    const r = await authFetch(`${API}/trips/${tripId}/packing/${id}`, { method: 'DELETE' })
    // 失败必须说出来——原来静默失败，用户只看到「点了没反应」
    if (r.ok) {
      setSelectedIds((prev) => prev.filter((sid) => sid !== id))
      reload()
    }
    else notify('删除失败，请重试', 'error')
  }
  const recategorize = async (itemId: string, category: string, reloadAfter = true) => {
    const ok = await updateItem(itemId, { category }, false)
    if (ok && reloadAfter) reload()
  }

  const cats = Array.from(new Set(['通用', ...customCats, ...data.items.map((i) => i.category || '通用')]))
  const displayedItems = filterCat === '全部'
    ? data.items
    : data.items.filter(i => (i.category || '通用') === filterCat)
  const groupedItems = cats
    .map((category) => ({
      category,
      items: displayedItems.filter((i) => (i.category || '通用') === category),
    }))
    .filter((group) => group.items.length > 0)

  const unused = data.templates.filter((t) => !data.items.some((i) => i.name === t))
  const selectedItems = data.items.filter((it) => selectedIds.includes(it.id))

  const addCategory = () => {
    const nextName = categoryName.trim()
    if (!nextName) return
    if (cats.includes(nextName)) {
      notify('该分类已存在')
      return
    }
    setCustomCats((prev) => Array.from(new Set([...prev, nextName])))
    setCat(nextName)
    setBulkCat(nextName)
    setCategoryName('')
    notify('分类已添加，可在添加物品时使用', 'success')
  }

  const startEditCategory = (category: string) => {
    setEditingCategoryName(category)
    setEditingCategoryValue(category)
  }

  const cancelEditCategory = () => {
    setEditingCategoryName('')
    setEditingCategoryValue('')
  }

  const saveCategoryName = async (from: string) => {
    const nextName = editingCategoryValue.trim()
    if (!nextName || nextName === from) {
      cancelEditCategory()
      return
    }
    if (cats.includes(nextName)) {
      notify('该分类已存在', 'error')
      return
    }
    setCustomCats((prev) => Array.from(new Set(prev.map((x) => x === from ? nextName : x).concat(nextName))))
    setCat((cur) => cur === from ? nextName : cur)
    setBulkCat((cur) => cur === from ? nextName : cur)
    setFilterCat((cur) => cur === from ? nextName : cur)
    const itemsToUpdate = data.items.filter((it) => (it.category || '通用') === from)
    for (const item of itemsToUpdate) {
      await recategorize(item.id, nextName, false)
    }
    cancelEditCategory()
    reload()
  }

  const openEditItem = (item: PackingData['items'][number]) => {
    setEditingItem(item)
    setEditingName(item.name)
    setEditingCat(item.category || '通用')
  }

  const saveEditingItem = async () => {
    if (!editingItem || !editingName.trim()) return
    const ok = await updateItem(editingItem.id, {
      name: editingName.trim(),
      category: editingCat.trim() || '通用',
    })
    if (ok) {
      setEditingItem(null)
      notify('物品已更新', 'success')
    }
  }

  const batchAdd = async () => {
    const rows = batchRows
      .map((row) => ({ name: row.name.trim(), category: row.category.trim() || '通用' }))
      .filter((row) => row.name)
    if (rows.length === 0) return
    for (const row of rows) {
      await add(row.name, row.category)
    }
    setBatchRows([{ name: '', category: bulkCat || '通用' }])
    setBatchOpen(false)
    reload()
  }

  const bulkMove = async () => {
    if (selectedIds.length === 0) return
    for (const id of selectedIds) {
      await recategorize(id, bulkCat || '通用', false)
    }
    setSelectedIds([])
    reload()
  }

  const bulkDelete = async () => {
    if (selectedIds.length === 0) return
    if (!window.confirm(`删除选中的 ${selectedIds.length} 个物品？`)) return
    for (const id of selectedIds) {
      await authFetch(`${API}/trips/${tripId}/packing/${id}`, { method: 'DELETE' })
    }
    setSelectedIds([])
    reload()
  }

  const renderRows = (items: PackingData['items']) => items.map((it) => (
    <tr key={it.id} className="trip-packing-item-row">
      <td className="trip-packing-select">
        <input
          type="checkbox"
          checked={selectedIds.includes(it.id)}
          onChange={(e) => setSelectedIds((prev) => e.target.checked
            ? Array.from(new Set([...prev, it.id]))
            : prev.filter((id) => id !== it.id))}
          aria-label={`选择 ${it.name}`}
        />
      </td>
      <td className="trip-packing-name">
        <div className="trip-packing-item-cell">
          <b>{it.name}</b>
          <small>{it.category || '通用'}</small>
        </div>
      </td>
      {data.members.map((m) => {
        const st = it.states[m] || 'na'
        const mine = m === username
        const by = it.marked_by?.[m]
        const statusText = st === 'packed' ? '已带' : st === 'unpacked' ? '未带' : '–'

        return (
          <td key={m}>
            <button
              className={`trip-pack-status ${st}${mine ? ' mine' : ''}`}
              title={`${mine ? '我' : m}：点击切换 已带 / 未带 / 未设置${by ? `（由 ${by} 代勾）` : ''}`}
              onClick={() => cycle(it.id, st, mine ? '' : m)}
            >
              {statusText}
              {by && <i>{by[0]?.toUpperCase()}</i>}
            </button>
          </td>
        )
      })}
      <td className="trip-packing-ops">
        <button className="trip-mini-action" onClick={() => openEditItem(it)}>编辑</button>
        <button className="trip-mini-action danger" onClick={() => remove(it.id, it.name)}>删除</button>
      </td>
    </tr>
  ))

  return (
    <div className="trip-panel trip-module">
      <div className="trip-panel-head">🧳 行李清单 <span className="trip-day-km">可以替同伴勾，会记下是谁勾的</span></div>

      <div className="trip-module-toolbar">
        <button className="trip-btn primary" onClick={() => setAdding(true)}>+ 添加物品</button>
        <button className="trip-btn" onClick={() => setBatchOpen(true)}>批量维护</button>
        <button className="trip-btn" onClick={() => setManageCats(true)}>
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

      {data.items.length > 0 && (
        <div className="trip-packing-filters">
          <button className={filterCat === '全部' ? 'active' : ''} onClick={() => setFilterCat('全部')}>
            全部 ({data.items.length})
          </button>
          {cats.map(c => {
            const count = data.items.filter(i => (i.category || '通用') === c).length
            return (
              <button key={c} className={filterCat === c ? 'active' : ''} onClick={() => setFilterCat(c)}>
                {c} ({count})
              </button>
            )
          })}
        </div>
      )}

      {data.items.length > 0 && (
        <div className="trip-packing-scroll">
          <table className="trip-packing-table">
            <thead>
              <tr>
                <th className="trip-packing-select">
                  <input
                    type="checkbox"
                    checked={displayedItems.length > 0 && displayedItems.every((it) => selectedIds.includes(it.id))}
                    onChange={(e) => {
                      const nextIds = e.target.checked ? displayedItems.map((it) => it.id) : []
                      setSelectedIds(nextIds)
                      if (nextIds.length > 0) {
                        setBulkCat(filterCat === '全部' ? cats[0] || '通用' : filterCat)
                        setBatchOpen(true)
                      }
                    }}
                    aria-label="选择当前列表全部物品"
                  />
                </th>
                <th className="trip-packing-name">物品</th>
                {data.members.map((m) => (
                  <th key={m} className={m === username ? 'me' : ''}>
                    <span className="trip-packing-avatar">{m[0]?.toUpperCase()}</span>
                    <b>{m}</b>
                  </th>
                ))}
                <th className="trip-packing-ops">操作</th>
              </tr>
            </thead>
            <tbody>
              {groupedItems.map((group) => (
                <Fragment key={group.category}>
                  <tr key={`${group.category}-group`} className="trip-packing-group-row">
                    <td colSpan={3 + data.members.length}>
                      <span>{group.category}</span>
                      <small>总数 {group.items.length}</small>
                    </td>
                  </tr>
                  {renderRows(group.items)}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
              <strong>管理分类</strong>
              <button className="modal-close" onClick={() => setManageCats(false)}>✕</button>
            </div>

            <div className="trip-category-section">
              <h3>当前分类</h3>
              <div className="trip-category-list">
                {cats.map((c) => (
                  <div key={c} className="trip-category-row">
                    {editingCategoryName === c ? (
                      <>
                        <span>
                          <input
                            className="trip-category-inline-input"
                            autoFocus
                            value={editingCategoryValue}
                            onChange={(e) => setEditingCategoryValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') saveCategoryName(c)
                              if (e.key === 'Escape') cancelEditCategory()
                            }}
                          />
                          <small>{data.items.filter((it) => (it.category || '通用') === c).length} 个物品</small>
                        </span>
                        <button className="trip-mini-action" onClick={() => saveCategoryName(c)}>保存</button>
                        <button className="trip-mini-action ghost" onClick={cancelEditCategory}>取消</button>
                      </>
                    ) : (
                      <>
                        <span>
                          <b>{c}</b>
                          <small>{data.items.filter((it) => (it.category || '通用') === c).length} 个物品</small>
                        </span>
                        <button
                          className="trip-mini-action"
                          onClick={() => startEditCategory(c)}
                          title={`修改分类 ${c}`}
                        >
                          修改
                        </button>
                        <button
                          className="trip-mini-action danger"
                          onClick={async () => {
                            if (c === '通用') {
                              notify('通用分类不能删除', 'error')
                              return
                            }
                            if (confirm(`确定删除分类"${c}"？该分类下的物品将移至"通用"分类。`)) {
                              const itemsToUpdate = data.items.filter(it => (it.category || '通用') === c)
                              for (const item of itemsToUpdate) {
                                await recategorize(item.id, '通用', false)
                              }
                              setCustomCats((prev) => prev.filter((x) => x !== c))
                              setCat((cur) => cur === c ? '通用' : cur)
                              setBulkCat((cur) => cur === c ? '通用' : cur)
                              setFilterCat((cur) => cur === c ? '全部' : cur)
                              reload()
                            }
                          }}
                          title={`删除分类 ${c}`}
                        >
                          删除
                        </button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="trip-category-section">
              <h3>新增分类</h3>
              <div className="trip-category-add">
                <input
                  type="text"
                  placeholder="例如：电子产品"
                  value={categoryName}
                  onChange={(e) => setCategoryName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') addCategory()
                  }}
                />
                <button
                  className="trip-btn primary"
                  onClick={addCategory}
                  disabled={!categoryName.trim()}
                >
                  确定添加
                </button>
              </div>
            </div>
          </div>
        </div>, document.body)}

      {editingItem && createPortal(
        <div className="modal-mask" onClick={() => setEditingItem(null)}>
          <div className="modal trip-manage-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>编辑物品</strong>
              <button className="modal-close" onClick={() => setEditingItem(null)}>✕</button>
            </div>
            <div className="trip-packing-edit-form">
              <label>
                <span>物品名</span>
                <input autoFocus value={editingName} onChange={(e) => setEditingName(e.target.value)} />
              </label>
              <label>
                <span>分类</span>
                <select value={editingCat} onChange={(e) => setEditingCat(e.target.value)}>
                  {cats.map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
            </div>
            <div className="trip-modal-foot">
              <button className="trip-btn danger" onClick={() => {
                if (!editingItem) return
                remove(editingItem.id, editingItem.name)
                setEditingItem(null)
              }}>删除</button>
              <span />
              <button className="trip-btn" onClick={() => setEditingItem(null)}>取消</button>
              <button className="trip-btn primary" onClick={saveEditingItem}>保存</button>
            </div>
          </div>
        </div>, document.body)}

      {batchOpen && createPortal(
        <div className="modal-mask" onClick={() => setBatchOpen(false)}>
          <div className="modal trip-manage-modal trip-batch-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <strong>批量维护</strong>
              <button className="modal-close" onClick={() => setBatchOpen(false)}>✕</button>
            </div>
            {selectedItems.length > 0 && (
              <div className="trip-batch-selected trip-batch-section">
                <b>已选 {selectedItems.length} 个物品</b>
                <small>{selectedItems.map((it) => it.name).join('、')}</small>
                <div className="trip-batch-actions">
                  <select value={bulkCat} onChange={(e) => setBulkCat(e.target.value)}>
                    {cats.map((c) => <option key={c}>{c}</option>)}
                  </select>
                  <button className="trip-btn" onClick={bulkMove}>把所选移到这个分类</button>
                  <button className="trip-btn danger" onClick={bulkDelete}>删除所选</button>
                  <button className="trip-btn ghost" onClick={() => setSelectedIds([])}>取消选择</button>
                </div>
              </div>
            )}
            <div className="trip-batch-section">
              <b>批量新增物品</b>
              <small>一小行就是一个物品；每行可以单独选择分类。</small>
              <div className="trip-batch-rows">
                {batchRows.map((row, index) => (
                  <div className="trip-batch-row" key={index}>
                    <select
                      value={row.category}
                      onChange={(e) => setBatchRows((prev) => prev.map((item, idx) => (
                        idx === index ? { ...item, category: e.target.value } : item
                      )))}
                    >
                      {cats.map((c) => <option key={c}>{c}</option>)}
                    </select>
                    <input
                      value={row.name}
                      placeholder="物品名"
                      onChange={(e) => setBatchRows((prev) => prev.map((item, idx) => (
                        idx === index ? { ...item, name: e.target.value } : item
                      )))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          setBatchRows((prev) => [...prev, { name: '', category: row.category }])
                        }
                      }}
                    />
                    <button
                      className="trip-btn tiny ghost"
                      onClick={() => setBatchRows((prev) => prev.length <= 1
                        ? [{ name: '', category: bulkCat || '通用' }]
                        : prev.filter((_, idx) => idx !== index))}
                    >
                      删除本行
                    </button>
                  </div>
                ))}
              </div>
              <button
                className="trip-btn"
                onClick={() => setBatchRows((prev) => [...prev, { name: '', category: bulkCat || prev.at(-1)?.category || '通用' }])}
              >
                + 添加一行
              </button>
            </div>
            <div className="trip-modal-foot">
              <span />
              <button className="trip-btn" onClick={() => setBatchOpen(false)}>关闭</button>
              <button className="trip-btn primary" onClick={batchAdd}>批量添加</button>
            </div>
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
