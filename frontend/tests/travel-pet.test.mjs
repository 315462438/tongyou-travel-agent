import test from 'node:test'
import assert from 'node:assert/strict'
import { addedPetMembers, petPreparation, petTask, readPetPreferences } from '../src/travelPet.ts'

const user = { id: 'u1', role: 'user', content: '杭州两天' }
const answer = { id: 'a1', role: 'assistant', content: '沿湖散步' }
test('pet state isolates turns and differentiates streaming, preliminary, errors and stops', () => {
  assert.equal(petTask([], false).phase, 'idle')
  assert.equal(petTask([user, answer], false).phase, 'ready')
  assert.equal(petTask([answer, user], false).phase, 'idle')
  assert.equal(petTask([user, { ...answer, meta: { preliminary: true } }], false).phase, 'idle')
  assert.equal(petTask([user, { ...answer, meta: { streaming: true } }], true).phase, 'working')
  assert.equal(petTask([user, answer], false, true).phase, 'stopped')
  assert.equal(petTask([user, { ...answer, content: '已停止本轮。' }], false).phase, 'stopped')
  assert.equal(petTask([user, { ...answer, content: '抱歉，处理过程中出错了，请重试。' }], false).phase, 'error')
  assert.equal(petTask([user, answer], false, false, true).phase, 'error')
  assert.equal(petTask([user, { ...answer, meta: { error: true } }], false).phase, 'error')
  assert.equal(petTask([user, { ...answer, meta: { cancelled: true } }], false).phase, 'stopped')
})
test('confirm reply resolves waiting; previous-turn handoff cannot leak', () => {
  const confirm = { id: 'p', role: 'progress', content: '需要登录', meta: { confirm: { id: 'ask' } } }
  assert.equal(petTask([user, confirm], true).phase, 'waiting')
  assert.equal(petTask([user, confirm, { id: 'r', role: 'action', content: '', meta: { confirm_reply: { confirm_id: 'ask' } } }], true).phase, 'working')
  assert.equal(petTask([confirm, user], true).phase, 'working')
})
test('preferences tolerate corrupt or incompatible local storage', () => {
  for (const value of ['bad', 'null', '[]', '{}']) assert.deepEqual(readPetPreferences(value), { visible: true, quiet: false, side: 'right' })
  assert.deepEqual(readPetPreferences('{"visible":false,"quiet":true,"side":"left"}'), { visible: false, quiet: true, side: 'left' })
})
test('member welcome only reports an actual addition after a baseline', () => {
  assert.deepEqual(addedPetMembers(null, ['me', 'old'], 'me'), [])
  assert.deepEqual(addedPetMembers(['me', 'old'], ['me'], 'me'), [])
  assert.deepEqual(addedPetMembers(['me', 'old'], ['old', 'me'], 'me'), [])
  assert.deepEqual(addedPetMembers(['me'], ['me', 'new', 'new'], 'me'), ['new'])
})
test('preparation inspects real fields and honors non-geographic stops', () => {
  const trip = { id: 't1', title: '旅行', destination: '', start_date: '', stops: [] }
  assert.equal(petPreparation(trip, []).length, 3)
  const complete = { ...trip, destination: '杭州', start_date: '2026-10-24', stops: [{ name: '西湖', start_time: '09:00', location: '120.15,30.25' }, { name: '休息', start_time: '12:00', tags: ['no_location'] }] }
  assert.deepEqual(petPreparation(complete, []), [])
  assert.equal(petPreparation({ ...complete, stops: [{ name: '西湖', location: ',30' }] }, []).length, 2)
  assert.equal(petPreparation(complete, [{ text: '时间冲突', level: 'warn' }, { text: '时间冲突', level: 'warn' }]).length, 1)
  assert.doesNotMatch(JSON.stringify(petPreparation(trip, [])), /未订|已订|免费|酒店/)
})

test('idle acts never repeat back to back and only play in calm phases', async () => {
  const { nextPetAct, petActAllowed, petActDelay, PET_ACTS } = await import('../src/travelPet.ts')
  for (const previous of PET_ACTS) for (const r of [0, 0.3, 0.6, 0.9999, 1]) {
    const act = nextPetAct(previous, r)
    assert.ok(PET_ACTS.includes(act)); assert.notEqual(act, previous)
  }
  assert.ok(PET_ACTS.includes(nextPetAct(null, 0.5)))
  assert.deepEqual(['idle', 'ready'].map(petActAllowed), [true, true])
  assert.deepEqual(['working', 'waiting', 'stopped', 'error'].map(petActAllowed), [false, false, false, false])
  assert.equal(petActDelay(0), 6000); assert.equal(petActDelay(1), 12000); assert.equal(petActDelay(2), 12000)
})

