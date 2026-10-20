import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})
const out='/tmp/tongyou-account-panels';await fs.mkdir(out,{recursive:true})
try {
 for(const [name,width,height,android,dark,admin] of [['android',390,844,true,false,true],['android-dark',320,780,true,true,true],['web',430,932,false,false,true],['desktop',1280,900,false,false,true],['desktop-dark',1280,900,false,true,true],['member',390,844,false,false,false]]) {
  if(process.env.QA_CASE&&process.env.QA_CASE!==name)continue
  const ctx=await browser.newContext({viewport:{width,height},colorScheme:dark?'dark':'light',reducedMotion:'reduce',...(android?{userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.8.2'}:{})})
  await ctx.addInitScript(android=>{localStorage.setItem('travel_token','fixture');if(android)window.TongyouNative={postMessage:()=>{}}},android)
  await ctx.route('**/travel/api/**',async r=>{
   const p=new URL(r.request().url()).pathname.replace('/travel/api','');let data=[]
   if(p==='/auth/me')data={username:'tester',display_name:'测试用户',is_admin:admin}
   else if(p.includes('unread'))data={count:0,unread:0}
   else if(p==='/onboarding')data={trending:[],questions:[]}
   else if(p==='/onboarding/covers')data={covers:{}}
   else if(p==='/admin/users')data={total:0,users:[]}
   else if(p==='/connectors')data={connectors:[]}
   else if(p.includes('connect/status'))data={state:'idle'}
   else if(p==='/support/messages')data={messages:[]}
   await r.fulfill({contentType:'application/json',body:JSON.stringify(data)})
  })
  const page=await ctx.newPage();page.setDefaultTimeout(8000);const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto(process.env.ACCOUNT_QA_URL||'http://127.0.0.1:4185/travel/')
  await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'我的',exact:true}).click()
  const account=page.getByRole('region',{name:'我的账户'})
  await account.getByText('更多工具与设置',{exact:true}).click()
  const tools=[['公告','公告'],['帮助与反馈','联系客服'],['旅行偏好与记忆','🧠 记忆'],['技能','🧩 我的技能'],['连接','连接'],...(admin?[['用户管理','用户管理']]:[])]
  for(const [label,title] of tools){
   await account.getByRole('button',{name:label,exact:true}).click()
   const panel=page.locator('.app > .modal-mask .side-panel'),close=panel.locator('.modal-close')
   await panel.locator('.modal-head strong').filter({hasText:title}).waitFor()
   // isVisible alone misses an opaque sibling covering the entire panel.
   await close.scrollIntoViewIfNeeded()
   assert.ok(await close.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),`${name}: ${label} close button must be above account without pressing 完成`)
   if(label==='公告')await page.screenshot({path:`${out}/${name}-announcement.png`})
   await close.click();await panel.waitFor({state:'detached'})
   assert.ok(await account.isVisible());assert.ok(await account.locator('details').evaluate(e=>e.open))
   await account.getByRole('button',{name:label,exact:true}).click()
   await panel.waitFor()
   if(android)assert.equal(await page.evaluate(()=>window.tongyouAndroidBack()),true)
   else await page.keyboard.press('Escape')
   await panel.waitFor({state:'detached'});assert.ok(await account.isVisible())
  }
  if(!admin)assert.equal(await account.getByRole('button',{name:'用户管理',exact:true}).count(),0)
  assert.deepEqual(errors,[]);console.log(name+': passed');await ctx.close()
 }
}finally{await browser.close()}
