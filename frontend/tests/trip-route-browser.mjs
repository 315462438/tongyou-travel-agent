import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})
const out='/tmp/tongyou-trip-route-qa';await fs.mkdir(out,{recursive:true})
const sdk=`window.mapCalls=[];window.AMap={
 Map:class {constructor(el){this.el=el;el.style.background='linear-gradient(140deg,#d9e6d6,#d6e4ee)';}add(x){if(x.el)this.el.appendChild(x.el)}remove(xs){xs.forEach(x=>x.el?.remove())}setFitView(a,b,p){window.mapCalls.push(['fit',p,a.map(x=>x.__stopId).filter(Boolean)])}setZoomAndCenter(z,p){window.mapCalls.push(['focus',p])}destroy(){this.el.innerHTML=''}},
 Marker:class {constructor(o){this.el=document.createElement('div');this.el.title=o.title;if(typeof o.content==='string')this.el.innerHTML=o.content;else this.el.appendChild(o.content);this.el.style.cssText='margin:30px 15px;border:0;background:transparent;';}on(k,fn){this.el.addEventListener(k,fn)}},
 Polyline:class{},Pixel:class{}
};window.___onAPILoaded();`
const real=process.env.REAL_MAP==='1'
const results=[]
try {for(const [name,w,h,android,dark,fail] of [['android-small',320,780,true,false,false],['android-dark',390,844,true,true,false],['web-mobile',430,932,false,false,false],['desktop',1280,900,false,false,false],['desktop-dark',1280,900,false,true,false],['map-failure',390,844,true,false,true],['landscape',844,390,true,false,false]]) {
 if(process.env.QA_CASE&&process.env.QA_CASE!==name)continue
 const ctx=await browser.newContext({viewport:{width:w,height:h},colorScheme:dark?'dark':'light',reducedMotion:'reduce',...(android?{userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.7.0'}:{})})
 if(process.env.TRIP_QA_DIST)await ctx.route('https://17tongyou.com/travel/**',async r=>{
  const path=new URL(r.request().url()).pathname;
  if(path.includes('/api/'))return r.fallback();
  const relative=path==='/travel/'?'index.html':path.replace('/travel/','');
  if(relative.includes('..'))return r.abort();
  try{const body=await fs.readFile(new URL('../dist/'+relative,import.meta.url));const ext=relative.split('.').pop();await r.fulfill({body,contentType:({html:'text/html',js:'application/javascript',css:'text/css',svg:'image/svg+xml',png:'image/png',webp:'image/webp'})[ext]||'application/octet-stream'})}catch{await r.fallback()}
 })
 await ctx.addInitScript(android=>{localStorage.setItem('travel_token','fixture');if(android)window.TongyouNative={postMessage:()=>{}}},android)
 if(!real)await ctx.route('https://webapi.amap.com/maps**',r=>fail?r.abort():r.fulfill({contentType:'application/javascript',body:sdk}))
 const stops=[{id:'s1',day:1,order_no:0,name:'西湖',location:'120.15,30.25',start_time:'09:00',note:'沿湖慢慢走',stay_min:90},{id:'s2',day:1,order_no:1,name:'午餐待定',location:''},{id:'s3',day:1,order_no:2,name:'灵隐寺',location:'120.1,30.24'},{id:'s4',day:2,order_no:0,name:'河坊街',location:'120.17,30.23'}]
 stops.forEach(s=>{for(const [k,v] of Object.entries({note:'',start_time:'',stay_min:null,transport:'',ticket_price:null,tags:[],nav:null}))if(!(k in s))s[k]=v})
 const trip={start_date:'',budget:null,source_conversation_id:'',ai_status:null,ai_review:'',updated_at:'fixture',id:'t0',title:'杭州的慢周末',destination:'杭州',days:3,role:'owner',members:[{username:'demo',role:'owner'}],stops,day_plans:[],day_titles:{'1':'沿湖慢慢走','2':'老街散步'}}
 let detailsUnavailable=fail;const calls=[]
 await ctx.route('**/travel/api/**',async r=>{const p=new URL(r.request().url()).pathname.replace('/travel/api','');calls.push(p);let data=[]
 if(p==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false}
 else if(p.includes('unread'))data={count:0,unread:0}
 else if(p==='/trips')data=[trip]
 else if(p==='/trips/t0')data=trip
 else if(p.endsWith('/details')&&detailsUnavailable)return r.fulfill({status:503,body:'{}'})
 else if(p.endsWith('/details'))data={status:'ok',description:'沿湖慢慢走',description_source:'行程说明',guide_excerpt:'西湖可以沿湖散步，安排休息。',photos:p.includes('/s2/')?[]:[{url:'/api/img?u='+ (p.includes('/s3/')?'missing':'fixture'),source:'高德地图'}],facts:[{label:'地址',value:'浙江省杭州市',source:'高德地图'}]}
 else if(p==='/img'&&r.request().url().includes('u=missing'))return r.fulfill({status:404,body:''})
 else if(p==='/img')return r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="400" height="300" fill="#b7d9d0"/></svg>'})
 else if(p==='/onboarding')data={trending:['杭州'],questions:[]}
 else if(p==='/onboarding/covers')data={covers:{}}
 else if(p.endsWith('/issues'))data={issues:[],ticket_total:0}
 else if(p.includes('/day-cities'))data={cities:{},overnight:{}}
 else if(p.includes('/expenses/summary'))data={count:0,total:0,by_category:{},per_person:[],transfers:[]}
 else if(p==='/staticmap')return r.abort()
 await r.fulfill({contentType:'application/json',body:JSON.stringify(data)})})
 const page=await ctx.newPage();page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.stack))
 let mapStyleLoaded=false,mapTilesLoaded=false
 if(real)page.on('response',r=>{const u=new URL(r.url()),type=r.headers()['content-type']||'';if(r.ok()&&!type.includes('json')){if(u.pathname.includes('/style/'))mapStyleLoaded=true;if(u.pathname.includes('/tile/'))mapTilesLoaded=true}})

 await page.goto(process.env.TRIP_QA_URL||'http://127.0.0.1:4185/travel/')
 await page.getByLabel('打开行程 杭州的慢周末').click();await page.locator('.trip-route-layout').waitFor().catch(async e=>{await page.screenshot({path:out+'/'+name+'-failure.png'});console.log(errors,await page.locator('body').innerText());throw e})
 const compact=await page.locator('.android-trip-toolbar').isVisible()
 const map=page.getByRole('region',{name:'当天路线地图'})
 await map.waitFor({state:'visible'})
 const first=compact?page.locator('[data-stop-id=s1]'):page.locator('.trip-table-row').first()
 await first.waitFor({state:'visible'})
 assert.equal(await page.getByRole('tab',{name:'路线地图',exact:true}).count(),0)
 await page.screenshot({path:`${out}/${name}-initial.png`,animations:'disabled'});
 if(h>500){const mr=await page.locator('.trip-jsmap,.trip-static-map,.trip-map-empty').first().boundingBox(),fr=await first.boundingBox();assert.ok(fr.y<h-50,`${name}: first place visible ${fr.y}`);assert.ok(mr.y<fr.y-80,`${name}: map above panel`)}
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no horizontal overflow')
 if(compact&&h>500){
  assert.ok(Math.abs((await map.boundingBox()).width-(await page.locator('.trip-jsmap,.trip-static-map').first().boundingBox()).width)<2,'map fills canvas without inner scrollbar')
  const second=await page.locator('[data-stop-id=s2] .trip-stop-summary').boundingBox(),clip=await page.locator('.trip-view-day').boundingBox();assert.ok(second.y<clip.y+clip.height-20,'second summary visible by default')
  assert.equal(await first.locator('time').count(),1);assert.equal(await first.getByText('费用待补充',{exact:true}).count(),0)
  if(!fail&&!real){await page.waitForFunction(()=>window.mapCalls.some(c=>c[0]==='fit'&&c[1][1]>200));const pad=await page.evaluate(()=>window.mapCalls.filter(c=>c[0]==='fit').at(-1)[1]);assert.ok(pad[1]>200&&pad[2]<50&&pad[3]<50,'AMap padding order top bottom left right')}
 }
 if(!fail){await page.locator('.trip-jsmarker').first().waitFor();assert.deepEqual(await page.locator('.trip-jsmarker').allTextContents(),['1','3'],'unlocated stop retains numbering')
  if(compact)await page.getByLabel('查看景点 西湖').click();else await page.locator('.trip-stop-title-button').first().click()
  await page.getByTestId('place-detail').waitFor();await page.getByText('浙江省杭州市',{exact:true}).waitFor();assert.equal(await page.locator('.place-gallery img').count(),1)
  await page.screenshot({path:`${out}/${name}-detail.png`,animations:'disabled'})
  await page.getByLabel('关闭行程操作').click()
  if(!real)await page.waitForFunction(()=>window.mapCalls.some(c=>c[0]==='fit'&&c[2].length===1&&c[2][0]==='s1'))
  if(real)await page.getByRole('button',{name:'全览',exact:true}).click()
  await page.locator('.trip-jsmarker').last().click()
  if(compact)await page.waitForFunction(()=>document.querySelector('[data-stop-id=s3] .trip-stop-focus')?.getAttribute('aria-pressed')==='true').catch(async e=>{await page.screenshot({path:out+'/real-click-failure.png'});console.log(await page.locator('.trip-jsmarker').evaluateAll(es=>es.map(e=>({html:e.parentElement.outerHTML,rect:JSON.stringify(e.getBoundingClientRect())}))));throw e})
  if(compact){await page.locator('[data-stop-id=s3] .trip-stop-thumbnail svg').waitFor();assert.equal(await page.locator('[data-stop-id=s2] .trip-stop-thumbnail img').count(),0)}
  await page.getByRole('button',{name:'全览',exact:true}).click()
  if(compact){assert.equal(await page.locator('.trip-stop-focus[aria-pressed=true]').count(),0);const outer=await map.boundingBox(),inner=await page.locator('.trip-jsmap').boundingBox();assert.ok(Math.abs(outer.x-inner.x)<2,'full view must not shift map horizontally')}
 }else {await page.getByText('地图暂不可交互，可继续编辑行程').waitFor().catch(async e=>{console.log(await map.innerHTML());throw e});assert.ok(await first.isVisible());await page.getByLabel('查看景点 西湖').click();await page.getByRole('button',{name:'重试',exact:true}).waitFor();detailsUnavailable=false;await page.getByRole('button',{name:'重试',exact:true}).click();await page.getByText('浙江省杭州市',{exact:true}).waitFor();await page.getByLabel('关闭行程操作').click()}
 if(real&&compact&&h>500){await page.waitForTimeout(8000);assert.ok(mapStyleLoaded&&mapTilesLoaded,'real map style and vector tiles loaded');await page.waitForFunction(()=>{const panel=document.querySelector('.trip-workspace-scroll').getBoundingClientRect();return [...document.querySelectorAll('.trip-jsmarker')].every(el=>{const r=el.getBoundingClientRect();return r.x>=0&&r.right<=innerWidth&&r.y>52&&r.bottom<panel.y})});await page.screenshot({path:`${out}/real-map.png`,animations:'disabled'})}
 // Capture initial composition with the first item visible.
 if(compact)await page.locator('.trip-workspace-scroll').evaluate(e=>e.scrollTop=0)
 await page.screenshot({path:`${out}/${name}.png`,animations:'disabled'})
 if(compact&&h>500){await page.getByLabel('展开行程面板').click();assert.equal(await page.locator('.trip-workspace-scroll').getAttribute('data-panel-level'),'2');await page.getByLabel('收起行程面板').click();assert.equal(await page.locator('.trip-workspace-scroll').getAttribute('data-panel-level'),'0');await page.getByLabel('展开行程面板').click();const handle=await page.locator('.trip-panel-handle').boundingBox();await page.mouse.move(handle.x+handle.width/2,handle.y+12);await page.mouse.down();await page.mouse.move(handle.x+handle.width/2,handle.y-65,{steps:5});await page.mouse.up();await page.waitForFunction(()=>document.querySelector('.trip-workspace-scroll').dataset.panelLevel==='2');await page.getByLabel('收起行程面板').click();await page.getByLabel('展开行程面板').click()}
 const day=d=>compact?page.locator('.android-trip-days button').nth(d-1):page.locator('.trip-sidebar-days button').nth(d-1)
 await day(2).click();await page.getByText('河坊街',{exact:true}).first().waitFor()
 if(!fail){assert.deepEqual(await page.locator('.trip-jsmarker').allTextContents(),['1'])}
 await day(3).click();assert.ok(await page.getByText(/这一天还没有安排|还没有行程点|这天还没有安排|还没有安排/).count() || await first.count()===0)
 if(compact){await page.getByLabel('行程更多操作').click();await page.getByRole('button',{name:'重新定位地图',exact:true}).waitFor();await page.getByRole('button',{name:'成员与邀请',exact:true}).click();await page.getByText('创建者 · 离线').waitFor();await page.getByLabel('关闭行程操作').click();await day(1).click();await page.getByLabel('编辑 西湖',{exact:true}).click();await page.locator('.trip-edit-modal').waitFor()}
 assert.deepEqual(errors,[]);results.push({name,passed:true});console.log(`${name}: passed`);await ctx.close()
}await fs.writeFile(out+'/results.json',JSON.stringify(results,null,2))}finally{await browser.close()}
