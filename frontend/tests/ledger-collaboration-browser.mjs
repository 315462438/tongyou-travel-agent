// UI contracts with fake users and APIs; never writes to production.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
console.log('Launching browser');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const base=process.env.LEDGER_QA_URL||'http://127.0.0.1:4179/travel/';
const output='/tmp/tongyou-ledger-collab-qa';await fs.mkdir(output,{recursive:true});
try { for(const mobile of [false,true]) {
 const ctx=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:1000},isMobile:mobile,reducedMotion:'reduce'});
 await ctx.addInitScript(m=>{localStorage.setItem('travel_token','fake');localStorage.setItem('travel_layout_mode',m?'mobile':'desktop')},mobile);
 let signedOut=false;let user='a',member=null,share=null,joins=0,tripJoins=0,invites=0,failInvite=true,joinedRole='viewer';
 const book={id:'b1',title:'马来西亚共享账本',target_currency:'CNY',trip:null,count:1,totals:{MYR:10000},by_category:[],entries:[{id:'e1',title:'同行晚餐',amount_minor:10000,currency:'MYR',category:'餐饮',spent_at:'2026-10-19',note:'',version:1}]};
 const role=()=>user==='a'?'owner':member?.status==='accepted'?member.role:null;
 await ctx.route('**/travel/api/**',async route=>{
  const r=route.request(),url=new URL(r.url()),path=url.pathname.replace('/travel/api',''),method=r.method(),body=method==='GET'?null:r.postDataJSON();let data=[],status=200;
  if(path==='/auth/me'){if(signedOut){status=401;data={detail:'登录后继续'}}else data={username:user==='a'?'alice':'bob',is_admin:false}}
  else if(path==='/auth/login'){signedOut=false;data={token:'fake',username:'bob',is_admin:false}}
  else if(path==='/onboarding')data={destinations:[],questions:[]};
  else if(path.includes('unread'))data={count:0};
  else if(path==='/ledger/invites/pending')data=user==='b'&&member?.status==='pending'?[{id:'b1',title:book.title,inviter:'alice',role:member.role}]:[];
  else if(path.startsWith('/ledger/shared/')){if(share&&path.endsWith(share.token))data={title:book.title,inviter:'alice',role:share.role,expires_at:share.expires_at};else{status=404;data={detail:'分享链接无效、已撤销或已过期'}}}
  else if(path==='/trips/join'){tripJoins++;data={trip_id:'unexpected'}}
  else if(path==='/ledger/join'){joins++;member={id:'b',username:'bob',role:joinedRole,status:'accepted'};data={id:'b1'}}
  else if(path==='/ledger')data=role()?[{...book,role:role()}]:[];
  else if(path==='/ledger/b1')data={...book,role:role()};
  else if(path==='/ledger/b1/conversion')data={target_currency:'CNY',total_minor:16000,items:[],missing:[],stale:false,source:'Frankfurter',fetched_at:''};
  else if(path==='/ledger/b1/members'&&method==='POST'){
   invites++;if(failInvite){failInvite=false;status=503;data={detail:'邀请暂时失败，请重试'}}else{member={id:'b',username:body.username,role:body.role,status:'pending'};data={ok:true}}
  } else if(path==='/ledger/b1/members')data=[{id:'a',username:'alice',role:'owner',status:'accepted'},...(member? [member]:[])];
  else if(path==='/ledger/b1/members/b'){if(method==='DELETE')member=null;else member.role=body.role;data={ok:true}}
  else if(path==='/ledger/b1/share'){
   if(method==='POST')share={token:'t'.repeat(42)+String(invites),role:body.role,expires_at:'2026-10-26T12:00:00Z'};
   if(method==='DELETE')share=null;data=share;
  } else if(path==='/ledger/b1/invites/respond'){member.status=body.accept?'accepted':'declined';data={id:'b1'}}
  else if(path==='/ledger/b1/leave'){member.status='left';data={ok:true}}
  return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
 });
 const page=await ctx.newPage(),errors=[];page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
 async function openLedger(){await page.goto(base);if(mobile)await page.getByRole('navigation',{name:'移动端主导航'}).getByRole('button',{name:'记账',exact:true}).click();else await page.getByRole('button',{name:'旅行记账',exact:true}).click()}
 async function openBook(){await page.getByRole('button',{name:/马来西亚共享账本/}).click();await page.getByRole('button',{name:'成员与分享',exact:true}).waitFor()}
 console.log('Owner UI',mobile);await openLedger();await openBook();await page.getByRole('button',{name:'成员与分享',exact:true}).click();
 console.log('Invite UI',mobile);await page.getByLabel('完整用户名').fill('bob');await page.getByLabel('邀请权限',{exact:true}).selectOption('editor');await page.getByRole('button',{name:'发送邀请',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'邀请暂时失败'}).waitFor();assert.equal(await page.getByLabel('完整用户名').inputValue(),'bob');
 await page.getByRole('button',{name:'发送邀请',exact:true}).click();await page.getByText('待接受邀请',{exact:true}).waitFor();assert.equal(member.role,'editor');
 await page.getByLabel('bob的权限').selectOption('viewer');assert.equal(member.role,'viewer');
 await page.getByRole('button',{name:'生成分享链接',exact:true}).click();await page.getByLabel('分享链接',{exact:true}).waitFor();assert.equal(share.role,'viewer');
 const old=share.token;await page.getByLabel('链接加入权限',{exact:true}).selectOption('editor');await page.getByRole('button',{name:'重新生成链接',exact:true}).click();await page.getByText('当前链接：可编辑',{exact:false}).waitFor();assert.equal(share.role,'editor');
 await page.screenshot({path:`${output}/${mobile?'phone':'desktop'}-members.png`,fullPage:true});
 assert.equal(await page.locator('.ledger-modal').evaluate(e=>e.scrollWidth>e.clientWidth+1),false);
 await page.getByRole('button',{name:'撤销链接',exact:true}).click();await page.getByRole('button',{name:'生成分享链接',exact:true}).waitFor();assert.equal(share,null);
 // User outside every trip accepts an independent ledger invitation.
 console.log('Viewer UI',mobile);user='b';await openLedger();await page.getByRole('button',{name:'接受邀请',exact:true}).click();await page.getByRole('button',{name:'成员与分享',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'＋ 记一笔',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'编辑账单 同行晚餐',exact:true}).count(),0);assert.equal(await page.getByLabel('汇总币种',{exact:true}).isDisabled(),true);
 await page.screenshot({path:`${output}/${mobile?'phone':'desktop'}-viewer.png`,fullPage:true});
 member.role='editor';await openLedger();await openBook();await page.getByRole('button',{name:'＋ 记一笔',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'编辑账本',exact:true}).count(),0);
 await page.getByRole('button',{name:'退出账本',exact:true}).click();await page.getByRole('button',{name:'确认退出',exact:true}).click();await page.getByText('还没有账本，为下一趟旅行建一个吧。').waitFor();assert.equal(member.status,'left');
 // Public link explicitly previews before join and preserves context through login.
 console.log('Link UI',mobile);share={token:old,role:'viewer',expires_at:'2026-10-26T12:00:00Z'};member=null;
 signedOut=true;await page.goto(base+'?ledger_join='+share.token+'&join=unrelated-trip-invite');await page.getByRole('button',{name:'登录或注册后加入'}).waitFor();assert.equal(joins,0);await page.getByRole('button',{name:'登录或注册后加入'}).click();await page.getByPlaceholder('用户名',{exact:true}).fill('bob');await page.locator('input[autocomplete=\"current-password\"]').fill('test-password');await page.getByRole('button',{name:'登机',exact:true}).click();await page.getByRole('button',{name:'确认加入账本'}).waitFor();assert.equal(joins,0);await page.screenshot({path:`${output}/${mobile?'phone':'desktop'}-join.png`,fullPage:true});
 await page.getByRole('button',{name:'确认加入账本'}).click();await page.getByRole('button',{name:'成员与分享',exact:true}).waitFor();assert.equal(joins,1);assert.equal(tripJoins,0);assert.equal(await page.getByRole('button',{name:'＋ 记一笔',exact:true}).count(),0);
 // Removed/invalid link displays error and never sends join.
 share=null;await page.goto(base+'?ledger_join='+old);await page.getByRole('alert').filter({hasText:'分享链接无效'}).waitFor();assert.equal(await page.getByRole('button',{name:'确认加入账本'}).isDisabled(),true);assert.equal(joins,1);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({mobile,ownerManage:true,inviteRetry:true,accept:true,viewerReadOnly:true,editorEntries:true,exit:true,explicitJoin:true,revokedLink:true,errors}));
 await ctx.close();
} } finally {await browser.close()}
