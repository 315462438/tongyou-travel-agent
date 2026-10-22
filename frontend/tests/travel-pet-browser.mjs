import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const url = process.env.PET_QA_URL || 'http://127.0.0.1:4191/travel/'
const out = process.env.PET_QA_OUTPUT || '/tmp/tongyou-pet-browser'
await fs.mkdir(out, { recursive: true })
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' })
const results = []
try {
  for (const [name, width, height, dark, android, motion] of [
    ['android-small', 320, 780, false, true, 'reduce'], ['android-dark', 390, 844, true, true, 'no-preference'],
    ['web-mobile', 430, 932, false, false, 'no-preference'], ['desktop', 1280, 900, false, false, 'reduce'], ['landscape', 844, 390, true, true, 'reduce'],
  ]) {
    if (process.env.QA_CASE && process.env.QA_CASE !== name) continue
    const context = await browser.newContext({ viewport: { width, height }, colorScheme: dark ? 'dark' : 'light', reducedMotion: motion, hasTouch: width < 600,
      ...(android ? { userAgent: 'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.9.3' } : {}) })
    await context.addInitScript(({ android }) => { localStorage.setItem('travel_token', 'fixture'); if (android) window.TongyouNative = { postMessage: () => {} } }, { android })
    let running = false, stopped = false, started = false, joined = false, failCheck = false, noTrips = false
    const calls = [], errors = []
    const trip = { id: 't1', title: '杭州的慢周末', destination: '杭州', days: 2, role: 'owner' }
    await context.route('**/travel/api/**', async route => {
      const req = route.request(), p = new URL(req.url()).pathname.replace('/travel/api', '')
      calls.push({ p, method: req.method() })
      let data = []
      if (p === '/auth/me') data = { username: 'pet-demo', display_name: '小旅', is_admin: false }
      else if (p.includes('unread')) data = { unread: 0, count: 0 }
      else if (p === '/onboarding') data = { trending: ['杭州', '武汉'], questions: [] }
      else if (p === '/onboarding/covers') data = { covers: {} }
      else if (p === '/trips') data = noTrips ? [] : [trip]
      else if (p === '/trips/t1') data = { ...trip, updated_at: joined ? 'v2' : 'v1', start_date: '', source_conversation_id: '', ai_status: null, ai_review: '', budget: null, members: [{ username: 'pet-demo', role: 'owner' }, ...(joined ? [{ username: '阿桃', role: 'editor' }] : [])], stops: [{ id: 's1', name: '西湖', day: 1, order_no: 0, start_time: '', location: '', note: '', stay_min: null, transport: '', ticket_price: null, tags: [], nav: null }], day_plans: [] }
      else if (p === '/trips/t1/issues') {
        if (failCheck) return route.fulfill({ status: 503, body: '{}' })
        data = { issues: [{ text: '第 1 天还有时间可以留给休息', level: 'info' }], ticket_total: 0 }
      }
      else if (p.includes('expenses/summary')) data = { total: 0, count: 0, by_category: {}, transfers: [], text: '' }
      else if (p.includes('day-cities')) data = { cities: {}, overnight: {} }
      else if (p === '/chat/conversations') data = req.method() === 'POST' ? { conversation_id: 'c1' } : [{ id: 'c1', title: '杭州周末' }]
      else if (p === '/chat/c1/messages') {
        if (req.method() === 'POST') { started = true; running = true; stopped = false; data = { ok: true } }
        else data = { running, messages: started ? [{ id: 'u1', role: 'user', content: '杭州周末' }, ...(running ? [{ id: 'p1', role: 'progress', content: '正在整理地点' }] : [{ id: 'a1', role: 'assistant', content: stopped ? '保留已经生成的部分。' : '沿湖散步，轻松安排每一天。' }])] : [] }
      }
      else if (p === '/chat/c1/stop') { stopped = true; running = false; data = { status: 'stopping' } }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    })
    const page = await context.newPage()
    page.setDefaultTimeout(10000)
    page.on('pageerror', error => { errors.push(error.message); console.error(name, error.message) })
    await page.goto(url)
    await page.locator('.travel-book').first().waitFor()
    const ai = () => page.getByRole('button', { name: '问 AI', exact: true })
    const initialTripLoads = calls.filter(call => call.p === '/trips').length
    await page.waitForTimeout(900)
    assert.equal(calls.filter(call => call.p === '/trips').length, initialTripLoads, 'pet does not start background fetching')
    await page.screenshot({ path: `${out}/${name}-home.png`, animations: 'disabled' })
    await ai().click()
    await page.getByRole('textbox', { name: '旅行需求', exact: true }).fill('周末去杭州，别太赶')
    await page.getByLabel('关闭 AI', { exact: true }).click()
    const box = await ai().boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down(); await page.waitForTimeout(650); await page.mouse.up()
    const tools = page.getByRole('dialog', { name: '游游 · 旅行搭子' })
    await tools.waitFor()
    assert.equal(await page.locator('.ai-workspace').isVisible(), false, 'long press does not open AI')
    await page.getByRole('button', { name: '摸摸游游' }).click()
    assert.match(await tools.textContent(), /咕噜/)
    await page.getByRole('button', { name: '出发检查', exact: true }).click()
    await page.getByRole('button', { name: '打开这份行程 ↗' }).waitFor()
    assert.match(await tools.textContent(), /确认并填写出发日期/)
    assert.match(await tools.textContent(), /地图位置/)
    assert.match(await tools.textContent(), /游览时间/)
    assert.match(await tools.textContent(), /留给休息/)
    await page.getByRole('checkbox', { name: '减少动态效果' }).check()
    await page.getByRole('button', { name: '摸摸游游' }).click()
    assert.equal(await tools.locator('.yp-otter').evaluate(element => getComputedStyle(element).animationName), 'none')
    await page.getByRole('combobox', { name: '游游停靠位置' }).selectOption('left')
    await page.getByRole('button', { name: '关闭游游旅行工具' }).click()
    assert.equal(await page.locator('.travel-pet-dock').getAttribute('data-side'), 'left')
    const [petRect, navRect] = await Promise.all([ai().boundingBox(), page.getByRole('navigation', { name: '主导航', exact: true }).boundingBox()])
    assert.ok(petRect.x + petRect.width <= navRect.x + 1, 'left pet does not overlap navigation')
    // Directional drag must not open a conversation or a long-press tool panel.
    await page.mouse.move(petRect.x + petRect.width / 2, petRect.y + petRect.height / 2)
    await page.mouse.down(); await page.mouse.move(width - 20, petRect.y + petRect.height / 2, { steps: 8 }); await page.mouse.up()
    assert.equal(await page.locator('.travel-pet-dock').getAttribute('data-side'), 'right')
    assert.equal(await tools.isVisible(), false)
    assert.equal(await page.locator('.ai-workspace').isVisible(), false)
    await ai().click()
    const prompt = page.getByRole('textbox', { name: '旅行需求', exact: true })
    assert.equal(await prompt.inputValue(), '周末去杭州，别太赶')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByRole('button', { name: /游游，正在整理你的旅行想法/ }).waitFor()
    await page.waitForTimeout(950)
    running = false
    await page.getByRole('button', { name: /游游，回复准备好啦/ }).waitFor()
    await page.getByRole('textbox', { name: '旅行问题', exact: true }).fill('再安排一下')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByRole('button', { name: /游游，正在整理你的旅行想法/ }).waitFor()
    await page.getByRole('button', { name: '停止生成', exact: true }).click()
    await page.getByRole('button', { name: /游游，已停下/ }).waitFor()
    await page.getByLabel('关闭 AI', { exact: true }).click()
    await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('button', { name: '我的', exact: true }).click()
    await page.getByRole('button', { name: '游游 · 旅行搭子', exact: true }).click()
    await page.getByRole('checkbox', { name: '在界面显示游游' }).uncheck()
    await page.getByRole('button', { name: '关闭游游旅行工具' }).click()
    assert.equal(await page.locator('.travel-pet-fab').count(), 0)
    assert.equal(await ai().isVisible(), true)
    await page.reload()
    assert.equal(await page.locator('.travel-pet-fab').count(), 0, 'visibility persists')
    await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('button', { name: '我的', exact: true }).click()
    await page.getByRole('button', { name: '游游 · 旅行搭子', exact: true }).click()
    await page.getByRole('checkbox', { name: '在界面显示游游' }).check()
    failCheck = true
    await page.getByRole('button', { name: '出发检查', exact: true }).click()
    await page.getByRole('button', { name: '重新检查', exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: '打开这份行程 ↗' }).count(), 0, 'failed check cannot report success')
    failCheck = false
    await page.getByRole('button', { name: '重新检查', exact: true }).click()
    await page.getByRole('button', { name: '打开这份行程 ↗' }).waitFor()
    await page.screenshot({ path: `${out}/${name}-tools.png`, animations: 'disabled' })
    await page.getByRole('button', { name: '打开这份行程 ↗' }).click()
    await page.locator('.trip-board').waitFor()
    assert.equal(await page.locator('.pet-member-welcome').count(), 0, 'existing members are not welcomed')
    assert.equal(await page.locator('.travel-pet-dock').isVisible(), false, 'pet retires from the map workspace')
    joined = true
    await page.locator('.pet-member-welcome').waitFor()
    assert.match(await page.locator('.pet-member-welcome').textContent(), /阿桃/)
    await page.getByRole('button', { name: '收起同行欢迎' }).click()
    await page.waitForTimeout(2600)
    assert.equal(await page.locator('.pet-member-welcome').count(), 0, 'presence refresh does not replay a welcome')
    if (await page.getByLabel('返回行程列表', { exact: true }).isVisible()) await page.getByLabel('返回行程列表', { exact: true }).click()
    await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('button', { name: '旅行', exact: true }).click()
    await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('button', { name: '我的', exact: true }).click()
    await page.getByRole('button', { name: '游游 · 旅行搭子', exact: true }).click()
    noTrips = true
    await page.getByRole('button', { name: '出发检查', exact: true }).click()
    await page.getByText('还没有行程，先一起想想去哪儿。', { exact: true }).waitFor()
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no horizontal overflow')
    assert.deepEqual(errors, [])
    results.push({ name, passed: true, directAI: true, longPress: true, drag: true, preparation: true, preparationRetry: true, settingsPersist: true, taskStop: true, memberWelcome: true })
    console.log(`${name}: passed`)
    await context.close()
  }
  await fs.writeFile(`${out}/results.json`, JSON.stringify(results, null, 2))
} finally { await browser.close() }
