// Startup bridge tests against the exact bundled APK web snapshot; no live business traffic.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const base=process.env.ANDROID_QA_URL || 'http://127.0.0.1:4182/travel/';
const results=[];
try {
 for(const mode of ['slow-auth','slow-chunk','guest','offline','timeout','expired','invite','web']) {
  const native=mode!=='web';
  const context=await browser.newContext({viewport:{width:390,height:844},...(native?{userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.4.1'}:{})});
  await context.addInitScript(({native,mode})=>{
   window.readySignals=[];
   if(mode!=='guest'&&mode!=='invite')localStorage.setItem('travel_token','startup-fixture');
   if(native)window.TongyouNative={postMessage:raw=>{if(JSON.parse(raw).type==='ready')window.readySignals.push({home:!!document.querySelector('.mobile-bottom-nav'),auth:!!document.querySelector('.auth-screen'),invite:!!document.querySelector('.ledger-join'),error:!!document.querySelector('[role=alert]')})}};
  },{native,mode});
  let retry=false, authCalls=0;
  await context.route('**/travel/api/**',async route=>{
   const path=new URL(route.request().url()).pathname.replace('/travel/api','');let data=[];
   if(path==='/auth/me') {
    authCalls++;
    if(mode==='slow-auth')await new Promise(r=>setTimeout(r,1200));
    if(mode==='offline'&&!retry)return route.abort('internetdisconnected');
    if(mode==='timeout'&&!retry){await new Promise(r=>setTimeout(r,10000));return route.abort().catch(()=>{});}
    if(mode==='expired')return route.fulfill({status:401,contentType:'application/json',body:'{}'});
    data={username:'demo',is_admin:false};
   }
   else if(path==='/onboarding')data={trending:[],questions:[]};
   else if(path.includes('unread'))data={count:0};
   else if(path.startsWith('/ledger/shared/'))data={title:'启动邀请测试',inviter:'好友',role:'viewer',expires_at:'2026-10-26'};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)}).catch(()=>{});
  });
  if(mode==='slow-chunk')await context.route(/\/assets\/Home-[^/]+\.js$/,async route=>{await new Promise(r=>setTimeout(r,1400));await route.continue();});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+(mode==='invite'?'?ledger_join=startup-invite-token':''),{waitUntil:'domcontentloaded'});
  if(mode.startsWith('slow-')) {
   await page.waitForTimeout(400);
   assert.equal(await page.evaluate(()=>window.readySignals.length),0,'no ready while auth/lazy chunk pending');
  }
  const expected=mode==='guest'||mode==='expired'?'.auth-screen':mode==='invite'?'.ledger-join':mode==='offline'||mode==='timeout'?'[role=alert]':'.mobile-bottom-nav';
  await page.locator(mode==='web'?'.app':expected).waitFor({timeout:14000});
  if(native) {
   await page.waitForFunction(()=>window.readySignals.length>0);
   assert.ok(await page.evaluate(()=>window.readySignals.every(s=>s.home||s.auth||s.invite||s.error)),'only signal usable screen');
  }else assert.equal(await page.evaluate(()=>window.readySignals.length),0);
  if(mode==='offline'||mode==='timeout') {
   assert.equal(await page.evaluate(()=>localStorage.getItem('travel_token')),'startup-fixture');
   retry=true;await page.getByRole('button',{name:'重新连接',exact:true}).click();
   await page.locator('.mobile-bottom-nav').waitFor();assert.ok(authCalls>=2);
  }
  if(mode==='invite') {
   assert.match(page.url(),/ledger_join=startup-invite-token/);
   assert.equal(await page.evaluate(()=>localStorage.getItem('travel_pending_ledger_join')),'startup-invite-token');
  }
  assert.deepEqual(errors,[]);results.push({mode,passed:true});console.log(`${mode}: passed`);
  await context.close();
 }
 await fs.writeFile('/tmp/android-startup-browser-results.json',JSON.stringify(results,null,2));
} finally {await browser.close();}
