import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { rippleGeometry, pressSize, pressHaptic, LARGE_PRESS_AREA } from '../src/pressFeedback.ts'

const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
const fake = (attrs) => ({ getAttribute: k => attrs[k] ?? null, hasAttribute: k => k in attrs })

test('ripple circle covers the farthest corner from the press point', () => {
  const rect = { left: 10, top: 20, width: 100, height: 40 }
  for (const [x, y] of [[10, 20], [110, 60], [60, 40], [30, 55]]) {
    const g = rippleGeometry(rect, x, y)
    const cx = g.left + g.size / 2, cy = g.top + g.size / 2
    assert.equal(Math.round(cx), x - rect.left); assert.equal(Math.round(cy), y - rect.top)
    for (const [px, py] of [[0, 0], [100, 0], [0, 40], [100, 40]]) assert.ok(Math.hypot(px - cx, py - cy) <= g.size / 2 + 0.5)
  }
})

test('large cards dip less than small buttons', () => {
  assert.equal(pressSize({ left: 0, top: 0, width: 80, height: 40 }), 'sm')
  assert.equal(pressSize({ left: 0, top: 0, width: 360, height: 120 }), 'lg')
  assert.ok(360 * 120 > LARGE_PRESS_AREA && 80 * 40 < LARGE_PRESS_AREA)
})

test('only toggles tick on press; ordinary buttons stay silent', () => {
  assert.equal(pressHaptic(fake({})), null)
  assert.equal(pressHaptic(fake({ role: 'tab' })), 'tick')
  assert.equal(pressHaptic(fake({ 'aria-pressed': 'false' })), 'tick')
  assert.equal(pressHaptic(fake({ 'aria-checked': 'true' })), 'tick')
  assert.equal(pressHaptic(fake({ 'data-haptic': 'confirm' })), 'confirm')
  assert.equal(pressHaptic(fake({ 'data-haptic': 'boom' })), null)
})

test('press styles never override component transforms and respect reduced motion', () => {
  const block = css.slice(css.indexOf('/* 按压反馈'), css.indexOf('/* 全局轻提示'))
  assert.ok(block.length > 0)
  assert.doesNotMatch(block, /transform\s*:/, 'uses the independent scale property, not transform')
  assert.match(block, /:where\(\[data-pressed="sm"\]\)/, 'zero specificity so component rules win')
  assert.match(block, /prefers-reduced-motion: reduce[\s\S]*press-ripple-host \{ display: none/)
  assert.match(block, /pointer-events: none/)
})

test('success and error toasts double as native result haptics', () => {
  const toast = readFileSync(new URL('../src/components/Toast.tsx', import.meta.url), 'utf8')
  assert.match(toast, /if \(kind !== 'info'\) nativeHaptic\(kind === 'success' \? 'confirm' : 'reject'\)/)
  const main = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8')
  assert.match(main, /installPressFeedback\(\)\s*\n\s*createRoot\(/, 'installed once before the app renders')
  const java = readFileSync(new URL('../../android/app/src/main/java/com/tongyou/travel/MainActivity.java', import.meta.url), 'utf8')
  assert.match(java, /case "haptic": haptic\(source,m\.optString\("kind"\)\)/)
})
