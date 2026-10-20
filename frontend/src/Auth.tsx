import { useState } from 'react'
import { API, setToken } from './api'
import { useToast } from './components/toast-context'
import { BrandWordmark } from './components/Brand'

interface AuthedUser {
  username: string
  is_admin: boolean
  display_name?: string
  avatar_url?: string
  must_change_password?: boolean
}

/**
 * 登录 / 注册（2026-10-19 与 iOS App 统一为 Liquid Glass 风格）。
 *
 * 旧版是「登机牌」双栏票根（天空 + WebGL 光线 + 副票根），手机上挤且多一层 WebGL 开销；
 * 现在照 iOS `LoginView` 的形状：三色光晕背景 + 一枚玻璃卡（分段控件 + 胶囊输入 + 主按钮）。
 * 交互与协议未变：同一个 /auth/login|register，邀请码只在注册时出现。
 */
export default function Auth({ onAuthed }: { onAuthed: (u: AuthedUser) => void }) {
  const [registering, setRegistering] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [invite, setInvite] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
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
      const mode = registering ? 'register' : 'login'
      const res = await fetch(`${API}/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password, invite_code: invite.trim() }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || '出了点问题，再试一次。')
        return
      }
      setToken(data.token)
      notify(registering ? '账号创建成功，欢迎登机' : '欢迎回来，正在载入你的行程', 'success')
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

  const switchMode = (next: boolean) => {
    setRegistering(next)
    setError('')
  }

  return (
    <div className="auth-screen">
      {/* 三色光晕（与 iOS Backdrop 同色：sky / dusk / warm），纯 CSS，不用 WebGL */}
      <div className="auth-aura" aria-hidden />

      <div className="auth-panel">
        <header className="auth-brand">
          <img className="auth-mark" src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width={76} height={76} />
          <BrandWordmark className="auth-wordmark" />
          <p className="auth-tagline">一起规划，一起出发</p>
        </header>

        <div className="auth-card glass">
          <div className="auth-seg" role="tablist" aria-label="账号操作">
            <button
              type="button" role="tab" aria-selected={!registering}
              className={!registering ? 'on' : ''} onClick={() => switchMode(false)}
            >
              登录
            </button>
            <button
              type="button" role="tab" aria-selected={registering}
              className={registering ? 'on' : ''} onClick={() => switchMode(true)}
            >
              注册
            </button>
          </div>

          <form onSubmit={(e) => { e.preventDefault(); submit() }} aria-busy={busy}>
            <label className="auth-field glass-input">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <circle cx="12" cy="8" r="3.6" /><path d="M4.5 20c.7-3.9 3.6-5.8 7.5-5.8s6.8 1.9 7.5 5.8" />
              </svg>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value.slice(0, 20))}
                placeholder="用户名"
                autoComplete="username"
                maxLength={20}
                disabled={busy}
                autoFocus
              />
              {registering && username.length > 0 && (
                <small className={`auth-hint${usernameHint ? ' bad' : ''}`}>
                  {usernameHint || `${username.length}/20`}
                </small>
              )}
            </label>

            <label className="auth-field glass-input">
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <rect x="4.5" y="10" width="15" height="10" rx="2.6" /><path d="M8 10V7.6a4 4 0 0 1 8 0V10" />
              </svg>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={registering ? '密码（至少 6 位）' : '密码'}
                autoComplete={registering ? 'new-password' : 'current-password'}
                disabled={busy}
              />
              <button
                type="button" className="auth-reveal"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
              >
                {showPassword ? '隐藏' : '显示'}
              </button>
            </label>

            {registering && (
              <label className="auth-field glass-input">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M3 9.5 12 4l9 5.5-9 5.5z" /><path d="M3 9.5V16l9 5.5V15" />
                </svg>
                <input
                  value={invite}
                  onChange={(e) => setInvite(e.target.value)}
                  placeholder="邀请码"
                  autoComplete="off"
                  disabled={busy}
                />
              </label>
            )}

            {registering && (
              <p className="auth-note">目前为邀请注册，可以向邀请你的朋友要邀请码。</p>
            )}

            <div className="auth-status" aria-live="polite">
              {error && <div className="auth-error">{error}</div>}
            </div>

            <button type="submit" className="auth-submit glass-primary" disabled={busy}>
              {busy ? <><span className="button-spinner" /> 办理中…</> : registering ? '注册并登录' : '登录'}
            </button>
          </form>
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
