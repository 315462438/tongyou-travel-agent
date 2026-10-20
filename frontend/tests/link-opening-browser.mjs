import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const base=process.env.LINK_QA_URL || 'http://127.0.0.1:4181/travel/';
const token='a'.repeat(43), results=[];
try {
 for(const [name,ua,show] of [
  ['iPhone Safari','Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 Version/26.0 Mobile Safari/604.1',true],
  ['iPhone WeChat','Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 Mobile MicroMessenger/8.0',false],
  ['Android browser','Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36',false],
  ['Desktop','Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36',false]
 ]) {
  const ctx=await browser.newContext({userAgent:ua,viewport:{width:390,height:844}});
  const writes=[];
  const mock=r=>{
   if(r.request().method()!=='GET')writes.push(r.request().url());
   return r.fulfill({contentType:'application/json',body:JSON.stringify({title:'跨端分享账本',role:'viewer',inviter:'朋友',expires_at:'2026-12-01T00:00:00Z'})});
  };
  await ctx.route('**/travel/api/**',mock);
  if(name.includes('WeChat')) await ctx.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{if(window.denyCopy)throw new Error('denied');window.copiedInvite=text}}}));
  const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'?ledger_join='+token);
  await page.getByRole('heading',{name:'跨端分享账本'}).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('ledger_join'),token);
  const open=page.getByRole('link',{name:'在 App 中打开'});
  assert.equal(await open.count(),show?1:0);
  await page.getByRole('button',{name:'登录或注册后加入'}).waitFor();
  if(show) {
   assert.equal(await open.getAttribute('href'),'tongyou://ledger/join?token='+token);
   {
    // Browser test records the exact handoff URL; OS-level handling is tested with simctl.
    await page.evaluate(()=>document.addEventListener('click',e=>{const a=e.target.closest('a[href^="tongyou:"]');if(a){window.handoff=a.href;e.preventDefault()}},true));
    await open.click();assert.equal(await page.evaluate(()=>window.handoff),'tongyou://ledger/join?token='+token);
    await page.getByRole('status').filter({hasText:'继续使用'}).waitFor();
    await page.screenshot({path:'/tmp/tongyou-ios-link-web.png'});
   }
   assert.equal(await page.getByRole('button',{name:'登录或注册后加入'}).isEnabled(),true);
  }
  if(name.includes('WeChat')) {
   await page.getByText('用 App 打开，请先切换到 Safari',{exact:true}).waitFor();
   await page.getByRole('button',{name:'复制完整邀请链接'}).click();
   await page.getByRole('status').filter({hasText:'链接已复制'}).waitFor();
   assert.equal(await page.evaluate(()=>window.copiedInvite),base+'?ledger_join='+token);
   await page.evaluate(()=>window.denyCopy=true);await page.getByRole('button',{name:'复制完整邀请链接'}).click();
   assert.equal(await page.getByRole('textbox',{name:'完整账本邀请链接'}).inputValue(),base+'?ledger_join='+token);
   await page.screenshot({path:'/tmp/tongyou-wechat-link-guide.png',fullPage:true});
   const fresh=await browser.newContext({userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1'});
   await fresh.route('**/travel/api/**',mock);const safari=await fresh.newPage();await safari.goto(page.url());
   await safari.getByRole('heading',{name:'跨端分享账本'}).waitFor();
   assert.equal(await safari.getByRole('link',{name:'在 App 中打开'}).getAttribute('href'),'tongyou://ledger/join?token='+token);
   await fresh.close();
   await page.getByRole('button',{name:'暂不加入'}).click();
   assert.equal(new URL(page.url()).searchParams.get('ledger_join'),null);
   assert.equal(await page.evaluate(()=>localStorage.getItem('travel_pending_ledger_join')),null);
   // Old pages already stripped the URL; restore the pending token for browser handoff.
   await page.evaluate(t=>localStorage.setItem('travel_pending_ledger_join',t),token);
   await page.goto(base);await page.getByRole('heading',{name:'跨端分享账本'}).waitFor();
   assert.equal(new URL(page.url()).searchParams.get('ledger_join'),token);
   results.push('WeChat: explicit guidance, copy/fallback, isolated Safari handoff, cancel cleanup, legacy pending URL restoration');
  }
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  results.push(name+': same HTTPS invitation, no automatic join, correct platform fallback');
  await ctx.close();
 }
 await fs.writeFile('/tmp/tongyou-link-opening-results.json',JSON.stringify({passed:results.length,results},null,2));
 console.log(JSON.stringify({passed:results.length,results},null,2));
} finally {await browser.close()}
