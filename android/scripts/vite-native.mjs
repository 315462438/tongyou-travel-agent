// Android-owned adapter. Shared web source and frontend/dist remain untouched.
import { createRequire } from 'node:module'
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const react = (await import(require.resolve('@vitejs/plugin-react'))).default
export default {
  base: '/travel/',
  plugins: [{
    name: 'tongyou-native-fallback', enforce: 'pre',
    transform(source, id) {
      if (!id.endsWith('/src/pages/Home.tsx')) return
      const marker = '  const mobileActive = '
      if (source.split(marker).length !== 2) throw new Error('Native fallback entry changed; update Android adapter and tests')
      const hook = `
  useEffect(() => {
    const target = window.tongyouFallbackRoute
    if (!isAndroidApp() || !target) return
    delete window.tongyouFallbackRoute
    switch (target.route) {
      case 'chat': if (target.id) void selectConv(target.id); break
      case 'ledger': openLedger(); break
      case 'account': openAccount(); break
      case 'notifications': setShowNotifications(true); break
      case 'trips': openMobileTrips(); if (target.id) setTripsBoard(target.id); break
      case 'createTrip': openMobileTrips(); setCreateTrip(true); break
      case 'history': openMobileHistory(); break
    }
  }, [])
`
      return source.replace(marker, hook + marker)
    }
  }, react()],
}
