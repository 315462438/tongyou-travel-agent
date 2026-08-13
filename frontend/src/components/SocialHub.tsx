import { useCallback, useEffect, useRef, useState } from 'react'

import { API, authFetch } from '../api'
import Aurora from './Aurora'

export type SocialTab = 'station' | 'friends' | 'profile'
type TravelPhase = 'planning' | 'on_trip' | 'returned'
type RelayKind = 'condition' | 'route' | 'question'

interface UserCard {
  id: string
  username: string
  display_name: string
  avatar_url: string
  bio: string
  home_city: string
  travel_styles: string[]
  friendship_id?: string
  friendship_status?: string
  requester_id?: string
}

interface Profile extends UserCard {
  profile_public: boolean
  avatar_upload_id?: string
  stats: { relay_posts: number; verified: number; friends: number }
  recent_relay: Pick<RelayPost, 'id' | 'destination' | 'phase' | 'kind' | 'content' | 'created_at'>[]
}

interface RelayPost {
  id: string
  destination: string
  phase: TravelPhase
  kind: RelayKind
  content: string
  expires_at: string | null
  expired: boolean
  created_at: string
  author: UserCard
  mine: boolean
  reactions: { useful: number; verified: number; outdated: number }
  my_reaction: string
}

interface FriendGroups {
  friends: (UserCard & { friendship_id: string })[]
  received: (UserCard & { friendship_id: string })[]
  sent: (UserCard & { friendship_id: string })[]
}

const FALLBACK_HOT_DESTINATIONS = ['平潭岛', '武功山', '杭州', '武汉']
const STYLE_OPTIONS = ['松弛慢游', '美食优先', '户外徒步', '人文历史', '亲子友好', '省钱玩家', '摄影打卡', '自驾探索']
const EMPTY_FRIENDS: FriendGroups = { friends: [], received: [], sent: [] }
const POST_PHASE_BY_KIND: Record<RelayKind, TravelPhase> = {
  question: 'planning',
  condition: 'on_trip',
  route: 'returned',
}

const PHASE_COPY: Record<TravelPhase, { label: string; hint: string }> = {
  planning: { label: '准备去', hint: '提问与收集路线' },
  on_trip: { label: '正在玩', hint: '72 小时现场情报' },
  returned: { label: '刚回来', hint: '路线复盘与避坑' },
}

const KIND_COPY: Record<RelayKind, { label: string; icon: string }> = {
  condition: { label: '现场情报', icon: '⌁' },
  route: { label: '路线分享', icon: '↗' },
  question: { label: '目的地提问', icon: '?' },
}

function ago(value: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 1000))
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

function Avatar({ user, size = 'md' }: { user: Pick<UserCard, 'display_name' | 'username' | 'avatar_url'>; size?: 'sm' | 'md' | 'lg' | 'xl' }) {
  return (
    <span className={`social-avatar ${size}`} aria-hidden>
      {user.avatar_url
        ? <img src={user.avatar_url} alt="" onError={(event) => { event.currentTarget.hidden = true }} />
        : <b>{(user.display_name || user.username || '旅')[0].toUpperCase()}</b>}
    </span>
  )
}

