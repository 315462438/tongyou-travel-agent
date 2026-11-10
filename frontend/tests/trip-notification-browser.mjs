// Offline browser regression: the real notification panel, trip loading and poll UI use fixture APIs.
import assert from 'node:assert/strict'
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})
const url = process.env.NOTIFICATION_QA_URL || 'http://127.0.0.1:4190/travel/'
const results = []
try {
  for (const width of [390, 1280]) {
    const ctx = await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'})
    await ctx.addInitScript(() => localStorage.setItem('travel_token','fixture'))
    const trips = ['t1','t2'].map(id => ({id,title:`通知测试 ${id}`,destination:'杭州',days:3,start_date:'2026-11-20',role:'owner',members:[{username:'demo',role:'owner'}],stops:[],day_plans:[],day_titles:{},ai_status:null,ai_review:'',updated_at:'fixture'}))
    const poll = (id, day) => ({id,day,question:`投票 ${id}`,closed:false,my_vote:null,total:0,members:2,created_by:'friend',mine:false,options:[{text:'A',votes:0,voters:[]},{text:'B',votes:0,voters:[]}]})
    const polls = {t1:[poll('p1',2),poll('all',null)],t2:[poll('p2',3)]}
    const notice = (id, trip, poll, day, type='trip_poll') => ({id,type,title:`通知 ${id}`,body:'请选择',target_kind:'trip',target_id:trip,meta:{trip_id:trip,poll_id:poll,day},read:false,created_at:null,actor:{id:'friend',username:'friend',display_name:'搭子',avatar_url:''}})
    const notices = [notice('day','t1','p1',2),notice('changed','t2','p2',1),notice('whole','t1','all',2),notice('gone','t2','deleted',99),notice('old','t1','p1',null),notice('chat','t1',null,null,'trip_chat')]
    const calls = []
    await ctx.route('https://webapi.amap.com/**',r=>r.abort())
    await ctx.route('**/travel/api/**',async r => {
      const req=r.request(), path=new URL(req.url()).pathname.replace('/travel/api','');calls.push([path,req.method()]);let data=[]
      if(path==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false}
      else if(path==='/trips')data=trips
      else if(trips.some(t=>path===`/trips/${t.id}`)) { await new Promise(resolve=>setTimeout(resolve,80)); data=trips.find(t=>path===`/trips/${t.id}`) }
      else if(path==='/notifications')data={notifications:notices,unread:notices.filter(n=>!n.read).length}
      else if(path.match(/^\/notifications\/.+\/read$/)){notices.find(n=>path.includes('/'+n.id+'/')).read=true;data={ok:true}}
      else if(path.endsWith('/polls'))data=polls[path.split('/')[2]] || []
      else if(path.endsWith('/vote')) {const p=polls[path.split('/')[2]].find(p=>path.includes('/'+p.id+'/'));p.my_vote=0;p.total=1;data=p}
      else if(path.includes('unread'))data={count:0,unread:0}
      else if(path.endsWith('/issues'))data={issues:[],ticket_total:0}
      else if(path.includes('day-cities'))data={cities:{},overnight:{}}
      else if(path.includes('expenses/summary'))data={count:0,total:0,by_category:{},per_person:[],transfers:[]}
      else if(path==='/onboarding')data={trending:[],questions:[]}
      else if(path==='/onboarding/covers')data={covers:{}}
      else if(path.endsWith('/chat'))data=[]
      await r.fulfill({contentType:'application/json',body:JSON.stringify(data)})
    })
    const page=await ctx.newPage();page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message))
    await page.goto(url);await page.getByLabel('打开行程 通知测试 t1').waitFor()
    const openNotice=async id => {
      // The same panel callback can arrive while a trip overlay remains mounted.
      const visible = page.getByRole('button',{name:/^通知(?:，|$)/}).filter({visible:true})
      if(await visible.count())await visible.first().click()
      else await page.locator('.topbar-bell').dispatchEvent('click')
      const item = page.locator('.notification-item').filter({hasText:`通知 ${id}`})
      if (await page.locator('.trip-chat-panel').count()) await item.dispatchEvent('click')
      else await item.click()
    }
    const expectPoll=async (id,day) => {
      const card=page.locator(`[data-poll-id="${id}"].notification-target`)
      await card.waitFor({state:'visible'})
      await page.waitForFunction(d=>document.querySelector('select[aria-label="投票属于哪一天"]')?.value===String(d),day)
      assert.ok(await card.evaluate(el=>{const r=el.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight}))
      assert.equal(await page.locator('.trip-chat-panel').count(),0,'poll notice must not open chat')
    }
    await openNotice('day');await expectPoll('p1',2)
    await page.locator('[data-poll-id=p1] .trip-poll-option').first().click()
    assert.ok(calls.some(([p,m])=>p==='/trips/t1/polls/p1/vote'&&m==='POST'))
    // Leaving the tool, choosing a day, and a normal data refresh must not replay the notice.
    if(width<720){await page.getByRole('button',{name:'‹ 返回当天行程'}).click();await page.locator('.compact-trip-days button').first().click()}
    else {await page.getByRole('tab',{name:/每日行程/}).click();await page.locator('.trip-sidebar-days button').first().click()}
    await page.waitForTimeout(2800)
    const selected=page.locator(width<720?'.compact-trip-days button[aria-selected=true]':'.trip-sidebar-days button.active')
    assert.match(await selected.innerText(),/1/)
    await openNotice('day');await expectPoll('p1',2) // same read notification again
    await openNotice('changed');await expectPoll('p2',3) // another trip, newer poll day
    await openNotice('whole');await expectPoll('all',1) // actual nil overrides stale day 2
    await openNotice('gone');await page.locator('[data-poll-id=p2]').waitFor({state:'visible'})
    assert.equal(await page.getByLabel('投票属于哪一天').inputValue(),'1')
    await openNotice('old');await expectPoll('p1',2) // old payload without day
    await openNotice('chat');await page.locator('.trip-chat-panel').waitFor({state:'visible'})
    await openNotice('day');await expectPoll('p1',2)
    assert.deepEqual(errors,[])
    results.push({width,passed:true,readCalls:calls.filter(([p])=>p.endsWith('/read')).length})
    await ctx.close()
  }
  const recovery = await browser.newContext()
  await recovery.addInitScript(() => localStorage.setItem('travel_token','retained-token'))
  let unavailable = true
  await recovery.route('**/travel/api/**', async r => {
    const auth = r.request().url().endsWith('/auth/me')
    if (auth && unavailable) return r.fulfill({status:503,body:'{}'})
    const data = auth ? {username:'demo',is_admin:false} : r.request().url().includes('unread') ? {count:0} : []
    await r.fulfill({contentType:'application/json',body:JSON.stringify(data)})
  })
  const page = await recovery.newPage()
  await page.goto(url);await page.getByRole('alert').filter({hasText:'登录信息已保留'}).waitFor()
  assert.equal(await page.evaluate(()=>localStorage.getItem('travel_token')),'retained-token')
  unavailable = false
  await page.getByRole('button',{name:'重新连接'}).click();await page.getByLabel('问 AI',{exact:true}).waitFor()
  results.push({authRecovery:true});await recovery.close()
} finally { await browser.close() }
console.log(JSON.stringify(results,null,2))
