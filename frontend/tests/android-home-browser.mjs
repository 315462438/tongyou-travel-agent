// Mocked business traffic only. Exercise APK styling and the browser's mobile preview.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.ANDROID_QA_URL || 'http://127.0.0.1:4181/travel/';
const output = process.env.ANDROID_LAYOUT_OUTPUT || '/tmp/tongyou-home-ios-qa';
await fs.mkdir(output, {recursive: true});
const browser = await chromium.launch({headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const results = [];
try {
 for(const [name,width,height,dark] of [['light-320',320,844,false],['light-360',360,844,false],['light-390',390,844,false],['light-430',430,932,false],['dark-320',320,844,true],['dark-360',360,844,true],['dark-390',390,844,true],['dark-430',430,932,true],['landscape',844,390,true]]) {
  const android=true;
  if(process.env.LAYOUT_CASE && process.env.LAYOUT_CASE!==name)continue;
  const context = await browser.newContext({viewport:{width,height},colorScheme:dark?'dark':'light', isMobile:width<600, hasTouch:width<600, reducedMotion:'reduce',
   ...(android ? {userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.2.0'} : {})});
  await context.addInitScript(native => {
   localStorage.setItem('travel_token','layout-qa');localStorage.setItem('travel_layout_mode','mobile');
   if(native)window.TongyouNative={postMessage:()=>{}};
  },android);
  const entries = [{id:'e1',version:1,title:'海鲜晚餐',category:'餐饮',note:'',currency:'MYR',amount_minor:12050,spent_at:'2026-10-19'}];
  const book = () => ({id:'b1',title:'马来西亚 · 海岛旅行',role:'owner',count:entries.length,target_currency:'CNY',totals:{MYR:12050},by_category:[],entries});
  const requests=[];let failUpload=false;
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
   else if(path==='/uploads'){if(failUpload)return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({detail:'图片上传失败，请重试'})});data={id:'home-image'};}
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

  const page=await context.newPage(), errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);
  await page.goto(url);await page.locator('.android-quick-starts').waitFor();
  assert.equal(await page.locator('.unified-submit').isDisabled(),true);
  assert.equal(await page.locator('.inspiration-status').isVisible(),false);
  const form=await page.locator('.unified-start').boundingBox();assert.ok(form.height<=180,JSON.stringify(form));
  const controls=await page.locator('.unified-attach-btn,.unified-tools button,.unified-submit').evaluateAll(els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}}));
  assert.equal(controls.length,4);assert.ok(Math.max(...controls.map(x=>x.y))-Math.min(...controls.map(x=>x.y))<=2,'one toolbar row');
  for(let i=0;i<controls.length;i++){const c=controls[i];assert.ok(c.w>=44&&c.h>=44);if(i)assert.ok(c.x>=controls[i-1].x+controls[i-1].w-1,'buttons must not overlap');}
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  const card=await page.locator('.destination-card').first().boundingBox(),nav=await page.locator('.mobile-bottom-nav').boundingBox();
  if(width>=360&&height>=800)assert.ok(card.y+card.height<=nav.y,`popular card hidden: ${JSON.stringify({card,nav})}`);
  assert.equal(await page.locator('.unified-idea textarea').evaluate(e=>getComputedStyle(e).color),dark?'rgb(240, 242, 247)':'rgb(25, 35, 53)');
  await page.screenshot({path:`${output}/${name}.png`});
  // Quick starts fill the sole composer without sending an unexpected request.
  await page.locator('.android-quick-starts button').first().click();assert.equal(requests.length,0);assert.equal(await page.getByLabel('旅行需求',{exact:true}).inputValue(),'杭州怎么玩');
  assert.equal(await page.locator('.unified-submit').isEnabled(),true);
  await page.getByRole('button',{name:'深度推理',exact:true}).click();await page.getByRole('button',{name:'联网搜索',exact:true}).click();
  await page.locator('.unified-submit').click();await page.locator('.msg-assistant').waitFor();assert.equal(requests.at(-1).content,'杭州怎么玩');assert.equal(requests.at(-1).deep_reasoning,true);assert.equal(requests.at(-1).web_search,false);
  await page.getByRole('navigation',{name:'移动端主导航'}).getByRole('button',{name:'首页',exact:true}).click();await page.locator('.unified-start').waitFor();
  // Image-only sending remains valid, and a selected image can be removed.
  await page.locator('.unified-attach input').setInputFiles({name:'photo.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhFoAAAAASUVORK5CYII=','base64')});
  await page.getByRole('button',{name:'移除这张图片'}).waitFor();await page.locator('.unified-submit:enabled').waitFor();assert.ok(await page.locator('.inspiration-status').isVisible());
  await page.getByRole('button',{name:'移除这张图片'}).click();assert.equal(await page.locator('.unified-submit').isDisabled(),true);
  await page.locator('.unified-attach input').setInputFiles({name:'photo.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhFoAAAAASUVORK5CYII=','base64')});
  await page.locator('.unified-submit:enabled').waitFor();await page.locator('.unified-submit').click();await page.locator('.msg-assistant').waitFor();assert.deepEqual(requests.at(-1).image_ids,['home-image']);
  await page.getByRole('navigation',{name:'移动端主导航'}).getByRole('button',{name:'首页',exact:true}).click();await page.locator('.unified-start').waitFor();
  await page.getByLabel('旅行需求',{exact:true}).fill('https://example.com/guide');await page.getByText('已识别 1 条链接，将自动整理').waitFor();await page.locator('.unified-submit').click();await page.locator('.msg-assistant').waitFor();assert.equal(requests.at(-1).deep_reasoning,true);assert.ok(requests.at(-1).content.includes('https://example.com/guide'));
  await page.getByRole('navigation',{name:'移动端主导航'}).getByRole('button',{name:'首页',exact:true}).click();await page.locator('.unified-start').waitFor();
  failUpload=true;await page.locator('.unified-attach input').setInputFiles({name:'bad.png',mimeType:'image/png',buffer:Buffer.from('bad image')});await page.getByText('图片上传失败，请重试',{exact:true}).waitFor();assert.equal(await page.locator('.unified-submit').isDisabled(),true);
  if(width===320){
   await page.evaluate(()=>{const es=[...document.querySelectorAll('.hero h1,.hero h2,.hero p,.hero button,.hero textarea')];const sizes=es.map(e=>parseFloat(getComputedStyle(e).fontSize)*1.2);es.forEach((e,i)=>e.style.fontSize=sizes[i]+'px')});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
   const a=await page.locator('.unified-tools').boundingBox(),b=await page.locator('.unified-submit').boundingBox();assert.ok(a.x+a.width<=b.x+1);
   await page.screenshot({path:`${output}/${name}-large-text.png`});
  }
  assert.deepEqual(errors,[]);results.push({name,formHeight:form.height,popularCardBottom:card.y+card.height,navTop:nav.y,toolbar:true,quickStarts:true,requests:true,images:true,links:true});
  console.log(`${name}: passed`);await context.close();
 }
 await fs.writeFile(`${output}/results.json`,JSON.stringify(results,null,2));
}finally{await browser.close();}
