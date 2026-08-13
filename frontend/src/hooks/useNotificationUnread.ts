import { useCallback, useEffect, useState } from 'react'

import { API, authFetch } from '../api'

const POLL_MS = 30000

/** 轮询社交通知未读数；面板打开时暂停，避免和面板请求重复。 */
export function useNotificationUnread(paused: boolean): [number, () => void] {
  const [unread, setUnread] = useState(0)
  const refresh = useCallback(async () => {
    try {
      const response = await authFetch(`${API}/notifications/unread-count`)
      if (response.ok) setUnread((await response.json()).unread || 0)
    } catch {
      /* 通知不可用不影响旅行主流程 */
    }
  }, [])

  useEffect(() => {
    if (paused) return
    refresh()
    const timer = window.setInterval(refresh, POLL_MS)
    window.addEventListener('focus', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
    }
  }, [paused, refresh])
  return [unread, refresh]
}
