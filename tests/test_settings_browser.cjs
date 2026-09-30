/* Modular Settings, real browser forms, controlled stores/engine; no real VPS claims. */
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;assert(base && new URL(base).hostname==='127.0.0.1');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const anonymous=await browser.newContext();
  assert.equal((await anonymous.request.get(base+'/settings',{maxRedirects:0})).status(),302);
  assert([302,303].includes((await anonymous.request.post(base+'/settings/health/proxy-defaults',{maxRedirects:0})).status()));
  await anonymous.close();
  const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const routes=async route=>{
   const url=route.request().url();if(url.startsWith(base))return route.continue();
   if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')&&process.env.BOOTSTRAP_CSS_PATH)
    return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
   return route.abort();
  };
  await page.route('**/*',routes);
  const nav=button=>Promise.all([page.waitForNavigation(),button.click()]);
  await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
  await page.goto(base+'/fixed-subscriptions/new');await page.locator('#subscription-name').fill('Settings Framework');
  await page.locator('#yaml-source').selectOption('custom');
  await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
  const uuid='11111111-1111-4111-8111-111111111111';
  await page.locator('#batch_nodes').fill(`US|Settings-node|vless://${uuid}@8.8.8.8:443?type=tcp`);
  await nav(page.locator('#generate-yaml'));const edit=page.url(),fixed=await page.locator('.fixed-url').inputValue();
  const read=async()=>{const r=await context.request.get(fixed);assert.equal(r.status(),200);return r.text();};
  const old=await read();
  const proxy=page.locator('#proxy-health');assert.equal(await proxy.locator('#proxy-defaults').count(),0);
  assert(await proxy.locator('#proxy-settings').isVisible());
  await proxy.locator('#proxy-scope').selectOption('custom');assert(await proxy.locator('#proxy-custom-fields').isVisible());
  assert.equal(await proxy.getByRole('link',{name:'Manage Global Defaults in Settings'}).getAttribute('href'),'/settings#health');
  await proxy.getByRole('link',{name:'Manage Global Defaults in Settings'}).click();
  assert(page.url().endsWith('/settings#health'));assert(await page.locator('#health').isVisible());
  const oldUrl=await page.locator('#global-probe-url').inputValue();
  await page.locator('#global-probe-url').fill('https://user:REJECTED_CREDENTIAL@8.8.8.8/');
  await nav(page.getByRole('button',{name:'Save Global Defaults'}));
  assert(await page.getByText(/Unable to save global proxy defaults/).isVisible());
  assert.equal(await page.locator('#global-probe-url').inputValue(),oldUrl);
  assert(!(await page.content()).includes('REJECTED_CREDENTIAL'));
  await page.locator('#global-probe-url').fill('https://probe.example/framework_status');
  await page.locator('#global-probe-status').fill('206');await page.locator('#global-probe-timeout').selectOption('3000');
  await nav(page.getByRole('button',{name:'Save Global Defaults'}));assert(page.url().endsWith('/settings#health'));
  assert(await page.getByText(/Global proxy defaults saved/).isVisible());
  const upload=async bytes=>{
   await page.locator('#geoip-file').setInputFiles({name:'country.mmdb',mimeType:'application/octet-stream',buffer:Buffer.from(bytes)});
   await nav(page.getByRole('button',{name:'Upload / Replace'}));
  };
  await upload('SYNTHETIC:SG');assert(page.url().endsWith('/settings#geoip'));
  assert.equal(await page.locator('[data-geoip-status]').textContent(),'Ready');assert.equal(await read(),old);
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:900});
   for(const [section,label] of [['overview','Overview'],['geoip','GeoIP'],['health','Health'],['runtime','Runtime']]){
    await page.getByRole('navigation',{name:'Settings sections'}).getByRole('link',{name:label,exact:true}).click();
    assert(page.url().endsWith('#'+section));assert(await page.locator('#'+section).isVisible());
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    if(process.env.SETTINGS_SCREENSHOT_DIR){
     fs.mkdirSync(process.env.SETTINGS_SCREENSHOT_DIR,{recursive:true});
     await page.locator('#'+section).screenshot({path:path.join(process.env.SETTINGS_SCREENSHOT_DIR,`${section}-${width}.png`)});
    }
   }
   assert.equal(await page.locator('#health button').count(),1); // Save only; no engine actions.
   assert.equal(await page.locator('#runtime input, #runtime button, #runtime form').count(),0);
  }
  const settingsHtml=await page.content();
  for(const secret of [uuid,'vless://','8.8.8.8',new URL(fixed).pathname.split('-fs_')[1],process.env.PREVIEW_TEST_PASSWORD,'REJECTED_CREDENTIAL'])
   assert(!settingsHtml.includes(secret));
  assert.equal(await page.locator('[data-runtime=session_lifetime]').textContent(),'30 days');
  await nav(page.getByRole('button',{name:'Remove Database'}));assert.equal(await read(),old);
  assert.equal(await page.locator('[data-geoip-status]').textContent(),'Not installed');
  await page.goto(edit);assert.equal(await page.locator('.fixed-url').inputValue(),fixed);
  assert((await page.locator('#global-proxy-summary').textContent()).includes('https://probe.example/framework_status'));
  assert.equal(await read(),old);assert(await page.locator('#proxy-settings').isVisible());
  // Core Settings navigation and submit also work with JavaScript disabled.
  const plain=await browser.newContext({javaScriptEnabled:false});const plainPage=await plain.newPage();await plainPage.route('**/*',routes);
  await plainPage.goto(base);await plainPage.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([plainPage.waitForNavigation(),plainPage.locator('#password').press('Enter')]);
  await plainPage.goto(base+'/settings#health');assert(await plainPage.locator('#proxy-defaults').isVisible());
  const [plainResponse]=await Promise.all([plainPage.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/settings/health/proxy-defaults')),plainPage.locator('#global-probe-status').press('Enter')]);
  assert.equal(plainResponse.status(),303);
  await plainPage.waitForLoadState('load');
  assert(plainPage.url().endsWith('/settings#health'));await plain.close();
  assert.deepEqual(errors,[]);await context.close();
  console.log('PASS Settings browser: auth, four modules, GeoIP actions, valid/invalid Proxy defaults, Fixed link/form boundary, secrets, anchors, read-only Runtime, no-JS forms, 1440/390 no overflow');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
