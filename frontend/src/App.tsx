import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { API, authFetch, clearToken, getToken, setUnauthorizedHandler } from './api'

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

  // Phase 42：分享链接落地（?join=token）——暂存到 localStorage 撑过注册/登录流程，
  // 由 Home 挂载后消费；随后清理地址栏参数
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const ledgerToken = params.get('ledger_join')
    if (ledgerToken) {
      // A ledger invite never consumes a separate trip invite, even in a mixed URL.
      params.delete('join')
      localStorage.removeItem('travel_pending_join')
      localStorage.setItem('travel_pending_ledger_join', ledgerToken)
      params.delete('ledger_join')
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

  const logout = useCallback(() => {
    authFetch(`${API}/auth/logout`, { method: 'POST' }).catch(() => {})
    clearToken()
    setUser(null)
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
  }, [])

  useEffect(() => {
    if (!getToken()) {
      setReady(true)
      return
    }
    authFetch(`${API}/auth/me`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => data && setUser({
        username: data.username, is_admin: data.is_admin,
        display_name: data.display_name, avatar_url: data.avatar_url,
        must_change_password: data.must_change_password,
      }))
      .finally(() => setReady(true))
  }, [])

  if (!ready) return <AppLoading label="正在确认登机信息…" />
  return (
    <Suspense fallback={<AppLoading label="正在准备你的旅程…" />}>
      {ledgerJoin && (user || !joinLogin) ? <LedgerJoin token={ledgerJoin} loggedIn={!!user} onLogin={() => setJoinLogin(true)} onCancel={() => {localStorage.removeItem('travel_pending_ledger_join'); setLedgerJoin(null)}} onJoined={id => {localStorage.removeItem('travel_pending_ledger_join'); localStorage.removeItem('travel_pending_join'); localStorage.setItem('travel_open_ledger', id); setLedgerJoin(null)}} /> : !user ? <Auth onAuthed={setUser} /> : (
        <Home
          user={user}
          onLogout={logout}
          onProfileChanged={(profile) => setUser((current) => current ? { ...current, ...profile } : current)}
          onPasswordChanged={() => setUser((u) => (u ? { ...u, must_change_password: false } : u))}
        />
      )}
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
