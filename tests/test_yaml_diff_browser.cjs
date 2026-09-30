/* Real DOM + real Flask in the disposable runner. Never contact a VPS/provider. */
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1');
const routePath = '/api/preview-yaml-diff';
const link = 'vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
const batch = 'US|OldTest|' + link;
const latest = 'US|LatestTest|' + link.replaceAll('11111111','22222222');
const sentinel = '<script>alert(1)</script><img data-diff-xss src=x> & Ω';
const source = 'proxies: [{name: old, type: vless, server: old.example, port: 443, uuid: fake}]\nproxy-groups: []\nrules: [MATCH,DIRECT]\nx-private: "'+sentinel+' '+ 'W'.repeat(5000)+'"\n';
async function setup(browser,width) {
  const context=await browser.newContext({viewport:{width,height:900}});
  const page=await context.newPage(), posts=[];
  page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
  page.on('dialog',async dialog=>{await dialog.dismiss();throw Error('Unexpected script/dialog execution');});
  await page.route('**/*',route=>{
    const url=route.request().url();
    if(url.startsWith(base))return route.continue();
    if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
      return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
    return route.abort();
  });
  await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
  return {page,context,posts,count:path=>posts.filter(p=>p===path).length};
}
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  for(const width of [1440,390]) {
   const {page,context,posts,count}=await setup(browser,width);
   const button=page.locator('#preview-yaml-diff'), status=page.locator('#yaml-diff-status');
   assert(await button.isVisible());assert.equal(await button.getAttribute('type'),'button');
   async function preview(expected=200) {
    const pending=page.waitForResponse(r=>new URL(r.url()).pathname===routePath);
    await button.click();const response=await pending;
    assert.equal(response.status(),expected);assert.equal(response.headers()['cache-control'],'no-store');
    await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
    return response.json();
   }
   await page.locator('#batch_nodes').fill(batch);
   assert((await preview()).changed);assert.equal(await status.textContent(),'Changed');
   assert((await page.locator('#yaml-diff-code').textContent()).startsWith('--- source.yaml\n+++ generated.yaml\n'));
   assert.equal(count('/process'),0);
   const parsed=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await page.locator('#parse-nodes').click();await parsed;
   await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
   await page.locator('#batch_nodes').fill(latest);
   await preview();assert((await page.locator('#yaml-diff-code').textContent()).includes('LatestTest'));
   assert(!(await page.locator('#yaml-diff-code').textContent()).includes('OldTest'));
   await page.locator('#yaml-source').selectOption('custom');
   const missingCount=count(routePath);await button.click();
   assert((await status.textContent()).includes('Custom YAML needs to be selected again.'));
   assert.equal(count(routePath),missingCount);assert.equal(count('/process'),0);
   async function upload(text) {await page.locator('[name=yaml_file]').setInputFiles({name:'custom.yaml',mimeType:'application/yaml',buffer:Buffer.from(text)});}
   await upload(source);const custom=await preview();
   assert(custom.diff.includes(sentinel));assert.equal(await page.locator('[data-diff-xss]').count(),0);
   assert.equal(await page.evaluate(()=>window.alertExecuted),undefined);
   const geometry=await page.locator('#yaml-diff-text').evaluate(pre=>({
     width:pre.clientWidth,scroll:pre.scrollWidth,overflow:getComputedStyle(pre).overflowX,
     space:getComputedStyle(pre).whiteSpace,font:getComputedStyle(pre).fontFamily,
     pageOverflow:document.documentElement.scrollWidth>innerWidth+1}));
   assert(geometry.scroll>geometry.width);assert.equal(geometry.overflow,'auto');assert.equal(geometry.space,'pre');
   assert(geometry.font.includes('monospace'));assert(!geometry.pageOverflow);
   await page.locator('#yaml-diff-panel').screenshot({path:`/private/tmp/clash-yaml-diff-${width}.png`});
   assert(!(await page.evaluate(()=>JSON.stringify({...localStorage}))).includes(sentinel));
   const before=count('/process');await page.locator('.aux-name').press('Enter');
   await page.waitForTimeout(80);assert.equal(count('/process'),before);
   // Hold a response after computing it, then edit. Old diff must not be displayed.
   let release,seen;
   const held=new Promise(resolve=>{release=resolve;}), intercepted=new Promise(resolve=>{seen=resolve;});
   await page.route('**/api/preview-yaml-diff',async route=>{const response=await route.fetch();seen();await held;await route.fulfill({response});});
   await button.click();await intercepted;
   await page.locator('#batch_nodes').fill(latest.replace('LatestTest','ChangedDuringPreview'));
   release();await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
   assert.equal(await status.textContent(),'Inputs changed; preview again.');
   assert.equal(await page.locator('#yaml-diff-code').textContent(),'');await page.unroute('**/api/preview-yaml-diff');
   await page.locator('#batch_nodes').fill(latest);
   await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
   assert.equal(count('/process'),before+1);
   const download=await context.request.get(await page.locator('#download-url').inputValue());
   assert(download.ok());const generated=await download.text();
   await upload(generated);const unchanged=await preview();
   assert(!unchanged.changed);assert.equal(unchanged.diff,'');assert.equal(await status.textContent(),'No YAML changes.');
   assert(await page.locator('#yaml-diff-text').isHidden());
   await page.locator('#batch_nodes').fill('PRIVATE-invalid-uri');await preview(400);
   assert((await status.textContent()).includes('Preview unavailable'));
   await page.locator('#batch_nodes').fill(latest);
   await page.locator('#process-form [name=csrf_token]').evaluate(input=>{input.value='invalid';});
   await preview(400);assert((await status.textContent()).includes('refresh or log in again'));
   await page.reload();await button.click();assert((await status.textContent()).includes('Custom YAML needs to be selected again.'));
   await upload(generated);
   const csrf=await page.locator('#process-form [name=csrf_token]').inputValue();
   await context.request.post(base+'/logout',{form:{csrf_token:csrf}});
   const anonymousHtml=await (await context.request.get(base)).text();
   const fresh=anonymousHtml.match(/name="csrf_token" value="([^"]+)"/)[1];
   await page.locator('#process-form [name=csrf_token]').evaluate((input,value)=>{input.value=value;},fresh);
   await preview(401);assert((await status.textContent()).includes('Session expired'));
   await context.close();
   // Independent normal generation never requires Diff Preview.
   const direct=await setup(browser,width);
   await direct.page.locator('#batch_nodes').fill(batch);
   await Promise.all([direct.page.waitForNavigation(),direct.page.locator('#generate-yaml').click()]);
   assert.equal(direct.count(routePath),0);assert.equal(direct.count('/process'),1);
   assert(await direct.page.locator('#download-url').isVisible());await direct.context.close();
   console.log(`YAML diff browser PASS: ${width}px; latest/default/custom/no-change/XSS/overflow/implicit-submit/CSRF/session/stale-response/direct Generate`);
  }
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
