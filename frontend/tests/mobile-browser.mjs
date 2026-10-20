// Local preview only: all business APIs are mocked, no production writes.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output=process.env.MOBILE_QA_OUTPUT || '/tmp/tongyou-mobile-qa';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined)});
try {
for(const width of [320,390,430]){
 const ctx=await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true,reducedMotion:'reduce'});
 await ctx.addInitScript(()=>{localStorage.setItem('travel_token','qa-only');localStorage.setItem('travel_layout_mode','mobile')});
 const calls=[];
 await ctx.route('**/travel/api/**',route=>{
  const r=route.request(),path=new URL(r.url()).pathname.replace('/travel/api','');calls.push([r.method(),path]);let data=[];
  if(path==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false};
  else if(path==='/onboarding')data={trending:['杭州','武汉'],questions:[]};
  else if(path.includes('unread'))data={count:0};
  else if(path==='/chat/conversations')data=[{id:'c1',title:'杭州周末旅行',updated_at:'2026-10-19T09:00:00'},{id:'c2',title:'马来西亚海岛',updated_at:'2026-10-18T09:00:00'}];
  else if(path==='/chat/c1/messages')data={messages:[{id:'m1',role:'user',content:'杭州周末旅行',created_at:'2026-10-19T09:00:00'}],running:false};
  else if(path==='/trips')data=[{id:'t1',title:'南京出发 · 吉隆坡 + 仙本那 + 亚庇',days:8,destination:'吉隆坡、仙本那、亚庇',role:'editor',updated_at:'2026-10-19T09:00:00'}];
  else if(path==='/social/me')data={id:'u1',username:'demo',display_name:'小旅',avatar_url:'',bio:'',home_city:'南京',travel_styles:[],stats:{},recent_relay:[]};
  else if(path==='/social/friends')data={friends:[],received:[],sent:[]};
  else if(path==='/social/station')data={posts:[],phase_counts:{planning:0,on_trip:0,returned:0}};
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
 await page.goto(process.env.MOBILE_QA_URL || 'http://127.0.0.1:4179/travel/');
 const nav=page.getByRole('navigation',{name:'移动端主导航'});
 await nav.waitFor();assert.deepEqual(await nav.locator('small').allTextContents(),['首页','行程','记账','历史','同游圈']);
 const check=async name=>{
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,`${name}: page overflow`);
  const b=await nav.boundingBox();assert.ok(b.x>=0&&b.x+b.width<=width+1&&b.y+b.height<=844,`${name}: tab bounds`);
  assert.equal(await nav.locator('[aria-current="page"]').count(),1);
  for(const button of await nav.locator('button').all()){const box=await button.boundingBox();assert.ok(box.height>=44&&box.width>=44);assert.ok(await button.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}),`${name}: tab obscured`)}
  await page.screenshot({path:`${output}/${name}-${width}.png`});
 };
 assert.equal(await page.locator('.hero-title').evaluate(e=>getComputedStyle(e).textAlign),'left');await check('home');
 await page.getByRole('button',{name:'我的',exact:true}).click();await page.getByRole('region',{name:'我的账户'}).waitFor();await check('account');await page.getByRole('button',{name:'关闭页面'}).click();
 await nav.getByRole('button',{name:'历史',exact:true}).click();const history=page.getByRole('region',{name:'历史记录'});await history.waitFor();await history.getByText('杭州周末旅行',{exact:true}).waitFor();
 await page.getByLabel('搜索历史对话').fill('杭州');assert.equal(await history.locator('.mobile-history-row').count(),1);await check('history');await history.locator('.mobile-history-row > button:first-child').click();await history.waitFor({state:'hidden'});await page.locator('.msg-user').first().waitFor();
 await nav.getByRole('button',{name:'首页',exact:true}).click();await page.locator('.hero-title').waitFor();
 await nav.getByRole('button',{name:'行程',exact:true}).click();await page.locator('.trip-card').waitFor();assert.equal(await page.locator('.trip-create').count(),0);await check('trips');
 await page.getByRole('button',{name:'新建行程',exact:true}).click();await page.locator('.trip-create').waitFor();await page.getByRole('button',{name:'收起新建行程',exact:true}).click();assert.equal(await page.locator('.trip-create').count(),0);
 await nav.getByRole('button',{name:'记账',exact:true}).click();await page.locator('.ledger-shell').waitFor();await check('ledger');
 await page.getByRole('button',{name:'＋ 新建账本'}).click();await page.getByRole('dialog',{name:'新建账本',exact:true}).waitFor();const save=page.getByRole('button',{name:'保存',exact:true});assert.ok(await save.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}));await page.getByRole('button',{name:'取消',exact:true}).click();
 await nav.getByRole('button',{name:'同游圈',exact:true}).click();await page.locator('.station-hot-card').first().waitFor();await check('social');const sub=await page.getByRole('navigation',{name:'社交中心导航'}).boundingBox();assert.ok(sub.y<180,'social subnavigation should be at top');
 await nav.getByRole('button',{name:'首页',exact:true}).click();const input=page.locator('.unified-idea textarea');await input.focus();
 // Simulate visual viewport contraction; actual OS keyboard remains a device check.
 await page.evaluate(()=>{Object.defineProperty(visualViewport,'height',{configurable:true,value:500});visualViewport.dispatchEvent(new Event('resize'))});await page.waitForFunction(()=>document.querySelector('.app').classList.contains('keyboard-open'));assert.equal(await nav.isVisible(),false);
 await page.evaluate(()=>{delete visualViewport.height;visualViewport.dispatchEvent(new Event('resize'))});await nav.waitFor();
 assert.deepEqual(errors,[]);assert.ok(calls.every(([method])=>method==='GET'),'navigation must not mutate data');console.log(JSON.stringify({width,pages:7,historySearchAndOpen:true,creationToggle:true,modalReachable:true,keyboardViewport:true,errors}));await ctx.close();
}
}finally{await browser.close()}
