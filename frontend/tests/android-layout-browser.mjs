// Mocked business traffic only. Exercise APK styling and the browser's mobile preview.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.ANDROID_QA_URL || 'http://127.0.0.1:4181/travel/';
const output = process.env.ANDROID_LAYOUT_OUTPUT || '/tmp/tongyou-android-layout';
await fs.mkdir(output, {recursive: true});
const browser = await chromium.launch({headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results = [];
try {
 for (const [name,width,android] of [['android-small',320,true],['android',390,true],['android-large',430,true],['web-phone',390,false],['web-preview',1440,false]]) {
  if(process.env.LAYOUT_CASE && process.env.LAYOUT_CASE!==name)continue;
  const context = await browser.newContext({viewport:{width,height:844}, isMobile:width<600, hasTouch:width<600, reducedMotion:'reduce',
   ...(android ? {userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.2.0'} : {})});
  await context.addInitScript(native => {
   localStorage.setItem('travel_token','layout-qa');localStorage.setItem('travel_layout_mode','mobile');
   if(native)window.TongyouNative={postMessage:()=>{}};
  },android);
  const entries = [{id:'e1',version:1,title:'海鲜晚餐',category:'餐饮',note:'',currency:'MYR',amount_minor:12050,spent_at:'2026-10-19'}];
  const book = () => ({id:'b1',title:'马来西亚 · 海岛旅行',role:'owner',count:entries.length,target_currency:'CNY',totals:{MYR:12050},by_category:[],entries});
  const requests=[];
  await context.route('**/travel/api/**',route=>{
   const req=route.request(), path=new URL(req.url()).pathname.replace('/travel/api','');let data=[];
   if(path==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false};
   else if(path.includes('unread'))data={count:0};
   else if(path==='/onboarding')data={trending:['杭州','武汉'],questions:[]};
   else if(path==='/chat/conversations')data=req.method()==='POST'?{conversation_id:'c1'}:[{id:'c1',title:'杭州周末旅行',updated_at:'2026-10-19T09:00:00'}];
   else if(path==='/chat/c1/messages'){
    if(req.method()==='POST'){requests.push(req.postDataJSON());data={ok:true};}
    else data={messages:[{id:'m1',role:'assistant',content:'测试回复',created_at:'2026-10-19T09:00:00'}],running:false};
   }
   else if(path==='/trips')data=Array.from({length:7},(_,i)=>({id:`t${i}`,title:i===0?'南京出发 · 吉隆坡 + 仙本那 + 亚庇八日海岛旅行':`周末旅行 ${i}`,days:8,destination:'吉隆坡、仙本那、亚庇',role:'editor'}));
   else if(path==='/ledger')data=[book(),{...book(),id:'b2',title:'下次旅行',count:0,totals:{}}];
   else if(path==='/ledger/b1')data=book();
   else if(path.endsWith('/conversion'))data={target_currency:'CNY',total_minor:19280,items:[],missing:[],stale:false};
   else if(path==='/ledger/b1/entries'&&req.method()==='POST'){
    const entry=req.postDataJSON();assert.equal(entry.title,'');entries.push({...entry,title:entry.category,amount_minor:100});data={ok:true};
   }
   else if(path==='/social/me')data={username:'demo',display_name:'小旅',stats:{},recent_relay:[],travel_styles:[]};
   else if(path==='/social/friends')data={friends:[],received:[],sent:[]};
   else if(path==='/social/station')data={posts:[],phase_counts:{}};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);
  await page.goto(url);const nav=page.getByRole('navigation',{name:'移动端主导航'});await nav.waitFor();
  const hit=async locator=>{
   await locator.scrollIntoViewIfNeeded();
   const state=await locator.evaluate(e=>{const r=e.getBoundingClientRect(),top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {text:e.textContent,width:r.width,height:r.height,x:r.x,y:r.y,top:top?.outerHTML.slice(0,180),hit:e.contains(top)}});
   if(!state.hit)await page.screenshot({path:`${output}/${name}-hit-failure.png`});
   assert.ok(state.height>=44&&state.width>=44&&state.hit,JSON.stringify(state));
  };
  const shot=async label=>{
   if(android){
    const caps={'.hero-title':26,'.trip-list-intro h1':24,'.mobile-page-header h1':24,'.mobile-social-title':24,'.ledger-header h1':24,'.ledger-shell[data-detail="true"] .ledger-header h1':18,'.ledger-modal h2':18,'.trip-card-title':14,'.ledger-book h2':16,'.unified-idea textarea':14,'.ledger-modal input':14};
    for(const [selector,max] of Object.entries(caps))for(const el of await page.locator(selector).all())if(await el.isVisible()){
     const style=await el.evaluate(e=>({size:parseFloat(getComputedStyle(e).fontSize),weight:parseInt(getComputedStyle(e).fontWeight)}));
     assert.ok(style.size<=max&&style.weight<=600,`${name}/${label} ${selector}: ${JSON.stringify(style)}`);
    }
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,`${name}/${label} overflow`);
   for(const el of await page.locator('.ledger-shell,.ledger-modal,.trips-list').all())assert.ok(await el.evaluate(e=>e.scrollWidth<=e.clientWidth+1),`${name}/${label} container overflow`);
   await page.screenshot({path:`${output}/${name}-${label}.png`});
  };
  const tools=page.getByRole('group',{name:'规划选项'});
  for(const label of ['深度推理','联网搜索']){const b=tools.getByRole('button',{name:label,exact:true});await hit(b);if(await b.getAttribute('aria-pressed')!=='true')await b.click();assert.equal(await b.getAttribute('aria-pressed'),'true');}
  assert.ok((await page.locator('.social-entry-copy').boundingBox()).width>160,'relay copy must not collapse in desktop mobile preview');
  if(android)assert.equal(await page.locator('.layout-switch').isVisible(),false);
  else {await hit(page.getByRole('button',{name:'网页端',exact:true}));await page.getByRole('button',{name:'网页端',exact:true}).click();await page.locator('.app.view-desktop').waitFor();await page.getByRole('button',{name:'移动端',exact:true}).click();await nav.waitFor();}
  await shot('home');
  // Persisted controls and actual request fields, not just button appearance.
  await page.reload();await tools.waitFor();assert.equal(await tools.getByRole('button',{name:'深度推理',exact:true}).getAttribute('aria-pressed'),'true');
  await page.getByLabel('旅行需求',{exact:true}).fill('帮我规划三天杭州旅行');await page.locator('.unified-submit').click();
  await page.waitForFunction(()=>!!document.querySelector('.msg-assistant'));assert.equal(requests.length,1);assert.equal(requests[0].deep_reasoning,true);assert.equal(requests[0].web_search,true);
  await nav.getByRole('button',{name:'首页',exact:true}).click();await tools.waitFor();
  for(const label of ['深度推理','联网搜索'])await tools.getByRole('button',{name:label,exact:true}).click();
  await page.getByLabel('旅行需求',{exact:true}).fill('今天吃什么');await page.locator('.unified-submit').click();await page.waitForFunction(()=>!!document.querySelector('.msg-assistant'));
  assert.equal(requests.at(-1).deep_reasoning,false);assert.equal(requests.at(-1).web_search,false);
  await nav.getByRole('button',{name:'行程',exact:true}).click();await page.locator('.trip-card').first().waitFor();await shot('trips');
  await page.locator('.trip-card').last().scrollIntoViewIfNeeded();for(const b of await nav.locator('button').all())await hit(b);
  await nav.getByRole('button',{name:'记账',exact:true}).click();await page.locator('.ledger-book').first().waitFor();await shot('books');
  await page.locator('.ledger-book').first().click();await page.locator('.ledger-total h2').filter({hasText:'CNY'}).waitFor();await shot('ledger');
  await page.getByRole('button',{name:'＋ 记一笔'}).click();const dialog=page.getByRole('dialog',{name:'记一笔',exact:true});await dialog.waitFor();
  await dialog.getByLabel('金额',{exact:true}).fill('1');await dialog.getByLabel('分类',{exact:true}).selectOption('交通');
  await shot('entry');
  if(android){
   await page.setViewportSize({width,height:490});await page.evaluate(()=>document.documentElement.classList.add('android-ime-open'));
   assert.equal(await nav.isVisible(),false);await dialog.getByRole('button',{name:'保存',exact:true}).scrollIntoViewIfNeeded();await hit(dialog.getByRole('button',{name:'保存',exact:true}));await shot('keyboard');
  }
  await dialog.getByRole('button',{name:'保存',exact:true}).click();await dialog.waitFor({state:'hidden'});assert.equal(entries.length,2);
  if(android){await page.setViewportSize({width,height:844});await page.evaluate(()=>document.documentElement.classList.remove('android-ime-open'));}
  await nav.getByRole('button',{name:'历史',exact:true}).click();await page.getByRole('region',{name:'历史记录'}).waitFor();await shot('history');
  await nav.getByRole('button',{name:'同游圈',exact:true}).click();await page.locator('.social-overlay').waitFor();await shot('social');
  assert.deepEqual(errors,[]);results.push({name,requestFlags:true,layoutSwitch:!android,emptyTitleSave:true,keyboard:android,pages:7});
  console.log(`${name}: passed`);await context.close();
 }
 await fs.writeFile(`${output}/results.json`,JSON.stringify(results,null,2));
}finally{await browser.close();}
