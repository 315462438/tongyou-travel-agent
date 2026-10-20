// Mocked local preview: material, navigation motion, scrolling and accessibility.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output=process.env.MOBILE_GLASS_QA_OUTPUT || '/tmp/tongyou-mobile-glass-qa';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined)});
try {
for(const width of [320,390,430]){
 const ctx=await browser.newContext({viewport:{width,height:844},isMobile:true,hasTouch:true});
 await ctx.addInitScript(()=>{localStorage.setItem('travel_token','qa-only');localStorage.setItem('travel_layout_mode','mobile')});
 await ctx.route('**/travel/api/**',route=>{
  const path=new URL(route.request().url()).pathname.replace('/travel/api','');let data=[];
  if(path==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false};
  else if(path==='/onboarding')data={trending:['杭州','武汉'],questions:[]};
  else if(path.includes('unread'))data={count:0};
  else if(path==='/trips')data=Array.from({length:40},(_,i)=>({id:'t'+i,title:i===0?'吉隆坡 · 仙本那 · 亚庇':`旅行计划 ${i+1}`,days:8,destination:'马来西亚',role:'editor',updated_at:'2026-10-19T09:00:00'}));
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
 await page.goto(process.env.MOBILE_QA_URL || 'http://127.0.0.1:4179/travel/');
 const nav=page.getByRole('navigation',{name:'移动端主导航'});await nav.waitFor();
 assert.match(await nav.evaluate(e=>getComputedStyle(e).backdropFilter),/blur\(20px\)/);
 const lens=()=>nav.evaluate(e=>{const s=getComputedStyle(e,'::before');return {x:new DOMMatrix(s.transform).m41,width:parseFloat(s.width),duration:parseFloat(s.transitionDuration),filter:s.backdropFilter,pointer:s.pointerEvents}});
 const first=await lens();assert.ok(first.duration>0);assert.equal(first.filter,'none');assert.equal(first.pointer,'none');
 assert.match(await page.locator('.inspiration-launchpad').evaluate(e=>getComputedStyle(e).backdropFilter),/blur\(12px\)/);
 await page.screenshot({path:`${output}/home-${width}.png`});
 await nav.getByRole('button',{name:'行程',exact:true}).click();await page.locator('.trip-card').first().waitFor();
 await page.waitForFunction(()=>{const n=document.querySelector('.mobile-bottom-nav'),s=getComputedStyle(n,'::before');return Math.abs(new DOMMatrix(s.transform).m41-parseFloat(s.width)-2)<1}).catch(async error=>{console.log('LENS_DIAGNOSTIC',await nav.evaluate(e=>{const s=getComputedStyle(e,'::before');return {active:e.dataset.active,index:s.getPropertyValue('--mobile-tab-index'),transform:s.transform,width:s.width,boxSizing:s.boxSizing,padding:s.padding,border:s.border}}));throw error});
 const next=await lens();assert.ok(next.x>first.x);assert.ok(Math.abs(next.x-next.width-2)<1);
 assert.ok(await page.locator('.trip-card').evaluateAll(els=>els.every(e=>getComputedStyle(e).backdropFilter==='none')),'long list must not allocate a live blur per card');
 const active=await nav.locator('[aria-current="page"]').boundingBox(),bar=await nav.boundingBox();assert.ok(Math.abs(bar.x+1+5+next.x-active.x)<2,'lens aligns with selected tab');
 await page.screenshot({path:`${output}/trips-${width}.png`});
 await page.locator('.trip-card').last().scrollIntoViewIfNeeded();
 const last=await page.locator('.trip-card').last().boundingBox();assert.ok(last.y+last.height<bar.y,'last card clears floating tab bar');
 assert.ok(await page.locator('.trip-card').last().evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}));
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
 await nav.getByRole('button',{name:'记账',exact:true}).click();await page.getByRole('button',{name:'＋ 新建账本'}).click();
 const sheet=page.getByRole('dialog',{name:'新建账本',exact:true});await sheet.waitFor();assert.match(await sheet.evaluate(e=>getComputedStyle(e).backdropFilter),/blur\(16px\)/);assert.equal(await page.locator('.ledger-modal-backdrop').evaluate(e=>getComputedStyle(e).backdropFilter),'none');
 await page.waitForFunction(()=>document.querySelector('.ledger-modal')?.getAnimations().length===0);
 const save=sheet.getByRole('button',{name:'保存',exact:true});assert.ok(await save.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))}));await page.screenshot({path:`${output}/sheet-${width}.png`});
 const cdp=await ctx.newCDPSession(page);await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-transparency',value:'reduce'},{name:'prefers-reduced-motion',value:'reduce'}]});
 await page.waitForFunction(()=>getComputedStyle(document.querySelector('.ledger-modal')).backdropFilter==='none');
 assert.equal(await sheet.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(249, 251, 255)');assert.equal(await sheet.evaluate(e=>getComputedStyle(e).animationName),'none');
 await sheet.getByRole('button',{name:'取消',exact:true}).click();await nav.getByRole('button',{name:'行程',exact:true}).click();
 assert.equal((await lens()).duration,0);assert.equal(await nav.evaluate(e=>getComputedStyle(e).backdropFilter),'none');assert.equal(await nav.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(249, 251, 255)');
 assert.equal(await page.locator('.trip-card').first().evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(249, 251, 255)');
 assert.deepEqual(errors,[]);console.log(JSON.stringify({width,liveGlass:true,singleSlidingLens:true,longListNoBlur:true,lastCardReachable:true,sheetReachable:true,reducedMotion:true,reducedTransparency:true,errors}));await ctx.close();
}
}finally{await browser.close()}
