import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'})
const out=process.env.AI_QA_OUTPUT || '/tmp/tongyou-ai-contrast'
await fs.mkdir(out,{recursive:true})
const results=[]
try {
 for(const [name,width,height,android] of [['desktop',1559,900,false],['mobile',390,844,false],['android',390,844,true]]) {
  const ctx=await browser.newContext({viewport:{width,height},colorScheme:'light',reducedMotion:'reduce',...(android?{userAgent:'Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 17TongyouAndroid/0.8.2'}:{})})
  await ctx.addInitScript(android=>{localStorage.setItem('travel_token','fixture');if(android)window.TongyouNative={postMessage:()=>{}}},android)
  await ctx.route('**/travel/api/**',route=>{
   const p=new URL(route.request().url()).pathname
   let data=[]
   if(p.endsWith('/auth/me'))data={username:'demo',is_admin:false}
   else if(p.includes('unread'))data={count:0,unread:0}
   else if(p.endsWith('/onboarding'))data={trending:[],questions:[]}
   else if(p.endsWith('/covers'))data={covers:{}}
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)})
  })
  const page=await ctx.newPage()
  await page.goto(process.env.AI_QA_URL || 'http://127.0.0.1:4185/travel/')
  await page.getByLabel('问 AI',{exact:true}).click()
  const prompt=page.getByRole('textbox',{name:'旅行需求',exact:true})
  await prompt.fill('杭州两天，想看西湖')
  const geometry=await prompt.boundingBox()
  for(const theme of ['light','dark','light']) {
   await page.emulateMedia({colorScheme:theme})
   if(android)await page.evaluate(theme=>document.documentElement.dataset.androidAppearance=theme,theme)
   assert.equal(await page.locator('.inspiration-launchpad.simple').evaluate(e=>getComputedStyle(e).backgroundImage),'none','input card must not retain a light glass gradient')
   const checks=await page.evaluate(()=>{
    const canvas=document.createElement('canvas'),context=canvas.getContext('2d')
    const rgb=s=>{context.clearRect(0,0,1,1);context.fillStyle=s;context.fillRect(0,0,1,1);const p=[...context.getImageData(0,0,1,1).data];return [...p.slice(0,3),p[3]/255]}
    const over=(a,b)=>a.slice(0,3).map((v,i)=>v*a[3]+b[i]*(1-a[3])).concat(1)
    const lum=c=>c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0)
    const selectors=['.hero-title','.hero-eyebrow','.hero-sub','.unified-idea > span','.unified-idea textarea','.unified-attach-btn','.unified-attach small','.unified-tools button','.inspiration-status','.journey-ai-tasks button','.journey-ai-header button']
    const values=[]
    for(const selector of selectors)for(const e of document.querySelectorAll('.ai-workspace '+selector)) {
     if(!e.getClientRects().length)continue
     const chain=[];for(let n=e;n;n=n.parentElement)chain.unshift(n)
     let bg=[255,255,255,1]
     for(const n of chain)bg=over(rgb(getComputedStyle(n).backgroundColor),bg)
     for(const pseudo of e.matches('textarea')?[null,'::placeholder']:[null]) {
      const s=getComputedStyle(e,pseudo),fg=rgb(s.webkitTextFillColor || s.color)
      fg[3]*=Number(s.opacity)
      const painted=over(fg,bg),a=lum(painted),b=lum(bg)
      values.push({selector:selector+(pseudo||''),text:e.textContent?.slice(0,25),ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05),fill:s.webkitTextFillColor,color:s.color,bg})
     }
    }
    return values
   })
   for(const check of checks)assert.ok(check.ratio >= (check.selector==='.hero-title'?3:4.5),`${name}/${theme}: ${JSON.stringify(check)}`)
   assert.equal(await prompt.inputValue(),'杭州两天，想看西湖')
   assert.deepEqual(await prompt.boundingBox(),geometry,'theme change preserves layout')
   await page.screenshot({path:`${out}/${name}-${theme}.png`})
   results.push({name,theme,checks})
  }
  console.log(`${name}: contrast, theme switch, layout and draft passed`)
  await ctx.close()
 }
 await fs.writeFile(`${out}/results.json`,JSON.stringify(results,null,2))
} finally {await browser.close()}
