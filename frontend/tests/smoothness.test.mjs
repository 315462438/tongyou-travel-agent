import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { mergeTripPresence, sameChatMessages } from '../src/interaction.ts'

const m = (over = {}) => ({ username: 'a', role: 'owner', online: true, editing_day: 1, ...over })

test('unchanged poll keeps the same trip object so the board skips re-rendering', () => {
  const cur = { id: 't', ai_status: null, members: [m()], stops: [] }
  assert.equal(mergeTripPresence(cur, { ai_status: null, members: [m()] }), cur)
})

test('presence or AI status change still produces a new trip', () => {
  const cur = { id: 't', ai_status: null, members: [m()], stops: [] }
  for (const next of [
    { ai_status: 'copilot', members: [m()] },
    { ai_status: null, members: [m({ online: false })] },
    { ai_status: null, members: [m({ editing_day: 2 })] },
    { ai_status: null, members: [m(), m({ username: 'b' })] },
  ]) {
    const out = mergeTripPresence(cur, next)
    assert.notEqual(out, cur)
    assert.deepEqual(out.members, next.members); assert.equal(out.ai_status, next.ai_status); assert.equal(out.stops, cur.stops)
  }
})

test('chat poll only swaps the array when a message was added or edited', () => {
  const a = [{ id: '1', content: 'hi' }, { id: '2', content: 'yo' }]
  assert.ok(sameChatMessages(a, a.map(x => ({ ...x }))))
  assert.ok(!sameChatMessages(a, [...a, { id: '3', content: 'new' }]))
  assert.ok(!sameChatMessages(a, [a[0], { id: '2', content: 'edited' }]))
  assert.ok(sameChatMessages([], []))
})

test('every large backdrop blur scales with --glass-k; Android halves it but reduced transparency still wins', () => {
  const dir = new URL('../src/', import.meta.url)
  const files = ['index.css', 'nativeAndroid.css', ...readdirSync(new URL('pages/', dir)).filter(f => f.endsWith('.css')).map(f => 'pages/' + f),
    ...readdirSync(new URL('components/', dir)).filter(f => f.endsWith('.css')).map(f => 'components/' + f)]
  for (const f of files) {
    for (const line of readFileSync(new URL(f, dir), 'utf8').split('\n')) {
      if (line.includes('@supports')) continue
      for (const [, px] of line.matchAll(/backdrop-filter:\s*blur\((\d+)px\)/g)) assert.ok(Number(px) < 8, `${f}: blur(${px}px) bypasses --glass-k`)
    }
  }
  const css = readFileSync(new URL('index.css', dir), 'utf8')
  assert.match(css, /html\.ua-android \{ --glass-k: \.45; --x-glass-blur: 11px; \}/)
  assert.match(css, /prefers-reduced-transparency: reduce\) \{\n[^\n]*\n\s*html\.ua-android \{ --x-glass-blur: 0px; \}/)
  const trips = readFileSync(new URL('pages/Trips.tsx', dir), 'utf8')
  assert.match(trips, /setTrip\(\(cur\) => \(cur \? mergeTripPresence\(cur, data\) : data\)\)/)
  assert.match(trips, /if \(sameChatMessages\(previous, next\)\) return/)
})
