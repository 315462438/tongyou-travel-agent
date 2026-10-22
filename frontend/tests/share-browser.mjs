import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const out=process.env.SHARE_QA_OUTPUT||'/tmp/tongyou-share-browser';await fs.mkdir(out,{recursive:true})
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})
const url=process.env.SHARE_QA_URL||'http://127.0.0.1:4186/travel/',results=[]
const markdown='# 七日轻松旅行\n'+Array.from({length:7},(_,i)=>`## Day ${i+1} · 城市漫步\n| 时间 | 行程安排 | 交通费用 | 备注 |\n| --- | --- | --- | --- |\n`+Array.from({length:6},(_,j)=>`| ${j+9}:00 | 第${i+1}天地点${j+1} | 待定 | 很长的补充说明不挤进简版列 |`).join('\n')).join('\n')+'\n## 旅行贴士\n完整攻略最后一条。'
try{for(const [name,width,dark,motion] of [['light',390,false,'no-preference'],['dark',390,true,'no-preference'],['small-reduced',320,false,'reduce']]){
 const ctx=await browser.newContext({viewport:{width,height:844},colorScheme:dark?'dark':'light',reducedMotion:motion,userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.9.0'})
 await ctx.addInitScript(()=>{localStorage.setItem('travel_token','fixture');window.nativeMessages=[];window.TongyouNative={postMessage:m=>window.nativeMessages.push(JSON.parse(m))}})
 let inviteStatus=404,invites=0,shareCalls=0
 const stops=Array.from({length:7},(_,i)=>Array.from({length:6},(_,j)=>({id:`s${i}-${j}`,day:i+1,order_no:j,name:`第${i+1}天地点${j+1}`,location:'',note:'',start_time:`${j+9}:00`,stay_min:null,transport:'',ticket_price:null,tags:[],nav:null}))).flat()
 const trip={id:'t0',title:'七日轻松旅行',destination:'杭州',days:7,start_date:'2026-10-24',members:[{username:'demo',role:'owner',online:false}],stops,role:'owner',day_titles:{},day_plans:[],ai_status:null,ai_review:''}
 await ctx.route('https://webapi.amap.com/**',r=>r.abort())
 await ctx.route('**/travel/api/**',async r=>{
  const req=r.request(),p=new URL(req.url()).pathname.replace('/travel/api','');let data=[]
  if(p==='/auth/me')data={username:'demo',display_name:'小旅',is_admin:false}
  else if(p==='/trips')data=[trip]
  else if(p==='/trips/t0')data=trip
  else if(p==='/trips/t0/invite'){invites++;await new Promise(res=>setTimeout(res,450));return r.fulfill({status:inviteStatus,contentType:'application/json',body:JSON.stringify(inviteStatus===200?{ok:true}:{detail:'用户不存在，请确认对方已注册'})})}
  else if(p==='/trips/t0/share'){shareCalls++;data=req.method()==='DELETE'?{ok:true}:{short_code:'abcd1234',token:'fixture-token'}}
  else if(p==='/chat/conversations')data=req.method()==='POST'?{conversation_id:'c1'}:[{id:'c1',title:trip.title}]
  else if(p.endsWith('/messages'))data=req.method()==='POST'?{ok:true}:{messages:[{id:'m1',role:'assistant',content:markdown,meta:{sources:[{title:'来源',url:'https://example.com/a'}]}}],running:false}
  else if(p.includes('unread'))data={count:0,unread:0}
  else if(p==='/onboarding')data={trending:[],questions:[]}
  else if(p==='/onboarding/covers')data={covers:{}}
  else if(p.includes('/expenses/summary'))data={count:0,total:0,per_person:[],transfers:[],by_category:{}}
  else if(p.endsWith('/issues'))data={issues:[],ticket_total:0}
  else if(p.includes('day-cities'))data={cities:{},overnight:{}}
  await r.fulfill({contentType:'application/json',body:JSON.stringify(data)})
 })
 const page=await ctx.newPage();page.setDefaultTimeout(12000);page.setDefaultNavigationTimeout(15000);const errors=[];page.on('pageerror',e=>errors.push(e.message))
 await page.goto(url);await page.getByLabel('问 AI',{exact:true}).click();await page.getByRole('button',{name:'找美食'}).click();await page.getByRole('button',{name:'发送',exact:true}).click()
 await page.locator('.guide-export').click();const dialog=page.getByRole('dialog',{name:'分享计划单'});await dialog.waitFor()
 const image=page.getByTestId('guide-share-image');await image.waitFor()
 const verify=async (label,book=false)=>{
  const pixels=await image.evaluate(async img=>{await img.decode();const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;const ctx=c.getContext('2d');ctx.drawImage(img,0,0);const p=ctx.getImageData(0,0,c.width,c.height).data;let ink=0;for(let i=0;i<p.length;i+=16)if(p[i]<160&&p[i+1]<170&&p[i+2]<185)ink++;return {width:c.width,height:c.height,ink:ink/(p.length/16),src:img.src}})
  if(book){assert.ok(pixels.width<=1120&&pixels.width>=560&&pixels.width*pixels.height<=16000000&&pixels.height>pixels.width*3,JSON.stringify(pixels).slice(0,160))}else{assert.equal(pixels.width,1120);assert.ok(pixels.height>1000&&pixels.height<4200,JSON.stringify(pixels).slice(0,160))};assert.ok(pixels.ink>.008,'image contains actual dark text')
  await fs.writeFile(`${out}/${name}-${label}.png`,Buffer.from(pixels.src.split(',')[1],'base64'))
 }
 // 默认是一张旅行手册长图：七天都在一张里，保存走单文件下载。
 assert.equal(await page.getByRole('radio',{name:/旅行手册/}).getAttribute('aria-checked'),'true')
 assert.equal(await page.getByRole('button',{name:'下一张',exact:true}).count(),0)
 await verify('book',true);await page.screenshot({path:`${out}/${name}-book.png`})
 const before=await page.evaluate(()=>window.nativeMessages.length)
 await page.getByRole('button',{name:'保存 / 分享旅行手册'}).click()
 await page.waitForFunction(n=>window.nativeMessages.slice(n).some(m=>m.type==='download'&&m.mime==='image/png'&&/旅行手册\.png$/.test(m.name)),before,{timeout:12000})
 await page.getByRole('radio',{name:'分页卡片'}).click();await image.waitFor()
 await verify('first');await page.screenshot({path:`${out}/${name}-preview.png`})
 let count=1;while(await page.getByRole('button',{name:'下一张',exact:true}).isEnabled()){await page.getByRole('button',{name:'下一张',exact:true}).click();count++}assert.ok(count>1);await verify('last')
 console.log(name+': saving all');await page.getByRole('button',{name:new RegExp(`全部保存 / 分享（${count} 张）`)}).click()
 await page.waitForFunction(n=>window.nativeMessages.some(m=>m.type==='images'&&m.files.length===n&&m.files.every(f=>f.data.startsWith('data:image/png;base64,')&&/_计划单_\d+\.png$/.test(f.name))),count,{timeout:12000})
 await page.getByRole('button',{name:`只存第 ${count} 张`}).click();await page.waitForFunction(()=>window.nativeMessages.some(m=>m.type==='download'&&m.mime==='image/png'),null,{timeout:12000})
 assert.equal(await dialog.getByRole('button',{name:'下载完整文字'}).count(),0,'raw full-text download removed')
 console.log(name+': exports passed');await page.getByLabel('关闭计划单').click();assert.ok(await page.locator('.guide-export').evaluate(e=>e===document.activeElement))
 await page.getByLabel('关闭 AI').click();await page.getByLabel('打开行程 七日轻松旅行').click();await page.getByLabel('行程更多操作').click();await page.getByRole('button',{name:'成员与邀请',exact:true}).click();await page.getByTestId('trip-invitation-panel').waitFor()
 assert.equal(shareCalls,0,'opening invitation does not create link access')
 assert.equal(await page.locator('.android-trip-sheet').evaluate(e=>getComputedStyle(e).animationName),motion==='reduce'?'none':'android-sheet-in')
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))
 const ticket=page.getByTestId('trip-invite-ticket'),box=await ticket.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+50);await page.mouse.down();await page.mouse.move(box.x+box.width/2+45,box.y+50,{steps:4})
 assert.equal(await ticket.evaluate(e=>getComputedStyle(e).transform==='none'),motion==='reduce');await page.mouse.up()
 const field=page.getByPlaceholder('对方的用户名');await field.fill('missing');await page.getByLabel('发送邀请',{exact:true}).click();await page.getByRole('alert').filter({hasText:'用户不存在'}).waitFor();assert.equal(await field.inputValue(),'missing')
 inviteStatus=200;await field.fill('  friend  ');await page.getByLabel('发送邀请',{exact:true}).click();assert.ok(await page.getByLabel('发送邀请',{exact:true}).isDisabled());await page.getByRole('status').filter({hasText:'已邀请 friend'}).waitFor();assert.equal(await field.inputValue(),'');assert.equal(invites,2)
 await page.getByRole('button',{name:'分享给朋友'}).click();await page.waitForFunction(()=>window.nativeMessages.some(m=>m.type==='share'&&m.text.includes('https://17tongyou.com/t/abcd1234')),null,{timeout:12000})
 page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'关闭链接邀请',exact:true}).click();await page.getByRole('status').filter({hasText:'邀请链接已关闭'}).waitFor()
 await page.locator('.android-trip-sheet').evaluate(e=>e.scrollTop=0);await page.screenshot({path:`${out}/${name}-invitation.png`})
 await page.getByLabel('关闭行程操作').click();await page.getByTestId('trip-invitation-panel').waitFor({state:'hidden'})
 await page.getByLabel('行程更多操作').click();await page.getByRole('button',{name:'导出攻略',exact:true}).click();await page.getByRole('button',{name:'📸 长图',exact:true}).click();await page.getByRole('dialog',{name:'分享计划单'}).waitFor();await image.waitFor();await verify('trip-plan',true)
 assert.deepEqual(errors,[]);results.push({name,passed:true,pages:count,renderNonblank:true,completeText:true,inviteErrorPreservesInput:true,inviteSuccess:true,motion});console.log(name+': passed');await ctx.close()
}await fs.writeFile(out+'/results.json',JSON.stringify(results,null,2))}finally{await browser.close()}
