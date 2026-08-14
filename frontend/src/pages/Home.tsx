import { isValidElement, lazy, memo, Suspense, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { BrandIcon, BrandWordmark } from '../components/Brand'
import { AdminAnnouncements, AnnouncementModal, AnnouncementPanel, useAnnouncementUnread } from '../components/Announcements'
import { NotificationPanel, type ProductNotification } from '../components/Notifications'
import type { SocialTab } from '../components/SocialHub'
import { AdminInvites } from '../components/AdminInvites'
import { AdminSupport, SupportChat, useSupportUnread } from '../components/Support'
import { useToast } from '../components/toast-context'
import { API, authFetch, setToken } from '../api'
import { useNotificationUnread } from '../hooks/useNotificationUnread'
import { useTypewriter } from '../hooks/useTypewriter'
import {
  expectedHintFor,
  expectedSecondsFor,
  extractGuideHeadings,
  formatThinkingElapsed,
  headingAnchor,
  inferThinkingMode,
  inferThinkingProgress,
  initialLayoutMode,
  MAX_PROMPT_LENGTH,
  mergeMessages,
  buildBudgetRoulettePrompt,
  buildInspirationImportPrompt,
  buildJourneyPreviewPrompt,
  buildTrendingChips,
  extractPublicInspirationUrls,
  isCompactDestinationIdea,
  type StarterChip,
  formatLastSeen,
  normalizePrompt,
  prepareMarkdown,
  shouldFollowBottom,
  shouldSubmitComposer,
  THINKING_STAGES,
  thinkingProgressRatio,
  waitReassurance,
  type LayoutMode,
} from '../interaction'

const TripsOverlay = lazy(() => import('./Trips'))
const SocialHub = lazy(() => import('../components/SocialHub'))

interface SubagentRun {
  id: string
  name: string          // 子代理类型，如 api-researcher
  title: string         // 从任务描述提炼的短标题
  prompt: string        // 任务描述摘要
  status: 'running' | 'done' | 'failed'
  tokens: number
  elapsed_s: number
  // Phase 94：完整派发内容与回复。**轮询返回的列表里没有这两项**（后端剥掉了），
  // 点开某一条时才走 /subagents/{id} 取，避免 800ms 轮询每次都拖几十 KB。
  prompt_full?: string
  output?: string
}

interface Msg {
  id: string
  role: 'user' | 'assistant' | 'progress' | 'action'
  content: string
  reasoning?: string | null
  meta?: {
    sources?: { title: string; url: string }[]
    handoff?: {
      site: string
      site_name: string
      url: string
      mode?: 'local' | 'remote'
      screenshot?: boolean
    }
    confirm?: { id: string; question: string; source?: { title?: string; domain?: string } }
    confirm_reply?: { confirm_id: string; choice: string }
    memories_used?: MemoryRef[]
    memories_saved?: { op: string; type: string; content: string }[]
    skills_used?: string[]
    artifacts?: { name: string; size: number; url: string }[]
    imported_trip_id?: string
    streaming?: boolean
    poster?: PosterData
    budget?: BudgetData
    preliminary?: boolean  // Phase 71：深度研究的初步回答，完整版随后到达
    hint?: string
    hint_prompt?: string
    // Phase 76：区域型提问的候选目的地，点一下即作为下一轮提问发出
    candidates?: { name: string; reason: string; tag: string }[]
    // Phase 88：深度研究并发派出的子代理运行态（面板置于对话最上方）
    subagents?: SubagentRun[]
  } | null
}

interface PosterStop {
  name: string
  type: string
  note: string
  photo: string
  order: number
}

interface PosterDay {
  day: number
  title: string
  subtitle: string
  distance: string
  duration: string
  map: string
  stops: PosterStop[]
}

interface PosterHotel {
  name: string
  area: string
  price: string
  note: string
  photo: string
}

interface PosterFood {
  name: string
  note: string
  photo: string
}

interface PosterSpecialty {
  name: string
  note: string
}

interface PosterData {
  title: string
  subtitle: string
  theme: string
  destination: string
  overall_map: string
  days: PosterDay[]
  hotels: PosterHotel[]
  foods: PosterFood[]
  specialties: PosterSpecialty[]
  tips: string[]
}

// Phase 67 预算面板：金额均为人均口径，汇总由后端重算
interface BudgetItem {
  category: string
  name: string
  day: number
  amount: number
  note: string
}

interface BudgetReservation {
  name: string
  channel: string
  advance: string
  note: string
}

interface BudgetData {
  currency: string
  headcount: number
  total: number
  group_total: number
  by_category: { category: string; amount: number; pct: number }[]
  by_day: { day: number; amount: number }[]
  shared: number
  items: BudgetItem[]
  reservations: BudgetReservation[]
  notes: string[]
}

interface MemoryRef {
  kind: 'memory' | 'past_chat'
  type?: string
  title?: string
  content: string
}

interface MemoryItem {
  id: string
  type: string
  key?: string | null
  explicit?: boolean
  content: string
  updated_at: string | null
}

const MEM_TYPE_LABEL: Record<string, string> = {
  preference: '偏好',
  fact: '事实',
  trip_state: '行程',
}

interface Conv {
  id: string
  title: string
  updated_at: string
}

function groupConvs(convs: Conv[]): { label: string; items: Conv[] }[] {
  const now = new Date()
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const today = startOfDay(now)
  const day = 86400000
  const buckets: Record<string, Conv[]> = { 今天: [], 昨天: [], '前 7 天': [], 更早: [] }
  for (const c of convs) {
    // updated_at 是服务器本地时区（CST）的无时区时间串，按本地时间解析（勿加 Z）
    const t = startOfDay(new Date(c.updated_at))
    if (t >= today) buckets['今天'].push(c)
    else if (t >= today - day) buckets['昨天'].push(c)
    else if (t >= today - 7 * day) buckets['前 7 天'].push(c)
    else buckets['更早'].push(c)
  }
  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }))
}

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // HTTP/IP 环境下 Clipboard API 可能存在但拒绝，继续走兼容路径。
  }
  const field = document.createElement('textarea')
  field.value = text
  field.style.position = 'fixed'
  field.style.opacity = '0'
  document.body.appendChild(field)
  field.select()
  const copied = document.execCommand('copy')
  document.body.removeChild(field)
  return copied
}

function reactText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(reactText).join('')
  if (isValidElement<{ children?: ReactNode }>(node)) return reactText(node.props.children)
  return ''
}

const CHIPS = [
  { icon: '🏨', label: '筛选酒店', description: '比较位置、价格与真实体验', meta: '实时查询 · 约 2-3 分钟', text: '帮我查一下成都市中心性价比高的酒店' },
  { icon: '🗺️', label: '规划路线', description: '按距离和节奏安排每日动线', meta: '路线规划 · 约 3-4 分钟', text: '帮我规划成都3天的游玩路线，节奏轻松一点' },
  { icon: '📖', label: '生成攻略', description: '景点、美食、交通与预算一次整理', meta: '完整攻略 · 约 3-4 分钟', text: '我想去成都玩3天，喜欢美食，帮我出一份攻略' },
  { icon: '⚖️', label: '帮我做选择', description: '多城市、多方案与预算深度比较', meta: '深度推理 · 约 4–6 分钟', text: '帮我对比成都和重庆，结合美食、预算和游玩节奏推荐更适合我的目的地', deep: true },
]

const FALLBACK_DESTINATIONS = ['杭州', '平潭岛', '武功山', '武汉']

interface InspirationLaunch {
  prompt: string
  deepReasoning?: boolean
}

