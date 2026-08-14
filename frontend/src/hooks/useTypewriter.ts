import { useEffect, useRef, useState } from 'react'
import { TYPEWRITER_TICK_MS, typewriterStep } from '../interaction'

/**
 * 打字机平滑 hook（2026-08-13 丝滑改造）。
 *
 * `target` 是轮询拿到的流式消息最新全文，返回逐步揭示的文本：
 * - 挂载时已有内容（切会话时流式进行中）直接显示全量，不重放；
 * - 动画期间每 TYPEWRITER_TICK_MS 走一步 `typewriterStep`（纯函数，速率自适应），
 *   积压越大揭示越快，保证不落后于后端到达速率；
 * - `active=false`（流式终稿/停止）或页面隐藏时直接追平全量，零延迟收尾。
 *
 * 注意：`shown` 只前进不后退（正文是 append-only）；target 意外变短时立即对齐。
 */
export function useTypewriter(target: string, active: boolean): string {
  const [shown, setShown] = useState(() => target.length)
  const shownRef = useRef(target.length)

  useEffect(() => {
    if (shownRef.current > target.length) {
      shownRef.current = target.length
      setShown(target.length)
    }
    if (!active || document.hidden) {
      // 终稿/隐藏：不播动画，直接全量（终稿瞬间不该让用户等打字机播完）
      if (shownRef.current !== target.length) {
        shownRef.current = target.length
        setShown(target.length)
      }
      return
    }
    if (shownRef.current >= target.length) return
    const timer = window.setInterval(() => {
      const next = typewriterStep({ shown: shownRef.current }, target)
      shownRef.current = next.shown
      setShown(next.shown)
      if (next.done) window.clearInterval(timer)
    }, TYPEWRITER_TICK_MS)
    return () => window.clearInterval(timer)
  }, [target, active])

  return shown === target.length ? target : target.slice(0, shown)
}
