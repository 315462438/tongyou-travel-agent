import { useState } from 'react'
import { API, setToken } from './api'
import SideRays from './components/SideRays'
import { useToast } from './components/toast-context'
import { BrandIcon, BrandWordmark } from './components/Brand'

interface AuthedUser {
  username: string
  is_admin: boolean
  display_name?: string
  avatar_url?: string
  must_change_password?: boolean
}

export default function Auth({ onAuthed }: { onAuthed: (u: AuthedUser) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [inviteCode, setInviteCode] = useState('')
  // 与后端 _USERNAME_RE 同规则，在输入时就给出提示，而不是提交后才报错
  const usernameHint = username && !/^[\u4e00-\u9fa5A-Za-z0-9_]{2,20}$/.test(username)
    ? (username.length < 2 ? '至少 2 位' : '仅限中英文、数字、下划线')
    : ''
  const { notify } = useToast()

  const submit = async () => {
    if (busy) return
    setError('')
    if (!username.trim() || !password) {
      setError('用户名和密码都要填。')
      return
    }
    setBusy(true)
    try {
      const res = await fetch(`${API}/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password, invite_code: inviteCode.trim() }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || '出了点问题，再试一次。')
        return
      }
      setToken(data.token)
      notify(mode === 'login' ? '欢迎回来，正在载入你的行程' : '账号创建成功，欢迎登机', 'success')
      onAuthed({
        username: data.username, is_admin: data.is_admin,
        display_name: data.display_name, avatar_url: data.avatar_url,
        must_change_password: data.must_change_password,
      })
    } catch {
      setError('连不上服务器，检查下网络。')
    } finally {
      setBusy(false)
    }
  }

  const today = new Date()
  const dateCode = `${today.getMonth() + 1}月${today.getDate()}日`.toUpperCase()

  return (
    <div className="auth-sky">
      <SideRays
        className="auth-rays"
        origin="top-right"
        rayColor1="#ffd06b"
        rayColor2="#bfe2ff"
        speed={2}
        intensity={2.6}
        spread={2.1}
        saturation={1.6}
        blend={0.42}
        falloff={1.5}
        opacity={0.92}
      />
      <div className="auth-brandline">
        <h1 className="auth-wordmark"><BrandWordmark /></h1>
        <p className="auth-tagline">17tongyou · 一起规划，一起出发</p>
      </div>

      <div className="auth-route" aria-hidden>
        <span className="auth-route-line" />
        <span className="auth-plane">✈</span>
        <span className="auth-route-line" />
      </div>

      <div className="pass">
        {/* 主票根：表单 */}
        <div className="pass-main">
          <div className="pass-eyebrow">BOARDING PASS · 登机牌</div>
          <h1 className="pass-title">{mode === 'login' ? '欢迎回来' : '开始旅程'}</h1>
          <div className="pass-sub">
            {mode === 'login' ? '登录后继续你的行程规划' : '注册一个账号，行程与记忆只属于你'}
          </div>

          <div className="pass-tabs" role="tablist" aria-label="账号操作">
            <button type="button" role="tab" aria-selected={mode === 'login'} className={mode === 'login' ? 'on' : ''} onClick={() => { setMode('login'); setError('') }}>
              登录
            </button>
            <button type="button" role="tab" aria-selected={mode === 'register'} className={mode === 'register' ? 'on' : ''} onClick={() => { setMode('register'); setError('') }}>
              注册
            </button>
          </div>

          <form onSubmit={(e) => { e.preventDefault(); submit() }} aria-busy={busy}>
            <label className="pass-field">
              <span className="pass-label">
                乘客 · PASSENGER
                {/* 即时校验：此前超长/非法用户名要提交后才由后端报错 */}
                {mode === 'register' && username.length > 0 && (
                  <small className={`pass-count${usernameHint ? ' bad' : ''}`}>
                    {usernameHint || `${username.length}/20`}
                  </small>
                )}
              </span>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value.slice(0, 20))}
                placeholder="用户名"
                autoComplete="username"
                maxLength={20}
                disabled={busy}
                autoFocus
              />
            </label>
            <label className="pass-field">
              <span className="pass-label">密钥 · PASSCODE</span>
              <span className="pass-password-wrap">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === 'register' ? '至少 6 位' : '密码'}
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                  disabled={busy}
                />
                <button type="button" className="pass-reveal" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? '隐藏密码' : '显示密码'}>
                  {showPassword ? '隐藏' : '显示'}
                </button>
              </span>
            </label>
            {mode === 'register' && (
              <label className="pass-field">
                <span className="pass-label">邀请码 · INVITE</span>
                <input
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  placeholder="向邀请你的朋友要一个"
                  autoComplete="off"
                  disabled={busy}
                />
              </label>
            )}

            <div className="pass-form-status" aria-live="polite">
              {error && <div className="pass-error">{error}</div>}
            </div>

            <button type="submit" className="pass-go" disabled={busy}>
              {busy ? <><span className="button-spinner" /> 办理中…</> : mode === 'login' ? '登机' : '办理登机'}
            </button>
          </form>
        </div>

        {/* 副票根：品牌 + 目的地 */}
        <div className="pass-stub">
          <div className="pass-perf" aria-hidden />
          <div className="stub-brand">
            <span className="stub-mark">
              <BrandIcon size={19} />
            </span>
            <BrandWordmark className="stub-name" />
          </div>
          <div className="stub-row"><span>航班</span><b>17·017</b></div>
          <div className="stub-row"><span>日期</span><b>{dateCode}</b></div>
          <div className="stub-row"><span>舱位</span><b>FIRST CLASS</b></div>
          <div className="stub-row"><span>目的地</span><b>ANYWHERE</b></div>
          <div className="stub-tag">你想去哪，都可以</div>
        </div>
      </div>

      <footer className="auth-beian">
        <a href="https://beian.miit.gov.cn" target="_blank" rel="noopener noreferrer">
          鄂ICP备2026020535号-2
        </a>
      </footer>
    </div>
  )
}
