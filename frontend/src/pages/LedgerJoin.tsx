import { useEffect, useState } from 'react'
import { API, authFetch } from '../api'
import { roleName } from './LedgerCollaboration'
import './Ledger.css'
import OpenLedgerApp from '../components/OpenLedgerApp'

type Preview = {title: string; inviter: string; role: string; expires_at: string}
export default function LedgerJoin({token, loggedIn, onLogin, onJoined, onCancel}: {token: string; loggedIn: boolean; onLogin: () => void; onJoined: (id: string) => void; onCancel: () => void}) {
  const [preview, setPreview] = useState<Preview | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => { let active = true; setPreview(null); setError(''); fetch(`${API}/ledger/shared/${encodeURIComponent(token)}`).then(async r => { const data = await r.json(); if (!r.ok) throw new Error(data.detail || '链接无效'); if (active) setPreview(data) }).catch(e => {if (active) setError(e.message)}); return () => {active = false} }, [token, retry])
  async function join() {
    if (!loggedIn) { onLogin(); return }
    setBusy(true); setError('')
    try { const r = await authFetch(`${API}/ledger/join`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token})}); const d = await r.json(); if (!r.ok) throw new Error(d.detail || '加入失败'); onJoined(d.id) }
    catch (e) { setError(e instanceof Error ? e.message : '加入失败') } finally { setBusy(false) }
  }
  return <section className="ledger-shell ledger-join"><div className="ledger-modal"><p>17同游 · 账本邀请</p><h1>{preview?.title || '加入共享账本'}</h1><OpenLedgerApp token={token} />{preview && <><p>{preview.inviter} 邀请你加入，权限为「{roleName(preview.role)}」。</p><p>{preview.role === 'editor' ? '加入后可以查看、添加、修改和删除账单。' : '加入后可以查看账单、统计和汇率，不可修改账单。'}</p><p>加入账本不会加入关联的协同行程。</p></>}{error && <p role="alert">{error}<button onClick={() => setRetry(x => x + 1)}>重试</button></p>}<div className="ledger-actions"><button disabled={busy} onClick={onCancel}>暂不加入</button><button className="ledger-primary" disabled={busy || !preview} onClick={() => void join()}>{busy ? '正在加入…' : loggedIn ? '确认加入账本' : '登录或注册后加入'}</button></div></div></section>
}
