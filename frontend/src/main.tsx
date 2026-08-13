import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/space-grotesk/700.css'
import './index.css'
import App from './App.tsx'
import { ToastProvider } from './components/Toast.tsx'

// P0：跨版本白屏防护——部署后新哈希 chunk 名变了，旧页面动态 import 会 404。
// Vite 会触发 vite:preloadError；这里自动刷新一次（sessionStorage 防死循环）拉到新版。
window.addEventListener('vite:preloadError', () => {
  if (!sessionStorage.getItem('reloaded_for_new_version')) {
    sessionStorage.setItem('reloaded_for_new_version', '1')
    window.location.reload()
  }
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </StrictMode>,
)