export default function SocialHub({
  onClose,
  onProfileChanged,
  initialTab = 'station',
  initialDestination = '天堂寨',
}: {
  onClose: () => void
  onProfileChanged?: (profile: { display_name: string; avatar_url: string }) => void
  initialTab?: SocialTab
  initialDestination?: string
}) {
  const startDestination = initialDestination.trim() || '天堂寨'
  const [tab, setTab] = useState<SocialTab>(initialTab)
  const [destination, setDestination] = useState(startDestination)
  const [destinationDraft, setDestinationDraft] = useState(startDestination)
  const [phase, setPhase] = useState<'all' | TravelPhase>('all')
  const [posts, setPosts] = useState<RelayPost[]>([])
  const [phaseCounts, setPhaseCounts] = useState<Record<TravelPhase, number>>({ planning: 0, on_trip: 0, returned: 0 })
  const [hotDestinations, setHotDestinations] = useState(FALLBACK_HOT_DESTINATIONS)
  const [hotCovers, setHotCovers] = useState<Record<string, string>>({})
  const [hotIsLive, setHotIsLive] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [viewProfile, setViewProfile] = useState<Profile | null>(null)
  const [friends, setFriends] = useState<FriendGroups>(EMPTY_FRIENDS)
  const [search, setSearch] = useState('')
  const [people, setPeople] = useState<UserCard[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [composerOpen, setComposerOpen] = useState(false)
  const [postKind, setPostKind] = useState<RelayKind>('question')
  const [postDestination, setPostDestination] = useState(startDestination)
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState(false)
  const avatarInputRef = useRef<HTMLInputElement>(null)
  const reducedMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const requestJson = useCallback(async (url: string, init?: RequestInit) => {
    const response = await authFetch(url, init)
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.detail || '操作失败，请稍后重试')
    return data
  }, [])

  const loadStation = useCallback(async (
    targetDestination = destination,
    targetPhase: 'all' | TravelPhase = phase,
  ) => {
    setLoading(true)
    setError('')
    try {
      const query = new URLSearchParams({ destination: targetDestination })
      if (targetPhase !== 'all') query.set('phase', targetPhase)
      const data = await requestJson(`${API}/social/station?${query.toString()}`)
      setPosts(data.posts || [])
      setPhaseCounts(data.phase_counts || { planning: 0, on_trip: 0, returned: 0 })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '接力站暂时无法加载')
    } finally {
      setLoading(false)
    }
  }, [destination, phase, requestJson])

  const enterDestination = useCallback((next = destinationDraft) => {
    const clean = next.trim().replace(/\s+/g, ' ').slice(0, 64)
    if (!clean) return
    setDestinationDraft(clean)
    setDestination(clean)
    setPhase('all')
    setComposerOpen(false)
    if (clean === destination && phase === 'all') void loadStation(clean, 'all')
  }, [destination, destinationDraft, loadStation, phase])

  const loadProfile = useCallback(async () => {
    try {
      const data = await requestJson(`${API}/social/me`)
      setProfile(data)
      if (!viewProfile) setViewProfile(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '个人主页暂时无法加载')
    }
  }, [requestJson, viewProfile])

  const loadFriends = useCallback(async () => {
    try {
      setFriends(await requestJson(`${API}/social/friends`))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '好友列表暂时无法加载')
    }
  }, [requestJson])

  useEffect(() => { void loadStation() }, [loadStation])
  useEffect(() => { void loadProfile(); void loadFriends() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let active = true
    const loadHotDestinations = async () => {
      try {
        const onboarding = await requestJson(`${API}/onboarding`)
        const live: string[] = Array.isArray(onboarding.trending)
          ? onboarding.trending.map((item: unknown) => String(item).trim()).filter((item: string) => Boolean(item)).slice(0, 4)
          : []
        const destinations: string[] = live.length ? live : FALLBACK_HOT_DESTINATIONS
        if (!active) return
        setHotDestinations(destinations)
        setHotIsLive(live.length > 0)
        const params = new URLSearchParams()
        destinations.forEach((city) => params.append('destinations', city))
        const coverData = await requestJson(`${API}/onboarding/covers?${params.toString()}`)
        if (active) setHotCovers(coverData.covers || {})
      } catch {
        if (active) {
          setHotDestinations(FALLBACK_HOT_DESTINATIONS)
          setHotCovers({})
          setHotIsLive(false)
        }
      }
    }
    void loadHotDestinations()
    return () => { active = false }
  }, [requestJson])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previous }
  }, [])

  const openPerson = async (userId: string) => {
    setError('')
    try {
      const data = await requestJson(`${API}/social/users/${userId}`)
      setViewProfile(data)
      setTab('profile')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '主页暂时无法打开')
    }
  }

  const publish = async () => {
    const targetDestination = postDestination.trim().replace(/\s+/g, ' ').slice(0, 64)
    if (!content.trim() || !targetDestination || busy) return
    const mappedPhase = POST_PHASE_BY_KIND[postKind]
    setBusy(true)
    setError('')
    try {
      await requestJson(`${API}/social/posts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ destination: targetDestination, phase: mappedPhase, kind: postKind, content: content.trim() }),
      })
      setContent('')
      setComposerOpen(false)
      setDestination(targetDestination)
      setDestinationDraft(targetDestination)
      setPhase('all')
      await loadStation(targetDestination, 'all')
      await loadProfile()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发布失败')
    } finally {
      setBusy(false)
    }
  }

  const react = async (post: RelayPost, reaction: string) => {
    try {
      const data = await requestJson(`${API}/social/posts/${post.id}/react`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reaction }),
      })
      setPosts((list) => list.map((item) => item.id === post.id
        ? { ...item, reactions: data.reactions, my_reaction: item.my_reaction === reaction ? '' : reaction }
        : item))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '反馈失败')
    }
  }

  const deletePost = async (postId: string) => {
    if (!window.confirm('删除这条接力内容？')) return
    try {
      await requestJson(`${API}/social/posts/${postId}`, { method: 'DELETE' })
      setPosts((list) => list.filter((item) => item.id !== postId))
      void loadProfile()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除失败')
    }
  }

  const findPeople = async () => {
    try {
      const data = await requestJson(`${API}/social/users?q=${encodeURIComponent(search.trim())}`)
      setPeople(data.users || [])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '搜索失败')
    }
  }

  const requestFriend = async (userId: string) => {
    try {
      const relationship = await requestJson(`${API}/social/friends/request/${userId}`, { method: 'POST' })
      setViewProfile((current) => current?.id === userId
        ? { ...current, friendship_id: relationship.id, friendship_status: 'pending' }
        : current)
      await Promise.all([findPeople(), loadFriends()])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '好友申请发送失败')
    }
  }

  const respondFriend = async (friendshipId: string, accept: boolean) => {
    try {
      await requestJson(`${API}/social/friends/${friendshipId}/respond`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accept }),
      })
      await loadFriends()
      await loadProfile()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '处理申请失败')
    }
  }

  const removeFriend = async (friendshipId: string) => {
    if (!window.confirm('删除这位好友？这不会影响已有协同行程。')) return
    try {
      await requestJson(`${API}/social/friends/${friendshipId}`, { method: 'DELETE' })
      await loadFriends()
      await loadProfile()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除好友失败')
    }
  }

  const saveProfile = async (next: Profile = profile as Profile) => {
    if (!next || busy) return
    setBusy(true)
    setError('')
    try {
      const saved = await requestJson(`${API}/social/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          display_name: next.display_name,
          bio: next.bio,
          home_city: next.home_city,
          travel_styles: next.travel_styles,
          profile_public: next.profile_public,
          avatar_upload_id: next.avatar_upload_id || null,
        }),
      })
      setProfile(saved)
      setViewProfile(saved)
      onProfileChanged?.({ display_name: saved.display_name, avatar_url: saved.avatar_url })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '资料保存失败')
    } finally {
      setBusy(false)
    }
  }

  const uploadAvatar = async (file: File) => {
    if (!profile || busy) return
    setBusy(true)
    setError('')
    try {
      const body = new FormData()
      body.append('file', file)
      const uploaded = await requestJson(`${API}/uploads`, { method: 'POST', body })
      const next = { ...profile, avatar_upload_id: uploaded.id, avatar_url: `/travel/api/uploads/${uploaded.id}` }
      setProfile(next)
      await saveProfile(next)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '头像上传失败')
    } finally {
      setBusy(false)
      if (avatarInputRef.current) avatarInputRef.current.value = ''
    }
  }

  const toggleStyle = (style: string) => {
    if (!profile) return
    setProfile({
      ...profile,
      travel_styles: profile.travel_styles.includes(style)
        ? profile.travel_styles.filter((item) => item !== style)
        : [...profile.travel_styles, style].slice(0, 6),
    })
  }

  const myProfile = viewProfile?.id === profile?.id

  return (
    <div className="social-overlay" role="dialog" aria-modal="true" aria-label="17同游社交中心">
      <aside className="social-rail">
        <div className="social-brand"><span>17</span><div><b>同游圈</b><small>真实旅行者接力</small></div></div>
        <nav aria-label="社交中心导航">
          <button className={tab === 'station' ? 'active' : ''} onClick={() => setTab('station')}><i>⌁</i><span>目的地接力站</span></button>
          <button className={tab === 'friends' ? 'active' : ''} onClick={() => setTab('friends')}><i>◌</i><span>好友</span>{friends.received.length > 0 && <b>{friends.received.length}</b>}</button>
          <button className={tab === 'profile' && myProfile ? 'active' : ''} onClick={() => { setViewProfile(profile); setTab('profile') }}><i>◎</i><span>我的主页</span></button>
        </nav>
        <div className="social-rail-note"><b>接力，不是刷屏</b><span>现场情报会过期，真实经验可以被下一位旅行者验证。</span></div>
        {profile && <button className="social-me-mini" onClick={() => { setViewProfile(profile); setTab('profile') }}><Avatar user={profile} size="lg" /><span><b>{profile.display_name}</b><small>{profile.home_city || '补充你的常驻城市'}</small></span></button>}
      </aside>

      <main className="social-main">
        <header className="social-topbar">
          <div><span>17同游 · 一起规划，也把经验留给下一位</span></div>
          <button className="social-close" onClick={onClose} aria-label="关闭同游圈">关闭 <b>×</b></button>
        </header>
        {error && <div className="social-error" role="alert"><span>{error}</span><button onClick={() => setError('')}>×</button></div>}

        {tab === 'station' && (
          <div className="station-page">
            <section className="station-hot">
              {!reducedMotion && <Aurora className="station-hot-aurora" colorStops={['#46d6a0', '#7397ff', '#bd71e8']} amplitude={0.72} blend={0.62} speed={0.42} />}
              <header><div><small>{hotIsLive ? '近 30 天真实热问' : '本期旅行灵感'}</small><h1>最近大家都想去</h1></div><p>点一个热门目的地，看看旅行者留下的真实近况。</p></header>
              <div className="station-hot-grid">
                {hotDestinations.map((city, index) => {
                  const cover = hotCovers[city]
                  return (
                    <button className={`station-hot-card hot-tone-${index % 4}${city === destination ? ' active' : ''}`} key={city} onClick={() => enterDestination(city)} aria-label={`查看${city}接力站`}>
                      <span className="station-hot-fallback" aria-hidden>{city.slice(0, 1)}</span>
                      {cover && <img src={`${API}/img?u=${encodeURIComponent(cover)}`} alt="" loading="lazy" onError={(event) => { event.currentTarget.hidden = true }} />}
                      <em>TOP {index + 1}</em>
                      <span className="station-hot-copy"><small>{hotIsLive ? '正在被规划' : '值得出发'}</small><strong>{city}</strong><b>查看接力 <i aria-hidden>↗</i></b></span>
                    </button>
                  )
                })}
              </div>
            </section>

            <section className="station-search-panel">
              <div className="station-search-copy"><small>没有你想去的？</small><b>搜索任意目的地</b></div>
              <form className="station-search" onSubmit={(event) => { event.preventDefault(); enterDestination() }}>
                <span aria-hidden>⌕</span>
                <input value={destinationDraft} maxLength={64} onChange={(event) => setDestinationDraft(event.target.value)} placeholder="输入任意目的地，例如黄山、京都或冰岛" aria-label="输入目的地" />
                <button type="submit" disabled={!destinationDraft.trim()} aria-label="查看目的地接力"><span>查看接力</span><b aria-hidden>→</b></button>
              </form>
              <button className="relay-compose-trigger" onClick={() => { setPostDestination(destination); setComposerOpen(true) }}>＋ 发接力</button>
            </section>

            {composerOpen && (
              <section className="relay-composer">
                <div className="relay-composer-head"><Avatar user={profile || { display_name: '我', username: 'me', avatar_url: '' }} /><div><b>你想留下什么？</b><small>选一种就可以，不用理解复杂分类</small></div></div>
                <div className="relay-kind-picker" aria-label="选择接力类型">
                  <button className={postKind === 'question' ? 'active' : ''} onClick={() => setPostKind('question')}><i>?</i><span><b>问一个问题</b><small>准备去 · 向当地人提问</small></span></button>
                  <button className={postKind === 'condition' ? 'active' : ''} onClick={() => setPostKind('condition')}><i>⌁</i><span><b>报个现场</b><small>正在玩 · 72 小时有效</small></span></button>
                  <button className={postKind === 'route' ? 'active' : ''} onClick={() => setPostKind('route')}><i>↗</i><span><b>分享路线</b><small>刚回来 · 留下经验</small></span></button>
                </div>
                <label className="relay-destination-field"><span>目的地</span><input value={postDestination} maxLength={64} onChange={(event) => setPostDestination(event.target.value)} placeholder="输入城市或景点" /></label>
                <textarea value={content} maxLength={1000} onChange={(event) => setContent(event.target.value)} placeholder={postKind === 'condition' ? '例如：白马大峡谷刚下过雨，木栈道湿滑，建议穿防滑鞋…' : postKind === 'route' ? '写下你实际走过的路线、耗时、花费和适合人群…' : '向正在当地或刚回来的人问一个具体问题…'} />
                <div className="relay-compose-foot"><span>{content.length}/1000</span><button onClick={() => setComposerOpen(false)}>取消</button><button className="primary" disabled={!content.trim() || !postDestination.trim() || busy} onClick={publish}>{busy ? '发布中…' : `发布到${postDestination.trim() || '目的地'}`}</button></div>
              </section>
            )}

            <section className="station-current">
              <div><small>正在浏览</small><h2>{destination}</h2><span>{Object.values(phaseCounts).reduce((sum, value) => sum + value, 0)} 条旅行者接力</span></div>
              <div className="station-phase-tabs" aria-label="旅行阶段筛选">
                <button className={phase === 'all' ? 'active' : ''} onClick={() => setPhase('all')}>全部 <b>{Object.values(phaseCounts).reduce((sum, value) => sum + value, 0)}</b></button>
                {(Object.entries(PHASE_COPY) as [TravelPhase, { label: string; hint: string }][]).map(([key, value]) => <button className={phase === key ? 'active' : ''} key={key} onClick={() => setPhase(key)}>{value.label} <b>{phaseCounts[key]}</b></button>)}
              </div>
            </section>

            <section className="relay-feed" aria-live="polite">
              {loading ? <div className="social-empty"><span className="spinner" /><b>正在打开接力站…</b></div> : posts.length === 0 ? (
                <div className="social-empty relay-first"><span>⌁</span><b>这里还没有人留下接力</b><p>成为 {destination} 第一位接棒人。你的一条真实经验，会比十条泛泛攻略更有用。</p><button onClick={() => setComposerOpen(true)}>留下第一条接力</button></div>
              ) : posts.map((post) => (
                <article className={`relay-card${post.expired ? ' expired' : ''}`} key={post.id}>
                  <div className="relay-author"><button onClick={() => openPerson(post.author.id)}><Avatar user={post.author} /><span><b>{post.author.display_name}</b><small>{post.author.home_city ? `${post.author.home_city} · ` : ''}{ago(post.created_at)}</small></span></button><div><span className={`relay-phase ${post.phase}`}>{PHASE_COPY[post.phase].label}</span><span className="relay-kind">{KIND_COPY[post.kind].icon} {KIND_COPY[post.kind].label}</span></div></div>
                  <p>{post.content}</p>
                  {post.kind === 'condition' && <div className={`relay-freshness${post.expired ? ' stale' : ''}`}><i />{post.expired ? '这条现场情报已经过期，请等待新的旅行者验证' : `现场情报 · ${post.expires_at ? new Date(post.expires_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''} 前有效`}</div>}
                  <footer>
                    <div className="relay-reactions">
                      <button disabled={post.mine} className={post.my_reaction === 'useful' ? 'active' : ''} onClick={() => react(post, 'useful')}>有用 <b>{post.reactions.useful || ''}</b></button>
                      <button disabled={post.mine} className={post.my_reaction === 'verified' ? 'active verified' : ''} onClick={() => react(post, 'verified')}>我也到过 · 属实 <b>{post.reactions.verified || ''}</b></button>
                      <button disabled={post.mine} className={post.my_reaction === 'outdated' ? 'active outdated' : ''} onClick={() => react(post, 'outdated')}>已失效 <b>{post.reactions.outdated || ''}</b></button>
                    </div>
                    {post.mine && <button className="relay-delete" onClick={() => deletePost(post.id)}>删除</button>}
                  </footer>
                </article>
              ))}
            </section>
          </div>
        )}

        {tab === 'friends' && (
          <div className="friends-page">
            <header><small>TRAVEL CONNECTIONS</small><h1>和同频的人保持联系</h1><p>好友不会自动看到你的私人行程；只有你主动分享或邀请协同时才会进入行程。</p></header>
            <section className="friend-search"><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void findPeople() }} placeholder="搜索用户名、昵称或常驻城市" /><button onClick={findPeople}>搜索旅行者</button></section>
            {people.length > 0 && <section className="people-results"><h2>找到这些旅行者</h2><div>{people.map((person) => <article key={person.id}><button className="person-main" onClick={() => openPerson(person.id)}><Avatar user={person} size="lg" /><span><b>{person.display_name}</b><small>@{person.username}{person.home_city ? ` · ${person.home_city}` : ''}</small><em>{person.travel_styles.slice(0, 3).join(' · ') || '旅行风格待补充'}</em></span></button>{person.friendship_status === 'accepted' ? <span className="friend-state">已是好友</span> : person.friendship_status === 'pending' ? <span className="friend-state">申请处理中</span> : <button className="friend-add" onClick={() => requestFriend(person.id)}>＋ 加好友</button>}</article>)}</div></section>}
            {friends.received.length > 0 && <FriendSection title={`新的好友申请 · ${friends.received.length}`} rows={friends.received} actions={(row) => <><button onClick={() => respondFriend(row.friendship_id, false)}>忽略</button><button className="primary" onClick={() => respondFriend(row.friendship_id, true)}>接受</button></>} onOpen={openPerson} />}
            <FriendSection title={`我的好友 · ${friends.friends.length}`} rows={friends.friends} empty="还没有好友。可以从接力站认识旅行风格相近的人。" actions={(row) => <button onClick={() => removeFriend(row.friendship_id)}>删除好友</button>} onOpen={openPerson} />
            {friends.sent.length > 0 && <FriendSection title="已发送的申请" rows={friends.sent} actions={(row) => <button onClick={() => removeFriend(row.friendship_id)}>撤回</button>} onOpen={openPerson} />}
          </div>
        )}

        {tab === 'profile' && viewProfile && (
          <div className="profile-page">
            <section className="profile-cover"><div className="profile-orbit" aria-hidden><i /><i /><i /></div><div className="profile-identity"><div className="profile-avatar-wrap"><Avatar user={viewProfile} size="xl" />{myProfile && <button onClick={() => avatarInputRef.current?.click()}>更换头像</button>}<input ref={avatarInputRef} type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadAvatar(file) }} /></div><div><small>17同游旅行主页</small><h1>{viewProfile.display_name}</h1><p>@{viewProfile.username}{viewProfile.home_city ? ` · 常驻 ${viewProfile.home_city}` : ''}</p>{!myProfile && (viewProfile.friendship_status === 'accepted' ? <span className="profile-friend-state">✓ 已是好友</span> : viewProfile.friendship_status === 'pending' ? <span className="profile-friend-state">申请处理中</span> : <button className="profile-add-friend" onClick={() => requestFriend(viewProfile.id)}>＋ 加为好友</button>)}</div></div><div className="profile-stats"><div><b>{viewProfile.stats.relay_posts}</b><span>旅行接力</span></div><div><b>{viewProfile.stats.verified}</b><span>被验证</span></div><div><b>{viewProfile.stats.friends}</b><span>好友</span></div></div></section>
            {myProfile && profile ? (
              <section className="profile-editor">
                <div className="profile-editor-head"><div><h2>完善旅行名片</h2><p>这些资料只用于同游圈，不会公开你的私人行程和记忆。</p></div><label className="profile-privacy"><input type="checkbox" checked={profile.profile_public} onChange={(event) => setProfile({ ...profile, profile_public: event.target.checked })} /><span>公开主页</span></label></div>
                <div className="profile-form-grid"><label><span>显示名称</span><input maxLength={40} value={profile.display_name} onChange={(event) => setProfile({ ...profile, display_name: event.target.value })} placeholder={profile.username} /></label><label><span>常驻城市</span><input maxLength={64} value={profile.home_city} onChange={(event) => setProfile({ ...profile, home_city: event.target.value })} placeholder="例如：武汉" /></label><label className="wide"><span>个人简介</span><textarea maxLength={240} value={profile.bio} onChange={(event) => setProfile({ ...profile, bio: event.target.value })} placeholder="介绍你的旅行方式、擅长路线或想认识怎样的旅行者" /></label></div>
                <div className="profile-styles"><span>我的旅行风格 · 最多 6 项</span><div>{STYLE_OPTIONS.map((style) => <button className={profile.travel_styles.includes(style) ? 'active' : ''} key={style} onClick={() => toggleStyle(style)}>{profile.travel_styles.includes(style) ? '✓ ' : '＋ '}{style}</button>)}</div></div>
                <button className="profile-save" disabled={busy} onClick={() => saveProfile()}>{busy ? '保存中…' : '保存个人主页'}</button>
              </section>
            ) : (
              <section className="public-profile-body"><div><h2>关于我</h2><p>{viewProfile.bio || '这位旅行者还没有填写个人简介。'}</p></div><div><h2>旅行风格</h2><div className="public-style-list">{viewProfile.travel_styles.length ? viewProfile.travel_styles.map((style) => <span key={style}>{style}</span>) : <p>暂未补充</p>}</div></div></section>
            )}
            {viewProfile.recent_relay.length > 0 && <section className="profile-relay-history"><div><small>RECENT RELAY</small><h2>最近留下的旅行接力</h2></div><div>{viewProfile.recent_relay.map((post) => <article key={post.id}><header><span>{post.destination}</span><b>{PHASE_COPY[post.phase].label} · {KIND_COPY[post.kind].label}</b><time>{ago(post.created_at)}</time></header><p>{post.content}</p></article>)}</div></section>}
          </div>
        )}
      </main>
    </div>
  )
}

function FriendSection({
  title,
  rows,
  empty,
  actions,
  onOpen,
}: {
  title: string
  rows: (UserCard & { friendship_id: string })[]
  empty?: string
  actions: (row: UserCard & { friendship_id: string }) => React.ReactNode
  onOpen: (id: string) => void
}) {
  return (
    <section className="friend-section"><h2>{title}</h2>{rows.length === 0 ? <div className="friend-empty">{empty}</div> : <div className="friend-grid">{rows.map((row) => <article key={row.friendship_id}><button className="person-main" onClick={() => onOpen(row.id)}><Avatar user={row} size="lg" /><span><b>{row.display_name}</b><small>@{row.username}{row.home_city ? ` · ${row.home_city}` : ''}</small><em>{row.bio || row.travel_styles.slice(0, 3).join(' · ') || '一起规划，也一起出发'}</em></span></button><div className="friend-actions">{actions(row)}</div></article>)}</div>}</section>
  )
}
