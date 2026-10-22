// 按压反馈真机行为：波纹出现且不改按钮自身样式、松手恢复、disabled/reduced-motion 不触发、安卓 App 只对切换类控件发触感。
// 先在 frontend/ 下启动：npm run dev -- --host 127.0.0.1 --port 4186
import assert from 'node:assert/strict'
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright')
const url=process.env.PRESS_QA_URL||'http://127.0.0.1:4186/travel/'
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})
const android='Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.9.0'
async function open(opts={}){
  const ctx=await browser.newContext({viewport:{width:390,height:844},reducedMotion:opts.reduce?'reduce':'no-preference',...(opts.android?{userAgent:android}:{})})
  await ctx.addInitScript(()=>{window.nativeMessages=[];window.TongyouNative={postMessage:m=>window.nativeMessages.push(JSON.parse(m))}})
  await ctx.route('**/travel/api/**',r=>r.fulfill({status:401,contentType:'application/json',body:'{"detail":"未登录"}'}))
  const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message))
  await page.goto(url);await page.waitForLoadState('networkidle')
  await page.evaluate(()=>{const box=document.createElement('div');box.style.cssText='position:fixed;left:20px;top:20px;z-index:99999;display:flex;gap:8px;flex-wrap:wrap;width:350px'
    box.innerHTML='<button id="plain" style="width:120px;height:44px;border-radius:12px;transform:translateY(3px);color:rgb(37,99,235)">普通<i>图标</i></button><button id="off" disabled style="width:80px;height:44px">禁用</button><button id="tab" role="tab" style="width:80px;height:44px">标签</button><button id="card" style="width:340px;height:140px">大卡片</button>'
    document.body.appendChild(box)})
  return {ctx,page,errors}
}
const center=async(page,sel)=>{const b=await page.locator(sel).boundingBox();return [b.x+b.width/2,b.y+b.height/2]}
const results=[]
try{
  {const {ctx,page,errors}=await open()
   const before=await page.$eval('#plain',el=>({t:getComputedStyle(el).transform,o:getComputedStyle(el).overflow,p:getComputedStyle(el).position,kids:el.childNodes.length}))
   const [x,y]=await center(page,'#plain');await page.mouse.move(x,y);await page.mouse.down()
   await page.waitForTimeout(140)
   const during=await page.evaluate(()=>{const el=document.querySelector('#plain'),host=document.querySelector('.press-ripple-host'),r=el.getBoundingClientRect(),h=host?.getBoundingClientRect()
     return {pressed:el.dataset.pressed,scale:getComputedStyle(el).scale,t:getComputedStyle(el).transform,o:getComputedStyle(el).overflow,p:getComputedStyle(el).position,kids:el.childNodes.length,host:!!host,
       aligned:h?Math.abs(h.left-r.left)<8&&Math.abs(h.top-r.top)<8:false,radius:host?getComputedStyle(host).borderRadius:'',color:host?getComputedStyle(host).color:'',pe:host?getComputedStyle(host).pointerEvents:''}})
   assert.equal(during.pressed,'sm');assert.notEqual(during.scale,'1');assert.equal(during.t,before.t,'existing transform untouched')
   assert.equal(during.o,before.o);assert.equal(during.p,before.p);assert.equal(during.kids,before.kids,'no nodes inserted into the button')
   assert.ok(during.host&&during.aligned,'ripple host sits over the button');assert.equal(during.radius,'12px');assert.equal(during.color,'rgb(37, 99, 235)');assert.equal(during.pe,'none')
   await page.mouse.up();await page.waitForTimeout(50)
   assert.equal(await page.$eval('#plain',el=>el.dataset.pressed??null),null,'released on pointerup')
   await page.waitForTimeout(950);assert.equal(await page.locator('.press-ripple-host').count(),0,'ripple cleans itself up')
   // 按住拖到按钮内的子元素不算离开
   await page.mouse.move(x-30,y);await page.mouse.down();const [ix,iy]=await center(page,'#plain i');await page.mouse.move(ix,iy);await page.mouse.move(x-40,y)
   assert.equal(await page.$eval('#plain',el=>el.dataset.pressed),'sm','child leave does not release');await page.mouse.up()
   const [cx,cy]=await center(page,'#card');await page.mouse.move(cx,cy);await page.mouse.down()
   assert.equal(await page.$eval('#card',el=>el.dataset.pressed),'lg','big cards dip less');await page.mouse.up()
   const [dx,dy]=await center(page,'#off');await page.mouse.move(dx,dy);await page.mouse.down()
   assert.equal(await page.$eval('#off',el=>el.dataset.pressed??null),null,'disabled gets no feedback');await page.mouse.up()
   const [tx,ty]=await center(page,'#tab');await page.mouse.click(tx,ty)
   assert.deepEqual(await page.evaluate(()=>window.nativeMessages),[],'browsers never post haptics')
   assert.equal(await page.evaluate(()=>document.documentElement.classList.contains('ua-android')),false,'desktop keeps full glass')
   assert.deepEqual(errors,[]);results.push('browser: ripple/scale/disabled/large ok');await ctx.close()}
  {const {ctx,page}=await open({reduce:true})
   const [x,y]=await center(page,'#plain');await page.mouse.move(x,y);await page.mouse.down()
   assert.equal(await page.$eval('#plain',el=>el.dataset.pressed??null),null);assert.equal(await page.locator('.press-ripple-host').count(),0)
   await page.mouse.up();results.push('reduced motion: no motion');await ctx.close()}
  {const {ctx,page}=await open({android:true})
   for(const sel of ['#plain','#tab','#card']){const [x,y]=await center(page,sel);await page.mouse.click(x,y)}
   assert.deepEqual(await page.evaluate(()=>window.nativeMessages.filter(m=>m.type==='haptic')),[{type:'haptic',kind:'tick'}],'only the tab ticks')
   const blur=await page.evaluate(()=>{const d=document.createElement('div');d.style.backdropFilter='blur(calc(22px * var(--glass-k, 1)))';document.body.appendChild(d);return {ua:document.documentElement.classList.contains('ua-android'),bf:getComputedStyle(d).backdropFilter,glass:getComputedStyle(document.documentElement).getPropertyValue('--x-glass-blur').trim()}})
   assert.ok(blur.ua);assert.match(blur.bf,/blur\(9\.9px\)/,'Android blur radius scaled down');assert.equal(blur.glass,'11px')
   results.push('android: tab tick only, blur scaled');await ctx.close()}
}finally{await browser.close()}
console.log(results.join('\n'))
