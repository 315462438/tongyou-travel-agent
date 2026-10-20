import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const url = process.env.JOURNEY_QA_URL || 'http://127.0.0.1:4185/travel/'
const out = process.env.JOURNEY_QA_OUTPUT || '/tmp/tongyou-journey-qa'
await fs.mkdir(out, {recursive:true})
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined)})
const results=[]
try {
for (const [name,width,height,dark,android,motion] of [
 ['android-small',320,780,false,true,'reduce'], ['android-dark',390,844,true,true,'no-preference'],
 ['web-mobile',430,932,false,false,'no-preference'], ['desktop',1280,900,false,false,'reduce'],
 ['desktop-dark',1280,900,true,false,'no-preference'], ['landscape',844,390,false,true,'reduce']
]) {
 if (process.env.QA_CASE && process.env.QA_CASE!==name) continue
 const ctx=await browser.newContext({viewport:{width,height},colorScheme:dark?'dark':'light',reducedMotion:motion,hasTouch:width<600,isMobile:width<600,...(android?{userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.6.0'}:{})})
 await ctx.addInitScript(({android})=>{localStorage.setItem('travel_token','fixture');if(android)window.TongyouNative={postMessage:()=>{}}},{android})
 const calls=[], errors=[]
 let failTrips=false, emptyTrips=false
 const trips=Array.from({length:6},(_,i)=>({id:`t${i}`,title:i===0?'杭州的慢周末':'吉隆坡与仙本那八天海岛旅行 '+i,destination:i===0?'杭州':'吉隆坡、仙本那',days:i===0?3:8,role:i===1?'editor':'owner'}))
 const book={id:'b1',title:'马来西亚',role:'owner',count:1,target_currency:'CNY',totals:{MYR:22000},by_category:[],entries:[]}
 await ctx.route('**/travel/api/**', async route=>{
  const req=route.request(),p=new URL(req.url()).pathname.replace('/travel/api','');calls.push({method:req.method(),p,body:req.postData()})
  let data=[]
  if(p==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false}
  else if(p.includes('unread'))data={count:0,unread:0}
  else if(p==='/onboarding')data={trending:['杭州','平潭岛','武汉'],questions:[]}
  else if(p==='/onboarding/covers')data={covers:{}}
  else if(p==='/trips'&&req.method()==='POST')data={id:'t0'}
  else if(p==='/trips') { if(failTrips)return route.fulfill({status:503,body:'{}'});data=emptyTrips?[]:trips }
  else if(p.endsWith('/issues'))data={issues:[],ticket_total:0}
  else if(p.includes('expenses/summary'))data={total:0,count:0,by_category:{},per_person:[],transfers:[],text:''}
  else if(p.includes('day-cities'))data={cities:{},overnight:{}}
  else if(p==='/trips/t0')data={...trips[0],members:[{username:'demo',role:'owner'}],stops:[],day_plans:[],ai_status:null}
  else if(p==='/chat/conversations')data=req.method()==='POST'?{conversation_id:'c2'}:[{id:'c1',title:'杭州两天',updated_at:'2026-10-19T09:00:00'}]
  else if(p.endsWith('/messages'))data=req.method()==='POST'?{ok:true}:{messages:[{id:'m1',role:'assistant',content:'沿湖散步，轻松安排每一天。'}],running:false}
  else if(p==='/ledger/shared/fixture-link')data={title:'共享旅行账本',inviter:'同伴',role:'viewer',expires_at:'2026-10-27'}
  else if(p==='/ledger/join')data={id:'b2'}
  else if(p==='/ledger')data=[book,{...book,id:'b2',title:'只读账本',role:'viewer'}]
  else if(p==='/ledger/b1')data=book
  else if(p==='/ledger/b2')data={...book,id:'b2',role:'viewer'}
  else if(p.endsWith('/conversion'))data={target_currency:'CNY',total_minor:33000,items:[],missing:[],stale:false}
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 const page=await ctx.newPage();page.setDefaultTimeout(12000);page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR',e.message)})
 await page.goto(url)
 const nav=page.getByRole('navigation',{name:'主导航',exact:true})
 await page.locator('.travel-book').first().waitFor()
 assert.deepEqual(await nav.locator('small').allTextContents(),['旅行','记账','我的'])
 assert.equal(await page.getByRole('button',{name:'同游圈',exact:true}).count(),0)
 assert.equal(await page.locator('.social-entry').count(),0)
 const shot=async label=>{
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`${name}/${label} no horizontal overflow`)

  await page.screenshot({animations:'disabled',path:`${out}/${name}-${label}.png`})
 }
 const hit=async locator=>{await locator.scrollIntoViewIfNeeded();assert.ok(await locator.evaluate(e=>{const r=e.getBoundingClientRect();return r.width>=44&&r.height>=44&&e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'control reachable')}
 await hit(page.getByLabel('问 AI',{exact:true}));await shot('home')
 await page.getByLabel('问 AI',{exact:true}).click()
 await page.getByRole('button',{name:'找美食'}).click()
 const prompt=page.getByRole('textbox',{name:'旅行需求',exact:true})
 assert.match(await prompt.inputValue(),/当地美食/)
 assert.equal(calls.filter(x=>x.method==='POST').length,0,'shortcut does not submit')
 await prompt.fill('杭州西湖附近，人均100元以内的美食')
 await page.getByLabel('关闭 AI').click();await page.getByLabel('问 AI',{exact:true}).click()
 assert.equal(await prompt.inputValue(),'杭州西湖附近，人均100元以内的美食','draft preserved')
 await shot('ai')
 await page.getByRole('button',{name:'发送',exact:true}).click()
 await page.locator('.msg-assistant').waitFor()
 assert.ok(calls.some(x=>x.p==='/chat/c2/messages'&&JSON.parse(x.body).web_search===true),'web search enabled')
 await page.getByLabel('关闭 AI').click();await page.getByLabel('问 AI',{exact:true}).click()
 await page.locator('.msg-assistant').waitFor()
 await page.getByLabel('关闭 AI').click()
 await nav.getByRole('button',{name:'我的',exact:true}).click()
 await shot('account');await page.getByRole('button',{name:'历史对话'}).click();await shot('history')
 await page.getByLabel('搜索历史对话').fill('杭州');await page.locator('.mobile-history-row>button').first().click()
 await page.locator('.msg-assistant').waitFor();await page.getByLabel('关闭 AI').click()
 await nav.getByRole('button',{name:'记账',exact:true}).click();await page.locator('.ledger-book').first().waitFor();await hit(nav.getByRole('button',{name:'我的',exact:true}));await shot('ledger')
 await page.locator('.ledger-book').last().click();await page.locator('.ledger-total').waitFor();assert.equal(await page.getByRole('button',{name:'＋ 记一笔',exact:true}).count(),0,'viewer cannot edit')
 await nav.getByRole('button',{name:'旅行',exact:true}).click();await page.locator('.travel-book').first().waitFor()
 await page.getByRole('button',{name:'新建旅行',exact:true}).click();await page.locator('.trip-create').waitFor()
 await page.getByLabel('行程名称',{exact:true}).fill('杭州的慢周末')
 await page.getByLabel('目的地',{exact:true}).fill('杭州');await shot('create')
 await page.getByRole('button',{name:'＋ 创建空白行程',exact:true}).click()
 await page.locator('.android-trip-board,.trip-board').waitFor()
 assert.ok(calls.some(x=>x.p==='/trips'&&x.method==='POST'&&JSON.parse(x.body).title==='杭州的慢周末'),'create trip request')
 if(await page.getByLabel('返回行程列表').isVisible())await page.getByLabel('返回行程列表').click()
 await nav.getByRole('button',{name:'旅行',exact:true}).click();await page.locator('.travel-book').first().waitFor()
 await page.getByLabel('打开行程 杭州的慢周末').click();await page.locator('.android-trip-board,.trip-board').waitFor();await shot('trip-detail');assert.ok(calls.some(x=>x.p==='/trips/t0'),'opens selected trip')
 if(await page.getByLabel('返回行程列表').isVisible())await page.getByLabel('返回行程列表').click()
 await nav.getByRole('button',{name:'旅行',exact:true}).click()
 failTrips=true;await page.reload();await page.getByRole('button',{name:'重新加载',exact:true}).waitFor();await shot('error')
 failTrips=false;emptyTrips=true;await page.getByRole('button',{name:'重新加载',exact:true}).click();await page.getByText('第一本旅行册，等你翻开').waitFor();await shot('empty')
 if(motion==='reduce')assert.equal(await page.locator('.travel-home').evaluate(e=>getComputedStyle(e).animationName),'none')
 await page.goto(url+'?ledger_join=fixture-link')
 await page.getByRole('button',{name:'确认加入账本',exact:true}).click()
 await page.locator('.ledger-total').waitFor()
 assert.equal(await page.getByRole('button',{name:'＋ 记一笔',exact:true}).count(),0,'shared viewer link opens correct book')
 assert.ok(calls.some(x=>x.p==='/ledger/join'&&JSON.parse(x.body).token==='fixture-link'))
 assert.deepEqual(errors,[])
 results.push({name,passed:true,navigation:true,draftPreserved:true,shortcutRequiresSend:true,history:true,ledgerViewer:true,tripOpen:true,errorRetry:true})
 console.log(name+': passed');await ctx.close()
}
await fs.writeFile(out+'/results.json',JSON.stringify(results,null,2))
} finally { await browser.close() }
