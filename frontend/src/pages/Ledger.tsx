import { useCallback, useEffect, useRef, useState } from 'react'
import { API, authFetch } from '../api'
import './Ledger.css'
import { LedgerInvites, LedgerMembers, roleName } from './LedgerCollaboration'

const currencies = ['CNY', 'MYR', 'SGD', 'USD', 'EUR', 'JPY', 'HKD', 'THB', 'KRW', 'GBP', 'AUD', 'TWD', 'VND', 'IDR']
const currencyNames: Record<string, string> = {CNY: '人民币', MYR: '马币', SGD: '新币', USD: '美元', EUR: '欧元', JPY: '日元', HKD: '港币', THB: '泰铢', KRW: '韩元', GBP: '英镑', AUD: '澳元', TWD: '台币', VND: '越南盾', IDR: '印尼盾'}
const categories = ['餐饮', '交通', '住宿', '门票', '购物', '其他']
type Entry = { version?: number; id: string; title: string; amount_minor: number; currency: string; category: string; spent_at: string; note: string }
type Trip = { id: string; title: string }
type Book = { role: string; trip?: Trip | null; id: string; title: string; count: number; target_currency: string; totals: Record<string, number>; by_category: {currency: string; category: string; amount_minor: number}[]; entries?: Entry[] }
type Conversion = { target_currency: string; total_minor: number | null; stale: boolean; source: string; fetched_at: string; missing: string[]; items: {currency: string; rate: string; rate_date: string; converted_minor: number}[] }
const money = (minor: number, currency: string) => `${currency} ${(minor / 100).toLocaleString('zh-CN', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
export async function ledgerRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await authFetch(`${API}/ledger${path}`, { method, headers: {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)}) })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '保存失败，请检查金额、日期和名称后重试')
  return data
}

const request = ledgerRequest

export default function Ledger({onClose, initialTrip, initialBookID}: {onClose: () => void; initialTrip?: Trip | null; initialBookID?: string | null}) {
  const [tripFilter, setTripFilter] = useState(initialTrip || null)
  const [books, setBooks] = useState<Book[]>([])
  const [selected, setSelected] = useState<string | null>(initialBookID || null)
  const [book, setBook] = useState<Book | null>(null)
  const [showMembers, setShowMembers] = useState(false)
  const [fx, setFx] = useState<Conversion | null>(null)
  const [fxBusy, setFxBusy] = useState(false)
  const [fxError, setFxError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [bookForm, setBookForm] = useState<{id?: string; title: string; trip?: Trip | null} | null>(null)
  const [entryForm, setEntryForm] = useState<Entry | 'new' | null>(null)
  const [confirm, setConfirm] = useState<{title: string; path: string; wholeBook: boolean; method?: string} | null>(null)
  const generation = useRef(0)
  const fxGeneration = useRef(0)
  const refreshFx = useCallback(async (id: string, refresh = false) => {
    const seq = ++fxGeneration.current
    setFxBusy(true); setFxError(''); setFx(null)
    try { const data = await request<Conversion>(`/${id}/conversion?refresh=${refresh}`); if (seq === fxGeneration.current) setFx(data) }
    catch (e) { if (seq === fxGeneration.current) setFxError(e instanceof Error ? e.message : '汇率查询失败') }
    finally { if (seq === fxGeneration.current) setFxBusy(false) }
  }, [])
  const load = useCallback(async () => {
    const seq = ++generation.current
    setLoading(true); setError('')
    try {
      if (selected) {
        const data = await request<Book>(`/${selected}`)
        if (seq === generation.current) { setBook(data); void refreshFx(selected) }
      } else {
        const data = await request<Book[]>(tripFilter ? `?trip_id=${encodeURIComponent(tripFilter.id)}` : '')
        if (seq === generation.current) setBooks(data)
      }
    } catch (e) { if (seq === generation.current) { setBook(null); setFx(null); setError(e instanceof Error ? e.message : '加载失败，请重试') } }
    finally { if (seq === generation.current) setLoading(false) }
  }, [selected, refreshFx, tripFilter])
  useEffect(() => { setBook(null); setFx(null); void load(); return () => { generation.current++; fxGeneration.current++ } }, [load])
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && !bookForm && !entryForm && !confirm && !busy) onClose() }
    window.addEventListener('keydown', esc); return () => window.removeEventListener('keydown', esc)
  }, [onClose, bookForm, entryForm, confirm, busy])
  useEffect(() => {
    const refresh = () => { if (!busy && !bookForm && !entryForm && !confirm && !showMembers && document.visibilityState === 'visible') void load() }
    const timer = window.setInterval(refresh, 15000)
    window.addEventListener('focus', refresh)
    return () => {clearInterval(timer); window.removeEventListener('focus', refresh)}
  }, [load, busy, bookForm, entryForm, confirm, showMembers])
  const remove = async () => {
    if (!confirm || busy) return
    setBusy(true); setError('')
    try { await request(confirm.path, confirm.method || 'DELETE'); setConfirm(null); if (confirm.wholeBook) { setBook(null); setSelected(null) } else await load() }
    catch (e) { setError(e instanceof Error ? e.message : '删除失败') }
    finally { setBusy(false) }
  }
  const setCurrency = async (currency: string) => {
    if (!book || busy) return
    setBusy(true); setError(''); setFx(null)
    try { await request(`/${book.id}/currency`, 'PATCH', {target_currency: currency}); setBook({...book, target_currency: currency}); await refreshFx(book.id) }
    catch (e) { setError(e instanceof Error ? e.message : '修改失败') }
    finally { setBusy(false) }
  }
  const canEdit = book?.role === 'owner' || book?.role === 'editor'
  const isOwner = book?.role === 'owner'
  const totals = (b: Book) => Object.entries(b.totals).map(([c, n]) => <span key={c}>{money(n, c)}</span>)
  const dates = [...new Set(book?.entries?.map(e => e.spent_at) || [])].sort().reverse()
  return <section className="ledger-shell" aria-label="旅行记账">
    <header className="ledger-header"><div><span className="ledger-eyebrow">旅行账本</span><h1>{book?.title || '旅行记账'}</h1></div><div className="ledger-actions">
      {tripFilter && <button onClick={() => { setTripFilter(null); setSelected(null) }}>显示全部账本</button>}
      {selected && <button disabled={busy} onClick={() => setSelected(null)}>全部账本</button>}
      <button disabled={busy || loading} onClick={() => void load()}>刷新账本</button>
      <button onClick={onClose} aria-label="关闭旅行记账">关闭</button>
    </div></header>
    <main className="ledger-content">
      {error && <div role="alert" className="ledger-error">{error}<button onClick={() => void load()}>重试</button></div>}
      {loading && <p role="status">正在加载…</p>}
      {!selected ? <>
        <LedgerInvites onJoined={id => { setTripFilter(null); setSelected(id) }} />
        <div className="ledger-intro"><div><h2>{tripFilter ? `${tripFilter.title} · 我的账本` : '把旅途花费，记得清清楚楚'}</h2><p>不必先建行程。记录原币支出，按你期望的币种汇总。</p></div><button className="ledger-primary" onClick={() => setBookForm({title: '', trip: tripFilter})}>＋ 新建账本</button></div>
        {!loading && !books.length && <div className="ledger-empty">还没有账本，为下一趟旅行建一个吧。</div>}
        <div className="ledger-books">{books.map(b => <button key={b.id} className="ledger-book" onClick={() => setSelected(b.id)}><span>{b.count} 笔支出 · {roleName(b.role)}</span><h2>{b.title}</h2><p>{b.trip ? `关联行程：${b.trip.title}` : '独立账本'}</p><div className="ledger-original">{b.count ? totals(b) : '还没有支出'}</div><small>查看账本 →</small></button>)}</div>
      </> : book && <>
        <p className="ledger-link-info">{book.trip ? `关联行程：${book.trip.title}` : '独立账本 · 未关联行程'} · {roleName(book.role)} · 仅账本成员可见</p>
        <div className="ledger-summary">
          <div className="ledger-total">
            <div className="ledger-total-head"><span>累计支出 · {book.count} 笔</span><select aria-label="汇总币种" value={book.target_currency} disabled={!isOwner || busy || fxBusy} onChange={e => void setCurrency(e.target.value)}>{currencies.map(c => <option key={c} value={c}>{c} · {currencyNames[c]}</option>)}</select></div>
            <div className="ledger-total-main"><h2 aria-live="polite">{fxBusy ? '正在换算…' : fx?.total_minor != null ? money(fx.total_minor, fx.target_currency) : '暂无法完整换算'}</h2>{canEdit && <button className="ledger-primary" onClick={() => setEntryForm('new')}>＋ 记一笔</button>}</div>
            <p>按最新参考汇率估算</p>
            {fxError && <p role="alert">{fxError}，可展开明细重试。</p>}
            {fx?.stale && <p role="alert">更新暂不可用，当前使用上次查询的汇率。</p>}
            {!!fx?.missing.length && <p role="alert">未获得 {fx.missing.join('、')} 汇率，暂不显示完整总额。</p>}
            <details className="ledger-rate"><summary>汇率与原币明细</summary><div className="ledger-rate-content">
              <div className="ledger-original">原币合计：{book.count ? totals(book) : '暂无支出'}</div>
              {fx?.items.filter(i => i.currency !== fx.target_currency).map(i => <p key={i.currency}>1 {i.currency} ≈ {Number(i.rate).toFixed(6)} {fx.target_currency}<small>行情日期 {i.rate_date}</small></p>)}
              {fx?.fetched_at && <small>Frankfurter · 查询于 {new Date(fx.fetched_at).toLocaleString('zh-CN')}</small>}
              <small>参考汇率按日更新，实际换汇或刷卡金额可能不同。</small>
              <button disabled={fxBusy || busy} onClick={() => void refreshFx(book.id, true)}>刷新汇率</button>
            </div></details>
          </div>
        </div>
        <div className="ledger-actions ledger-toolbar"><h3>支出明细</h3><button onClick={() => setShowMembers(true)}>成员与分享</button><details className="ledger-more"><summary>更多</summary><div className="ledger-more-menu">{isOwner ? <><button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); setBookForm({id: book.id, title: book.title, trip: book.trip}) }}>编辑账本</button><button className="ledger-danger" onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); setConfirm({title: '删除账本及全部账单？所有成员将失去访问权，此操作不可恢复。', path: `/${book.id}`, wholeBook: true}) }}>删除账本</button></> : <button onClick={e => { e.currentTarget.closest('details')?.removeAttribute('open'); setConfirm({title: '退出此账本？已有账单将保留，你将失去访问权限。', path: `/${book.id}/leave`, method: 'POST', wholeBook: true}) }}>退出账本</button>}</div></details></div>
        <div className="ledger-detail-grid"><section>
          {!book.entries?.length && <div className="ledger-empty">还没有账单，先记下今天的第一笔花费吧。</div>}
          {dates.map(date => <section key={date} className="ledger-day"><h3>{date}</h3>{book.entries?.filter(e => e.spent_at === date).map(e => <article key={e.id} className="ledger-entry"><div><h4>{e.title}</h4><p>{e.category}{e.note && ` · ${e.note}`}</p></div><b>{money(e.amount_minor, e.currency)}</b>{canEdit && <div className="ledger-actions"><button aria-label={`编辑账单 ${e.title}`} onClick={() => setEntryForm(e)}>编辑</button><button aria-label={`删除账单 ${e.title}`} className="ledger-danger" onClick={() => setConfirm({title: `删除「${e.title}」？`, path: `/${book.id}/entries/${e.id}?version=${e.version || 1}`, wholeBook: false})}>删除</button></div>}</article>)}</section>)}
        </section><aside className="ledger-categories"><h3>分类汇总 · 原币</h3>{book.by_category.map(c => <p key={c.currency+c.category}><span>{c.category}</span><b>{money(c.amount_minor,c.currency)}</b></p>)}</aside></div>
      </>}
    </main>
    {showMembers && book && <LedgerMembers bookID={book.id} owner={isOwner} onClose={() => setShowMembers(false)} onChanged={() => void load()} />}
    {bookForm && <BookEditor initial={bookForm} onClose={() => setBookForm(null)} onSaved={() => { setBookForm(null); void load() }} />}
    {entryForm && book && <EntryEditor bookID={book.id} defaultCurrency={book.entries?.[0]?.currency || 'CNY'} entry={entryForm === 'new' ? undefined : entryForm} onClose={() => {setEntryForm(null); void load()}} onSaved={() => { setEntryForm(null); void load() }} />}
    {confirm && <div className="ledger-modal-backdrop"><section className="ledger-modal" role="alertdialog" aria-modal="true" aria-label="确认删除"><h2>{confirm.title}</h2>{error && <p role="alert">{error}</p>}<div className="ledger-actions"><button disabled={busy} onClick={() => setConfirm(null)}>取消</button><button className="ledger-danger" disabled={busy} onClick={() => void remove()}>{busy ? '处理中…' : confirm.method === 'POST' ? '确认退出' : '确认删除'}</button></div></section></div>}
  </section>
}
function BookEditor({initial, onClose, onSaved}: {initial: {id?: string; title: string; trip?: Trip | null}; onClose: () => void; onSaved: () => void}) {
  const [title, setTitle] = useState(initial.title), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [tripID, setTripID] = useState(initial.trip?.id || '')
  const [trips, setTrips] = useState<Trip[]>(initial.trip ? [initial.trip] : [])
  const [tripError, setTripError] = useState('')
  const loadTrips = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/trips`)
      if (!res.ok) throw new Error('行程加载失败，可重试；仍可保存独立账本。')
      setTrips(await res.json()); setTripError('')
    } catch { setTripError('行程加载失败，可重试；仍可保存独立账本。') }
  }, [])
  useEffect(() => { void loadTrips() }, [loadTrips])
  return <div className="ledger-modal-backdrop"><form className="ledger-modal" role="dialog" aria-modal="true" aria-label={initial.id ? '编辑账本' : '新建账本'} onSubmit={async e => { e.preventDefault(); if (busy) return; setBusy(true); try { await request(initial.id ? `/${initial.id}` : '', initial.id ? 'PATCH' : 'POST', {title, trip_id: tripID || null}); onSaved() } catch (e) {setError(e instanceof Error ? e.message : '保存失败')} finally {setBusy(false)} }}>
    <h2>{initial.id ? '编辑账本' : '新建账本'}</h2><label>账本名称<input autoFocus required maxLength={80} value={title} onChange={e => setTitle(e.target.value)} placeholder="比如：马来西亚旅行" /></label>
    <label>关联行程（选填）<select aria-label="关联行程" value={tripID} onChange={e => setTripID(e.target.value)}><option value="">不关联 · 独立账本</option>{tripID && !trips.some(t => t.id === tripID) && <option value={tripID}>原关联行程（需重新选择）</option>}{trips.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
    <p>默认仅自己可见。创建后可单独邀请账本成员，关联行程不会自动共享。</p>
    {tripError && <p role="alert">{tripError}<button type="button" onClick={() => void loadTrips()}>重试加载行程</button></p>}{error && <p role="alert">{error}</p>}<div className="ledger-actions"><button type="button" disabled={busy} onClick={onClose}>取消</button><button className="ledger-primary" disabled={busy || !title.trim()}>{busy ? '保存中…' : '保存'}</button></div>
  </form></div>
}
function EntryEditor({bookID, defaultCurrency, entry, onClose, onSaved}: {bookID: string; defaultCurrency: string; entry?: Entry; onClose: () => void; onSaved: () => void}) {
  const [id] = useState(() => crypto.randomUUID())
  const [title, setTitle] = useState(entry?.title || ''), [amount, setAmount] = useState(entry ? (entry.amount_minor/100).toFixed(2) : '')
  const [currency, setCurrency] = useState(entry?.currency || defaultCurrency), [category, setCategory] = useState(entry?.category || '餐饮')
  const [date, setDate] = useState(entry?.spent_at || today()), [note, setNote] = useState(entry?.note || '')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  return <div className="ledger-modal-backdrop"><form className="ledger-modal" role="dialog" aria-modal="true" aria-label={entry ? '编辑账单' : '记一笔'} onSubmit={async e => {
    e.preventDefault(); if (busy) return
    if (!/^\d{1,7}(\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) {setError('请输入大于 0、最多两位小数的金额'); return}
    setBusy(true); setError('')
    try { await request(`/${bookID}/entries${entry ? `/${entry.id}` : ''}`, entry ? 'PATCH' : 'POST', {id, title, amount, currency, category, spent_at: date, note, version: entry?.version}); onSaved() }
    catch (e) {setError(e instanceof Error ? e.message : '保存失败')} finally {setBusy(false)}
  }}>
    <h2>{entry ? '编辑账单' : '记一笔'}</h2>
    <div className="ledger-form-row"><label>金额<input autoFocus inputMode="decimal" required value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /></label><label>币种<select aria-label="币种" value={currency} onChange={e => setCurrency(e.target.value)}>{currencies.map(c => <option key={c} value={c}>{c} · {currencyNames[c]}</option>)}</select></label></div>
    <div className="ledger-form-row"><label>分类<select aria-label="分类" value={category} onChange={e => setCategory(e.target.value)}>{categories.map(c => <option key={c}>{c}</option>)}</select></label><label>发生日期<input required type="date" value={date} onChange={e => setDate(e.target.value)} /></label></div>
    <label>花了什么（选填）<input maxLength={80} value={title} onChange={e => setTitle(e.target.value)} placeholder="不填则使用分类名称，比如：餐饮" /></label>
    <label>备注<textarea maxLength={500} value={note} onChange={e => setNote(e.target.value)} placeholder="选填" rows={3} /></label>
    {error && <p role="alert">{error}</p>}<div className="ledger-actions"><button type="button" disabled={busy} onClick={onClose}>取消</button><button className="ledger-primary" disabled={busy || !amount.trim()}>{busy ? '保存中…' : '保存'}</button></div>
  </form></div>
}