test('flight lands exactly on the header pet and arcs above both ends', async () => {
  const { petFlightFrames } = await import('../src/travelPet.ts')
  const from = { left: 300, top: 700, width: 69, height: 84 }, to = { left: 120, top: 14, width: 34, height: 41 }
  const frames = petFlightFrames(from, to)
  assert.equal(frames[0].offset, 0); assert.equal(frames.at(-1).offset, 1)
  assert.match(frames.at(-1).transform, /translate\(-180px, -686px\) scale\(0\.493\)/)
  const midY = Number(frames[2].transform.match(/translate\([-\d]+px, (-?\d+)px\)/)[1])
  assert.ok(midY < -686 * 0.6, 'mid point lifts above the straight line')
  assert.match(petFlightFrames({ ...from, width: 0 }, to).at(-1).transform, /scale\(1\.000\)/)
})

test('progress bubble text is short, readable and current-turn only', async () => {
  const { petProgressText, petTask, PET_BUBBLE_MAX } = await import('../src/travelPet.ts')
  assert.equal(petProgressText('🔎 搜索：杭州 美食'), '搜索：杭州 美食')
  assert.equal(petProgressText('🌐 浏览器读取：https://www.xiaohongshu.com/explore/abc?x=1'), '浏览器读取：xiaohongshu.com')
  assert.equal(petProgressText('\n\n**正在理解你的旅行需求…**\n第二行'), '正在理解你的旅行需求…')
  assert.equal(petProgressText('   '), undefined)
  const long = petProgressText('正在补充资料：' + '西湖、灵隐寺、'.repeat(10))
  assert.equal([...long].length, PET_BUBBLE_MAX); assert.ok(long.endsWith('…'))
  const user = { id: 'u', role: 'user', content: '杭州' }
  assert.equal(petTask([user, { id: 'p', role: 'progress', content: '📕 小红书搜索：杭州' }], true).detail, '小红书搜索：杭州')
  assert.equal(petTask([user, { id: 'a', role: 'assistant', content: '第一天', meta: { streaming: true } }], true).detail, '正在写回复…')
  assert.equal(petTask([{ id: 'p0', role: 'progress', content: '旧的进度' }, user], true).detail, undefined)
  assert.equal(petTask([user, { id: 'p', role: 'progress', content: '搜索' }], true, true).detail, undefined, 'stopping shows its own label')
})

test('bubble priority and one-time tips', async () => {
  const { petBubble, nextPetTip, PET_TIPS, readPetPreferences } = await import('../src/travelPet.ts')
  const tip = nextPetTip([], 'idle')
  assert.equal(tip.id, 'ask')
  assert.equal(nextPetTip(['ask'], 'ready').id, 'tools')
  assert.equal(nextPetTip(PET_TIPS.map(t => t.id), 'idle'), null)
  assert.equal(nextPetTip([], 'working'), null)
  assert.equal(petBubble({ phase: 'working', label: '整理中', turn: '', detail: '搜索：杭州' }, false, tip).text, '搜索：杭州')
  assert.equal(petBubble({ phase: 'working', label: '整理中', turn: '' }, false, null).text, '整理中')
  assert.equal(petBubble({ phase: 'waiting', label: '', turn: '' }, false, tip).kind, 'waiting')
  assert.equal(petBubble({ phase: 'error', label: '', turn: '' }, true, tip).kind, 'error')
  assert.equal(petBubble({ phase: 'ready', label: '', turn: '' }, true, tip).kind, 'done')
  assert.equal(petBubble({ phase: 'idle', label: '', turn: '' }, false, tip).kind, 'tip')
  assert.equal(petBubble({ phase: 'idle', label: '', turn: '' }, false, null), null)
  assert.deepEqual(readPetPreferences('{"tipsSeen":["ask",3,null,"drag"]}').tipsSeen, ['ask', 'drag'])
  assert.equal(readPetPreferences('{}').tipsSeen, undefined)
})

test('trip board dark theme flips surfaces together with text', async () => {
  const fs = await import('node:fs/promises')
  const css = await fs.readFile(new URL('../src/pages/TripWorkspace.css', import.meta.url), 'utf8')
  const media = css.slice(css.indexOf('@media (prefers-color-scheme: dark)'))
  for (const token of ['--trip-surface:', '--tx-surface:', '--x-n100:', '--x-glass:', '--tw-surface:', '--tw-ink:'])
    assert.ok(media.includes(token), `dark block sets ${token}`)
  assert.ok(css.includes('html.native-android[data-android-appearance=dark] .app.journey-shell .trips-overlay'), 'Android dark copy')
  // Light palette stays exactly the pre-dark values.
  assert.match(css, /--tw-surface: #fff; --tw-canvas: #f5f7fb;/)
  const lightPart = css.slice(css.indexOf('*/') + 2, css.indexOf('/* ---------- 深色主题'))
  assert.equal((lightPart.match(/#fff(?![0-9a-f])/gi) || []).length, 1, 'no hard-coded white surfaces outside the token block')
})
