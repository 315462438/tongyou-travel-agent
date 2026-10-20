import { useState } from 'react'

export default function OpenLedgerApp({token}: {token: string}) {
  const [attempted, setAttempted] = useState(false)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'manual'>('idle')
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  if (!ios || !/^[A-Za-z0-9_-]{32,64}$/.test(token)) return null
  const wechat = /MicroMessenger/i.test(navigator.userAgent)
  if (wechat) {
    const link = new URL(import.meta.env.BASE_URL, window.location.origin)
    link.searchParams.set('ledger_join', token)
    return <div className="ledger-open-app ledger-open-app-wechat" aria-label="微信打开 App 指引">
      <strong>用 App 打开，请先切换到 Safari</strong>
      <ol><li>点微信右上角“…”菜单，选择用浏览器打开。</li><li>在 Safari 页面点“在 App 中打开”，按系统提示确认。</li></ol>
      <p>找不到浏览器入口？复制完整链接，粘贴到 Safari 地址栏打开。</p>
      <button type="button" className="ledger-primary" onClick={async () => {
        try { await navigator.clipboard.writeText(link.href); setCopyState('copied') }
        catch { setCopyState('manual') }
      }}>复制完整邀请链接</button>
      {copyState === 'copied' && <p role="status">链接已复制。请打开 Safari，粘贴到地址栏。</p>}
      {copyState === 'manual' && <label>请长按下方链接复制<input aria-label="完整账本邀请链接" readOnly value={link.href} onFocus={event => event.target.select()} /></label>}
      <small>也可以留在微信，使用下方的网页版加入账本。</small>
    </div>
  }
  return <div className="ledger-open-app">
    <a className="ledger-primary" href={`tongyou://ledger/join?token=${encodeURIComponent(token)}`} onClick={() => {
      setAttempted(true)
    }}>在 App 中打开</a>
    <small>需安装新版 17同游 iOS App；也可直接在下方使用网页版。</small>
    {attempted && <p role="status">若未打开 App，请确认已安装 1.0.6 或更高版本，或继续使用下方网页版。</p>}
  </div>
}
