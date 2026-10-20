import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const url=process.env.ANDROID_QA_URL||'http://127.0.0.1:4181/travel/';
const output='/tmp/android-modules-qa';await fs.mkdir(output,{recursive:true});
const results=[];
try {
 for(const [name,width,height,dark] of [['light-320',320,844,false],['light-390',390,844,false],['light-430',430,932,false],['dark-320',320,844,true],['dark-390',390,844,true],['dark-430',430,932,true],['landscape',844,390,true]]) {
  if(process.env.LAYOUT_CASE&&process.env.LAYOUT_CASE!==name)continue;
  const context=await browser.newContext({viewport:{width,height},colorScheme:dark?'dark':'light',reducedMotion:'reduce',isMobile:width<600,hasTouch:true,userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.5.0'});
  await context.addInitScript(()=>{localStorage.setItem('travel_token','fixture');window.TongyouNative={postMessage:()=>{}};});
  const author={id:'u1',username:'demo',display_name:'小旅',avatar_url:'',home_city:'',travel_styles:[]};
  const profile={...author,stats:{relay_posts:1,verified:2,friends:0},recent_relay:[],profile_public:true,bio:''};
  let posts=[{id:'p1',author,kind:'condition',phase:'returned',content:'天堂寨漂流因天气原因暂停开放，请出发前再次确认。',created_at:'2026-08-19T09:00:00',expired:true,mine:true,reactions:{useful:0,verified:2,outdated:0}}];
  let convs=Array.from({length:12},(_,i)=>({id:`c${i}`,title:i===0?'合肥两天':i===1?'北京二日游':'吉隆坡和仙本那八天海岛旅行，包含交通与美食安排 '+i,updated_at:'2026-10-18T09:00:00'}));
  let trips=Array.from({length:12},(_,i)=>({id:`t${i}`,title:'南京出发 · 吉隆坡 + 仙本那 + 亚庇八日海岛旅行 '+i,days:8,destination:'吉隆坡、仙本那、亚庇',role:i===0?'editor':'owner'}));
  const entries=[{id:'e1',version:1,title:'海鲜晚餐',category:'餐饮',note:'',currency:'MYR',amount_minor:12050,spent_at:'2026-10-19'}];
  const book={id:'b1',title:'马来西亚',role:'owner',count:3,target_currency:'CNY',totals:{CNY:33900,MYR:22000,USD:5000},by_category:[],entries};
  const requests=[];
  await context.route('**/travel/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),path=u.pathname.replace('/travel/api','');let data=[];
   if(req.method()!=='GET')requests.push({path,method:req.method(),body:req.postDataJSON()});
   if(path==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false};
   else if(path.includes('unread'))data={count:0};
   else if(path==='/onboarding')data={trending:['合肥','吉隆坡','呈坎'],questions:[]};
   else if(path==='/chat/conversations')data=convs;
   else if(path.startsWith('/chat/conversations/')&&req.method()==='DELETE'){convs=convs.filter(c=>c.id!==path.split('/').at(-1));data={ok:true};}
   else if(path.endsWith('/messages'))data={messages:[{id:'m1',role:'assistant',content:'这是历史攻略',created_at:'2026-10-19T09:00:00'}],running:false};
   else if(path==='/trips')data=trips;
   else if(/^\/trips\/t\d+(\/leave)?$/.test(path)&&req.method()!=='GET'){trips=trips.filter(t=>!path.includes('/'+t.id));data={ok:true};}
   else if(path==='/ledger')data=[book,{...book,id:'b2',title:'只读旅行账本',role:'viewer'}];
   else if(path==='/ledger/b1')data=book;
   else if(path==='/ledger/b2')data={...book,id:'b2',title:'只读旅行账本',role:'viewer'};
   else if(path.endsWith('/conversion'))data={target_currency:'CNY',total_minor:100000,items:[],missing:[],stale:false};
   else if(path==='/social/me')data=profile;
   else if(path==='/social/friends')data={friends:[],received:[],sent:[]};
   else if(path==='/social/station')data={posts:u.searchParams.has('phase')?posts.filter(p=>p.phase===u.searchParams.get('phase')):posts,phase_counts:{planning:0,on_trip:0,returned:posts.length}};
   else if(path==='/social/posts'&&req.method()==='POST'){data={...req.postDataJSON(),id:'p2',author,created_at:'2026-10-19T09:00:00',mine:true,reactions:{}};posts=[data,...posts];}
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  const page=await context.newPage();page.setDefaultTimeout(12000);page.on('dialog',d=>d.accept());const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const metrics=()=>page.evaluate(()=>Object.fromEntries(['.hero-title','.hero-sub','.unified-start','.unified-idea textarea','.social-entry','.mobile-bottom-nav'].map(s=>{const e=document.querySelector(s),r=e.getBoundingClientRect(),c=getComputedStyle(e);return [s,{x:r.x,y:r.y,width:r.width,height:r.height,size:c.fontSize,weight:c.fontWeight,color:c.color}]})));
  if(name==='dark-390'||name==='light-390') {
   await page.goto('http://127.0.0.1:4183/travel/');await page.locator('.android-quick-starts button').first().waitFor();await page.waitForTimeout(150);var baseline=await metrics();
  }
  await page.goto(url);const nav=page.getByRole('navigation',{name:'移动端主导航'});await nav.waitFor();await page.locator('.android-quick-starts button').first().waitFor();await page.waitForTimeout(150);
  if(name==='dark-390'||name==='light-390')assert.deepEqual(await metrics(),baseline,'accepted homepage must remain identical');
  const color=dark?'rgb(240, 242, 247)':'rgb(25, 35, 53)';
  const hit=async loc=>{await loc.scrollIntoViewIfNeeded();assert.ok(await loc.evaluate(e=>{const r=e.getBoundingClientRect();return r.width>=44&&r.height>=44&&e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),'44px tappable control');};
  const shot=async label=>{assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,label+' overflow');await page.screenshot({path:`${output}/${name}-${label}.png`});};
  await nav.getByRole('button',{name:'行程',exact:true}).click();await page.locator('.trip-card').first().waitFor();
  assert.equal(await page.locator('.trip-card-title').first().evaluate(e=>getComputedStyle(e).color),color);await shot('trips');
  await hit(page.locator('.trip-card-del').last());await hit(page.locator('.trip-card-del').first());await page.locator('.trip-card-del').first().click();await page.waitForFunction(()=>document.querySelectorAll('.trip-card').length===11);assert.ok(requests.some(r=>r.path==='/trips/t0/leave'&&r.method==='POST'));
  await page.locator('.trip-card-del').first().click();await page.waitForFunction(()=>document.querySelectorAll('.trip-card').length===10);assert.ok(requests.some(r=>r.path==='/trips/t1'&&r.method==='DELETE'));
  await nav.getByRole('button',{name:'历史',exact:true}).click();await page.locator('.mobile-history-row').first().waitFor();await shot('history');
  await hit(page.locator('.mobile-history-row').last().locator('button').first());await page.getByLabel('搜索历史对话').fill('合肥');assert.equal(await page.locator('.mobile-history-row').count(),1);await page.locator('.mobile-history-row>button').first().click();await page.locator('.msg-assistant').waitFor();
  await nav.getByRole('button',{name:'历史',exact:true}).click();await page.getByLabel('搜索历史对话').fill('北京');await page.locator('.mobile-delete').click();await page.waitForFunction(()=>!document.querySelector('.mobile-history-row'));assert.ok(requests.some(r=>r.path==='/chat/conversations/c1'&&r.method==='DELETE'));
  await nav.getByRole('button',{name:'记账',exact:true}).click();await page.locator('.ledger-book').first().waitFor();await shot('books');
  assert.equal(await page.locator('.ledger-book h2').first().evaluate(e=>getComputedStyle(e).color),color);
  const lines=await page.locator('.ledger-book').first().locator('.ledger-original span').evaluateAll(els=>els.map(e=>e.getBoundingClientRect().y));assert.ok(lines[0]<lines[1]&&lines[1]<lines[2],'each currency on its own line');
  await page.locator('.ledger-book').first().click();await page.locator('.ledger-total h2').filter({hasText:'CNY'}).waitFor();await shot('ledger');await page.getByRole('button',{name:'＋ 记一笔',exact:true}).click();const dialog=page.getByRole('dialog',{name:'记一笔',exact:true});await dialog.waitFor();await shot('entry');
  assert.equal(await dialog.locator('input').first().evaluate(e=>getComputedStyle(e).color),color);assert.equal(await dialog.evaluate(e=>getComputedStyle(e).backgroundColor),dark?'rgb(27, 32, 49)':'rgb(244, 246, 252)','sheet surface follows theme');await dialog.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByRole('button',{name:'全部账本',exact:true}).click();await page.locator('.ledger-book').last().click();await page.locator('.ledger-total').waitFor();assert.equal(await page.getByRole('button',{name:'＋ 记一笔',exact:true}).count(),0,'viewer cannot edit');
  await nav.getByRole('button',{name:'同游圈',exact:true}).click();await page.locator('.relay-card').waitFor();await shot('social');
  const rects=await page.locator('.android-station-cities,.station-current,.android-relay-actions,.relay-feed').evaluateAll(els=>els.map(e=>({c:e.className,y:e.getBoundingClientRect().y})));assert.ok(rects.find(e=>e.c==='station-current').y<rects.find(e=>e.c==='android-relay-actions').y);
  assert.equal(await page.locator('.relay-card>p').evaluate(e=>getComputedStyle(e).color),color);assert.equal(await page.locator('.relay-freshness.stale').isVisible(),true);
  await page.locator('.station-phase-tabs button').nth(1).click();await page.locator('.social-empty').waitFor();await page.locator('.station-phase-tabs button').first().click();await page.locator('.relay-card').waitFor();
  await page.getByRole('button',{name:'搜索其他目的地'}).click();await page.getByLabel('输入目的地',{exact:true}).fill('京都');await page.getByRole('button',{name:'查看目的地接力',exact:true}).click();await page.locator('.station-current h2').filter({hasText:'京都'}).waitFor();
  await page.locator('.android-relay-actions button').nth(2).click();await page.locator('.relay-composer textarea').fill('沿河散步，行程轻松。');await shot('compose');await page.getByRole('button',{name:'发布到京都',exact:true}).click();await page.locator('.relay-composer').waitFor({state:'hidden'});assert.ok(requests.some(r=>r.path==='/social/posts'&&r.body.kind==='route'&&r.body.phase==='returned'&&r.body.destination==='京都'));
  await page.getByLabel('同游圈更多').click();await page.locator('.android-social-menu button').filter({hasText:/^好友/}).click();await page.locator('.friends-page').waitFor();await shot('friends');
  await page.getByLabel('同游圈更多').click();await page.locator('.android-social-menu button').filter({hasText:'我的主页'}).click();await page.locator('.profile-page').waitFor();await shot('profile');
  await page.evaluate(()=>window.tongyouAndroidBack());await page.locator('.station-current').waitFor();await page.evaluate(()=>window.tongyouAndroidBack());await page.locator('.station-search-panel').waitFor({state:'hidden'});await page.evaluate(()=>window.tongyouAndroidBack());await page.locator('.social-overlay').waitFor({state:'hidden'});
  assert.deepEqual(errors,[]);results.push({name,passed:true,homeBaseline:name.endsWith('390'),tripPermissions:true,history:true,ledgerViewer:true,socialPublishing:true});console.log(`${name}: passed`);await context.close();
 }
 await fs.writeFile(output+'/results.json',JSON.stringify(results,null,2));
}finally{await browser.close();}
