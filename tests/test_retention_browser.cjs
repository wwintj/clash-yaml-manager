/* Actual browser storage and restart; disposable loopback Flask/profile only. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;
assert.equal(new URL(base).hostname,'127.0.0.1');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'clash-retention-browser-'));fs.chmodSync(profile,0o700);
const node='US|Synthetic Private Draft|vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
let context;const errors=[];
async function route(ctx){await ctx.route('**/*',r=>{
 const u=r.request().url();if(u.startsWith(base))return r.continue();
 if(u.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css'))return r.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
 if(u.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'))return r.fulfill({path:process.env.BOOTSTRAP_JS_PATH,contentType:'text/javascript'});
 return r.abort();
});}
async function launch(){context=await chromium.launchPersistentContext(profile,{headless:true,viewport:{width:390,height:844}});context.setDefaultTimeout(10000);context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));await route(context);return context;}
async function signIn(page){await page.bringToFront();await page.goto(base);if(await page.locator('#password').count()){
 await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
}}
(async()=>{
 try{
  await launch();let page=await context.newPage();await signIn(page);
  assert.equal(await page.locator('#keep-draft').isChecked(),false);
  assert((await page.locator('#draft-privacy').textContent()).includes('shared computer'));
  assert.equal(await page.locator('#keep-draft').getAttribute('aria-describedby'),'draft-privacy');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.locator('#batch_nodes').fill(node);
  await page.waitForFunction(()=>document.getElementById('draft-status').textContent==='Draft saved',null,{timeout:10000});
  let record=await page.evaluate(()=>JSON.parse(localStorage.getItem(Drafts.KEY)));
  assert.equal(record.version,1);assert.equal(record.retention_policy,undefined);
  await page.locator('#keep-draft').check();
  record=await page.evaluate(()=>JSON.parse(localStorage.getItem(Drafts.KEY)));
  assert.equal(record.retention_policy,'keep');
  await page.evaluate(()=>{const d=JSON.parse(localStorage.getItem(Drafts.KEY));d.saved_at=Date.now()-Drafts.TTL*3;localStorage.setItem(Drafts.KEY,JSON.stringify(d));});
  await page.reload();assert.equal(await page.locator('#batch_nodes').inputValue(),node);
  assert(await page.locator('#keep-draft').isChecked());
  // Actual Chromium process restart with a private persistent profile.
  await context.close();context=null;await launch();page=await context.newPage();await signIn(page);
  assert.equal(await page.locator('#batch_nodes').inputValue(),node);
  assert(await page.locator('#keep-draft').isChecked());
  // Credentials/CSRF/file bytes are excluded even with permanent opt-in.
  await page.locator('#yaml-source').selectOption('custom');
  await page.locator('[name=yaml_file]').setInputFiles({name:'synthetic.yaml',mimeType:'application/yaml',buffer:Buffer.from('PRIVATE_FILE_BYTES')});
  await page.evaluate(()=>{document.querySelector('#changePasswordModal input[type=password]').value='PRIVATE_ACCOUNT_PASSWORD';window.saveDraft();});
  const saved=await page.evaluate(()=>localStorage.getItem(Drafts.KEY));
  const csrf=await page.locator('#process-form [name=csrf_token]').inputValue();
  for(const secret of ['PRIVATE_FILE_BYTES','PRIVATE_ACCOUNT_PASSWORD',csrf,'csrf_token','session'])assert(!saved.includes(secret));
  const other=await context.newPage();await signIn(other);
  await other.locator('#batch_nodes').fill(node+' Other tab');
  // Clear while autosave is pending: submit/pagehide/visibility cannot restore it.
  await page.locator('#batch_nodes').fill(node+'\n');
  await page.bringToFront();
  const dialog=page.waitForEvent('dialog',{timeout:10000});
  const clicking=page.locator('.clear-draft').first().click();
  await (await dialog).accept();await clicking;
  await page.evaluate(()=>{window.saveDraft();window.dispatchEvent(new Event('pagehide'));document.dispatchEvent(new Event('visibilitychange'));});
  await other.waitForFunction(()=>document.getElementById('draft-status').textContent==='Draft cleared in another tab',null,{timeout:10000});
  await other.evaluate(()=>{window.saveDraft();window.dispatchEvent(new Event('pagehide'));});
  await other.close();
  await page.waitForTimeout(350);
  assert.equal(await page.evaluate(()=>localStorage.getItem(Drafts.KEY)),null);
  await page.reload();assert.equal(await page.locator('#batch_nodes').inputValue(),'');
  assert(await page.locator('#keep-draft').isChecked());
  // A stale legacy draft cannot be resurrected by the preference or mode toggle.
  await page.evaluate(()=>{localStorage.setItem(Drafts.KEY,JSON.stringify({version:1,saved_at:Date.now()-Drafts.TTL,batch:'EXPIRED_MUST_NOT_RETURN',source:'default',rows:[],policies:[]}));});
  await page.reload();assert.equal(await page.locator('#batch_nodes').inputValue(),'');
  assert.equal(await page.evaluate(()=>localStorage.getItem(Drafts.KEY)),null);
  await page.locator('#keep-draft').uncheck();await page.locator('#keep-draft').check();
  assert.equal(await page.evaluate(()=>localStorage.getItem(Drafts.KEY)),null);
  await page.evaluate(()=>localStorage.setItem(Drafts.KEY,'{corrupt'));
  await page.reload();assert.equal(await page.evaluate(()=>localStorage.getItem(Drafts.KEY)),null);
  // Timed opt-back stores a new finite timestamp; expiry still removes it.
  await page.locator('#keep-draft').uncheck();await page.locator('#batch_nodes').fill(node);
  await page.waitForFunction(()=>document.getElementById('draft-status').textContent==='Draft saved',null,{timeout:10000});
  await page.evaluate(()=>{const d=JSON.parse(localStorage.getItem(Drafts.KEY));d.saved_at=Date.now()-Drafts.TTL;localStorage.setItem(Drafts.KEY,JSON.stringify(d));});
  await page.reload();assert.equal(await page.locator('#batch_nodes').inputValue(),'');
  assert.equal(await page.evaluate(()=>localStorage.getItem(Drafts.KEY)),null);
  // Quota failure preserves old bytes and new DOM, never POSTs drafts to server.
  await page.locator('#batch_nodes').fill(node);
  await page.waitForFunction(()=>document.getElementById('draft-status').textContent==='Draft saved',null,{timeout:10000});
  const old=await page.evaluate(()=>localStorage.getItem(Drafts.KEY));let posts=0;
  page.on('request',r=>{if(r.method()==='POST')posts++;});
  await page.evaluate(()=>{Storage.prototype.setItem=function(){throw new DOMException('quota','QuotaExceededError');};});
  await page.locator('#batch_nodes').fill('Unsaved synthetic input');
  await page.waitForFunction(()=>document.getElementById('draft-status').textContent.includes('could not be saved'),null,{timeout:10000});
  assert.equal(await page.evaluate(()=>localStorage.getItem(Drafts.KEY)),old);
  await page.locator('#keep-draft').click();assert.equal(await page.locator('#keep-draft').isChecked(),false);
  assert.equal(posts,0);assert.deepEqual(errors,[]);
  await context.close();context=null;
  // Storage access denied on initial page load: form remains operable.
  await launch();await context.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new DOMException('denied','SecurityError');}}));
  page=await context.newPage();await signIn(page);
  await page.locator('#batch_nodes').fill(node);
  await page.waitForFunction(()=>document.getElementById('draft-status').textContent.includes('could not be saved'),null,{timeout:10000});
  assert.equal(await page.locator('#batch_nodes').inputValue(),node);
  assert.deepEqual(errors,[]);
  console.log('PASS retention browser: legacy 30-day default, permanent opt-in, actual browser restart, Clear Draft prevents same/cross-tab autosave resurrection, expired/corrupt records absent, sensitive fields excluded, quota/denied safe, mobile fit');
 }finally{if(context)await context.close();fs.rmSync(profile,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1);});
