import { useCallback, useEffect, useState } from 'react'
import { ledgerRequest as request } from './Ledger'

export const roleName = (role: string) => ({owner: '创建者', editor: '可编辑', viewer: '只读'}[role] || role)
type Member = {id: string; username: string; role: string; status: string}
type Share = {token: string; role: string; expires_at: string}
export type LedgerInvite = {id: string; title: string; role: string; inviter: string}

export function LedgerInvites({onJoined}: {onJoined: (id: string) => void}) {
  const [items, setItems] = useState<LedgerInvite[]>([]), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const load = useCallback(async () => { try { setItems(await request('/invites/pending')); setError('') } catch { setError('账本邀请加载失败') } }, [])
  useEffect(() => { void load(); const timer = window.setInterval(load, 30000); return () => clearInterval(timer) }, [load])
  async function respond(id: string, accept: boolean) {
    setBusy(true)
    try { await request(`/${id}/invites/respond`, 'POST', {accept}); await load(); if (accept) onJoined(id) }
    catch (e) { setError(e instanceof Error ? e.message : '处理失败') } finally { setBusy(false) }
  }
  return <section aria-label="账本邀请">{error && <p role="alert">{error}<button onClick={() => void load()}>重试</button></p>}{items.map(i => <article className="ledger-entry" key={i.id}><div><h3>{i.title}</h3><p>{i.inviter} 邀请你协作 · {roleName(i.role)}</p></div><div className="ledger-actions"><button disabled={busy} onClick={() => void respond(i.id, false)}>拒绝</button><button disabled={busy} onClick={() => void respond(i.id, true)}>接受邀请</button></div></article>)}</section>
}

export function LedgerMembers({bookID, owner, onClose, onChanged}: {bookID: string; owner: boolean; onClose: () => void; onChanged: () => void}) {
  const [members, setMembers] = useState<Member[]>([]), [share, setShare] = useState<Share | null>(null)
  const [username, setUsername] = useState(''), [role, setRole] = useState('viewer'), [linkRole, setLinkRole] = useState('viewer')
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const load = useCallback(async () => {
    const data = await request<Member[]>(`/${bookID}/members`); setMembers(data)
    if (owner) setShare(await request<Share | null>(`/${bookID}/share`))
  }, [bookID, owner])
  useEffect(() => { void load().catch(e => setError(e.message)) }, [load])
  async function act(path: string, method: string, body?: unknown, message = '') {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try { await request(`/${bookID}${path}`, method, body); await load(); onChanged(); setNotice(message) }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败') } finally { setBusy(false) }
  }
  const link = share ? `${window.location.origin}${import.meta.env.BASE_URL}?ledger_join=${share.token}` : ''
  return <div className="ledger-modal-backdrop"><section className="ledger-modal ledger-members" role="dialog" aria-modal="true" aria-label="账本成员与分享">
    <h2>账本成员与分享</h2><p>账本权限独立于行程。编辑成员可增改删账单，只读成员只能查看。</p>
    {error && <p role="alert">{error}<button onClick={() => void load().catch(e => setError(e.message))}>重新加载</button></p>}{notice && <p role="status">{notice}</p>}
    {members.map(m => <div className="ledger-member" key={m.id}><div><strong>{m.username}</strong><small>{m.status === 'pending' ? '待接受邀请' : roleName(m.role)}</small></div>{owner && m.role !== 'owner' && <div className="ledger-actions"><select aria-label={`${m.username}的权限`} disabled={busy} value={m.role} onChange={e => void act(`/members/${m.id}`, 'PATCH', {role: e.target.value})}><option value="viewer">只读</option><option value="editor">可编辑</option></select><button disabled={busy} className="ledger-danger" onClick={() => { if (window.confirm(`移除 ${m.username}？此人将无法访问账本，已有账单保留。`)) void act(`/members/${m.id}`, 'DELETE') }}>移除</button></div>}</div>)}
    {owner && <>
      <form onSubmit={e => {e.preventDefault(); void act('/members', 'POST', {username: username.trim(), role}, '邀请已发送，对方可在记账页接受')}}><h3>邀请用户</h3><label>完整用户名<input required maxLength={64} value={username} onChange={e => setUsername(e.target.value)} placeholder="无需是好友或行程成员" /></label><label>邀请权限<select aria-label="邀请权限" value={role} onChange={e => setRole(e.target.value)}><option value="viewer">只读</option><option value="editor">可编辑 · 可增改删账单</option></select></label><button disabled={busy || !username.trim()}>发送邀请</button></form>
      <h3>通过链接加入</h3><p>持有链接的人登录后可自行加入。链接有效期 7 天，请只发给信任的人。</p>
      <label>链接加入权限<select aria-label="链接加入权限" value={linkRole} onChange={e => setLinkRole(e.target.value)}><option value="viewer">只读</option><option value="editor">可编辑 · 可增改删账单</option></select></label>
      <button disabled={busy} onClick={() => { if (!share || window.confirm('重新生成会使旧链接立即失效，已加入成员不受影响。')) void act('/share', 'POST', {role: linkRole}) }}>{share ? '重新生成链接' : '生成分享链接'}</button>
      {share && <div className="ledger-share"><p>当前链接：{roleName(share.role)} · 到期 {new Date(share.expires_at).toLocaleString('zh-CN')}</p><label>分享链接<input readOnly value={link} onFocus={e => e.target.select()} /></label><div className="ledger-actions"><button onClick={async () => { try { await navigator.clipboard.writeText(link); setNotice('链接已复制') } catch { setNotice('请长按链接或选中后复制') } }}>复制链接</button><button disabled={busy} onClick={() => { if (window.confirm('撤销链接？已加入的成员仍保留权限。')) void act('/share', 'DELETE') }}>撤销链接</button></div><small>撤销链接不移除已加入成员；如需收回权限，请在上方移除成员。</small></div>}
    </>}
    <div className="ledger-actions"><button disabled={busy} onClick={onClose}>完成</button></div>
  </section></div>
}
