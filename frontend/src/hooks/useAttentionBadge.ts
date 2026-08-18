import { useEffect, useRef } from 'react'

import { badgedTitle } from '../interaction'

/** favicon 角标的红点尺寸（相对 64×64 画布） */
const CANVAS = 64
const DOT_R = 20

function faviconLink(): HTMLLinkElement | null {
  return document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
}

/**
 * 在现有 favicon 上画一个红点，返回 data URI。
 *
 * 用 canvas 而不是另外准备一张「带红点的图」：品牌图标只有一份，红点是叠加层，
 * 换了图标不用同步维护第二份。CSP 允许 `img-src data:`（Phase 69），所以 data URI 可用。
 */
function drawBadge(src: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = CANVAS
      const ctx = canvas.getContext('2d')
      if (!ctx) return reject(new Error('no 2d context'))
      ctx.drawImage(img, 0, 0, CANVAS, CANVAS)
      ctx.beginPath()
      ctx.arc(CANVAS - DOT_R + 4, DOT_R - 4, DOT_R, 0, Math.PI * 2)
      ctx.fillStyle = '#ef4444'
      ctx.fill()
      // 描一圈底色，让红点在深色标签栏上也能和图标分开
      ctx.lineWidth = 5
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
      resolve(canvas.toDataURL('image/png'))
    }
    img.onerror = () => reject(new Error('favicon load failed'))
    img.src = src
  })
}

/**
 * 未读时在**标签页标题和 favicon** 上提醒（Phase 98）。
 *
 * 为什么不是 Web Push：Chrome/Edge 的推送走 FCM，实测服务器与国内浏览器都连不上
 * `fcm.googleapis.com`，主要用户群根本收不到。标题和 favicon 是浏览器自己就会显示的，
 * 无需授权、无需 Service Worker、不依赖任何外部服务，覆盖「挂着页面在干别的」这个最高频场景。
 *
 * 失败一律静默降级：favicon 画不出来时标题提醒照常工作——提醒是增强，不能因为它报错。
 */
export function useAttentionBadge(unread: number): void {
  const baseTitleRef = useRef<string>('')
  const baseIconRef = useRef<string>('')
  const shownRef = useRef<boolean | null>(null)

  // 原始标题/图标只在挂载时捕获一次。反复从 document 上读会把徽标叠进去（`(1) (2) 标题`）。
  useEffect(() => {
    baseTitleRef.current = badgedTitle(document.title, 0)
    baseIconRef.current = faviconLink()?.getAttribute('href') || ''
    return () => {
      document.title = baseTitleRef.current
      const link = faviconLink()
      if (link && baseIconRef.current) link.setAttribute('href', baseIconRef.current)
    }
  }, [])

  useEffect(() => {
    if (baseTitleRef.current) document.title = badgedTitle(baseTitleRef.current, unread)
  }, [unread])

  useEffect(() => {
    const want = unread > 0
    if (shownRef.current === want) return  // 只在状态翻转时改 favicon，避免每轮轮询都重画
    shownRef.current = want
    const link = faviconLink()
    const base = baseIconRef.current
    if (!link || !base) return
    if (!want) {
      link.setAttribute('href', base)
      return
    }
    let cancelled = false
    drawBadge(base)
      .then((url) => { if (!cancelled) link.setAttribute('href', url) })
      .catch(() => { /* 画不出来就只留标题提醒 */ })
    return () => { cancelled = true }
  }, [unread])
}
