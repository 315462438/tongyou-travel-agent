// Android-only capabilities; inactive in browsers and in the SwiftUI application.
import { useEffect, useRef } from 'react'
import './nativeAndroid.css'

declare global {
  interface Window {
    tongyouAndroidAppearance?: 'light' | 'dark'
    TongyouNative?: { postMessage: (message: string) => void }
    tongyouAndroidBack?: () => boolean
    tongyouAndroidDownload?: (url: string, name?: string) => Promise<void>
  }
}
export const isAndroidApp = () => /17TongyouAndroid\//.test(navigator.userAgent) && !!window.TongyouNative
const handlers = new Map<symbol, {priority: number; back: () => boolean}>()
export function useAndroidBack(back: () => boolean, priority = 10) {
  const latest = useRef(back)
  latest.current = back
  useEffect(() => {
    const id = Symbol()
    handlers.set(id, {priority, back: () => latest.current()})
    return () => { handlers.delete(id) }
  }, [priority])
}
function post(data: object) { window.TongyouNative?.postMessage(JSON.stringify(data)) }
export function notifyAndroidReady() {
  if (!isAndroidApp()) return
  const frame = requestAnimationFrame(() => post({type: 'ready'}))
  return () => cancelAnimationFrame(frame)
}
export function shareAndroidLink(title: string, url: string) {
  if (!isAndroidApp()) return false
  post({type: 'share', title, text: url})
  return true
}
function visible(element: Element) { return element.getClientRects().length > 0 && getComputedStyle(element).visibility !== 'hidden' }

if (isAndroidApp()) {
  localStorage.setItem('travel_layout_mode', 'mobile')
  document.documentElement.classList.add('native-android')
  document.documentElement.dataset.androidAppearance = window.tongyouAndroidAppearance || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  window.tongyouAndroidBack = () => {
    // A dialog consumes Back even while saving, so its parent cannot accidentally close.
    const dialogs = [...document.querySelectorAll('[role="dialog"], .modal-mask, .trip-chat-panel, .trip-source-panel')].filter(visible)
    const top = dialogs.at(-1)
    if (top) {
      const buttons = [...top.querySelectorAll<HTMLButtonElement>('button')].filter(visible)
      const close = buttons.find(b => /^(取消|关闭|完成|返回|×|✕|✖)$/.test(b.textContent?.trim() || '') || /^关闭/.test(b.getAttribute('aria-label') || ''))
      if (close) { if (!close.disabled) close.click(); return true }
      // A required dialog without a dismiss action stays open.
      return true
    }
    const menu = [...document.querySelectorAll('details[open]')].filter(visible).at(-1)
    if (menu) { menu.removeAttribute('open'); return true }
    for (const h of [...handlers.values()].sort((a, b) => b.priority - a.priority)) if (h.back()) return true
    return false
  }
  const save = async (href: string, name = '17同游导出文件') => {
    try {
      const url = new URL(href, location.href)
      if (!['blob:', 'data:'].includes(url.protocol) && url.origin !== location.origin) throw new Error('请在浏览器中下载外部文件')
      const headers: Record<string, string> = {}
      if (url.origin === location.origin && url.pathname.startsWith('/travel/api/')) {
        const token = localStorage.getItem('travel_token'); if (token) headers.Authorization = `Bearer ${token}`
      }
      const r = await fetch(url.href, {headers, redirect: 'error'})
      if (!r.ok) throw new Error('下载失败，请检查网络后重试')
      const blob = await r.blob()
      if (blob.size > 20 * 1024 * 1024) throw new Error('文件超过 20 MB，请使用网页版下载')
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(blob)
      })
      post({type: 'download', name, mime: blob.type, data})
    } catch (e) { post({type: 'message', text: e instanceof Error ? e.message : '下载失败，请重试'}) }
  }
  window.tongyouAndroidDownload = save
  const revoke = URL.revokeObjectURL.bind(URL)
  URL.revokeObjectURL = url => { window.setTimeout(() => revoke(url), 60000) }
  const anchorClick = HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click = function () {
    if (this.hasAttribute('download')) { void save(this.href, this.download); return }
    anchorClick.call(this)
  }
  document.addEventListener('click', e => {
    const a = (e.target as Element)?.closest<HTMLAnchorElement>('a[download]')
    if (a) { e.preventDefault(); void save(a.href, a.download) }
  }, true)
  window.print = () => post({type: 'print', title: document.title})
  Object.defineProperty(navigator, 'share', {configurable: true, value: async (data: ShareData) => {
    if (data.files?.length) throw new Error('请先保存文件，再通过系统分享')
    post({type: 'share', title: data.title || '17同游', text: [data.text, data.url].filter(Boolean).join('\n')})
  }})
}
