// Run against the local preview only; every business API is mocked.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
import fs from 'node:fs/promises';
const output=process.env.WORKSPACE_QA_OUTPUT || '/tmp/tongyou-trip-workspace-qa';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined),args:['--no-sandbox']});
const stops=[
 {id:'s1',day:1,order_no:0,name:'西湖 · 断桥残雪',note:'沿白堤慢慢走，给湖边散步留一点时间。不赶景点，也是一种旅行。',location:'120.15,30.25',start_time:'09:00',stay_min:90,transport:'步行',ticket_price:null,tags:[],nav:{amap:'https://uri.amap.com',apple:'https://maps.apple.com',domestic:true}},
 {id:'s2',day:1,order_no:1,name:'浙江省博物馆',note:'预约后入馆，雨天也可以安心安排。',location:'120.16,30.26',start_time:'11:00',stay_min:120,transport:'公交',ticket_price:0,tags:[],nav:null},
 {id:'s3',day:1,order_no:2,name:'河坊街晚餐',note:'晚餐和自由活动时间，按大家的体力灵活调整。',location:null,start_time:'17:30',stay_min:60,transport:'地铁',ticket_price:80,tags:[],nav:null},
 {id:'s4',day:2,order_no:0,name:'灵隐寺',note:'提前预约，早点出发。',location:'120.1,30.2',start_time:'08:00',stay_min:120,transport:'打车',ticket_price:45,tags:[],nav:null},
];
const trip={id:'demo-trip',title:'杭州三日 · 把时间留给山水',destination:'杭州',days:3,budget:1800,budget_breakdown:{住宿:900},start_date:'2026-10-24',source_conversation_id:'qa-conv',ai_status:null,ai_review:'',updated_at:'2026-10-19T10:00:00Z',members:[{username:'demo',role:'owner',online:true,editing_day:1},{username:'同伴',role:'editor',online:false}],stops,day_titles:{'1':'湖畔漫步与老城烟火','2':'山林与寺院','3':'自由探索'},day_plans:[{day:1,type:'stay',overnight_required:true,overnight_city:'杭州'}],hotel_recommendations:[]};
const requests=[];
for(const [name,width,height,mobile] of [['desktop',1440,1000,false],['phone',390,844,true]]) {
 const context=await browser.newContext({viewport:{width,height},isMobile:mobile,deviceScaleFactor:1,reducedMotion:"reduce"});
 await context.route('https://webapi.amap.com/**',route=>route.abort());
 await context.addInitScript(mobile=>{localStorage.setItem('travel_token','qa-only');localStorage.setItem('travel_layout_mode',mobile?'mobile':'desktop');},mobile);
 await context.route('**/travel/api/**',async route=>{
  const url=new URL(route.request().url());const path=url.pathname.replace('/travel/api','');
  if(route.request().method()!=='GET') requests.push({method:route.request().method(),path:url.pathname+url.search});
  let data=[];
  if(path==='/auth/me')data={username:'demo',is_admin:false,display_name:'旅行者'};
  else if(path==='/trips/demo-trip')data=trip;
  else if(path==='/trips')data=[trip];
  else if(path==='/trips/demo-trip/issues')data={issues:[],ticket_total:125};
  else if(path.includes('expenses/summary'))data={total:0,count:0,by_category:{},per_person:[],transfers:[],text:''};
  else if(path.includes('unread'))data={count:0};
  else if(path==='/onboarding')data={destinations:[],questions:[]};
  else if(path.includes('day-cities'))data={cities:{},overnight:{}};
  else if(path.includes('ai/order'))data={ok:true,km_before:8,km_after:6,unlocated:[]};
  else if(path.includes('staticmap'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><rect width="600" height="600" fill="#edf3ee"/><path d="M0 200L600 450M200 0L450 600M0 450L600 200" stroke="#fff" stroke-width="28"/><ellipse cx="210" cy="280" rx="100" ry="150" fill="#cddfe9"/><path d="M250 150L400 350" stroke="#2563eb" stroke-width="5"/><circle cx="250" cy="150" r="15" fill="#2563eb"/><circle cx="400" cy="350" r="15" fill="#2563eb"/></svg>'});
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto((process.env.WORKSPACE_QA_URL || 'http://127.0.0.1:4179/travel/') + '#trips=demo-trip');
 await page.getByRole('button',{name:'添加地点',exact:false}).first().waitFor();
 await page.screenshot({path:`${output}/${name}.png`,fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
 await page.getByRole('button',{name:'编辑 西湖',exact:false}).click();
 await page.getByText('编辑行程',{exact:true}).waitFor({timeout:3000});
 const editOverflow = await page.locator('.trip-edit-modal').evaluate(el=>el.scrollWidth > el.clientWidth + 2);
 if(editOverflow)throw new Error('Edit drawer has horizontal overflow');
 await page.keyboard.press('Escape');
 await page.locator('summary[aria-label^="更多操作 西湖"]').click();
 await page.getByRole('button',{name:'上移 西湖',exact:false}).waitFor();
 await page.locator('summary[aria-label^="更多操作 西湖"]').click();
 if(mobile){
  await page.getByRole('tab',{name:'旅行工具',exact:true}).click();
  await page.getByLabel('选择工具',{exact:true}).selectOption('tips');
  await page.screenshot({path:`${output}/${name}-tools.png`,fullPage:true});
  await page.getByRole('tab',{name:'地图',exact:false}).first().click();
  const mapVisible=await page.locator('.trip-col-map').isVisible();
  if(!mapVisible)throw new Error('Phone map did not open');
 } else {
  await page.getByRole('button',{name:'整理当天顺序',exact:true}).click();
 }
 if(overflow || errors.length)throw new Error(JSON.stringify({name,overflow,errors}));
 console.log(JSON.stringify({name,overflow,errors,editDrawer:true,moreActions:true}));
 await context.close();
}
await fs.writeFile(`${output}/requests.json`,JSON.stringify(requests,null,2));
await browser.close();
