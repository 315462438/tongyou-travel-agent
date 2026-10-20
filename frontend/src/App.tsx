import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react'
import { API, authFetch, clearToken, getToken, setUnauthorizedHandler } from './api'
import { isAndroidApp, notifyAndroidReady } from './nativeAndroid'

const Home = lazy(() => import('./pages/Home'))
const LedgerJoin = lazy(() => import('./pages/LedgerJoin'))
const Auth = lazy(() => import('./Auth'))

interface AuthedUser {
  username: string
  is_admin: boolean
  display_name?: string
  avatar_url?: string
  must_change_password?: boolean
}

export default function App() {
  const [user, setUser] = useState<AuthedUser | null>(null)
  const [ledgerJoin, setLedgerJoin] = useState(() => new URLSearchParams(window.location.search).get('ledger_join') || localStorage.getItem('travel_pending_ledger_join'))
  const [joinLogin, setJoinLogin] = useState(false)
  const [ready, setReady] = useState(false)
  const [connectionError, setConnectionError] = useState(false)
  const [retry, setRetry] = useState(0)

  // Phase 42：分享链接落地（?join=token）——暂存到 localStorage 撑过注册/登录流程，
  // 行程由 Home 消费；账本邀请在用户完成前保留 URL，允许微信转 Safari。
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const ledgerToken = params.get('ledger_join') || localStorage.getItem('travel_pending_ledger_join')
    if (ledgerToken) {
      // A ledger invite never consumes a separate trip invite, even in a mixed URL.
      params.delete('join')
      localStorage.removeItem('travel_pending_join')
      localStorage.setItem('travel_pending_ledger_join', ledgerToken)
      params.set('ledger_join', ledgerToken)
      const qs = params.toString()
      window.history.replaceState(null, '', window.location.pathname + (qs ? `?${qs}` : '') + window.location.hash)
    }
    const join = params.get('join')
    if (join) {
      localStorage.setItem('travel_pending_join', join)
      params.delete('join')
      const qs = params.toString()
      window.history.replaceState(null, '', window.location.pathname + (qs ? `?${qs}` : ''))
    }
  }, [])

  function finishLedgerInvite() {
    localStorage.removeItem('travel_pending_ledger_join')
    const url = new URL(window.location.href)
    url.searchParams.delete('ledger_join')
    window.history.replaceState(null, '', url.pathname + url.search + url.hash)
    setLedgerJoin(null)
    setJoinLogin(false)
  }

  const logout = useCallback(() => {
    authFetch(`${API}/auth/logout`, { method: 'POST' }).catch(() => {})
    clearToken()
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
  }, [])

  useEffect(() => {
    setConnectionError(false)
    if (!getToken()) {
      setReady(true)
      return
    }
    // A stalled authentication request must not leave the Android launch screen forever.
    const controller = new AbortController()
    let active = true
    const timeout = isAndroidApp() ? window.setTimeout(() => controller.abort(), 8000) : undefined
    authFetch(`${API}/auth/me`, { signal: controller.signal })
      .then((r) => { if (r.status >= 500) throw new Error('service unavailable'); return r.ok ? r.json() : null })
      .then((data) => active && data && setUser({
        username: data.username, is_admin: data.is_admin,
        display_name: data.display_name, avatar_url: data.avatar_url,
        must_change_password: data.must_change_password,
      }))
      .catch(() => { if (active && isAndroidApp()) setConnectionError(true) })
      .finally(() => { window.clearTimeout(timeout); if (active) setReady(true) })
    return () => { active = false; window.clearTimeout(timeout); controller.abort() }

  }, [retry])

  if (connectionError) return <AndroidReady><div className="app-loading" role="alert"><span>暂时连接不上服务器，登录信息已保留。</span><button onClick={() => { setReady(false); setRetry(n => n + 1) }}>重新连接</button></div></AndroidReady>
  if (!ready) return <AppLoading label="正在确认登机信息…" />
  return (
    <Suspense fallback={<AppLoading label="正在准备你的旅程…" />}>
      <AndroidReady>
      {ledgerJoin && (user || !joinLogin) ? <LedgerJoin token={ledgerJoin} loggedIn={!!user} onLogin={() => setJoinLogin(true)} onCancel={finishLedgerInvite} onJoined={id => {localStorage.removeItem('travel_pending_join'); localStorage.setItem('travel_open_ledger', id); finishLedgerInvite()}} /> : !user ? <Auth onAuthed={setUser} /> : (
        <Home
          user={user}
          onLogout={logout}
          onProfileChanged={(profile) => setUser((current) => current ? { ...current, ...profile } : current)}
          onPasswordChanged={() => setUser((u) => (u ? { ...u, must_change_password: false } : u))}
        />
      )}
      </AndroidReady>
    </Suspense>
  )
}

function AppLoading({ label }: { label: string }) {
  return (
    <div className="app-loading" role="status" aria-live="polite">
      <span className="app-loading-mark">✈</span>
      <span>{label}</span>
    </div>
  )
}

// Inside Suspense: runs only after the actual screen (including lazy chunks) commits.
function AndroidReady({ children }: { children: ReactNode }) {
  useEffect(() => notifyAndroidReady(), [])
  return children
}
