// Test first-run defaults and user overrides through real mocked send requests.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const base=process.env.SEARCH_QA_URL || 'http://127.0.0.1:4179/travel/';
const results=[];
try {
 for(const [name,width,android] of [['desktop',1440,false],['mobile',390,false],['android',390,true]]){
  const context=await browser.newContext({viewport:{width,height:900},isMobile:width<600,reducedMotion:'reduce',
   ...(android?{userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.2.1'}:{})});
  await context.addInitScript(native=>{localStorage.setItem('travel_token','defaults-test');if(native)window.TongyouNative={postMessage:()=>{}}},android);
  const sent=[];
  await context.route('**/travel/api/**',r=>{
   const path=new URL(r.request().url()).pathname.replace('/travel/api','');let data=[];
   if(path==='/auth/me')data={username:'test',is_admin:false};
   else if(path.includes('unread'))data={count:0};
   else if(path==='/onboarding')data={trending:[],questions:[]};
   else if(path==='/chat/conversations'&&r.request().method()==='POST')data={conversation_id:'test-chat'};
   else if(path==='/chat/test-chat/messages'){
    if(r.request().method()==='POST'){sent.push(r.request().postDataJSON());data={ok:true};}
    else data={messages:[],running:false};
   }
   return r.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  const page=await context.newPage();page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const options=page.getByRole('group',{name:'规划选项'});
  const search=options.getByRole('button',{name:'联网搜索',exact:true});
  const deep=options.getByRole('button',{name:'深度推理',exact:true});
  const send=async()=>{const count=sent.length;await page.getByLabel('旅行需求',{exact:true}).fill('今天去杭州怎么玩');await page.locator('.unified-submit').click();await page.waitForResponse(r=>r.url().endsWith('/chat/test-chat/messages')&&r.request().method()==='GET');assert.equal(sent.length,count+1);return sent.at(-1)};
  await page.goto(base);await options.waitFor();
  assert.equal(await search.getAttribute('aria-pressed'),'true');assert.equal(await deep.getAttribute('aria-pressed'),'false');
  const first=await send();assert.equal(first.web_search,true);assert.equal(first.deep_reasoning,false);
  await page.goto(base);await options.waitFor();await search.click();await deep.click();
  await page.reload();await options.waitFor();assert.equal(await search.getAttribute('aria-pressed'),'false');assert.equal(await deep.getAttribute('aria-pressed'),'true');
  const changed=await send();assert.equal(changed.web_search,false);assert.equal(changed.deep_reasoning,true);
  assert.deepEqual(errors,[]);results.push({name,initial:{web_search:true,deep_reasoning:false},explicitChoicePersisted:true,requestFields:true});
  console.log(`${name}: defaults and persisted overrides passed`);await context.close();
 }
 await fs.writeFile(process.env.SEARCH_QA_RESULTS||'/tmp/search-defaults-browser-results.json',JSON.stringify(results,null,2));
}finally{await browser.close()}
