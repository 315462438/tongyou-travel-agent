import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ToastContext, type ToastKind } from './toast-context'

interface ToastItem {
  id: number
  message: string
  kind: ToastKind
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, number>())

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) window.clearTimeout(timer)
    timers.current.delete(id)
    setItems((list) => list.filter((item) => item.id !== id))
  }, [])

  const notify = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = nextId.current++
    setItems((list) => [...list.slice(-2), { id, message, kind }])
    timers.current.set(id, window.setTimeout(() => dismiss(id), kind === 'error' ? 4500 : 2800))
  }, [dismiss])

  useEffect(() => () => {
    timers.current.forEach((timer) => window.clearTimeout(timer))
    timers.current.clear()
  }, [])

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      <div className="toast-region" aria-live="polite" aria-atomic="true">
        {items.map((item) => (
          <div key={item.id} className={`app-toast ${item.kind}`} role={item.kind === 'error' ? 'alert' : 'status'}>
            <span className="toast-icon" aria-hidden>
              {item.kind === 'success' ? '✓' : item.kind === 'error' ? '!' : 'i'}
            </span>
            <span>{item.message}</span>
            <button type="button" onClick={() => dismiss(item.id)} aria-label="关闭提示">×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