export default function Home({ user, onLogout, onPasswordChanged, onProfileChanged }: {
  user: { username: string; is_admin: boolean; display_name?: string; avatar_url?: string; must_change_password?: boolean }
  onLogout: () => void
  onPasswordChanged?: () => void
  onProfileChanged?: (profile: { display_name: string; avatar_url: string }) => void
}) {
  const { notify } = useToast()
  const [cid, setCid] = useState<string | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [convs, setConvs] = useState<Conv[]>([])
  const [input, setInput] = useState('')
  const [showSocial, setShowSocial] = useState(false)
  const [socialLaunch, setSocialLaunch] = useState<{ tab: SocialTab; destination: string }>({ tab: 'station', destination: '天堂寨' })
  const openSocial = useCallback((tab: SocialTab = 'station', destination = '天堂寨') => {
    setSocialLaunch({ tab, destination })
    setShowSocial(true)
  }, [])
  const [running, setRunning] = useState(false)
  const [deep, setDeep] = useState(() => localStorage.getItem('travel_deep') === '1')
  const toggleDeep = useCallback(() => {
    setDeep((d) => {
      localStorage.setItem('travel_deep', d ? '0' : '1')
      return !d
    })
  }, [])
  const enableDeep = useCallback(() => {
    localStorage.setItem('travel_deep', '1')
    setDeep(true)
  }, [])
  const [sandbox, setSandbox] = useState(() => localStorage.getItem('travel_sandbox') === '1')
  const toggleSandbox = useCallback(() => {
    setSandbox((s) => {
      localStorage.setItem('travel_sandbox', s ? '0' : '1')
      return !s
    })
  }, [])
  const [showMemories, setShowMemories] = useState(false)
  // 协同板开关/当前 board 存进 URL hash，刷新后恢复（否则回主对话）
  const [showTrips, setShowTrips] = useState(() => window.location.hash.startsWith('#trips'))
  const [tripsBoard, setTripsBoard] = useState<string | null>(() => {
    const m = window.location.hash.match(/^#trips=(.+)$/)
    return m ? decodeURIComponent(m[1]) : null
  })
  // showTrips/tripsBoard 变化即同步 hash（replaceState 不污染历史栈）
  useEffect(() => {
    const target = showTrips ? (tripsBoard ? `#trips=${encodeURIComponent(tripsBoard)}` : '#trips') : ''
    if (window.location.hash !== target) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search + target)
    }
  }, [showTrips, tripsBoard])
  // Phase 35b：全局轮询待接受的行程邀请（30s），弹卡接受/拒绝
  const [tripInvites, setTripInvites] = useState<{ trip_id: string; title: string; inviter: string }[]>([])
  // Phase 42：分享链接自动加入（?join=token 在 App 入口暂存，这里消费）
  useEffect(() => {
    const token = localStorage.getItem('travel_pending_join')
    if (!token) return
    localStorage.removeItem('travel_pending_join')
    authFetch(`${API}/trips/join`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }).then(async (res) => {
      if (res.ok) {
        const { trip_id } = await res.json()
        setTripsBoard(trip_id)
        setShowTrips(true)
        notify('已加入协同行程', 'success')
      } else {
        const body = await res.json().catch(() => null)
        notify(body?.detail || '分享链接已失效或无法加入', 'error')
      }
    }).catch(() => notify('暂时无法加入协同行程，请检查网络', 'error'))
  }, [notify])

  useEffect(() => {
    const pull = async () => {
      try {
        const res = await authFetch(`${API}/trips/invites/pending`)
        if (res.ok) setTripInvites(await res.json())
      } catch { /* 静默 */ }
    }
    pull()
    const t = window.setInterval(pull, 30000)
    return () => window.clearInterval(t)
  }, [])
  const respondInvite = useCallback(async (tripId: string, accept: boolean) => {
    try {
      const res = await authFetch(`${API}/trips/${tripId}/invites/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ accept }),
      })
      if (!res.ok) throw new Error()
      setTripInvites((list) => list.filter((i) => i.trip_id !== tripId))
      notify(accept ? '已接受邀请' : '已拒绝邀请', accept ? 'success' : 'info')
      if (accept) {
        setTripsBoard(tripId)
        setShowTrips(true)
      }
    } catch {
      notify('处理邀请失败，请稍后重试', 'error')
    }
  }, [notify])
  const [showSkills, setShowSkills] = useState(false)
  const [traceFor, setTraceFor] = useState<string | null>(null)  // 打开调用链抽屉的 turn_id
  // 发送门闩（Phase 92）：同步生效，堵住 setRunning 提交前的那段窗口
  const sendingRef = useRef(false)
  // Phase 90：对话 / 轨迹 双视图。轨迹按需加载（只在切过去时才打 Langfuse）
  const [chatTab, setChatTab] = useState<'chat' | 'traj'>('chat')
  const toggleTrace = useCallback((turnId: string) => {
    setTraceFor((cur) => (cur === turnId ? null : turnId))
  }, [])
  const [showAdmin, setShowAdmin] = useState(false)
  // Phase 73 客服：抽屉关着时低频轮询未读（红点）；打开时暂停，改由抽屉自己 3s 轮询消息
  // （抽屉读取即已读，关闭那一刻 hook 会立刻重跑一次，红点自然清零）
  const [showSupport, setShowSupport] = useState(false)
  const supportUnread = useSupportUnread(true, showSupport)
  // Phase 76：攻略出完后主动给「下一步」。08-04 那批 8 个拿到攻略的人里只有 1 个
  // 自己摸到了「出海报 → 带真实日期回来重排」这条路径——它不该藏在一排小按钮里。
  const refineByDate = useCallback(() => {
    setInput('我的日期定了：8月15日出发、8月18日返程，帮我把行程排到每一天（含具体时间）')
  }, [])
  // Phase 76：点候选目的地 = 直接作为下一轮提问发出，用户不用再打字
  const pickDestination = useCallback((name: string) => {
    if (running) return
    send(`去${name}`)
  }, [running])  // eslint-disable-line react-hooks/exhaustive-deps
  // Phase 74 公告：顶栏喇叭红点。抽屉打开时暂停轮询，打开即全部标记已读
  // Phase 75：空状态素材（平台热门目的地 + 常驻城市）。失败就用静态示例兜底，绝不白屏。
  const [onboarding, setOnboarding] = useState<{ home_city: string; trending: string[] } | null>(null)
  const [destinationCovers, setDestinationCovers] = useState<Record<string, string>>({})
  useEffect(() => {
    authFetch(`${API}/onboarding`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setOnboarding)
      .catch(() => setOnboarding(null))
  }, [])
  const trendingDestinations = onboarding?.trending?.length ? onboarding.trending : FALLBACK_DESTINATIONS
  const trendingChips = buildTrendingChips(trendingDestinations, onboarding?.home_city || '')
  const starterChips = trendingChips.length ? trendingChips : CHIPS
  useEffect(() => {
    const cities = Array.from(new Set([...trendingDestinations.slice(0, 4), '天堂寨']))
    if (!cities.length) return
    const params = new URLSearchParams()
    cities.forEach((city) => params.append('destinations', city))
    let active = true
    authFetch(`${API}/onboarding/covers?${params.toString()}`)
      .then((response) => (response.ok ? response.json() : { covers: {} }))
      .then((data) => { if (active) setDestinationCovers(data.covers || {}) })
      .catch(() => { if (active) setDestinationCovers({}) })
    return () => { active = false }
  }, [onboarding]) // eslint-disable-line react-hooks/exhaustive-deps
  const [showAnn, setShowAnn] = useState(false)
  const [annUnread, refreshAnnUnread] = useAnnouncementUnread(showAnn)
  const [showNotifications, setShowNotifications] = useState(false)
  const [socialUnread, refreshSocialUnread] = useNotificationUnread(showNotifications)
  const notificationUnread = annUnread + socialUnread
  const openNotificationTarget = useCallback((item: ProductNotification) => {
    if (item.target_kind === 'relay') {
      openSocial('station', item.meta.destination || '天堂寨')
      return
    }
    openSocial('friends')
  }, [openSocial])
  // 红点太弱容易被忽略 → 有未读时首次直接弹窗。两个约束：
  //   ① 任务运行中不弹（会盖住流式正文，几分钟的等待期被打断很烦），跑完再说
  //   ② 本次会话点过「稍后」就不再弹，但**没确认**的公告下次进来还会弹
  const [annDismissed, setAnnDismissed] = useState(false)
  const showAnnModal = annUnread > 0 && !annDismissed && !running && !showAnn && !showNotifications
  const [collapsed, setCollapsed] = useState(() => window.innerWidth <= 720)  // 手机默认收起（抽屉式）
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(() => (
    initialLayoutMode(
      window.innerWidth,
      localStorage.getItem('travel_layout_mode'),
      window.matchMedia('(pointer: coarse)').matches,
    )
  ))
  const [search, setSearch] = useState('')
  const pollRef = useRef<number | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  // 生成期间每 1.5s 轮询刷新一次消息，若无条件 scrollIntoView 会把用户往回拽，
  // 上翻看前文根本停不住（线上反馈）。只在「用户本来就贴着底部」时才跟随。
  const threadRef = useRef<HTMLDivElement>(null)
  const stickBottomRef = useRef(true)
  const [showJumpBottom, setShowJumpBottom] = useState(false)
  // Phase 30 停滞提示：running 期间超过 30s 消息列表无任何变化 → 显式提示仍在运行
  // （模型长推理/写产物阶段没有新进度气泡，静默转圈像卡死）
  const lastChangeRef = useRef(Date.now())
  const msgSigRef = useRef('')
  const [staleSec, setStaleSec] = useState(0)
  const runStartedAtRef = useRef<number | null>(null)
  const [runElapsedSec, setRunElapsedSec] = useState(0)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (showNotifications) setShowNotifications(false)
      else if (traceFor) setTraceFor(null)
      else if (showAnn) setShowAnn(false)
      else if (showSupport) setShowSupport(false)
      else if (showAdmin) setShowAdmin(false)
      else if (showSkills) setShowSkills(false)
      else if (showMemories) setShowMemories(false)
      else if (showSocial) setShowSocial(false)
      else if (showTrips) { setShowTrips(false); setTripsBoard(null) }
      else if (window.innerWidth <= 720 && !collapsed) setCollapsed(true)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [collapsed, showAdmin, showAnn, showMemories, showNotifications, showSkills, showSocial, showSupport, showTrips, traceFor])
  const trackChange = useCallback((msgs: Msg[]) => {
    const last = msgs[msgs.length - 1]
    const sig = `${msgs.length}:${last ? (last.content?.length ?? 0) + (last.reasoning?.length ?? 0) : 0}`
    if (sig !== msgSigRef.current) {
      msgSigRef.current = sig
      lastChangeRef.current = Date.now()
    }
    setStaleSec(Math.floor((Date.now() - lastChangeRef.current) / 1000))
  }, [])

  useEffect(() => {
    if (!running) {
      runStartedAtRef.current = null
      setRunElapsedSec(0)
      return
    }
    if (runStartedAtRef.current === null) runStartedAtRef.current = Date.now()
    const tick = () => {
      setRunElapsedSec(Math.floor((Date.now() - (runStartedAtRef.current ?? Date.now())) / 1000))
    }
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [running])

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const el = threadRef.current
    stickBottomRef.current = true
    setShowJumpBottom(false)
    if (el) el.scrollTo({ top: el.scrollHeight, behavior })
  }, [])

  const onThreadScroll = useCallback((event: React.UIEvent<HTMLDivElement>) => {
    const follow = shouldFollowBottom(event.currentTarget)
    stickBottomRef.current = follow
    setShowJumpBottom(!follow)
  }, [])

  // 向上滚的瞬间就脱离跟随：只靠 onScroll 的话，程序化平滑滚动自己触发的 scroll 事件
  // 会在动画途中把 near 判回 true，和用户抢方向盘。
  const onThreadWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < 0) stickBottomRef.current = false
  }, [])

  useEffect(() => {
    if (!stickBottomRef.current) return
    const el = threadRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const loadConvs = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/chat/conversations`)
      if (res.ok) setConvs(await res.json())
    } catch {
      /* 列表加载失败不影响对话 */
    }
  }, [])
  useEffect(() => {
    loadConvs()
  }, [loadConvs])

  const stopPoll = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])
  useEffect(() => () => stopPoll(), [stopPoll])

  // 单次拉取（2026-08-13）：轮询间隔与「切回页面立即补拉」共用同一份逻辑
  const pullOnce = useCallback(async (conv: string) => {
    const res = await authFetch(`${API}/chat/${conv}/messages`)
    if (!res.ok) return
    const data = await res.json()
    // 增量合并（2026-08-13 丝滑改造）：未变化的消息保持原对象引用，
    // React.memo 跳过重渲染；只有流式那条/新增消息触发重渲染。
    setMessages((prev) => mergeMessages(prev, data.messages))
    setRunning(data.running)
    trackChange(data.messages)
    if (!data.running) {
      stopPoll()
      loadConvs()
    }
  }, [stopPoll, loadConvs, trackChange])

  const poll = useCallback(
    (conv: string) => {
      stopPoll()
      pollRef.current = window.setInterval(() => {
        void pullOnce(conv)
      }, 800)
    },
    [stopPoll, pullOnce],
  )

  // 切回页面立即补拉一次：用户从别的标签页回来，不等下一个轮询周期（0.8s）也能秒见结果
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && cid && pollRef.current !== null) {
        void pullOnce(cid)
      }
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [cid, pullOnce])

  const selectConv = useCallback(
    async (id: string) => {
      stopPoll()
      if (window.innerWidth <= 720) setCollapsed(true)  // 手机：选完自动收抽屉
      setCid(id)
      setMessages([])
      stickBottomRef.current = true  // 换会话：先回到最新
      setShowJumpBottom(false)
      const res = await authFetch(`${API}/chat/${id}/messages`)
      if (!res.ok) return
      const data = await res.json()
      setMessages(data.messages)
      setRunning(data.running)
      if (data.running) poll(id)
    },
    [stopPoll, poll],
  )

  const newChat = useCallback(() => {
    stopPoll()
    if (window.innerWidth <= 720) setCollapsed(true)
    setCid(null)
    setMessages([])
    setRunning(false)
  }, [stopPoll])

  // 移动底栏是一级导航，不是叠加按钮：切换入口时必须关闭上一层全屏视图。
  const openMobileChat = useCallback(() => {
    setShowSocial(false)
    setShowTrips(false)
    setTripsBoard(null)
    setShowMemories(false)
    setShowSkills(false)
    setShowAdmin(false)
    setTraceFor(null)
    setCollapsed(true)
    newChat()
  }, [newChat])

  const openMobileTrips = useCallback(() => {
    setShowSocial(false)
    setShowMemories(false)
    setShowSkills(false)
    setShowAdmin(false)
    setTraceFor(null)
    setCollapsed(true)
    setShowTrips(true)
  }, [])

  const openMobileHistory = useCallback(() => {
    setShowSocial(false)
    setShowTrips(false)
    setTripsBoard(null)
    setShowMemories(false)
    setShowSkills(false)
    setShowAdmin(false)
    setTraceFor(null)
    setCollapsed(false)
  }, [])

  const openMobileSocial = useCallback(() => {
    setShowTrips(false)
    setTripsBoard(null)
    setShowMemories(false)
    setShowSkills(false)
    setShowAdmin(false)
    setTraceFor(null)
    setCollapsed(true)
    openSocial('station')
  }, [openSocial])

  const changeLayoutMode = useCallback((mode: LayoutMode) => {
    localStorage.setItem('travel_layout_mode', mode)
    setLayoutMode(mode)
    setCollapsed(mode === 'mobile')
  }, [])

  const deleteConv = useCallback(
    async (id: string) => {
      const target = convs.find((c) => c.id === id)
      if (!window.confirm(`删除对话「${target?.title || '未命名对话'}」？此操作无法撤销。`)) return
      try {
        const res = await authFetch(`${API}/chat/conversations/${id}`, { method: 'DELETE' })
        if (!res.ok) throw new Error()
        setConvs((list) => list.filter((c) => c.id !== id))
        if (id === cid) newChat()
        notify('对话已删除', 'success')
      } catch {
        notify('删除失败，请稍后重试', 'error')
      }
    },
    [cid, convs, newChat, notify],
  )

  const stop = useCallback(async () => {
    if (!cid) return
    const res = await authFetch(`${API}/chat/${cid}/stop`, { method: 'POST' }).catch(() => null)
    notify(res?.ok ? '已请求停止，正在保存当前结果' : '停止请求未送达，请重试', res?.ok ? 'info' : 'error')
    // 后端在检查点终稿本轮，轮询会将 running 置为 false
  }, [cid, notify])

  const send = async (text: string, options: { deepReasoning?: boolean } = {}) => {
    const content = normalizePrompt(text)
    // `running` 是 React 状态，setRunning 要到下一次渲染才生效；而它本身又在 await 之后
    // 才设置——两次快速点击都会读到 false 从而都发出去（线上实测双发）。
    // 用 ref 做**同步**门闩：赋值立即可见，覆盖整个 await 窗口。
    if (!content || running || sendingRef.current) return
    sendingRef.current = true
    const requestDeep = options.deepReasoning ?? deep
    try {
      let conv = cid
      if (!conv) {
        const res = await authFetch(`${API}/chat/conversations`, { method: 'POST' })
        if (!res.ok) throw new Error('创建对话失败')
        conv = (await res.json()).conversation_id as string
        setCid(conv)
      }
      const res = await authFetch(`${API}/chat/${conv}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, deep_reasoning: requestDeep, sandbox_enabled: sandbox }),
      })
      if (res.status === 409) {
        // 后端说这轮还在跑（多标签页、或门闩之外的重复提交）。
        // 静默忽略——用户看到的就是"没反应"，而不是一句吓人的报错。
        setRunning(true)
        poll(conv)
        return
      }
      if (!res.ok) throw new Error('发送失败')
      setInput('')
      setMessages((m) => [...m, { id: 'tmp', role: 'user', content }])
      setRunning(true)
      stickBottomRef.current = true  // 自己发了新消息 → 重新贴底跟随
      setShowJumpBottom(false)
      lastChangeRef.current = Date.now()
      setStaleSec(0)
      loadConvs()
      poll(conv)
    } catch {
      notify('消息发送失败，内容已为你保留', 'error')
    } finally {
      sendingRef.current = false
    }
  }

  // Phase 46：从协同板发起「携程实价」——建新会话、强制深度推理（走 guide/携程流水线）、关板打开对话
  const askInChat = useCallback(async (text: string) => {
    try {
      const res = await authFetch(`${API}/chat/conversations`, { method: 'POST' })
      if (!res.ok) return
      const conv = (await res.json()).conversation_id as string
      enableDeep()  // Phase 46.1：本条强制深度推理，把开关也点亮，追问延续深度模式、视觉一致
      setShowTrips(false)
      setTripsBoard(null)
      setCid(conv)
      setMessages([{ id: 'tmp', role: 'user', content: text }])
      setRunning(true)
      stickBottomRef.current = true
      setShowJumpBottom(false)
      lastChangeRef.current = Date.now()
      setStaleSec(0)
      await authFetch(`${API}/chat/${conv}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text, deep_reasoning: true, sandbox_enabled: false }),
      })
      loadConvs()
      poll(conv)
    } catch {
      notify('发起查询失败', 'error')
    }
  }, [loadConvs, poll, notify, enableDeep])

  // 批2：从快答提示卡「一键用深度模式重新生成」——复用原问题、在当前会话强制深度推理重跑，
  // 不用复制粘贴。走 send 相同的 POST，只是 deep_reasoning 硬编 true 且点亮开关。
  const regenerateDeep = useCallback(async (text: string) => {
    const content = normalizePrompt(text)
    if (!content || running || !cid) return
    try {
      enableDeep()
      const res = await authFetch(`${API}/chat/${cid}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, deep_reasoning: true, sandbox_enabled: sandbox }),
      })
      if (!res.ok) throw new Error('发送失败')
      setMessages((m) => [...m, { id: 'tmp', role: 'user', content }])
      setRunning(true)
      lastChangeRef.current = Date.now()
      setStaleSec(0)
      loadConvs()
      poll(cid)
    } catch {
      notify('重新生成失败，请手动重试', 'error')
    }
  }, [cid, running, sandbox, enableDeep, loadConvs, poll, notify])

  const empty = messages.length === 0
  const filteredConvs = search.trim()
    ? convs.filter((c) => c.title.toLowerCase().includes(search.trim().toLowerCase()))
    : convs
  // action 消息不渲染，只用来还原确认卡片的「已选择」状态。
  // Phase 60：当前轮普通 progress 与空流式占位收拢进统一思考工作台；
  // 登录接管/来源确认/深度提示仍保留原交互卡片。
  const allVisibleMessages = messages.filter((m) => m.role !== 'action')
  const lastUserIndex = messages.findLastIndex((m) => m.role === 'user')
  const currentTurnMessages = messages.slice(lastUserIndex + 1)
  const currentStreaming = currentTurnMessages.findLast(
    (m) => m.role === 'assistant' && !!m.meta?.streaming,
  )
  const latestPlainProgress = currentTurnMessages.findLast(
    (m) => m.role === 'progress' && !m.meta?.confirm && !m.meta?.handoff && !m.meta?.hint,
  )
  const lastVisibleMessage = allVisibleMessages[allVisibleMessages.length - 1]
  const waitingForUser = !!(
    running
    && lastVisibleMessage?.role === 'progress'
    && (lastVisibleMessage.meta?.confirm || lastVisibleMessage.meta?.handoff)
  )
  // Phase 88：取最新一条带 subagents 的 progress 快照（后端就地更新同一条消息）
  const subagentRuns = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const runs = messages[i].meta?.subagents
      if (runs && runs.length) return runs
    }
    return [] as SubagentRun[]
  }, [messages])

  const showThinkingWorkspace = running && !currentStreaming?.content.trim() && !waitingForUser
  const visibleMessages = allVisibleMessages.filter((m) => {
    if (running && m.role === 'progress' && !m.meta?.confirm && !m.meta?.handoff && !m.meta?.hint) return false
    if (showThinkingWorkspace && m.role === 'assistant' && m.meta?.streaming && !m.content.trim()) return false
    return true
  })
  const thinkingText = latestPlainProgress?.content
    || (currentStreaming ? '正在生成你的旅行方案…' : '正在理解你的旅行需求…')
  const thinkingStage = inferThinkingProgress(
    currentTurnMessages
      .filter((m) => m.role === 'progress' && !m.meta?.confirm && !m.meta?.handoff && !m.meta?.hint)
      .map((m) => m.content),
    {
    streaming: !!currentStreaming,
    reasoning: !!currentStreaming?.reasoning,
    },
  )
  // Phase 71.1：按实际路由判定模式（开关只表达意愿）——开着深度推理问明确规划问题时，
  // 后端按设计仍走攻略流水线，此时不该显示「通常 4-6 分钟」。
  const thinkingMode = inferThinkingMode(
    currentTurnMessages
      .filter((m) => m.role === 'progress' && !m.meta?.confirm && !m.meta?.handoff && !m.meta?.hint)
      .map((m) => m.content),
    !!currentStreaming,
  )
  // Phase 71：把已走过的进度做成「足迹」列表——长任务的等待期需要有内容可读，
  // 只显示一行「当前动作」的话，用户看不出到底推进了多少。最新的排前面，不含当前那条。
  const thinkingTrail = currentTurnMessages
    .filter((m) => m.role === 'progress' && !m.meta?.confirm && !m.meta?.handoff && !m.meta?.hint)
    .map((m) => m.content.trim())
    .filter((t) => t && t !== thinkingText)
    .slice(-5)
    .reverse()
  // 每条消息所属轮次 = 它之前最近一条 user 消息的 id（调用链按 turn_id 匹配 trace）
  const turnIds: string[] = []
  {
    let lastUser = ''
    for (const m of visibleMessages) {
      if (m.role === 'user') lastUser = m.id
      turnIds.push(lastUser)
    }
  }
  const confirmReplies = new Map<string, string>()
  for (const m of messages) {
    const r = m.meta?.confirm_reply
    if (m.role === 'action' && r) confirmReplies.set(r.confirm_id, r.choice)
  }
  const activeConversationTitle = convs.find((conv) => conv.id === cid)?.title || (empty ? '开始新旅程' : '旅行规划')

  return (
    <div className={`app view-${layoutMode}${collapsed ? ' collapsed' : ''}`}>
      {user.must_change_password && <AdminPasswordBanner onDone={onPasswordChanged} />}
      {!collapsed && <button className="sidebar-scrim" aria-label="关闭侧栏" onClick={() => setCollapsed(true)} />}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">
            <BrandIcon size={20} />
          </span>
          <BrandWordmark className="brand-name" />
          <button className="sidebar-toggle" aria-label="收起侧栏" onClick={() => setCollapsed(true)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M9 4v16" />
            </svg>
          </button>
        </div>
        <button className="nav-item" onClick={newChat}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
          </svg>
          <span>新对话</span>
        </button>
        <div className="nav-item search-item">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
          </svg>
          <input
            className="search-input"
            placeholder="搜索对话"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="conv-list">
          {filteredConvs.length === 0 && (
            <div className="sidebar-empty">{search ? '没有匹配的对话' : '暂无历史对话'}</div>
          )}
          {groupConvs(filteredConvs).map((g) => (
            <div key={g.label}>
              <div className="sidebar-section">{g.label}</div>
              {g.items.map((c) => (
                <div
                  key={c.id}
                  className={`conv-item${c.id === cid ? ' active' : ''}`}
                  onClick={() => selectConv(c.id)}
                  onKeyDown={(e) => {
                    if (e.target !== e.currentTarget) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      selectConv(c.id)
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-current={c.id === cid ? 'page' : undefined}
                  title={c.title}
                >
                  <span className="conv-title">{c.title}</span>
                  <button
                    className="conv-del"
                    aria-label="删除对话"
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteConv(c.id)
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <button className="nav-item" onClick={() => openSocial('station')}>
            <span className="nav-social-icon" aria-hidden>⌁</span>
            <span>同游圈</span>
          </button>
          <button className="nav-item" onClick={() => setShowTrips(true)}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 20l-5.5-2V5l5.5 2 6-2 5.5 2v13l-5.5-2zM9 7v13M15 5v13" />
            </svg>
            <span>协同行程</span>
          </button>
          <button className="nav-item" onClick={() => setShowMemories(true)}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
            </svg>
            <span>记忆</span>
          </button>
          <button className="nav-item" onClick={() => setShowSkills(true)}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2l2.4 5.2L20 8l-4 4 1 6-5-2.8L7 18l1-6-4-4 5.6-.8z" />
            </svg>
            <span>技能</span>
          </button>
          <button className="nav-item" onClick={() => setShowSupport(true)}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
            </svg>
            <span>联系客服</span>
            {supportUnread > 0 && <b className="support-badge">{supportUnread}</b>}
          </button>
          {user.is_admin && (
            <button className="nav-item" onClick={() => setShowAdmin(true)}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
              <span>用户管理</span>
            </button>
          )}
          <div className="user-card">
            <button className="user-profile-trigger" onClick={() => openSocial('profile')} aria-label="打开个人主页">
              <span className="user-avatar">{user.avatar_url ? <img src={user.avatar_url} alt="" /> : (user.username[0] || 'U').toUpperCase()}</span>
              <span className="user-meta">
                <span className="user-name" title={user.display_name || user.username}>{user.display_name || user.username}</span>
                <span className="user-plan">{user.is_admin ? '管理员' : `@${user.username}`}</span>
              </span>
            </button>
            <button className="user-logout" onClick={onLogout} aria-label="退出登录" title="退出登录">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
              </svg>
            </button>
          </div>
          <a className="sidebar-beian" href="https://beian.miit.gov.cn" target="_blank" rel="noopener noreferrer">
            鄂ICP备2026020535号-2
          </a>
        </div>
      </aside>
      {collapsed && (
        <button className="sidebar-expand" aria-label="展开侧栏" onClick={() => setCollapsed(false)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" />
          </svg>
        </button>
      )}

      {showTrips && (
        <Suspense fallback={<div className="overlay-loading" role="status"><span className="spinner" /> 正在打开协同行程…</div>}>
          <TripsOverlay
            username={user.username}
            layoutMode={layoutMode}
            initialBoardId={tripsBoard}
            onBoardChange={setTripsBoard}
            onClose={() => { setShowTrips(false); setTripsBoard(null) }}
            onOpenConversation={(convId) => {
              setShowTrips(false)
              setTripsBoard(null)
              selectConv(convId)
            }}
            onAskInChat={askInChat}
          />
        </Suspense>
      )}
      {tripInvites.length > 0 && (
        <div className="invite-toasts">
          {tripInvites.map((iv) => (
            <div key={iv.trip_id} className="invite-toast">
              <div className="invite-toast-text">
                🗺️ <b>{iv.inviter}</b> 邀请你协同规划「{iv.title}」
              </div>
              <div className="invite-toast-ops">
                <button className="trip-btn primary" onClick={() => respondInvite(iv.trip_id, true)}>接受</button>
                <button className="trip-btn" onClick={() => respondInvite(iv.trip_id, false)}>拒绝</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {showMemories && <MemoryPanel onClose={() => setShowMemories(false)} />}
      {showSkills && <SkillPanel onClose={() => setShowSkills(false)} />}
      {traceFor && cid && <TraceDrawer cid={cid} turnId={traceFor} onClose={() => setTraceFor(null)} />}
      {showAdmin && <AdminPanel onClose={() => setShowAdmin(false)} />}
      <SupportChat open={showSupport} onClose={() => setShowSupport(false)} />
      <NotificationPanel
        open={showNotifications}
        onClose={() => setShowNotifications(false)}
        announcementUnread={annUnread}
        onOpenAnnouncements={() => setShowAnn(true)}
        onNavigate={openNotificationTarget}
        onUnreadChange={refreshSocialUnread}
      />
      <AnnouncementPanel open={showAnn} onClose={() => setShowAnn(false)} onRead={refreshAnnUnread} />
      <AnnouncementModal
        open={showAnnModal}
        onAcknowledged={() => { setAnnDismissed(true); refreshAnnUnread() }}
        onDismiss={() => setAnnDismissed(true)}
      />

      <main className="main">
        <header className="app-topbar">
          <button className="mobile-menu-button" aria-label="打开历史对话" onClick={() => setCollapsed(false)}>
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <div className="topbar-context">
            <span className="topbar-mark"><BrandIcon size={21} /></span>
            <span>
              <small>17tongyou</small>
              <strong title={activeConversationTitle}>{activeConversationTitle}</strong>
            </span>
          </div>
          <button
            className={`topbar-bell${notificationUnread > 0 ? ' has-unread' : ''}`}
            aria-label={notificationUnread > 0 ? `通知，${notificationUnread} 条未读` : '通知'}
            title="通知"
            onClick={() => setShowNotifications((value) => !value)}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 11a9 9 0 0 1 9-9v0a9 9 0 0 1 9 9v3l1.5 3h-21L3 14z" />
              <path d="M9.5 20a2.5 2.5 0 0 0 5 0" />
            </svg>
            {notificationUnread > 0 && <b className="bell-count">{notificationUnread > 99 ? '99+' : notificationUnread}</b>}
          </button>
          <div className="layout-switch" role="group" aria-label="界面视图">
            <button
              className={layoutMode === 'desktop' ? 'active' : ''}
              aria-pressed={layoutMode === 'desktop'}
              onClick={() => changeLayoutMode('desktop')}
              title="切换网页端布局"
            >
              <span aria-hidden>▱</span>
              网页端
            </button>
            <button
              className={layoutMode === 'mobile' ? 'active' : ''}
              aria-pressed={layoutMode === 'mobile'}
              onClick={() => changeLayoutMode('mobile')}
              title="切换移动端布局"
            >
              <span aria-hidden>▯</span>
              移动端
            </button>
          </div>
        </header>
        {empty ? (
          <div className="hero">
            <div className="hero-soft-glow" aria-hidden />
            <div className="hero-content">
              <div className="hero-eyebrow">17同游 · 一起规划，一起出发</div>
              <h1 className="hero-title">想去哪儿，就从这里出发</h1>
              <p className="hero-sub">说一个目的地、贴一篇攻略，或者直接问我旅行问题。</p>
              <InspirationLaunchpad
                homeCity={onboarding?.home_city || ''}
                running={running}
                suggestions={starterChips.slice(0, 4)}
                covers={destinationCovers}
                onSocial={() => openSocial('station')}
                onLaunch={({ prompt, deepReasoning }: InspirationLaunch) => {
                  if (deepReasoning) enableDeep()
                  void send(prompt, { deepReasoning })
                }}
              />
            </div>
          </div>
        ) : (
          <>
            {cid && (
              <div className="chat-tabs" role="tablist" aria-label="对话视图">
                <button role="tab" aria-selected={chatTab === 'chat'}
                  className={chatTab === 'chat' ? 'active' : ''}
                  onClick={() => setChatTab('chat')}>对话</button>
                <button role="tab" aria-selected={chatTab === 'traj'}
                  className={chatTab === 'traj' ? 'active' : ''}
                  onClick={() => setChatTab('traj')}>轨迹</button>
              </div>
            )}
            {chatTab === 'traj' && cid ? (
              <div className="thread"><div className="thread-inner">
                <SurfacePanel cid={cid} tick={running ? 1 : 0} />
                <TrajectoryView cid={cid} running={running} />
              </div></div>
            ) : (
            <div className="thread" ref={threadRef} onScroll={onThreadScroll} onWheel={onThreadWheel}>
              <div className="thread-inner">
                {visibleMessages.map((m, i) => (
                  <Message
                    key={m.id + i}
                    msg={m}
                    isLast={i === visibleMessages.length - 1}
                    running={running}
                    cid={cid}
                    confirmReplies={confirmReplies}
                    deepOn={deep}
                    onEnableDeep={enableDeep}
                    onPickDestination={pickDestination}
                    onRefineByDate={refineByDate}
                    onRegenerateDeep={regenerateDeep}
                    turnId={turnIds[i]}
                    traceOpen={traceFor === turnIds[i]}
                    onToggleTrace={toggleTrace}
                    onPosterStart={() => {
                      if (cid) {
                        setRunning(true)
                        poll(cid)
                      }
                    }}
                    onImportTrip={(tripId) => {
                      setTripsBoard(tripId)
                      setShowTrips(true)
                    }}
                  />
                ))}
                {subagentRuns.length > 0 && cid && <SubagentPanel runs={subagentRuns} cid={cid} />}
                {showThinkingWorkspace && (
                  <ThinkingWorkspace
                    stage={thinkingStage}
                    activity={thinkingText}
                    trail={thinkingTrail}
                    elapsedSec={runElapsedSec}
                    staleSec={staleSec}
                    mode={thinkingMode}
                    onStop={stop}
                  />
                )}
                <div ref={bottomRef} />
              </div>
              {showJumpBottom && (
                <button className="jump-bottom" onClick={() => scrollToBottom()}>
                  <span aria-hidden>↓</span>
                  {running ? '回到最新内容' : '回到底部'}
                </button>
              )}
            </div>
            )}
            <div className="composer-wrap">
              <Composer value={input} onChange={setInput} onSend={send} onStop={stop} running={running} deep={deep} onToggleDeep={toggleDeep} sandbox={sandbox} onToggleSandbox={toggleSandbox} chips={starterChips} />
            </div>
            <div className="composer-hint">内容由 AI 生成，价格与营业信息请以平台实时数据为准</div>
          </>
        )}
      </main>
      {showSocial && (
        <Suspense fallback={<div className="overlay-loading" role="status"><span className="spinner" /> 正在打开同游圈…</div>}>
          <SocialHub
            initialTab={socialLaunch.tab}
            initialDestination={socialLaunch.destination}
            onClose={() => setShowSocial(false)}
            onProfileChanged={onProfileChanged}
          />
        </Suspense>
      )}
      <nav className="mobile-bottom-nav" aria-label="移动端主导航">
        <button className={empty && !showTrips && !showMemories && !showSocial ? 'active' : ''} onClick={openMobileChat}>
          <span aria-hidden>✦</span>
          <small>新对话</small>
        </button>
        <button className={showTrips ? 'active' : ''} onClick={openMobileTrips}>
          <span aria-hidden>🗺</span>
          <small>行程</small>
        </button>
        <button className={!collapsed && !showTrips && !showSocial ? 'active' : ''} onClick={openMobileHistory}>
          <span aria-hidden>☰</span>
          <small>历史</small>
        </button>
        <button className={showSocial ? 'active' : ''} onClick={openMobileSocial}>
          <span aria-hidden>⌁</span>
          <small>同游圈</small>
        </button>
      </nav>
    </div>
  )
}

/**
 * Phase 77.1：单入口自动分流。
 * 有 URL → 收藏整理；没有主输入但有出发地+预算 → 预算推荐；其余 → 旅行预演。
 * 产品内部分类不再暴露成三个等权 tab。
 */
function InspirationLaunchpad({
  homeCity,
  running,
  suggestions,
  covers,
  onSocial,
  onLaunch,
}: {
  homeCity: string
  running: boolean
  suggestions: StarterChip[]
  covers: Record<string, string>
  onSocial: () => void
  onLaunch: (launch: InspirationLaunch) => void
}) {
  const [error, setError] = useState('')
  const [idea, setIdea] = useState('')
  const [origin, setOrigin] = useState(homeCity)
  const [days, setDays] = useState('3 天')
  const [budget, setBudget] = useState('')
  const [pace, setPace] = useState('松弛一点')
  const ideaRef = useRef<HTMLTextAreaElement>(null)

  // onboarding 比首屏组件晚返回；只补空的出发地，绝不覆盖用户已经输入的城市。
  useEffect(() => {
    if (!homeCity) return
    setOrigin((current) => current || homeCity)
  }, [homeCity])

  const urls = extractPublicInspirationUrls(idea)
  const routeKind = urls.length
    ? 'import'
    : (!idea.trim() && origin.trim() && budget.trim()
        ? 'budget'
        : (isCompactDestinationIdea(idea) ? 'preview' : 'question'))
  const actionLabel = routeKind === 'import'
    ? '整理成行程'
    : routeKind === 'budget'
      ? '按预算推荐'
      : routeKind === 'question' && idea.trim()
        ? '发送问题'
        : '开始规划'

  const launch = () => {
    setError('')
    if (urls.length) {
      const prompt = buildInspirationImportPrompt({ urls, origin, days })
      onLaunch({ prompt, deepReasoning: true })
      return
    }
    if (!idea.trim() && origin.trim() && budget.trim()) {
      const prompt = buildBudgetRoulettePrompt({ origin, budget, days, vibe: pace })
      onLaunch({ prompt, deepReasoning: true })
      return
    }
    const prompt = routeKind === 'question'
      ? idea.trim()
      : buildJourneyPreviewPrompt({ destination: idea, origin, days, pace, budget })
    if (!prompt) {
      setError('输入一个目的地或攻略链接；如果还没想好，就填写出发地和预算。')
      return
    }
    onLaunch({ prompt })
  }

  const pickSuggestion = (city: string) => {
    setIdea(city)
    setError('')
    requestAnimationFrame(() => ideaRef.current?.focus())
  }

  return (
    <div className="journey-launcher">
      <section className="inspiration-launchpad simple" aria-label="开始规划旅行">
        <form className="unified-start" onSubmit={(event) => { event.preventDefault(); launch() }}>
        <label className="unified-idea">
          <span>今天想从哪里开始？</span>
          <textarea
            ref={ideaRef}
            value={idea}
            onChange={(event) => { setIdea(event.target.value); setError('') }}
            placeholder={'输入目的地、粘贴攻略链接\n或直接问“第一次去日本怎么准备？”'}
            rows={2}
            autoFocus
          />
        </label>

        <div className="unified-constraints">
          <label><span>出发地</span><input value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="可不填" /></label>
          <label><span>天数</span><select value={days} onChange={(event) => setDays(event.target.value)}><option>周末 2 天</option><option>3 天</option><option>4-5 天</option><option>一周左右</option><option>还没确定</option></select></label>
          <label><span>预算</span><span className="money-input"><i>¥</i><input inputMode="numeric" value={budget} onChange={(event) => setBudget(event.target.value.replace(/[^0-9]/g, ''))} placeholder="可不填" /></span></label>
          <label><span>节奏</span><select value={pace} onChange={(event) => setPace(event.target.value)}><option>松弛一点</option><option>张弛有度</option><option>尽量多玩</option><option>早上不要赶</option></select></label>
        </div>

        <div className="unified-footer">
          <div>
            <p className={`inspiration-status${error ? ' error' : ''}`} aria-live="polite">
              {error || (routeKind === 'import'
                ? `已识别 ${urls.length} 条链接，将自动整理`
                : routeKind === 'budget'
                  ? '没选目的地，将根据预算推荐'
                  : routeKind === 'question' && idea.trim()
                    ? '会自动判断快速回答还是深度规划'
                    : '会检查路线、节奏、预算和备选方案')}
            </p>
          </div>
          <button className="unified-submit" type="submit" disabled={running}>{actionLabel}<span aria-hidden>→</span></button>
        </div>
        </form>
      </section>

      <section className="social-entry" aria-label="目的地旅行接力站">
        <button type="button" onClick={onSocial}>
          <span className="social-entry-people" aria-hidden>
            <i>旅</i><i>山</i><i>友</i>
          </span>
          <span className="social-entry-copy">
            <em>NEW · 真实旅行者接力</em>
            <strong>有人正在天堂寨，把现场情况留给下一位</strong>
            <small>看 72 小时现场情报、抄真实路线，也把你的经验接下去</small>
          </span>
          <span className="social-entry-meta"><b>准备去</b><b>正在玩</b><b>刚回来</b></span>
          <span className="social-entry-cta">进入接力站 <b aria-hidden>→</b></span>
        </button>
      </section>

      {!!suggestions.length && (
        <section className="trending-destinations" aria-labelledby="trending-destinations-title">
          <div className="trending-destinations-head">
            <div>
              <span className="trending-kicker">近 30 天真实热问</span>
              <h2 id="trending-destinations-title">最近大家都想去</h2>
            </div>
            <small>选一个，再补充你的预算和节奏</small>
          </div>
          <div className="trending-destination-grid">
            {suggestions.map((item, index) => {
              const city = item.label.replace(/怎么玩$/, '')
              const cover = covers[city]
              return (
                <button className="destination-card" type="button" key={city} onClick={() => pickSuggestion(city)} aria-label={`选择${city}`}>
                  <span className={`destination-cover cover-tone-${index % 4}`}>
                    <span className="destination-cover-fallback" aria-hidden>{item.icon}</span>
                    {cover && <img src={`${API}/img?u=${encodeURIComponent(cover)}`} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
                    <em>TOP {index + 1}</em>
                  </span>
                  <span className="destination-card-copy">
                    <strong>{city}</strong>
                    <span>{item.description}</span>
                    <small>带入规划 <b aria-hidden>↗</b></small>
                  </span>
                </button>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

interface AdminUser {
  id: string
  username: string
  is_admin: boolean
  conversations: number
  memories: number
  created_at: string | null
  last_seen_at: string | null
  online: boolean          // 服务端判定，前端不重算阈值
}

function AdminPanel({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<{ total: number; users: AdminUser[] } | null>(null)
  const [tab, setTab] = useState<'users' | 'support' | 'invites' | 'announce'>('users')
  const [roleBusy, setRoleBusy] = useState('')
  const { notify } = useToast()
  const [unreadTotal, setUnreadTotal] = useState(0)
  const [now, setNow] = useState(() => Date.now())

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/admin/users`)
      if (res.ok) {
        setData(await res.json())
        setNow(Date.now())
      }
    } catch {
      /* 面板加载失败不影响主界面 */
    }
  }, [])

  useEffect(() => {
    load()
    // 在线状态会过期，面板开着时定期刷新，否则「在线」会一直挂着不掉
    const timer = window.setInterval(load, 30000)
    return () => window.clearInterval(timer)
  }, [load])

  useEffect(() => {
    const tick = async () => {
      try {
        const res = await authFetch(`${API}/admin/support/threads`)
        if (res.ok) setUnreadTotal((await res.json()).unread_total || 0)
      } catch {
        /* 徽标拿不到不影响 */
      }
    }
    tick()
    const timer = window.setInterval(tick, 15000)
    return () => window.clearInterval(timer)
  }, [])

  const onlineCount = data?.users.filter((u) => u.online).length ?? 0

  const setRole = async (u: AdminUser, isAdmin: boolean) => {
    const verb = isAdmin ? '升为管理员' : '降为普通用户'
    if (!window.confirm(`确定把「${u.username}」${verb}吗？`)) return
    setRoleBusy(u.id)
    try {
      const res = await authFetch(`${API}/admin/users/${u.id}/role`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_admin: isAdmin }),
      })
      if (!res.ok) {
        // 服务端的防呆理由（改自己 / 最后一个管理员）要原样告诉用户
        const detail = await res.json().catch(() => null)
        throw new Error(detail?.detail || '操作失败')
      }
      notify(`已把「${u.username}」${verb}`, 'success')
      load()
    } catch (err) {
      notify(err instanceof Error ? err.message : '操作失败', 'error')
    } finally {
      setRoleBusy('')
    }
  }

  return (
    <div className="modal-mask panel-mask" onClick={onClose}>
      <div className="modal side-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>用户管理</strong>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="admin-tabs">
          <button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>
            用户
          </button>
          <button className={tab === 'support' ? 'active' : ''} onClick={() => setTab('support')}>
            客服会话
            {unreadTotal > 0 && <b className="support-badge">{unreadTotal}</b>}
          </button>
          <button className={tab === 'invites' ? 'active' : ''} onClick={() => setTab('invites')}>
            邀请码
          </button>
          <button className={tab === 'announce' ? 'active' : ''} onClick={() => setTab('announce')}>
            公告
          </button>
        </div>
        {tab === 'users' ? (
          <>
            <div className="modal-sub">
              {data ? `共 ${data.total} 位注册用户 · ${onlineCount} 人在线` : '加载中…'}
            </div>
            <div className="modal-body">
              {data?.users.map((u) => (
                <div key={u.id} className="admin-row">
                  <span className="admin-name">
                    <span className={`online-dot ${u.online ? 'on' : ''}`} aria-hidden />
                    {u.is_admin ? '👑 ' : ''}{u.username}
                  </span>
                  <span className="admin-stat">
                    <b className={u.online ? 'is-online' : ''}>
                      {u.online ? '在线' : formatLastSeen(u.last_seen_at, now)}
                    </b>
                    {u.conversations} 会话 · {u.memories} 记忆
                    <button
                      className={u.is_admin ? 'role-btn demote' : 'role-btn'}
                      disabled={roleBusy === u.id}
                      onClick={() => setRole(u, !u.is_admin)}
                    >
                      {u.is_admin ? '取消管理员' : '设为管理员'}
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </>
        ) : tab === 'support' ? (
          <AdminSupport />
        ) : tab === 'invites' ? (
          <AdminInvites />
        ) : (
          <AdminAnnouncements />
        )}
      </div>
    </div>
  )
}

function MemoryPanel({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<MemoryItem[] | null>(null)
  const [tidying, setTidying] = useState(false)
  const { notify } = useToast()

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/memory`)
      if (!res.ok) throw new Error()
      setItems(await res.json())
    } catch {
      setItems([])
      notify('记忆加载失败，请稍后重试', 'error')
    }
  }, [notify])
  useEffect(() => {
    load()
  }, [load])

  const remove = async (id: string) => {
    if (!window.confirm('删除这条记忆？删除后不会再用于后续规划。')) return
    const res = await authFetch(`${API}/memory/${id}`, { method: 'DELETE' }).catch(() => null)
    if (res?.ok) {
      setItems((list) => (list ? list.filter((m) => m.id !== id) : list))
      notify('记忆已删除', 'success')
    } else {
      notify('删除记忆失败', 'error')
    }
  }

  const consolidate = async () => {
    setTidying(true)
    try {
      const res = await authFetch(`${API}/memory/consolidate`, { method: 'POST' })
      if (res.ok) {
        await load()
        notify('记忆已整理完成', 'success')
      } else {
        notify('整理记忆失败', 'error')
      }
    } catch {
      notify('整理记忆失败，请检查网络', 'error')
    } finally {
      setTidying(false)
    }
  }

  return (
    <div className="modal-mask panel-mask" onClick={onClose}>
      <div className="modal side-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>🧠 记忆</strong>
          <div className="modal-head-actions">
            <button className="mem-tidy-btn" onClick={consolidate} disabled={tidying || !items?.length}>
              {tidying ? '整理中…' : '✨ 整理记忆'}
            </button>
            <button className="modal-close" onClick={onClose}>
              ✕
            </button>
          </div>
        </div>
        <div className="modal-sub">从对话中自动积累的长期记忆，会用于后续规划。「整理记忆」会去重合并成规范条目。</div>
        <div className="modal-body">
          {items === null && <div className="modal-empty">加载中…</div>}
          {items?.length === 0 && <div className="modal-empty">还没有记忆，多聊几次就有了</div>}
          {items?.map((m) => (
            <div key={m.id} className="memory-row">
              <span className="memory-card-tag">{m.key || MEM_TYPE_LABEL[m.type] || m.type}</span>
              <span className="memory-row-content">
                {m.content}
                {m.explicit && <span className="mem-explicit" title="用户明确表达">·亲述</span>}
              </span>
              <button className="memory-row-del" onClick={() => remove(m.id)} aria-label="删除">
                🗑
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------- 用户上传技能面板（Phase 27） ----------

interface SkillItem {
  id: string
  name: string
  description: string
  content: string
  files: string[]
  updated_at: string | null
}

function SkillPanel({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<SkillItem[] | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const zipInputRef = useRef<HTMLInputElement>(null)
  const { notify } = useToast()

  const load = useCallback(async () => {
    const res = await authFetch(`${API}/skills`)
    if (res.ok) setItems(await res.json())
  }, [])
  useEffect(() => {
    load()
  }, [load])

  const remove = async (id: string) => {
    if (!window.confirm('删除这个技能？后续深度研究将不再使用它。')) return
    const res = await authFetch(`${API}/skills/${id}`, { method: 'DELETE' }).catch(() => null)
    if (res?.ok) {
      setItems((list) => (list ? list.filter((s) => s.id !== id) : list))
      notify('技能已删除', 'success')
    } else {
      notify('删除技能失败', 'error')
    }
  }

  const upload = async () => {
    if (!draft.trim()) return
    setUploading(true)
    setError('')
    try {
      const res = await authFetch(`${API}/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft }),
      })
      if (res.ok) {
        setDraft('')
        await load()
        notify('技能上传成功', 'success')
      } else {
        const body = await res.json().catch(() => null)
        setError(body?.detail || '上传失败')
      }
    } finally {
      setUploading(false)
    }
  }

  const uploadZip = async (file: File) => {
    setUploading(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await authFetch(`${API}/skills/upload`, { method: 'POST', body: form })
      if (res.ok) {
        await load()
        notify('技能包上传成功', 'success')
      } else {
        const body = await res.json().catch(() => null)
        setError(body?.detail || '上传失败')
      }
    } finally {
      setUploading(false)
      if (zipInputRef.current) zipInputRef.current.value = ''
    }
  }

  return (
    <div className="modal-mask panel-mask" onClick={onClose}>
      <div className="modal side-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>🧩 我的技能</strong>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-sub">
          只在你自己的「深度推理」问题里生效，别人看不到。粘贴完整 SKILL.md（含 ---
          frontmatter---），或者打包上传 zip（SKILL.md + 参考文件/脚本）。同名会覆盖更新。
          脚本默认只能被读取当参考、不会被执行——发消息时额外打开「🐳 沙箱执行」开关，
          本条消息才会真的在隔离沙箱里运行脚本（服务器未配置沙箱时开关不生效）。
        </div>
        <div className="skill-form">
          <textarea
            className="skill-textarea"
            placeholder={'---\nname: my-skill\ndescription: 这个技能做什么、什么时候用\n---\n\n正文...'}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={6}
          />
          {error && <div className="skill-error">{error}</div>}
          <div className="skill-form-actions">
            <button className="mem-tidy-btn" onClick={upload} disabled={uploading || !draft.trim()}>
              {uploading ? '上传中…' : '上传文本'}
            </button>
            <button className="mem-tidy-btn" onClick={() => zipInputRef.current?.click()} disabled={uploading}>
              📦 上传 zip
            </button>
            <input
              ref={zipInputRef}
              type="file"
              accept=".zip"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) uploadZip(file)
              }}
            />
          </div>
        </div>
        <div className="modal-body">
          {items === null && <div className="modal-empty">加载中…</div>}
          {items?.length === 0 && <div className="modal-empty">还没有自己的技能，上传一个试试</div>}
          {items?.map((s) => (
            <div key={s.id} className="memory-row">
              <span className="memory-card-tag">{s.name}</span>
              <span className="memory-row-content">
                {s.description}
                {s.files.length > 1 && <span className="skill-file-count"> · {s.files.length} 个文件</span>}
              </span>
              <button className="memory-row-del" onClick={() => remove(s.id)} aria-label="删除">
                🗑
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}


// ---------- 会话轨迹（Phase 90，借鉴 dsh Trajectory）----------

interface TrajEvent {
  id: string
  turnId: string
  turnNo: number
  step: number
  lane: 'input' | 'model' | 'tools'
  type: string
  name: string
  model: string
  startMs: number
  offsetMs: number
  durMs: number | null
  tokens: number | null
  input: string
  output: string
  inputFull: string
  outputFull: string
  usage: Record<string, number>
}

interface SurfaceEntry {
  id: string
  role: string
  chars: number
  surfaceOp: string
  inSurface: boolean
  shadowedBy: string | null
  at: string
  preview: string
  truncated: boolean
}

interface SurfaceStats {
  logged: number; loggedChars: number
  surface: number; surfaceChars: number
  shadowed: number; shadowedChars: number
  summaries: { id: string; chars: number; preview: string }[]
  nonContext: number
  entries: SurfaceEntry[]
}

/** 日志 vs 投影（Phase 91）：压缩到底压掉了什么，一眼可见。 */
const ROLE_LABEL: Record<string, string> = {
  user: '用户', assistant: '助手', summary: '摘要',
}

function SurfacePanel({ cid, tick }: { cid: string; tick: number }) {
  const [s, setS] = useState<SurfaceStats | null>(null)
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    authFetch(`${API}/chat/${cid}/surface`)
      .then(async (r) => { if (alive && r.ok) setS(await r.json()) })
      .catch(() => {})
    return () => { alive = false }
  }, [cid, tick])
  if (!s) return null
  const kc = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

  return (
    <div className={`surface-panel${open ? ' open' : ''}`}>
      <button className="surface-summary" onClick={() => setOpen((v) => !v)}
        aria-expanded={open} aria-label="展开查看每条日志与遮蔽情况">
        <span className="surface-cell">
          <b>{s.logged}</b><small>日志条数</small>
        </span>
        <i className="surface-arrow" aria-hidden="true">→</i>
        <span className="surface-cell">
          <b>{s.surface}</b><small>进上下文</small>
        </span>
        {s.shadowed > 0 && (
          <span className="surface-cell shadowed">
            <b>{s.shadowed}</b><small>被摘要遮蔽</small>
          </span>
        )}
        <span className="surface-cell chars">
          <b>{kc(s.surfaceChars)}</b>
          <small>字 / 日志 {kc(s.loggedChars)}</small>
        </span>
        <span className="surface-caret" aria-hidden="true">{open ? '︿' : '﹀'}</span>
      </button>

      {open && (
        <div className="surface-detail">
          <p className="surface-note">
            日志只增不减；被摘要遮蔽的条目**不进模型上下文，但原文仍在**，随时可回放。
            {s.nonContext > 0 && ` 另有 ${s.nonContext} 条进度/动作消息本就不参与上下文。`}
          </p>
          <ul className="surface-entries">
            {s.entries.map((e, i) => (
              <li key={e.id}
                className={`surface-entry role-${e.role}${e.inSurface ? '' : ' shadowed'}`}>
                <button className="surface-entry-head"
                  onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                  <span className="surface-no">{i + 1}</span>
                  <span className={`surface-role role-${e.role}`}>
                    {ROLE_LABEL[e.role] || e.role}
                  </span>
                  <span className="surface-preview">{e.preview || '（空）'}</span>
                  <span className="surface-entry-meta">
                    {!e.inSurface && <em className="tag-shadowed">已遮蔽</em>}
                    {e.surfaceOp === 'replace' && <em className="tag-replace">遮蔽者</em>}
                    <em>{e.chars} 字</em>
                  </span>
                </button>
                {expanded === e.id && (
                  <div className="surface-entry-body">
                    <pre className="traj-pre">{e.preview}{e.truncated ? '\n…（预览截断，完整内容见对话流）' : ''}</pre>
                    <div className="surface-entry-facts">
                      <span>投影：{e.inSurface ? '进上下文' : '被遮蔽'}</span>
                      <span>surface_op：{e.surfaceOp}</span>
                      {e.at && <span>{e.at.slice(0, 19).replace('T', ' ')}</span>}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

const LANES: { key: TrajEvent['lane']; label: string }[] = [
  { key: 'input', label: 'Input' },
  { key: 'model', label: 'Model' },
  { key: 'tools', label: 'Tools' },
]

/** 会话轨迹：三泳道密度条 + 按时间排的事件流。
 *  回答的是「这个会话一路上都发生了什么、时间花在哪」——
 *  与「调用链」抽屉（单轮内部树）互补。 */
function TrajectoryView({ cid, running }: { cid: string; running: boolean }) {
  const [data, setData] = useState<{
    enabled: boolean; events: TrajEvent[]; turns: { id: string; route: string | null }[]; spanMs: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [failed, setFailed] = useState(false)
  const [picked, setPicked] = useState<TrajEvent | null>(null)
  const [tick, setTick] = useState(0)
  const [live, setLive] = useState(true)

  // 实时轨迹：运行中每 4s 拉一次（Langfuse 埋点有落库延迟，更快没意义）；
  // 空闲时停轮询，避免一直打 Langfuse。
  useEffect(() => {
    if (!live || !running) return
    const t = window.setInterval(() => setTick((v) => v + 1), 4000)
    return () => window.clearInterval(t)
  }, [live, running])

  useEffect(() => {
    let alive = true
    if (tick === 0) setLoading(true)   // 只有首次显示「正在读取」，刷新时不闪
    setFailed(false)
    authFetch(`${API}/chat/${cid}/trajectory`)
      .then(async (r) => {
        if (!alive) return
        if (!r.ok) { setFailed(true); return }
        setData(await r.json())
      })
      .catch(() => alive && setFailed(true))
      .finally(() => alive && setLoading(false))
    return () => { alive = false }
  }, [cid, tick])

  if (loading) return <div className="traj-empty">正在读取轨迹…</div>
  if (failed) return <div className="traj-empty">轨迹服务暂时不可用。</div>
  if (!data?.enabled) {
    return <div className="traj-empty">未启用可观测埋点，轨迹不可用（需要配置 Langfuse）。</div>
  }
  if (!data.events.length) return <div className="traj-empty">这个会话还没有轨迹记录。</div>

  const kw = q.trim().toLowerCase()
  const shown = kw
    ? data.events.filter((e) =>
      `${e.name} ${e.model} ${e.input} ${e.output}`.toLowerCase().includes(kw))
    : data.events
  const span = Math.max(data.spanMs, 1)
  const totalMs = data.events.reduce((a, e) => a + (e.durMs || 0), 0)
  const fmtMs = (ms: number | null) => {
    if (!ms) return ''
    return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
  }

  return (
    <div className="traj">
      <div className="traj-head">
        <span className="traj-stat">{data.turns.length} 轮</span>
        <span className="traj-stat">{data.events.length} 个事件</span>
        <span className="traj-stat">累计 {fmtMs(totalMs)}</span>
        <span className="traj-stat">跨度 {fmtMs(span)}</span>
        <button className={`traj-live${live && running ? ' on' : ''}`}
          onClick={() => { setLive((v) => !v); setTick((v) => v + 1) }}
          title={running ? '运行中每 4 秒自动刷新' : '当前空闲，点一下手动刷新'}>
          {live && running ? '● 实时' : '↻ 刷新'}
        </button>
        <input className="traj-search" placeholder="搜索工具名 / 内容…"
          value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {/* 密度条：一眼看出这段时间在等模型还是在跑工具，以及工具是否密集到不正常 */}
      <div className="traj-lanes" aria-label="时间线概览">
        {LANES.map((lane) => (
          <div key={lane.key} className="traj-lane">
            <span className="traj-lane-name">{lane.label}</span>
            <div className="traj-lane-track">
              {data.events.filter((e) => e.lane === lane.key).map((e) => (
                <i
                  key={e.id}
                  className={`traj-tick lane-${lane.key}`}
                  style={{
                    left: `${(e.offsetMs / span) * 100}%`,
                    width: `${Math.max(0.35, ((e.durMs || 0) / span) * 100)}%`,
                  }}
                  title={`${e.name}${e.durMs ? ` · ${fmtMs(e.durMs)}` : ''}`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      <ul className="traj-list">
        {shown.map((e) => (
          <li key={e.id} className={`traj-row lane-${e.lane}${picked?.id === e.id ? ' picked' : ''}`}
            onClick={() => setPicked(e)} role="button" tabIndex={0}
            onKeyDown={(k) => k.key === 'Enter' && setPicked(e)}>
            <span className={`traj-badge lane-${e.lane}`}>
              {e.lane === 'model' ? 'MODEL' : e.lane === 'tools' ? 'TOOL' : 'USER'}
            </span>
            <span className="traj-body">
              <b>{e.name}{e.model ? ` · ${e.model}` : ''}</b>
              {e.input && <small className="traj-in">{e.input}</small>}
              {e.output && <small className="traj-out">→ {e.output}</small>}
            </span>
            <span className="traj-meta">
              {e.tokens ? <em>{e.tokens} tok</em> : null}
              {e.durMs ? <em>{fmtMs(e.durMs)}</em> : null}
            </span>
          </li>
        ))}
        {!shown.length && <li className="traj-empty">没有匹配「{q}」的事件。</li>}
      </ul>
      {picked && <TrajDetail ev={picked} onClose={() => setPicked(null)} />}
    </div>
  )
}

/** 轨迹详情：Summary / Preview / Raw 三视图（借鉴 dsh 的节点详情面板）。 */
function TrajDetail({ ev, onClose }: { ev: TrajEvent; onClose: () => void }) {
  const [tab, setTab] = useState<'summary' | 'preview' | 'raw'>('preview')
  const raw = JSON.stringify(
    { name: ev.name, type: ev.type, model: ev.model, durMs: ev.durMs, usage: ev.usage,
      input: ev.inputFull, output: ev.outputFull }, null, 2)

  return createPortal(
    <div className="traj-detail-mask" onClick={onClose}>
      <div className="traj-detail" onClick={(e) => e.stopPropagation()}>
        <div className="traj-detail-head">
          <span className={`traj-badge lane-${ev.lane}`}>
            {ev.lane === 'model' ? 'MODEL' : ev.lane === 'tools' ? 'TOOL' : 'USER'}
          </span>
          <b>Turn {ev.turnNo} · Step {ev.step}</b>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="traj-detail-tabs">
          {(['summary', 'preview', 'raw'] as const).map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
              {t === 'summary' ? 'Summary' : t === 'preview' ? 'Preview' : 'Raw'}
            </button>
          ))}
        </div>
        <div className="traj-detail-body">
          {tab === 'summary' && (
            <dl className="traj-kv">
              <dt>名称</dt><dd>{ev.name}</dd>
              <dt>类型</dt><dd>{ev.type}</dd>
              {ev.model && <><dt>模型</dt><dd>{ev.model}</dd></>}
              <dt>耗时</dt><dd>{ev.durMs ? `${ev.durMs} ms` : '—'}</dd>
              <dt>Token</dt>
              <dd>{Object.keys(ev.usage || {}).length
                ? Object.entries(ev.usage).map(([k, v]) => `${k} ${v}`).join(' · ')
                : '—'}</dd>
            </dl>
          )}
          {tab === 'preview' && (
            <>
              <div className="traj-detail-label">输入</div>
              <pre className="traj-pre">{ev.inputFull || '（空）'}</pre>
              <div className="traj-detail-label">输出</div>
              <pre className="traj-pre">{ev.outputFull || '（空）'}</pre>
            </>
          )}
          {tab === 'raw' && <pre className="traj-pre">{raw}</pre>}
        </div>
      </div>
    </div>,
    document.body,
  )
}

// ---------- 调用链抽屉（Phase 25） ----------

interface TraceNode {
  id: string
  parentId: string | null
  type: string
  name: string
  model: string
  startTime: string
  durMs: number | null
  input: string
  output: string
  usage: { input?: number; output?: number; total?: number }
}

interface TraceData {
  enabled: boolean
  trace: { id: string; name: string; latency: number | null; timestamp: string; route?: string | null } | null
  nodes: TraceNode[]
}

// 类型徽章：文案 + 配色 class（对齐 Langfuse UI：TRACE 紫 / CHAIN 蓝 / AGENT 靛 /
// GEN 绿 / TOOL 红 / SPAN·EVENT 灰）
const NODE_BADGE: Record<string, { label: string; cls: string }> = {
  TRACE: { label: 'TRACE', cls: 'trace' },
  CHAIN: { label: 'CHAIN', cls: 'chain' },
  AGENT: { label: 'AGENT', cls: 'agent' },
  GENERATION: { label: 'GEN', cls: 'gen' },
  TOOL: { label: 'TOOL', cls: 'tool' },
  SPAN: { label: 'SPAN', cls: 'span' },
  EVENT: { label: 'EVENT', cls: 'span' },
}

function fmtMs(ms: number | null): string {
  if (ms == null) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${ms}ms`
}

/** JSON 尝试 pretty-print；解析失败（截断 payload 等）原样返回 */
function prettyJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2)
  } catch {
    return s
  }
}

function TraceDrawer({ cid, turnId, onClose }: { cid: string; turnId: string; onClose: () => void }) {
  const [data, setData] = useState<TraceData | null>(null)
  const [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  useEffect(() => {
    setData(null)
    setError('')
    setSelectedId(null)
    setCollapsed(new Set())
    authFetch(`${API}/chat/${cid}/trace?turn_id=${turnId}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        setData(await res.json())
      })
      .catch(() => setError('调用链服务暂时不可用'))
  }, [cid, turnId])

  // 按 parentId 建树（子节点按 startTime 排序；父不在集合内的孤儿挂根下）
  const nodes = data?.nodes ?? []
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const children = new Map<string, TraceNode[]>()
  const roots: TraceNode[] = []
  for (const n of nodes) {
    if (n.parentId && byId.has(n.parentId)) {
      const arr = children.get(n.parentId) ?? []
      arr.push(n)
      children.set(n.parentId, arr)
    } else {
      roots.push(n)
    }
  }
  const bySt = (a: TraceNode, b: TraceNode) => a.startTime.localeCompare(b.startTime)
  roots.sort(bySt)
  children.forEach((arr) => arr.sort(bySt))

  // 迷你时间条：相对整轮的偏移与宽度
  const t0 = roots.length ? Date.parse(roots[0].startTime) : 0
  const totalMs = Math.max(1, (data?.trace?.latency ?? 0) * 1000)
  const bar = (n: TraceNode) => {
    const left = Math.min(96, Math.max(0, ((Date.parse(n.startTime) - t0) / totalMs) * 100))
    const width = Math.min(100 - left, Math.max(1.5, ((n.durMs ?? 0) / totalMs) * 100))
    return { left: `${left}%`, width: `${width}%` }
  }

  const selected = selectedId ? byId.get(selectedId) : undefined

  const renderNode = (n: TraceNode, depth: number): ReactNode => {
    const kids = children.get(n.id) ?? []
    const isCollapsed = collapsed.has(n.id)
    const badge = NODE_BADGE[n.type] || NODE_BADGE.SPAN
    return (
      <div key={n.id}>
        <button
          className={`trace-node-row${selectedId === n.id ? ' selected' : ''}`}
          style={{ paddingLeft: 8 + depth * 16 }}
          onClick={() => setSelectedId(n.id)}
        >
          <span
            className={`trace-caret${kids.length ? '' : ' empty'}`}
            onClick={(e) => {
              if (!kids.length) return
              e.stopPropagation()
              setCollapsed((s) => {
                const next = new Set(s)
                if (next.has(n.id)) next.delete(n.id)
                else next.add(n.id)
                return next
              })
            }}
          >
            {kids.length ? (isCollapsed ? '▸' : '▾') : ''}
          </span>
          <span className={`trace-badge ${badge.cls}`}>{badge.label}</span>
          <span className="trace-node-main">
            <span className="trace-name">{n.name || '(未命名)'}</span>
            <span className="trace-timebar"><i style={bar(n)} /></span>
          </span>
          <span className="trace-dur">{fmtMs(n.durMs)}</span>
        </button>
        {!isCollapsed && kids.map((k) => renderNode(k, depth + 1))}
      </div>
    )
  }

  return (
    <div className="trace-drawer wide">
      <div className="trace-head">
        <strong>🔗 调用链</strong>
        {data?.trace?.route && <span className="trace-route">{data.trace.route}</span>}
        <button className="modal-close" onClick={onClose}>✕</button>
      </div>
      {error && <div className="modal-empty">{error}</div>}
      {!error && data === null && <div className="modal-empty">加载中…</div>}
      {data && !data.enabled && <div className="modal-empty">未启用调用链埋点（LANGFUSE_ENABLED）</div>}
      {data && data.enabled && !data.trace && (
        <div className="modal-empty">该轮没有调用链记录（可能早于埋点上线）</div>
      )}
      {data?.trace && (
        <div className="trace-split">
          <div className="trace-tree">
            <div className="trace-tree-head">观测树 <span>{nodes.length} 条</span></div>
            <div className="trace-node-row root" onClick={() => setSelectedId(null)}>
              <span className="trace-caret empty" />
              <span className="trace-badge trace">TRACE</span>
              <span className="trace-node-main">
                <span className="trace-name">{data.trace.name || 'conversation_turn'}</span>
                <span className="trace-timebar"><i style={{ left: 0, width: '100%' }} /></span>
              </span>
              <span className="trace-dur">
                {data.trace.latency != null ? `${data.trace.latency.toFixed(1)}s` : ''}
              </span>
            </div>
            {roots.map((n) => renderNode(n, 1))}
          </div>
          <div className="trace-detail">
            {!selected && (
              <div className="modal-empty">点击左侧节点查看输入 / 输出详情</div>
            )}
            {selected && (
              <>
                <div className="trace-detail-head">
                  <span className={`trace-badge ${(NODE_BADGE[selected.type] || NODE_BADGE.SPAN).cls}`}>
                    {(NODE_BADGE[selected.type] || NODE_BADGE.SPAN).label}
                  </span>
                  <strong className="trace-detail-title">{selected.name || '(未命名)'}</strong>
                  {selected.model && <span className="trace-model">{selected.model}</span>}
                  <span className="trace-dur">耗时 {fmtMs(selected.durMs)}</span>
                </div>
                <div className="trace-detail-body">
                  {selected.usage?.total != null && (
                    <div className="trace-usage">
                      tokens：{selected.usage.input ?? '?'} in / {selected.usage.output ?? '?'} out
                      / {selected.usage.total} total
                    </div>
                  )}
                  {selected.input && (
                    <>
                      <div className="trace-payload-label">输入</div>
                      <pre className="trace-pre">{prettyJson(selected.input)}</pre>
                    </>
                  )}
                  {selected.output && (
                    <>
                      <div className="trace-payload-label">输出</div>
                      <pre className="trace-pre">{prettyJson(selected.output)}</pre>
                    </>
                  )}
                  {!selected.input && !selected.output && (
                    <div className="modal-empty">该节点没有记录输入/输出</div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  running,
  autoFocus,
  deep,
  onToggleDeep,
  sandbox,
  onToggleSandbox,
  chips = CHIPS,
}: {
  value: string
  onChange: (v: string) => void
  onSend: (text: string) => void
  onStop?: () => void
  running: boolean
  autoFocus?: boolean
  deep?: boolean
  onToggleDeep?: () => void
  sandbox?: boolean
  onToggleSandbox?: () => void
  chips?: StarterChip[]
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
    el.style.overflowY = el.scrollHeight > 160 ? 'auto' : 'hidden'
  }, [value])

  return (
    <div className="composer-shell">
      {menuOpen && (
        <>
          <div className="composer-menu-mask" onClick={() => setMenuOpen(false)} />
          <div className="composer-menu">
            {chips.map((c) => (
              <button
                key={c.label}
                onClick={() => {
                  onChange(c.text)
                  setMenuOpen(false)
                  ref.current?.focus()
                }}
              >
                <span className="cm-icon">{c.icon}</span>
                <span className="cm-label">{c.label}</span>
                <span className="cm-text">{c.text}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <div className="composer">
        <button
          className="composer-plus"
          aria-label="快捷模板"
          onClick={() => setMenuOpen((o) => !o)}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
        <textarea
          ref={ref}
          rows={1}
          placeholder="问我任何旅行问题…"
          value={value}
          maxLength={MAX_PROMPT_LENGTH}
          aria-label="旅行问题"
          aria-describedby="composer-shortcut"
          autoFocus={autoFocus}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (shouldSubmitComposer({ key: e.key, shiftKey: e.shiftKey, isComposing: e.nativeEvent.isComposing })) {
              e.preventDefault()
              onSend(value)
            }
          }}
        />
        <div className="composer-modes">
          <button
            className={`deep-toggle${deep ? ' on' : ''}`}
            onClick={() => onToggleDeep?.()}
            disabled={running}
            aria-pressed={deep}
            title="深度推理：多来源对比研究，适合多城市对比/预算测算/签证政策等复杂问题（约 3-6 分钟）"
          >
            🧠 深度推理
          </button>
          <button
            className={`sandbox-toggle${sandbox ? ' on' : ''}`}
            onClick={() => onToggleSandbox?.()}
            disabled={running}
            aria-pressed={sandbox}
            title="沙箱执行：给深度推理里的技能脚本真实的代码执行能力（生成 PPT/图表等文件），仅本条消息生效"
          >
            🐳 沙箱执行
          </button>
        </div>
        {running ? (
          <button className="send-btn stop-btn" onClick={() => onStop?.()} aria-label="停止生成">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2.5" />
            </svg>
          </button>
        ) : (
          <button
            className="send-btn"
            onClick={() => onSend(value)}
            disabled={!value.trim()}
            aria-label="发送"
          >
            ↑
          </button>
        )}
      </div>
      <div className="composer-meta" id="composer-shortcut">
        <span><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行</span>
        <span className={value.length >= MAX_PROMPT_LENGTH ? 'limit' : ''}>{value.length}/{MAX_PROMPT_LENGTH}</span>
      </div>
    </div>
  )
}


/** 子代理面板（Phase 88）：深度研究会并发派多个子代理，这里让它们可见。
 *  折叠时只占一行（「N 个子代理」+ 运行中计数），展开看每个在查什么、多久、多少 token。 */
/** 子代理详情抽屉（Phase 94）：完整的派发内容与回复。
 *  内容按需拉取——列表行里没有全文，见 SubagentRun 的注释。 */
function SubagentDetail({ cid, run, onClose }: {
  cid: string
  run: SubagentRun
  onClose: () => void
}) {
  const [tab, setTab] = useState<'input' | 'output'>('input')
  const [full, setFull] = useState<SubagentRun | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    setFull(null)
    setErr('')
    authFetch(`${API}/chat/${cid}/subagents/${run.id}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => alive && setFull(d))
      .catch(() => alive && setErr('取不到这条子代理的详情'))
    return () => {
      alive = false
    }
  }, [cid, run.id])

  // 运行中的子代理还没有回复，默认停在「输入」页，不给一个空白的输出页
  const output = full?.output || ''
  const body = tab === 'input' ? full?.prompt_full || '' : output

  return (
    // 复用轨迹详情的抽屉骨架——同一类「点开看原始输入输出」的东西，
    // 不该有两套长得不一样的壳
    <div className="traj-detail-mask" onClick={onClose}>
      <div className="traj-detail subagent-drawer" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label="子代理详情">
        <div className="traj-detail-head">
          <span className={`subagent-badge status-${run.status}`}>{run.name}</span>
          <b>{run.title}</b>
          <button className="modal-close" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <div className="traj-detail-tabs">
          <button className={tab === 'input' ? 'active' : ''} onClick={() => setTab('input')}>
            派发内容
          </button>
          <button className={tab === 'output' ? 'active' : ''} onClick={() => setTab('output')}>
            回复{run.status === 'running' ? '（运行中）' : ''}
          </button>
        </div>
        <div className="traj-detail-body">
          {err && <p className="traj-empty">{err}</p>}
          {!err && !full && <p className="traj-empty">加载中…</p>}
          {!err && full && !body && (
            <p className="traj-empty">
              {tab === 'output' && run.status === 'running'
                ? '这个子代理还在跑，回复要等它结束。'
                : '（空）'}
            </p>
          )}
          {body && <pre className="traj-pre">{body}</pre>}
        </div>
      </div>
    </div>
  )
}

function SubagentPanel({ runs, cid }: { runs: SubagentRun[]; cid: string }) {
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<SubagentRun | null>(null)
  const active = runs.filter((r) => r.status === 'running').length
  const totalTok = runs.reduce((a, r) => a + (r.tokens || 0), 0)

  const fmtTok = (n: number) =>
    n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}K` : String(n)
  const fmtSec = (s: number) => {
    const v = Math.max(0, Math.round(s))
    return v >= 60 ? `${Math.floor(v / 60)}分${String(v % 60).padStart(2, '0')}秒` : `${v}秒`
  }

  return (
    <div className={`subagent-panel${open ? ' open' : ''}`}>
      <button className="subagent-summary" onClick={() => setOpen((v) => !v)}
        aria-expanded={open} aria-label={`${runs.length} 个子代理，${active} 个运行中`}>
        <span className="subagent-count">{runs.length} 个子代理</span>
        {active > 0 && <i className="subagent-active-dot" aria-hidden="true" />}
        {active > 0 && <span className="subagent-active">{active} 运行中</span>}
        <span className="subagent-total">{fmtTok(totalTok)} tok</span>
        <span className="subagent-caret" aria-hidden="true">{open ? '︿' : '﹀'}</span>
      </button>
      {open && (
        <ul className="subagent-list">
          {runs.map((r) => (
            <li key={r.id} className={`subagent-item status-${r.status}`}>
              {/* 整行可点：进去看完整的派发内容与回复 */}
              <button className="subagent-row" onClick={() => setPicked(r)}
                aria-label={`查看子代理「${r.title}」的派发内容与回复`}>
                <i className="subagent-dot" aria-hidden="true" />
                <span className="subagent-main">
                  <b>{r.title}</b>
                  <small>{r.prompt}</small>
                </span>
                <span className="subagent-meta">
                  <em>{fmtTok(r.tokens)} tok</em>
                  <em>{fmtSec(r.elapsed_s)}</em>
                </span>
                <span className="subagent-open" aria-hidden="true">›</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {picked && (
        <SubagentDetail cid={cid} run={picked} onClose={() => setPicked(null)} />
      )}
    </div>
  )
}

function ThinkingWorkspace({
  stage,
  activity,
  trail,
  elapsedSec,
  staleSec,
  mode,
  onStop,
}: {
  stage: number
  activity: string
  trail: string[]
  elapsedSec: number
  staleSec: number
  mode: string
  onStop: () => void
}) {
  const isPoster = mode === '手账生成'
  const title = isPoster ? '正在绘制你的旅行手账' : mode === '深度推理'
    ? '正在进行深度旅行研究'
    : '正在为你规划这段旅程'
  // Phase 71 预期管理：给出「预计多久」并按预期推进进度条——不确定性比时长更劝退
  const expectedSec = expectedSecondsFor(mode)
  const ratio = thinkingProgressRatio(elapsedSec, expectedSec)
  const overtime = elapsedSec > expectedSec

  return (
    <section className="thinking-workspace" role="status" aria-live="polite" aria-label="智能体工作进度">
      <div className="thinking-glow" aria-hidden />
      <div className="thinking-head">
        <div className="thinking-orb" aria-hidden>
          <span className="thinking-orb-core">✦</span>
          <span className="thinking-orbit orbit-one"><i /></span>
          <span className="thinking-orbit orbit-two"><i /></span>
        </div>
        <div className="thinking-heading">
          <div className="thinking-kicker">
            <span>{mode}</span>
            <i />
            <time>{formatThinkingElapsed(elapsedSec)}</time>
            <i />
            <span className="thinking-expect">{expectedHintFor(mode)}</span>
          </div>
          <h2>{title}</h2>
          <p>{waitReassurance(elapsedSec, mode)}</p>
        </div>
        <button className="thinking-stop" onClick={onStop} aria-label="停止当前任务">
          <span aria-hidden />
          停止
        </button>
      </div>

      <div
        className={`thinking-progress${overtime ? ' overtime' : ''}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
        aria-label="预计完成进度"
      >
        <span className="thinking-progress-fill" style={{ width: `${(ratio * 100).toFixed(1)}%` }} />
      </div>

      <div className="thinking-stages" aria-label="任务阶段">
        {THINKING_STAGES.map((item, index) => {
          const state = index < stage ? 'done' : index === stage ? 'active' : 'waiting'
          return (
            <div className={`thinking-stage ${state}`} key={item.id} aria-current={state === 'active' ? 'step' : undefined}>
              <span className="thinking-stage-mark" aria-hidden>
                {state === 'done' ? '✓' : index + 1}
              </span>
              <span className="thinking-stage-label">{item.label}</span>
              {index < THINKING_STAGES.length - 1 && <i className="thinking-stage-line" aria-hidden />}
            </div>
          )
        })}
      </div>

      <div className="thinking-activity" key={activity}>
        <span className="thinking-activity-spark" aria-hidden>✦</span>
        <span className="thinking-activity-copy">
          <small>当前动作</small>
          <strong>{activity}</strong>
        </span>
        <span className="thinking-activity-wave" aria-hidden><i /><i /><i /></span>
      </div>

      {trail.length > 0 && (
        <ul className="thinking-trail" aria-label="已完成的步骤">
          {trail.map((item, i) => (
            <li key={`${i}-${item}`}>
              <span className="thinking-trail-dot" aria-hidden />
              <span className="thinking-trail-text">{item}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Phase 71：静默期是正常现象（模型在长推理/写终稿），文案不再暗示「可能卡死」，
          并明确告诉用户可以离开——很多人不是没耐心，是怕关了页面白等。 */}
      {staleSec >= 45 && (
        <div className="thinking-stale">
          <span className="thinking-stale-pulse" aria-hidden />
          正在深入思考中（这一步没有中间进度，属正常）。
          <b>可以关掉页面</b>，任务在服务器继续跑，完成后回来在这条会话里就能看到。
        </div>
      )}
    </section>
  )
}

function Message({
  msg,
  isLast,
  running,
  cid,
  confirmReplies,
  onPosterStart,
  onImportTrip,
  deepOn,
  onEnableDeep,
  onPickDestination,
  onRefineByDate,
  onRegenerateDeep,
  turnId,
  traceOpen,
  onToggleTrace,
}: {
  msg: Msg
  isLast: boolean
  running: boolean
  cid: string | null
  confirmReplies: Map<string, string>
  onPosterStart: () => void
  onImportTrip?: (tripId: string) => void
  deepOn?: boolean
  onEnableDeep?: () => void
  onPickDestination?: (name: string) => void
  onRefineByDate?: () => void
  onRegenerateDeep?: (text: string) => void
  turnId?: string
  traceOpen?: boolean
  onToggleTrace?: (turnId: string) => void
}) {
  const { notify } = useToast()
  // 流式丝滑（2026-08-13）：打字机平滑只在 streaming 消息上生效（其余直接全量）。
  // 放在所有 early return 之前，保证 hooks 调用顺序稳定。
  const streaming = !!msg.meta?.streaming
  const animatedContent = useTypewriter(msg.content, streaming)
  if (msg.role === 'progress') {
    if (msg.meta?.hint === 'deep_reasoning') {
      return (
        <div className="deep-hint">
          <span className="deep-hint-icon">🧠</span>
          <div className="deep-hint-body">
            <div className="deep-hint-text">{msg.content}</div>
            {msg.meta?.hint_prompt ? (
              <button
                className="deep-hint-btn"
                disabled={running}
                onClick={() => onRegenerateDeep?.(msg.meta!.hint_prompt as string)}
              >
                🧠 用深度模式重新回答（约 2-6 分钟）
              </button>
            ) : deepOn ? (
              <span className="deep-hint-done">已开启深度推理，重新发送问题即可</span>
            ) : (
              <button className="deep-hint-btn" onClick={() => onEnableDeep?.()}>
                打开深度推理
              </button>
            )}
          </div>
        </div>
      )
    }
    if (msg.meta?.confirm) {
      return (
        <ConfirmCard
          confirm={msg.meta.confirm}
          replied={confirmReplies.get(msg.meta.confirm.id)}
          active={isLast && running}
          cid={cid}
        />
      )
    }
    if (msg.meta?.handoff) {
      return (
        <HandoffCard
          handoff={msg.meta.handoff}
          text={msg.content}
          waiting={isLast && running}
          cid={cid}
        />
      )
    }
    return (
      <div className="progress-line">
        {isLast && running ? <span className="spinner" /> : <span className="progress-dot" />}
        {msg.content}
      </div>
    )
  }
  if (msg.role === 'user') {
    return (
      <div className="msg-user">
        <div>{msg.content}</div>
      </div>
    )
  }
  if (msg.meta?.candidates?.length) {
    return (
      <div className="msg-assistant">
        <p className="cand-lead">{msg.content}</p>
        <div className="cand-list">
          {msg.meta.candidates.map((c) => (
            <button key={c.name} className="cand-card" onClick={() => onPickDestination?.(c.name)}>
              <span className="cand-name">{c.name}</span>
              {c.tag && <span className="cand-tag">{c.tag}</span>}
              {c.reason && <small className="cand-reason">{c.reason}</small>}
            </button>
          ))}
        </div>
        <p className="cand-foot">都不合适？直接说个地名，或者让我来定。</p>
      </div>
    )
  }
  if (msg.meta?.poster) {
    return (
      <div className="msg-assistant">
        <PosterView poster={msg.meta.poster} />
      </div>
    )
  }
  if (msg.meta?.budget) {
    return (
      <div className="msg-assistant">
        <BudgetView budget={msg.meta.budget} />
      </div>
    )
  }
  const preliminary = !!msg.meta?.preliminary
  const saved = msg.meta?.memories_saved?.filter((s) => s.op !== 'delete') ?? []
  // 是行程攻略（有来源且含标题）→ 提供生成手账海报入口
  const isGuide = !streaming && !!msg.meta?.sources?.length && msg.content.includes('##')
  return (
    <div className={`msg-assistant${preliminary ? ' is-preliminary' : ''}`}>
      {preliminary && (
        <div className="preliminary-badge">
          <span aria-hidden>💡</span>
          初步判断 · 正在查证实时资料，完整分析稍后送到
        </div>
      )}
      {msg.meta?.memories_used && msg.meta.memories_used.length > 0 && (
        <MemoriesUsed items={msg.meta.memories_used} />
      )}
      {msg.meta?.skills_used && msg.meta.skills_used.length > 0 && (
        <SkillsUsed names={msg.meta.skills_used} />
      )}
      {msg.reasoning && <Reasoning text={msg.reasoning} streaming={streaming && !msg.content} />}
      {msg.content ? (
        <GuideBody content={animatedContent} />
      ) : streaming ? (
        <div className="progress-line">
          <span className="spinner" />
          正在生成…
        </div>
      ) : null}
      {streaming && msg.content && (
        <span className="stream-foot" aria-hidden>
          <span className="stream-cursor" />
          <span className="stream-chars">已生成 {msg.content.length} 字</span>
        </span>
      )}
      {saved.length > 0 && (
        <div className="memory-saved">
          🧠 已记住：{saved.map((s) => s.content).join('；')}
        </div>
      )}
      {msg.meta?.sources && msg.meta.sources.length > 0 && <Sources sources={msg.meta.sources} />}
      {msg.meta?.artifacts && msg.meta.artifacts.length > 0 && <SandboxArtifacts items={msg.meta.artifacts} />}
      {!streaming && msg.content && (
        <div className="message-actions" aria-label="回复操作">
          <button className="export-btn" onClick={async () => {
            const copied = await copyText(msg.content)
            notify(copied ? '回复已复制' : '复制失败，请手动选择文字', copied ? 'success' : 'error')
          }}>📋 复制</button>
          {turnId && turnId !== 'tmp' && (
            <button
              className={`export-btn trace-btn${traceOpen ? ' on' : ''}`}
              onClick={() => onToggleTrace?.(turnId)}
              title="查看本轮调用链（LLM 请求与工具调用）"
            >
              🔗 调用链
            </button>
          )}
          {isGuide && <BudgetButton cid={cid} messageId={msg.id} disabled={running} onStart={onPosterStart} />}
        </div>
      )}
      {isGuide && (
        <div className="next-steps">
          <div className="next-steps-head">接下来</div>
          <div className="next-steps-grid">
            <PosterButton
              cid={cid} messageId={msg.id} disabled={running} onStart={onPosterStart}
              variant="card"
            />
            <button
              className="next-step-card"
              disabled={running}
              onClick={() => onRefineByDate?.()}
            >
              <span className="ns-icon" aria-hidden>📅</span>
              <b>日期定了？排到每一天</b>
              <small>给我具体的出发和返程时间，我把行程落到钟点</small>
            </button>
            {onImportTrip && (
              msg.meta?.imported_trip_id ? (
                <button className="next-step-card" onClick={() => onImportTrip(msg.meta!.imported_trip_id!)}>
                  <span className="ns-icon" aria-hidden>🗺️</span>
                  <b>打开协同行程</b>
                  <small>已导入，可继续和同行者一起改</small>
                </button>
              ) : (
                <TripImportButton
                  cid={cid} messageId={msg.id} disabled={running} onDone={onImportTrip}
                  variant="card"
                />
              )
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function PosterButton({
  cid, messageId, disabled, onStart, variant,
}: { cid: string | null; messageId: string; disabled: boolean; onStart: () => void
     variant?: 'card' }) {
  const [clicked, setClicked] = useState(false)
  const { notify } = useToast()
  const run = async () => {
    if (!cid || clicked) return
    setClicked(true)
    try {
      const res = await authFetch(`${API}/chat/${cid}/poster`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: messageId }),
      })
      if (!res.ok) throw new Error()
      notify('手账海报已开始生成', 'info')
      onStart()  // 重启轮询，接住即将生成的海报（攻略已终稿，running 已回落）
    } catch {
      setClicked(false)
      notify('启动海报生成失败', 'error')
    }
  }
  if (variant === 'card') {
    return (
      <button className="next-step-card" onClick={run} disabled={disabled || clicked}>
        <span className="ns-icon" aria-hidden>🎨</span>
        <b>{clicked ? '手账生成中…' : '生成手账海报'}</b>
        <small>一张图带走整条路线，出门时能直接看</small>
      </button>
    )
  }
  return (
    <button className="export-btn poster-trigger" onClick={run} disabled={disabled || clicked}>
      {clicked ? '手账生成中…' : '🎨 生成手账海报'}
    </button>
  )
}

function BudgetButton({
  cid, messageId, disabled, onStart,
}: { cid: string | null; messageId: string; disabled: boolean; onStart: () => void }) {
  const [clicked, setClicked] = useState(false)
  const { notify } = useToast()
  const run = async () => {
    if (!cid || clicked) return
    setClicked(true)
    try {
      const res = await authFetch(`${API}/chat/${cid}/budget`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message_id: messageId }),
      })
      if (!res.ok) throw new Error()
      notify('正在统计预算明细', 'info')
      onStart()  // 同海报：重启轮询接住结果（攻略已终稿，running 已回落）
    } catch {
      setClicked(false)
      notify('启动预算统计失败', 'error')
    }
  }
  return (
    <button className="export-btn budget-trigger" onClick={run} disabled={disabled || clicked}>
      {clicked ? '统计中…' : '💰 预算明细'}
    </button>
  )
}

const BUDGET_CAT_COLORS: Record<string, string> = {
  大交通: '#6366f1', 住宿: '#0ea5e9', 餐饮: '#f59e0b',
  门票: '#10b981', 交通: '#8b5cf6', 其他: '#94a3b8',
}

function BudgetView({ budget }: { budget: BudgetData }) {
  const [cat, setCat] = useState<string>('全部')
  // 估算值取整到元：模型给的是区间中值，显示到分（¥4,105.75）会假装出不存在的精度
  const yuan = (n: number) => `¥${Math.round(n).toLocaleString('zh-CN')}`
  const cats = ['全部', ...budget.by_category.map((c) => c.category)]
  const items = cat === '全部' ? budget.items : budget.items.filter((i) => i.category === cat)
  // 明细排序：先按天（整趟通用的 day=0 排最后），同天按金额降序
  const sorted = [...items].sort((a, b) =>
    (a.day || 99) - (b.day || 99) || b.amount - a.amount)

  return (
    <div className="budget-card">
      <div className="budget-head">
        <div>
          <div className="budget-title">💰 预算明细</div>
          <div className="budget-sub">
            人均估算 · 非实时报价，下单前请到平台核对
            {budget.headcount > 1 && ` · 按 ${budget.headcount} 人出行`}
          </div>
        </div>
        <div className="budget-total">
          <div className="budget-total-num">{yuan(budget.total)}</div>
          <div className="budget-total-label">
            人均{budget.headcount > 1 && ` · 合计 ${yuan(budget.group_total)}`}
          </div>
        </div>
      </div>

      {budget.reservations.length > 0 && (
        <div className="budget-resv">
          <div className="budget-resv-title">📋 需提前预约</div>
          <ul>
            {budget.reservations.map((r, i) => (
              <li key={i}>
                <b>{r.name}</b>
                {r.advance && <span className="budget-resv-tag">{r.advance}</span>}
                {r.channel && <span className="budget-resv-ch">{r.channel}</span>}
                {r.note && <span className="budget-resv-note">{r.note}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {budget.by_category.length > 0 && (
        <div className="budget-bars">
          {budget.by_category.map((c) => (
            <div className="budget-bar-row" key={c.category}>
              <span className="budget-bar-name">{c.category}</span>
              <span className="budget-bar-track">
                <span
                  className="budget-bar-fill"
                  style={{ width: `${c.pct}%`, background: BUDGET_CAT_COLORS[c.category] || '#94a3b8' }}
                />
              </span>
              <span className="budget-bar-amt">{yuan(c.amount)}</span>
              <span className="budget-bar-pct">{c.pct}%</span>
            </div>
          ))}
        </div>
      )}

      {budget.items.length > 0 && (
        <>
          <div className="budget-filters">
            {cats.map((c) => (
              <button
                key={c}
                className={c === cat ? 'on' : ''}
                onClick={() => setCat(c)}
              >{c}</button>
            ))}
          </div>
          <div className="budget-table-wrap">
            <table className="budget-table">
              <thead>
                <tr><th>项目</th><th>类别</th><th>天</th><th className="ta-r">金额</th></tr>
              </thead>
              <tbody>
                {sorted.map((it, i) => (
                  <tr key={i}>
                    <td>
                      {it.name}
                      {it.note && <span className="budget-item-note">{it.note}</span>}
                    </td>
                    <td>
                      <span
                        className="budget-chip"
                        style={{ background: `${BUDGET_CAT_COLORS[it.category] || '#94a3b8'}1a`,
                                 color: BUDGET_CAT_COLORS[it.category] || '#64748b' }}
                      >{it.category}</span>
                    </td>
                    <td>{it.day > 0 ? `D${it.day}` : '通用'}</td>
                    <td className="ta-r">{yuan(it.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {budget.by_day.length > 0 && (
        <div className="budget-days">
          {budget.by_day.map((d) => (
            <span key={d.day} className="budget-day-pill">
              D{d.day} <b>{yuan(d.amount)}</b>
            </span>
          ))}
          {budget.shared > 0 && (
            <span className="budget-day-pill shared">通用 <b>{yuan(budget.shared)}</b></span>
          )}
        </div>
      )}

      {budget.notes.length > 0 && (
        <ul className="budget-notes">
          {budget.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </div>
  )
}

function TripImportButton({
  cid, messageId, disabled, onDone, variant,
}: {
  cid: string | null; messageId: string; disabled?: boolean
  onDone: (tripId: string) => void
  variant?: 'card'
}) {
  const [busy, setBusy] = useState(false)
  const { notify } = useToast()
  const run = async () => {
    // disabled：本轮修改还在跑时不许导入旧版本攻略（用户实测：容易导到过期内容）
    if (!cid || busy || disabled) return
    setBusy(true)
    try {
      const res = await authFetch(`${API}/trips/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: cid, message_id: messageId }),
      })
      if (res.ok) {
        notify('已创建协同行程，正在提取地点、酒店与预算', 'success')
        onDone((await res.json()).id)  // 打开协同规划板（后台还在提取，板上有起草中提示）
      } else {
        notify('导入协同行程失败', 'error')
      }
    } catch {
      notify('导入失败，请检查网络', 'error')
    } finally {
      setBusy(false)
    }
  }
  if (variant === 'card') {
    return (
      <button className="next-step-card" onClick={run} disabled={busy || disabled}
        title={disabled ? '本轮修改还在生成，完成后再导入' : undefined}>
        <span className="ns-icon" aria-hidden>👥</span>
        <b>{busy ? '导入中…' : '叫上同行的人一起改'}</b>
        <small>变成可协作的行程板，大家各自加想去的地方</small>
      </button>
    )
  }
  return (
    <button className="export-btn" onClick={run} disabled={busy || disabled}
      title={disabled ? '本轮修改还在生成，完成后再导入' : undefined}>
      {busy ? '导入中…' : '🗺️ 导入协同行程'}
    </button>
  )
}

function MemoriesUsed({ items }: { items: MemoryRef[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="memories-used">
      <button className="reasoning-toggle" onClick={() => setOpen((o) => !o)}>
        🧠 记忆 · {items.length} <span>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="memory-cards">
          {items.map((m, i) => (
            <div key={i} className="memory-card">
              <div className="memory-card-tag">
                {m.kind === 'past_chat' ? '历史对话' : MEM_TYPE_LABEL[m.type ?? ''] || '记忆'}
              </div>
              {m.kind === 'past_chat' && <div className="memory-card-title">{m.title}</div>}
              <div className="memory-card-body">{m.content}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SkillsUsed({ names }: { names: string[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="memories-used">
      <button className="reasoning-toggle" onClick={() => setOpen((o) => !o)}>
        🧩 技能 · {names.length} <span>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="memory-cards">
          {names.map((name) => (
            <div key={name} className="memory-card">
              <div className="memory-card-body">{name}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Sources({ sources }: { sources: { title: string; url: string }[] }) {
  const [open, setOpen] = useState(false)
  const hosts = [...new Set(sources.map((s) => hostOf(s.url)))].slice(0, 3)
  return (
    <div className="sources">
      <button className="sources-toggle" onClick={() => setOpen((o) => !o)}>
        🌐 参考了 {sources.length} 个网站
        <span className="sources-hosts">{hosts.join(' · ')}</span>
        <span>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="sources-list">
          {sources.map((s, i) => (
            <a key={i} href={s.url} target="_blank" rel="noreferrer" className="source-item">
              <span className="source-index">{i + 1}</span>
              <span className="source-title">{s.title || s.url}</span>
              <span className="source-host">{hostOf(s.url)}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg)$/i

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function SandboxArtifacts({ items }: { items: { name: string; size: number; url: string }[] }) {
  return (
    <div className="sandbox-artifacts">
      <div className="sandbox-artifacts-head">🐳 沙箱产物 · {items.length}（30 分钟后自动过期）</div>
      <div className="sandbox-artifacts-list">
        {items.map((it, i) => {
          const href = `${API}${it.url}`
          return IMAGE_EXT.test(it.name) ? (
            <a key={i} href={href} target="_blank" rel="noreferrer" className="artifact-item artifact-image">
              <img src={href} alt={it.name} loading="lazy" />
              <span className="artifact-name">{it.name}</span>
            </a>
          ) : (
            <a key={i} href={href} download={it.name} className="artifact-item">
              <span className="artifact-icon">📎</span>
              <span className="artifact-name">{it.name}</span>
              <span className="artifact-size">{formatBytes(it.size)}</span>
            </a>
          )
        })}
      </div>
    </div>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function ConfirmCard({
  confirm,
  replied,
  active,
  cid,
}: {
  confirm: { id: string; question: string; source?: { title?: string; domain?: string } }
  replied?: string
  active: boolean
  cid: string | null
}) {
  const [localChoice, setLocalChoice] = useState<string | null>(null)
  const choice = replied ?? localChoice

  const send = async (c: 'login' | 'skip') => {
    if (!cid || choice) return
    setLocalChoice(c)
    await authFetch(`${API}/chat/${cid}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm_id: confirm.id, choice: c }),
    })
  }

  return (
    <div className="handoff-card">
      <div className="handoff-badge web">确认</div>
      <div className="handoff-main">
        <div className="handoff-title">需要登录的来源</div>
        <div className="handoff-desc">{confirm.question}</div>
        {choice ? (
          <div className="confirm-chosen">已选择：{choice === 'login' ? '登录读取' : '跳过'}</div>
        ) : active ? (
          <div className="confirm-actions">
            <button className="confirm-btn primary" onClick={() => send('login')}>
              登录读取
            </button>
            <button className="confirm-btn" onClick={() => send('skip')}>
              跳过
            </button>
          </div>
        ) : (
          <div className="confirm-chosen">已超时自动跳过</div>
        )}
      </div>
    </div>
  )
}

function HandoffCard({
  handoff,
  text,
  waiting,
  cid,
}: {
  handoff: NonNullable<NonNullable<Msg['meta']>['handoff']>
  text: string
  waiting: boolean
  cid: string | null
}) {
  const remote = handoff.mode === 'remote'
  // 截图直播：等待期间每 4s 刷新登录页截图（二维码实时可见）
  const [tick, setTick] = useState(0)
  const [imgOk, setImgOk] = useState(true)
  const hasShot = remote && !!handoff.screenshot && !!cid
  const showShot = hasShot && (waiting || imgOk)
  useEffect(() => {
    if (!hasShot || !waiting) return
    const t = window.setInterval(() => setTick((n) => n + 1), 4000)
    return () => window.clearInterval(t)
  }, [hasShot, waiting])

  return (
    <div className="handoff-card">
      <div
        className={`handoff-badge ${handoff.site === 'xhs' ? 'xhs' : handoff.site === 'ctrip' ? 'ctrip' : 'web'}`}
      >
        {handoff.site === 'xhs' ? '小红书' : handoff.site === 'ctrip' ? '携程' : '登录'}
      </div>
      <div className="handoff-main">
        <div className="handoff-title">
          {remote ? `用 ${handoff.site_name} App 扫码登录` : `请在浏览器中登录${handoff.site_name}`}
        </div>
        <div className="handoff-desc">{text}</div>
        {showShot && (
          <img
            className="handoff-shot"
            style={imgOk ? undefined : { display: 'none' }}
            src={`${API}/chat/${cid}/handoff-screenshot?t=${tick}`}
            alt={`${handoff.site_name}登录页`}
            onLoad={() => setImgOk(true)}
            onError={() => setImgOk(false)}
          />
        )}
        {showShot && !imgOk && <div className="handoff-shot-loading">登录页截图加载中…</div>}
        {waiting && (
          <span className="handoff-waiting">
            <span className="pulse-dot" />
            {remote ? '等待扫码登录中，完成后自动继续…' : '等待登录中，完成后会自动继续…'}
          </span>
        )}
      </div>
    </div>
  )
}

function Reasoning({ text, streaming }: { text: string; streaming?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button className="reasoning-toggle" onClick={() => setOpen((o) => !o)}>
        {streaming ? '思考中…' : '已深度思考'} <span>{open ? '▾' : '▸'}</span>
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  )
}

// 与后端 staticmap DAY_COLORS 对齐：左栏序号色 = 地图 marker 色
const DAY_COLORS = ['#FF5A5F', '#2EC4B6', '#3D5AFE', '#FF9F1C', '#9B5DE5', '#00B894']
const CN_NUM = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
const dayColor = (i: number) => DAY_COLORS[i % DAY_COLORS.length]

function StopPhoto({
  photo,
  icon,
  name,
  className = 'poster-stop-photo',
}: {
  photo: string
  icon: string
  name: string
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  if (!photo || failed) {
    return <div className={`${className} poster-stop-noimg`}>{icon}</div>
  }
  return (
    <img className={className} src={photo} alt={name} crossOrigin="anonymous" onError={() => setFailed(true)} />
  )
}

function PosterView({ poster }: { poster: PosterData }) {
  const ref = useRef<HTMLDivElement>(null)
  const [saving, setSaving] = useState(false)
  const city = poster.destination || (poster.title || '').replace(/\d+日.*|手账|攻略/g, '').trim()

  const save = async () => {
    if (!ref.current || saving) return
    setSaving(true)
    try {
      const { default: html2canvas } = await import('html2canvas')
      const canvas = await html2canvas(ref.current, { backgroundColor: '#f6f1e4', scale: 2, useCORS: true })
      const link = document.createElement('a')
      link.download = `${city || '旅行'}路线图.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rmap-scroll">
      <div className="rmap" ref={ref}>
        <header className="rmap-head">
          <div className="rmap-title-row">
            <span className="rmap-city">{city}</span>
            <span className="rmap-title-main">旅行路线图</span>
            {city && <span className="rmap-seal">{city[0]}</span>}
          </div>
          {(poster.theme || poster.subtitle) && (
            <div className="rmap-theme">{poster.theme || poster.subtitle}</div>
          )}
        </header>

        <div className="rmap-body">
          <aside className="rmap-col rmap-left">
            {poster.days.map((d, idx) => (
              <div className="route-card" key={d.day} style={{ ['--rc' as string]: dayColor(idx) }}>
                <div className="route-card-head">
                  <span className="route-card-kw">路线{CN_NUM[idx] || idx + 1}</span>
                  <span className="route-card-name">{d.title}</span>
                </div>
                {d.subtitle && <div className="route-card-sub">{d.subtitle}</div>}
                <ol className="route-stops">
                  {d.stops.map((s) => (
                    <li className="route-stop" key={s.order}>
                      <span className="route-dot">{s.order}</span>
                      <span className="route-stop-name">{s.name}</span>
                    </li>
                  ))}
                </ol>
                {(d.distance || d.duration) && (
                  <div className="route-card-foot">
                    {[d.distance, d.duration].filter(Boolean).join(' · ')}
                  </div>
                )}
              </div>
            ))}
          </aside>

          <div className="rmap-col rmap-center">
            {poster.days.some((d) => d.map) ? (
              poster.days.map((d, idx) =>
                d.map ? (
                  <div className="rmap-map-frame" key={d.day} style={{ ['--rc' as string]: dayColor(idx) }}>
                    <div className="rmap-map-cap">
                      路线{CN_NUM[idx] || idx + 1} · {d.title}
                    </div>
                    <img className="rmap-map" src={d.map} alt={`${d.title}路线`} crossOrigin="anonymous" />
                  </div>
                ) : null,
              )
            ) : poster.overall_map ? (
              <div className="rmap-map-frame">
                <img className="rmap-map" src={poster.overall_map} alt="路线地图" crossOrigin="anonymous" />
              </div>
            ) : (
              <div className="rmap-map-frame rmap-map-empty">🗺️ 地图生成中…</div>
            )}
            <div className="rmap-legend">
              {poster.days.map((d, idx) => (
                <span className="rmap-legend-item" key={d.day}>
                  <i style={{ background: dayColor(idx) }} />
                  {d.title}
                </span>
              ))}
            </div>
          </div>

        </div>

        <div className="rmap-recs">
          <div className="rmap-recs-col">
            {poster.foods?.length > 0 && (
              <section className="rec-block">
                <h3 className="rec-title rec-food">🍜 美食推荐</h3>
                {poster.foods.map((f, i) => (
                  <div className="rec-item" key={i}>
                    <StopPhoto photo={f.photo} icon="🍜" name={f.name} className="rec-photo" />
                    <div className="rec-text">
                      <div className="rec-name">{f.name}</div>
                      {f.note && <div className="rec-note">{f.note}</div>}
                    </div>
                  </div>
                ))}
              </section>
            )}
            {poster.specialties?.length > 0 && (
              <section className="rec-block">
                <h3 className="rec-title rec-gift">🎁 当地特产</h3>
                <div className="rec-chips">
                  {poster.specialties.map((s, i) => (
                    <div className="rec-chip" key={i}>
                      <span className="rec-chip-name">{s.name}</span>
                      {s.note && <span className="rec-chip-note">{s.note}</span>}
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
          <div className="rmap-recs-col">
            {poster.hotels?.length > 0 && (
              <section className="rec-block">
                <h3 className="rec-title rec-hotel">🏨 酒店推荐</h3>
                {poster.hotels.map((h, i) => (
                  <div className="rec-item" key={i}>
                    <StopPhoto photo={h.photo} icon="🏨" name={h.name} className="rec-photo" />
                    <div className="rec-text">
                      <div className="rec-name">{h.name}</div>
                      <div className="rec-note">
                        {[h.area, h.price].filter(Boolean).join(' · ')}
                        {h.note && <span className="rec-hotel-note"> {h.note}</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </section>
            )}
            {poster.tips?.length > 0 && (
              <section className="rec-block">
                <h3 className="rec-title rec-tip">💡 旅行贴士</h3>
                <ul className="rec-tips">
                  {poster.tips.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </div>

        <div className="rmap-summary">
          <div className="rmap-summary-head">路线一览</div>
          <div className="rmap-summary-cols">
            {poster.days.map((d, idx) => (
              <div className="rmap-summary-card" key={d.day} style={{ ['--rc' as string]: dayColor(idx) }}>
                <div className="rmap-summary-name">
                  路线{CN_NUM[idx] || idx + 1} · {d.title}
                </div>
                <div className="rmap-summary-stops">{d.stops.map((s) => s.name).join(' → ')}</div>
                {(d.distance || d.duration) && (
                  <div className="rmap-summary-meta">{[d.distance, d.duration].filter(Boolean).join(' · ')}</div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="rmap-foot">✿ 17同游 · 为你手绘 ✿</div>
      </div>
      <button className="export-btn" onClick={save} disabled={saving}>
        {saving ? '生成图片中…' : '💾 保存路线图'}
      </button>
    </div>
  )
}

// memo（2026-08-13 丝滑改造）：props 只有 content，引用相等即跳过 react-markdown
// 重解析——轮询增量合并（mergeMessages）保证未变化消息的 content 引用不变。
const GuideBody = memo(function GuideBody({ content }: { content: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const isGuide = content.includes('##') || content.length > 200
  const headings = extractGuideHeadings(content)

  const exportImage = async () => {
    if (!ref.current) return
    // 图片经同源代理加载，useCORS 让 html2canvas 能画进 canvas（否则跨域污染导致导出失败）
    const { default: html2canvas } = await import('html2canvas')
    const canvas = await html2canvas(ref.current, { backgroundColor: '#ffffff', scale: 2, useCORS: true })
    const link = document.createElement('a')
    link.download = '旅行攻略.png'
    link.href = canvas.toDataURL('image/png')
    link.click()
  }

  return (
    <div className="guide-body">
      {headings.length >= 2 && (
        <details className="guide-outline">
          <summary><span>本篇目录</span><small>{headings.length} 个章节</small></summary>
          <nav>
            {headings.map((heading, index) => (
              <button key={`${heading.id}-${index}`} className={heading.level === 3 ? 'sub' : ''} onClick={() => {
                document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}>
                <span>{String(index + 1).padStart(2, '0')}</span>{heading.title}
              </button>
            ))}
          </nav>
        </details>
      )}
      <div ref={ref} className="md guide-markdown">
        <ReactMarkdown
          // singleTilde:false —— `¥400~600` 里两个 `~` 会互相配成删除线吞掉中间文字（走查 P0-3）
          remarkPlugins={[[remarkGfm, { singleTilde: false }]]}
          components={{
            h1: ({ children }) => <h1 className="guide-title">{children}</h1>,
            h2: ({ children }) => {
              const title = reactText(children)
              const day = /(^|[\s📅])day\s*\d+/iu.test(title)
              return <h2 id={headingAnchor(title)} className={day ? 'guide-day-heading' : 'guide-section-heading'}>{children}</h2>
            },
            h3: ({ children }) => <h3 id={headingAnchor(reactText(children))} className="guide-subheading">{children}</h3>,
            table: ({ children, ...props }) => (
              <div className="guide-table-wrap"><table {...props}>{children}</table></div>
            ),
            img: ({ alt, ...props }) => <img {...props} alt={alt || '行程配图'} loading="lazy" />,
          }}
        >{prepareMarkdown(content)}</ReactMarkdown>
      </div>
      {isGuide && (
        <button className="export-btn guide-export" onClick={exportImage}>
          ↧ 导出长图
        </button>
      )}
    </div>
  )
})

// Phase 51 批6（P1 安全）：admin 仍在用默认口令 admin123 → 顶部横幅强提示改密，改完即消
function AdminPasswordBanner({ onDone }: { onDone?: () => void }) {
  const { notify } = useToast()
  const [open, setOpen] = useState(false)
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (busy) return
    if (newPw.length < 6) { notify('新密码至少 6 位', 'error'); return }
    setBusy(true)
    try {
      const res = await authFetch(`${API}/auth/change-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        notify(d.detail || '改密失败', 'error')
        return
      }
      const data = await res.json()
      if (data.token) setToken(data.token)  // 旧会话已失效，换用新 token
      notify('管理员密码已更新', 'success')
      onDone?.()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="admin-pw-banner" role="alert">
      <span className="admin-pw-msg">⚠️ 管理员仍在使用默认口令 <code>admin123</code>，存在安全风险，请立即修改。</span>
      {!open ? (
        <button className="admin-pw-btn" onClick={() => setOpen(true)}>立即修改</button>
      ) : (
        <span className="admin-pw-form">
          <input type="password" placeholder="原密码" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" />
          <input type="password" placeholder="新密码（≥6位）" value={newPw} onChange={(e) => setNewPw(e.target.value)}
            autoComplete="new-password" onKeyDown={(e) => { if (e.key === 'Enter') submit() }} />
          <button className="admin-pw-btn" onClick={submit} disabled={busy}>{busy ? '提交中…' : '确认'}</button>
        </span>
      )}
    </div>
  )
}
