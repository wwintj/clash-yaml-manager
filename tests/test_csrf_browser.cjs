/* Original browser matrix plus real authenticated refresh, only disposable Flask. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;
assert.equal(new URL(base).hostname,'127.0.0.1');
const link='US|Synthetic CSRF Draft|vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const context=await browser.newContext(),page=await context.newPage(),errors=[],requests=[];
  context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));
  page.on('pageerror',e=>errors.push(e.message));
  context.on('request',r=>requests.push({method:r.method(),path:new URL(r.url()).pathname,url:r.url()}));
  await context.route('**/*',route=>{
   const url=route.request().url();if(url.startsWith(base))return route.continue();
   if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css'))return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
   if(url.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'))return route.fulfill({path:process.env.BOOTSTRAP_JS_PATH,contentType:'text/javascript'});
   return route.abort();
  });
  const count=path=>requests.filter(r=>r.path===path).length;
  await page.goto(base);assert.equal(await page.locator('script[src$="csrf.js"]').count(),0);
  await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
  const second=await context.newPage();await second.goto(base);
  const fixed=await context.newPage();await fixed.goto(base+'/fixed-subscriptions/new');
  await page.locator('#batch_nodes').fill(link);
  await second.locator('#batch_nodes').fill(link.replace('Draft','Other Tab'));
  await fixed.locator('#subscription-name').fill('Unsaved Synthetic Name');
  // Invalid/stale DOM tokens are replaced before the first business POST.
  for(const tab of [page,second,fixed]){
   await tab.locator('#process-form [name=csrf_token]').evaluate(input=>{input.value='stale-token';});
   const response=tab.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await tab.locator('#parse-nodes').click();assert.equal((await response).status(),200);
   await tab.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
   assert.notEqual(await tab.locator('#process-form [name=csrf_token]').inputValue(),'stale-token');
  }
  assert.equal(await page.locator('#batch_nodes').inputValue(),link);
  assert.equal(await fixed.locator('#subscription-name').inputValue(),'Unsaved Synthetic Name');
  const token=await page.locator('#process-form [name=csrf_token]').inputValue();
  const storage=await page.evaluate(()=>JSON.stringify({...localStorage}));
  assert(!storage.includes(token)&&!storage.includes('csrf_token')&&!storage.includes('session'));
  assert(!(await page.locator('body').innerText()).includes(token));
  assert(!requests.some(r=>r.url.includes(token)));
  // A malformed token transport must never echo response bytes into AJAX errors.
  const privateMarker='TEST_ONLY_MALFORMED_TOKEN_MUST_NOT_DISPLAY';
  await context.route('**/api/csrf-token',route=>route.fulfill({status:200,contentType:'application/json',body:privateMarker}));
  const failedParse=count('/parse-nodes');await page.locator('#parse-nodes').click();
  await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
  assert.equal(count('/parse-nodes'),failedParse);
  assert((await page.locator('#parse-summary').textContent()).includes('Security token could not be refreshed'));
  assert(!(await page.locator('body').innerText()).includes(privateMarker));
  await context.unroute('**/api/csrf-token');
  // No background token polling, no unnecessary permanent session extension.
  const idle=count('/api/csrf-token');await page.waitForTimeout(200);assert.equal(count('/api/csrf-token'),idle);
  // Failed refresh leaves DOM/file inputs and draft intact and never sends Generate.
  await page.locator('#yaml-source').selectOption('custom');
  await page.locator('[name=yaml_file]').setInputFiles({name:'synthetic.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules: [MATCH,DIRECT]\n')});
  await context.route('**/api/csrf-token',route=>route.abort());
  const before=count('/process');await page.locator('#generate-yaml').click();
  await page.locator('[data-csrf-feedback]').waitFor();
  assert.equal(count('/process'),before);
  assert.equal(await page.locator('[data-csrf-feedback]').getAttribute('role'),'alert');
  assert.equal(await page.locator('#batch_nodes').inputValue(),link);
  assert.equal(await page.locator('[name=yaml_file]').evaluate(e=>e.files.length),1);
  assert((await page.evaluate(()=>localStorage.getItem(window.Drafts.KEY))).includes('Synthetic CSRF Draft'));
  await page.waitForTimeout(200);assert.equal(count('/process'),before);
  await context.unroute('**/api/csrf-token');
  // Manual retry (including a double click during refresh) dispatches one POST.
  let release,seen;
  const held=new Promise(resolve=>{release=resolve;}),intercepted=new Promise(resolve=>{seen=resolve;});
  await context.route('**/api/csrf-token',async route=>{seen();await held;await route.continue();});
  const freshCount=count('/api/csrf-token');
  const generated=page.waitForRequest(r=>new URL(r.url()).pathname==='/process');
  const navigated=page.waitForNavigation();
  await page.locator('#generate-yaml').click();await intercepted;
  await page.locator('#generate-yaml').click();
  assert.equal(count('/api/csrf-token'),freshCount+1);assert.equal(count('/process'),before);
  release();await navigated;await context.unroute('**/api/csrf-token');
  assert.equal(count('/process'),before+1);
  assert((await generated).postData().includes('generate'));
  assert(await page.locator('#download-url').isVisible());
  // Force server CSRF rejection after preflight. There is no retry or replay.
  await page.goto(base);await page.locator('#batch_nodes').fill(link);
  await page.route('**/parse-nodes',route=>{
   const data=new URLSearchParams(route.request().postData());data.set('csrf_token','invalid');
   return route.continue({postData:data.toString(),headers:{...route.request().headers(),'content-type':'application/x-www-form-urlencoded'}});
  });
  const rejected=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
  const parsed=count('/parse-nodes');await page.locator('#parse-nodes').click();assert.equal((await rejected).status(),400);
  await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
  await page.waitForTimeout(200);assert.equal(count('/parse-nodes'),parsed+1);
  assert((await page.locator('#parse-summary').textContent()).includes('refresh or log in again'));
  await page.unroute('**/parse-nodes');
  // Another long-open tab refreshes after that nonce rotation, with no navigation.
  const recovered=second.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
  await second.locator('#parse-nodes').click();assert.equal((await recovered).status(),200);
  // Logout through an authenticated form works; old open forms cannot re-authenticate.
  await Promise.all([page.waitForNavigation(),page.locator('form[action="/logout"] button').click()]);
  const expired=second.waitForResponse(r=>new URL(r.url()).pathname==='/api/csrf-token');
  const oldCount=count('/parse-nodes');await second.locator('#parse-nodes').click();assert.equal((await expired).status(),401);
  await second.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
  assert.equal(count('/parse-nodes'),oldCount);
  assert((await second.locator('#parse-summary').textContent()).includes('Session expired'));
  assert((await second.locator('#batch_nodes').inputValue()).includes('Other Tab'));
  // Login leaves existing local draft restoration available.
  await second.goto(base);await second.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([second.waitForNavigation(),second.locator('#password').press('Enter')]);
  assert.equal(await second.locator('#draft-status').textContent(),'Draft restored');
  assert.deepEqual(errors,[]);await context.close();
  console.log('PASS CSRF browser: three open forms, fresh before first POST, failed refresh preserves drafts/files, one explicit retry, rejected POST not replayed, logout/session expiry, no token storage/URL/display leak, no polling');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
