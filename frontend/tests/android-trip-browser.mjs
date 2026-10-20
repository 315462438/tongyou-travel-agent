// Run against the local preview only; every business API is mocked.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const output=process.env.WORKSPACE_QA_OUTPUT || '/tmp/tongyou-trip-workspace-qa';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined),args:['--no-sandbox']});
const stops=[
 {id:'s1',day:1,order_no:0,name:'西湖 · 断桥残雪',note:'沿白堤慢慢走，给湖边散步留一点时间。不赶景点，也是一种旅行。',location:'120.15,30.25',start_time:'09:00',stay_min:90,transport:'步行',ticket_price:null,tags:[],nav:{amap:'https://uri.amap.com',apple:'https://maps.apple.com',domestic:true}},
 {id:'s2',day:1,order_no:1,name:'浙江省博物馆',note:'预约后入馆，雨天也可以安心安排。',location:'120.16,30.26',start_time:'11:00',stay_min:120,transport:'公交',ticket_price:0,tags:[],nav:null},
 {id:'s3',day:1,order_no:2,name:'河坊街晚餐',note:'晚餐和自由活动时间，按大家的体力灵活调整。',location:null,start_time:'17:30',stay_min:60,transport:'地铁',ticket_price:80,tags:[],nav:null},
 {id:'s4',day:2,order_no:0,name:'灵隐寺',note:'提前预约，早点出发。',location:'120.1,30.2',start_time:'08:00',stay_min:120,transport:'打车',ticket_price:45,tags:[],nav:null},
];
const template={id:'demo-trip',title:'杭州三日 · 把时间留给山水',destination:'杭州',days:3,budget:1800,budget_breakdown:{住宿:900},start_date:'2026-10-24',source_conversation_id:'qa-conv',ai_status:null,ai_review:'',updated_at:'2026-10-19T10:00:00Z',members:[{username:'demo',role:'owner',online:true,editing_day:1},{username:'同伴',role:'editor',online:false}],stops,day_titles:{'1':'湖畔漫步与老城烟火','2':'山林与寺院','3':'自由探索'},day_plans:[{day:1,type:'stay',overnight_required:true,overnight_city:'杭州'}],hotel_recommendations:[]};
const requests=[];
for(const [name,width,height,mobile] of [['android-320',320,740,true],['android-390',390,844,true],['android-430',430,932,true],['android-landscape',844,390,true]]) {
 if(process.env.LAYOUT_CASE && process.env.LAYOUT_CASE!==name)continue;
 const trip=structuredClone(template);
 const context=await browser.newContext({viewport:{width,height},colorScheme:process.env.ANDROID_COLOR_SCHEME || 'light',isMobile:mobile,userAgent:"Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.2.1",deviceScaleFactor:1,reducedMotion:"reduce"});
 await context.route('https://webapi.amap.com/**',route=>route.abort());
 await context.addInitScript(mobile=>{window.TongyouNative={postMessage:()=>{}};localStorage.setItem('travel_token','qa-only');localStorage.setItem('travel_layout_mode',mobile?'mobile':'desktop');},mobile);
 await context.route('**/travel/api/**',async route=>{
  const url=new URL(route.request().url());const path=url.pathname.replace('/travel/api','');
  if(route.request().method()!=='GET') requests.push({method:route.request().method(),path:url.pathname+url.search});
  let data=[];
  if(path==='/auth/me')data={username:'demo',is_admin:false,display_name:'旅行者'};
  else if(path==='/trips/demo-trip'){
   if(route.request().method()==='PATCH')Object.assign(trip,route.request().postDataJSON(),{updated_at:String(Date.now())});
   data=trip;
  }
  else if(path==='/trips/demo-trip/stops/reorder'){const b=route.request().postDataJSON();for(const x of trip.stops)if(x.day===b.day)x.order_no=b.ordered_ids.indexOf(x.id);data={ok:true};}
  else if(path==='/trips/demo-trip/stops'){trip.stops.push({id:'added',day:1,order_no:99,...route.request().postDataJSON()});trip.updated_at=String(Date.now());data=trip;}
  else if(path.startsWith('/trips/demo-trip/stops/')){const id=path.split('/').at(-1);if(route.request().method()==='DELETE')trip.stops=trip.stops.filter(x=>x.id!==id);else Object.assign(trip.stops.find(x=>x.id===id),route.request().postDataJSON());trip.updated_at=String(Date.now());data=trip;}
  else if(path==='/trips')data=[trip];
  else if(path==='/trips/demo-trip/share')data={short_code:'testcode'};
  else if(path==='/trips/demo-trip/source-guide')data={title:trip.title,content:'## 原攻略\n这是导入的路线',sources:[],can_open_conversation:false};
  else if(path==='/trips/demo-trip/issues')data={issues:[],ticket_total:125};
  else if(path.includes('expenses/summary'))data={total:0,count:0,by_category:{},per_person:[],transfers:[],text:''};
  else if(path.includes('unread'))data={count:0};
  else if(path==='/onboarding')data={destinations:[],questions:[]};
  else if(path.includes('day-cities'))data={cities:{},overnight:{}};
  else if(path.includes('ai/order'))data={ok:true,km_before:8,km_after:6,unlocated:[]};
  else if(path.includes('staticmap'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><rect width="600" height="600" fill="#edf3ee"/><path d="M0 200L600 450M200 0L450 600M0 450L600 200" stroke="#fff" stroke-width="28"/><ellipse cx="210" cy="280" rx="100" ry="150" fill="#cddfe9"/><path d="M250 150L400 350" stroke="#2563eb" stroke-width="5"/><circle cx="250" cy="150" r="15" fill="#2563eb"/><circle cx="400" cy="350" r="15" fill="#2563eb"/></svg>'});
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });

 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto((process.env.WORKSPACE_QA_URL || 'http://127.0.0.1:4181/travel/')+'#trips=demo-trip');
 await page.locator('.android-trip-stop').first().waitFor();
 assert.equal(await page.locator('.trips-head').isVisible(),false);
 assert.equal(await page.locator('.mobile-bottom-nav').isVisible(),false);
 assert.equal(await page.getByRole('button',{name:'行程群聊'}).locator('svg').isVisible(),true);
 assert.equal(await page.locator('.trip-col-timeline').evaluate(e=>getComputedStyle(e).overflowY),'visible');
 for(const [selector,max] of Object.entries({'.android-trip-intro h1':18,'.android-trip-day-title h2':16,'.android-trip-stop h3':14,'.android-trip-note':13})){
  const styles=await page.locator(selector).first().evaluate(e=>({size:parseFloat(getComputedStyle(e).fontSize),weight:parseInt(getComputedStyle(e).fontWeight)}));
  assert.ok(styles.size<=max&&styles.weight<=600,`${selector} ${JSON.stringify(styles)}`);
 }
 const bounds=await page.locator('.android-trip-stop').first().boundingBox();
 if(width===390)assert.ok(bounds.y<500,'compact overview must leave more room for stops');
 if(height>700&&width>=390)assert.ok(bounds.y+bounds.height<height,'first complete stop must fit the first screen');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 if(process.env.ANDROID_COLOR_SCHEME==='dark'){assert.equal(await page.locator('.android-trip-intro h1').evaluate(e=>getComputedStyle(e).color),'rgb(240, 242, 247)');assert.equal(await page.locator('.android-trip-board').evaluate(e=>getComputedStyle(e).backgroundColor),'rgba(0, 0, 0, 0)');assert.ok(await page.locator('.trips-overlay').evaluate(e=>getComputedStyle(e).backgroundImage.includes('23, 44, 88')));}
 await page.screenshot({path:`${output}/${name}.png`});
 await page.getByRole('tab',{name:'路线地图',exact:true}).click();assert.ok(await page.locator('.trip-col-map').isVisible());
 await page.getByRole('tab',{name:'Day 2',exact:false}).click();assert.ok(await page.locator('.trip-col-map').isVisible());
 await page.getByRole('tab',{name:'当天行程',exact:true}).click();await page.getByRole('heading',{name:'灵隐寺'}).waitFor();
 await page.getByRole('tab',{name:'Day 3',exact:false}).click();await page.getByText('这一天还没有安排').waitFor();
 await page.getByRole('tab',{name:'Day 1',exact:false}).click();
 await page.locator('.trip-date-chip').click();await page.getByLabel('出发日期',{exact:true}).fill('2026-10-25');await page.getByRole('dialog',{name:'设置出发日期'}).getByRole('button',{name:'保存',exact:true}).click();assert.equal(trip.start_date,'2026-10-25');
 await page.getByRole('button',{name:'修改当天标题',exact:true}).click();
 await page.getByLabel('当天标题',{exact:true}).fill('自由漫步');await page.getByRole('dialog').getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('heading',{name:'自由漫步',exact:true}).waitFor();
 await page.getByRole('button',{name:'添加地点',exact:false}).first().click();
 await page.getByPlaceholder('如：双子塔夜景').fill('湖边咖啡');await page.locator('.trip-edit-footer').getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('heading',{name:'湖边咖啡',exact:true}).waitFor();
 await page.getByRole('button',{name:'编辑 湖边咖啡',exact:true}).click();
 assert.equal(await page.locator('.trip-edit-modal').evaluate(e=>e.scrollWidth>e.clientWidth+2),false);
 if(process.env.ANDROID_COLOR_SCHEME==='dark'){assert.equal(await page.locator('.trip-edit-modal').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(27, 32, 49)');await page.screenshot({path:`${output}/${name}-edit.png`});}
 await page.getByPlaceholder('如：双子塔（KLCC）').fill('湖边茶室');await page.locator('.trip-edit-footer').getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('heading',{name:'湖边茶室',exact:true}).waitFor();
 await page.getByLabel('更多操作 湖边茶室',{exact:true}).click();await page.getByRole('button',{name:'上移 湖边茶室'}).click();
 assert.ok(requests.some(r=>r.path.endsWith('/stops/reorder')));
 await page.getByLabel('更多操作 湖边茶室',{exact:true}).click();await page.getByRole('button',{name:'删除 湖边茶室',exact:true}).click();
 await page.getByRole('button',{name:'删除地点',exact:true}).click();await page.getByRole('heading',{name:'湖边茶室',exact:true}).waitFor({state:'hidden'});
 await page.getByRole('button',{name:'行程更多操作'}).click();await page.getByRole('dialog',{name:'行程操作',exact:true}).getByRole('button',{name:'导出攻略',exact:true}).click();
 await page.getByRole('checkbox',{name:'AI 润色'}).waitFor();
 await page.evaluate(()=>window.tongyouAndroidBack());await page.getByRole('dialog').waitFor({state:'hidden'});
 await page.getByRole('button',{name:'查看同行成员'}).click();await page.getByPlaceholder('输入用户名',{exact:true}).waitFor();
 await page.getByRole('button',{name:'🔗 分享',exact:true}).click();await page.getByRole('button',{name:'分享给朋友',exact:true}).click();
 await page.evaluate(()=>window.tongyouAndroidBack());await page.locator('.share-mask').waitFor({state:'hidden'});assert.ok(await page.getByRole('dialog',{name:'成员与邀请'}).isVisible());
 await page.getByRole('button',{name:'查看原攻略',exact:false}).click();await page.getByText('这是导入的路线').waitFor();await page.getByRole('button',{name:'关闭原攻略'}).click();
 await page.evaluate(()=>window.tongyouAndroidBack());await page.getByRole('dialog').waitFor({state:'hidden'});
 await page.getByRole('button',{name:'AI 调整',exact:false}).click();assert.ok(await page.locator('.trip-col-ai').isVisible());
 await page.getByLabel('选择工具',{exact:true}).selectOption('tips');await page.screenshot({path:`${output}/${name}-tools.png`});
 await page.evaluate(()=>window.tongyouAndroidBack());await page.getByRole('tab',{name:'当天行程',exact:true}).waitFor();
 // Stress fixture: real polling response, 30 days, long titles and import progress.
 trip.days=30;trip.title='南京出发 · 吉隆坡、仙本那、亚庇和海岛漫游的超长协同行程标题';trip.ai_status='locating';trip.updated_at=String(Date.now());
 await page.getByRole('tab',{name:'Day 30',exact:false}).waitFor();await page.getByRole('tab',{name:'Day 30',exact:false}).click();
 assert.equal(await page.getByRole('tab',{name:'Day 30',exact:false}).getAttribute('aria-selected'),'true');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.evaluate(()=>{const els=[...document.querySelectorAll('.android-trip-board h1,.android-trip-board h2,.android-trip-board h3,.android-trip-board p,.android-trip-board button,.android-trip-board small')];const sizes=els.map(e=>parseFloat(getComputedStyle(e).fontSize)*1.2);els.forEach((e,i)=>e.style.fontSize=sizes[i]+'px')});
 await page.getByRole('button',{name:'行程更多操作'}).click();const sheet=page.getByRole('dialog');
 assert.equal(await sheet.evaluate(e=>e.scrollWidth>e.clientWidth+2),false);await page.screenshot({path:`${output}/${name}-large-type.png`});
 await page.evaluate(()=>window.tongyouAndroidBack());await page.evaluate(()=>document.body.style.zoom='');
 trip.ai_status='failed';trip.ai_review='部分日期导入失败';trip.members[0].role='editor';trip.updated_at=String(Date.now());
 await page.getByRole('button',{name:'继续重试'}).waitFor();
 await page.getByRole('button',{name:'查看同行成员'}).click();assert.equal(await page.getByPlaceholder('输入用户名',{exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'🔗 分享',exact:true}).count(),0);
 await page.evaluate(()=>window.tongyouAndroidBack());
 await page.getByRole('button',{name:'返回行程列表'}).click();await page.locator('.trip-list-page').waitFor();assert.ok(await page.locator('.mobile-bottom-nav').isVisible());
 assert.deepEqual(errors,[]);console.log(JSON.stringify({name,firstStop:bounds,layout:true,CRUD:true,map:true,tools:true,sheets:true,nativeBack:true,longTrip:true,errors}));
 await context.close();
}
await fs.writeFile(`${output}/requests.json`,JSON.stringify(requests,null,2));await browser.close();
