/**
 * 邀请码管理（Phase 74）：取代写死在 .env 的单一常量。
 * 每码限量（默认 5 人），用满即失效，需要再生成新的。
 */
import { useCallback, useEffect, useState } from 'react'
import { API, authFetch } from '../api'

export interface InviteCode {
  code: string
  max_uses: number
  used_count: number
  active: boolean
  exhausted: boolean
  usable: boolean
  created_at: string | null
}

export function AdminInvites() {
  const [items, setItems] = useState<InviteCode[]>([])
  const [envFallback, setEnvFallback] = useState(false)
  const [uses, setUses] = useState(5)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/admin/invites`)
      if (!res.ok) return
      const data = await res.json()
      setItems(data.invites || [])
      setEnvFallback(!!data.env_fallback)
    } catch {
      /* 忽略 */
    }
  }, [])
  useEffect(() => { load() }, [load])

  const create = async () => {
    setBusy(true)
    try {
      const res = await authFetch(`${API}/admin/invites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_uses: uses }),
      })
      if (res.ok) load()
    } finally {
      setBusy(false)
    }
  }

  const deactivate = async (code: string) => {
    if (!window.confirm(`停用邀请码 ${code}？已用它注册的账号不受影响。`)) return
    await authFetch(`${API}/admin/invites/${code}`, { method: 'DELETE' })
    load()
  }

  const copy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(code)
      window.setTimeout(() => setCopied(''), 1600)
    } catch {
      /* 剪贴板不可用时用户可以手抄，码里已排除易混字符 */
    }
  }

  return (
    <div className="modal-body">
      <div className="admin-form invite-form">
        <label>
          每个码可邀请
          <input
            type="number"
            min={1}
            max={500}
            value={uses}
            onChange={(e) => setUses(Math.max(1, Number(e.target.value) || 1))}
          />
          人
        </label>
        <button onClick={create} disabled={busy}>{busy ? '生成中…' : '＋ 生成邀请码'}</button>
      </div>
      {envFallback && (
        <div className="invite-note">
          注意：服务器 .env 里还配着一个固定邀请码，它**不限人数**且仍然有效。
          想完全改用限量码，请清空服务器的 <code>REGISTER_INVITE_CODE</code> 后重启。
        </div>
      )}
      {items.length === 0 && (
        <div className="support-empty">
          <span aria-hidden>🎟️</span>
          <p>还没有邀请码。生成一个后发给朋友，用满 {uses} 人自动失效。</p>
        </div>
      )}
      {items.map((c) => (
        <div key={c.code} className={`invite-row${c.usable ? '' : ' dead'}`}>
          <button className="invite-code" onClick={() => copy(c.code)} title="点击复制">
            {c.code}
            <small>{copied === c.code ? '已复制' : '复制'}</small>
          </button>
          <span className="invite-uses">
            {c.used_count} / {c.max_uses}
            <i>{!c.active ? '已停用' : c.exhausted ? '已用完' : '可用'}</i>
          </span>
          {c.active && (
            <button className="link-danger" onClick={() => deactivate(c.code)}>停用</button>
          )}
        </div>
      ))}
    </div>
  )
}
