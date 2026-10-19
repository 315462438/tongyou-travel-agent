// Local preview only. All business APIs are mocked; no real ledger is created.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output=process.env.LEDGER_QA_OUTPUT || '/tmp/tongyou-ledger-qa';await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined)});
try {
for(const [name,width,height,mobile] of [['desktop',1440,1000,false],['phone',390,844,true]]) {
 const ctx=await browser.newContext({viewport:{width,height},isMobile:mobile,reducedMotion:'reduce'});
 await ctx.addInitScript(m=>{localStorage.setItem('travel_token','qa-only');localStorage.setItem('travel_layout_mode',m?'mobile':'desktop')},mobile);
 let book=null,entries=[],failSave=true;const sentIDs=[],calls=[];let trips=[{id:'owned',title:'我的杭州行程',role:'owner',days:2,destination:'杭州'},{id:'invited',title:'朋友的旅行',role:'editor',days:3,destination:'上海'}];
 const summary=()=>{
  const totals={},cats={};for(const e of entries){totals[e.currency]=(totals[e.currency]||0)+e.amount_minor;const k=e.currency+'|'+e.category;cats[k]=(cats[k]||0)+e.amount_minor}
  return {...book,count:entries.length,totals,by_category:Object.entries(cats).map(([k,amount_minor])=>({currency:k.split('|')[0],category:k.split('|')[1],amount_minor})),entries};
 };
 await ctx.route('**/travel/api/**',async route=>{
  const r=route.request(),url=new URL(r.url()),path=url.pathname.replace('/travel/api',''),method=r.method();calls.push([method,path,url.search]);
  const body=method==='GET'?null:r.postDataJSON();let data=[];
  if(path==='/auth/me')data={username:'demo',is_admin:false};
  else if(path==='/onboarding')data={destinations:[],questions:[]};
  else if(path.includes('unread'))data={count:0};
  else if(path==='/ledger'&&method==='POST'){book={id:'b1',title:body.title,target_currency:'CNY',role:'owner',trip:trips.find(t=>t.id===body.trip_id)||null};data=summary()}
  else if(path==='/ledger')data=book?[summary()]:[];
  else if(path==='/ledger/b1'&&method==='DELETE'){book=null;entries=[];data={ok:true}}
  else if(path==='/ledger/b1'&&method==='PATCH'){book.title=body.title;book.trip=trips.find(t=>t.id===body.trip_id)||null;data={ok:true}}
  else if(path==='/ledger/b1')data=summary();
  else if(path==='/ledger/b1/currency'){book.target_currency=body.target_currency;data={ok:true}}
  else if(path==='/ledger/b1/conversion'){
   const totals=summary().totals,target=book.target_currency,items=Object.entries(totals).map(([currency,n])=>{const rate=currency===target?1:target==='CNY'?1.6:0.2;return {currency,rate:String(rate),rate_date:'2026-10-19',converted_minor:Math.round(n*rate)}});
   data={target_currency:target,total_minor:items.reduce((s,i)=>s+i.converted_minor,0),items,missing:[],stale:false,source:'Frankfurter',fetched_at:'2026-10-19T05:00:00Z'};
  } else if(path==='/ledger/b1/entries'&&method==='POST'){
   sentIDs.push(body.id);
   if(failSave){failSave=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'网络暂时不可用，请重试'})})}
   const entry={...body,version:1,id:body.id.replaceAll('-',''),amount_minor:Math.round(Number(body.amount)*100)};entries.push(entry);data=entry;
  } else if(path.startsWith('/ledger/b1/entries/')){
   const id=path.split('/').pop();
   if(method==='DELETE')entries=entries.filter(e=>e.id!==id);
   else entries=entries.map(e=>e.id===id?{...e,...body,id,amount_minor:Math.round(Number(body.amount)*100)}:e);
   data={ok:true};
  } else if(path==='/trips/owned'&&method==='GET')data={...trips[0],updated_at:'2026-10-19T12:00:00Z',stops:[],members:[{username:'demo',role:'owner'}],day_titles:{},day_plans:[],budget_breakdown:{},hotel_recommendations:[]};
  else if(path==='/trips/owned/issues')data={issues:[],ticket_total:0};
  else if(path.endsWith('/day-cities'))data={cities:{},overnight:{}};
  else if(path==='/trips')data=trips;
  else if(method==='DELETE'&&path==='/trips/owned'){trips=trips.filter(t=>t.id!=='owned');data={ok:true}}
  else if(method==='POST'&&path==='/trips/invited/leave'){trips=trips.filter(t=>t.id!=='invited');data={ok:true}}
  return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await ctx.newPage(),errors=[];page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 await page.goto(process.env.LEDGER_QA_URL||'http://127.0.0.1:4179/travel/');
 if(mobile)await page.getByRole('navigation',{name:'移动端主导航'}).getByRole('button',{name:'记账',exact:true}).click();
 else await page.getByRole('button',{name:'旅行记账',exact:true}).click();
 await page.getByRole('button',{name:'＋ 新建账本'}).click();
 await page.getByLabel('账本名称').fill('马来西亚旅行');await page.getByLabel('关联行程',{exact:true}).selectOption('owned');await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('button',{name:/马来西亚旅行/}).click();
 await page.getByText('关联行程：我的杭州行程',{exact:false}).waitFor();
 await page.getByRole('button',{name:'编辑账本',exact:true}).click();await page.getByLabel('关联行程',{exact:true}).selectOption('invited');await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('关联行程：朋友的旅行',{exact:false}).waitFor();
 await page.getByRole('button',{name:'编辑账本',exact:true}).click();await page.getByLabel('关联行程',{exact:true}).selectOption('');await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('独立账本 · 未关联行程',{exact:false}).waitFor();
 await page.getByRole('button',{name:'＋ 记一笔'}).click();
 await page.getByLabel('金额',{exact:true}).fill('100.01');await page.getByLabel('币种',{exact:true}).selectOption('MYR');await page.getByLabel('花了什么').fill('海鲜晚餐');
 await page.getByRole('button',{name:'保存',exact:true}).click();await page.getByRole('alert').filter({hasText:'网络暂时不可用'}).waitFor();
 assert.equal(await page.getByLabel('金额',{exact:true}).inputValue(),'100.01');
 await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.locator('.ledger-total h2').filter({hasText:'CNY 160.02'}).waitFor();assert.equal(sentIDs[0],sentIDs[1]);assert.equal(entries.length,1);
 await page.getByRole('button',{name:'编辑账单 海鲜晚餐',exact:true}).click();await page.getByLabel('金额',{exact:true}).fill('120.50');await page.getByRole('button',{name:'保存',exact:true}).click();
 await page.locator('.ledger-total h2').filter({hasText:'CNY 192.80'}).waitFor();
 await page.getByLabel('汇总币种',{exact:true}).selectOption('USD');await page.locator('.ledger-total h2').filter({hasText:'USD 24.10'}).waitFor();
 await page.getByLabel('汇总币种',{exact:true}).selectOption('CNY');await page.locator('.ledger-total h2').filter({hasText:'CNY 192.80'}).waitFor();
 await page.getByRole('button',{name:'刷新汇率',exact:true}).click();await page.locator('.ledger-total h2').filter({hasText:'CNY 192.80'}).waitFor();
 assert.ok(calls.some(c=>c[1].endsWith('/conversion')&&c[2]==='?refresh=true'));
 await page.screenshot({path:`${output}/${name}.png`,fullPage:true});
 assert.equal(await page.locator('.ledger-shell').evaluate(el=>el.scrollWidth>el.clientWidth+1),false);
 await page.getByRole('button',{name:'删除账单 海鲜晚餐',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();assert.equal(entries.length,1);
 await page.getByRole('button',{name:'删除账单 海鲜晚餐',exact:true}).click();await page.getByRole('button',{name:'确认删除',exact:true}).click();await page.getByText('还没有账单，先记下今天的第一笔花费吧。').waitFor();
 await page.getByRole('button',{name:'删除账本',exact:true}).click();await page.getByRole('button',{name:'确认删除',exact:true}).click();await page.getByText('还没有账本，为下一趟旅行建一个吧。').waitFor();
 await page.getByRole('button',{name:'关闭旅行记账'}).click();
 if(mobile)await page.getByRole('navigation',{name:'移动端主导航'}).getByRole('button',{name:'行程',exact:true}).click();else await page.getByRole('button',{name:'协同行程',exact:true}).click();
 await page.locator('.trips-overlay').waitFor();
 await page.screenshot({path:`${output}/${name}-trips.png`,fullPage:true});
 await page.locator('.trip-card').filter({hasText:'我的杭州行程'}).click();await page.getByRole('button',{name:'旅行账本',exact:true}).click();await page.getByRole('button',{name:'＋ 新建账本'}).click();assert.equal(await page.getByLabel('关联行程',{exact:true}).inputValue(),'owned');await page.getByRole('button',{name:'取消',exact:true}).click();await page.goto((process.env.LEDGER_QA_URL||'http://127.0.0.1:4179/travel/')+'#trips');await page.reload();
 await page.getByRole('button',{name:'删除行程 我的杭州行程',exact:true}).click();await page.getByText('我的杭州行程',{exact:true}).waitFor({state:'hidden'});
 await page.getByRole('button',{name:'退出行程 朋友的旅行',exact:true}).click();await page.getByText('朋友的旅行',{exact:true}).waitFor({state:'hidden'});
 assert.deepEqual(trips,[]);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({name,errors,entryCRUD:true,failedSaveRetained:true,retrySameID:true,currencyConversion:true,deleteAndLeave:true,overflow:false}));
 await ctx.close();
}
}finally{await browser.close()}
