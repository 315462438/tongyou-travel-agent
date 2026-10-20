// Local preview only; all business APIs are mocked.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output=process.env.GLASS_QA_OUTPUT || '/tmp/tongyou-glass-qa';
await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined)});
const luminance=rgb=>rgb.map(v=>v/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[0.2126,0.7152,0.0722][i],0);
try {
 for(const width of [390,1440]){
  const ctx=await browser.newContext({viewport:{width,height:844},isMobile:width===390,reducedMotion:'reduce'});
  await ctx.route('**/travel/api/**',r=>r.fulfill({contentType:'application/json',status:401,body:JSON.stringify({detail:'测试登录错误'})}));
  const page=await ctx.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.GLASS_QA_URL || 'http://127.0.0.1:4179/travel/');
  await page.locator('.auth-card').waitFor();
  await page.waitForFunction(()=>document.querySelector('.auth-mark')?.complete);
  assert.ok(await page.locator('.auth-mark').evaluate(e=>e.naturalWidth>0),'brand SVG must decode');
  const colors=await page.locator('.auth-wordmark,.auth-tagline').evaluateAll(els=>els.map(e=>getComputedStyle(e).color.match(/[\d.]+/g).slice(0,3).map(Number)));
  for(const color of colors)assert.ok((luminance([220,226,242])+0.05)/(luminance(color)+0.05)>=4.5,'brand text must contrast with pale aura');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`${output}/login-${width}.png`});
  await page.getByRole('tab',{name:'注册',exact:true}).click();
  await page.getByPlaceholder('邀请码',{exact:true}).fill('demo');
  await page.getByPlaceholder('用户名',{exact:true}).fill('tester');
  await page.getByPlaceholder('密码（至少 6 位）',{exact:true}).fill('testing-password');
  await page.getByRole('button',{name:'注册并登录',exact:true}).click();
  await page.getByText('测试登录错误',{exact:true}).waitFor();
  await page.screenshot({path:`${output}/register-${width}.png`});
  const cdp=await ctx.newCDPSession(page);
  await cdp.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-transparency',value:'reduce'}]});
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.auth-card')).backdropFilter==='none');
  const styles=await page.evaluate(()=>{
   // Exercise a plain modal as well as the three shared material classes.
   const modal=document.createElement('div');modal.className='modal';document.body.append(modal);
   return {reduced:matchMedia('(prefers-reduced-transparency: reduce)').matches,filters:[...document.querySelectorAll('.glass,.glass-input,.modal')].map(e=>getComputedStyle(e).backdropFilter),background:getComputedStyle(modal).backgroundColor};
  });
  assert.ok(styles.reduced);assert.ok(styles.filters.every(v=>v==='none'));assert.equal(styles.background,'rgba(255, 255, 255, 0.97)');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({width,logoLoaded:true,brandContrast:true,registrationError:true,reducedTransparency:true,overflow:false,errors}));
  await ctx.close();
 }
} finally {await browser.close()}
