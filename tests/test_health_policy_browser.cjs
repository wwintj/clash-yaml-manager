/* Synthetic Full Proxy outcomes only, isolated Flask and temporary private state. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL, control=process.env.EXTERNAL_TEST_CONTROL;
assert(base && new URL(base).hostname==='127.0.0.1');
assert(control && new URL(control).hostname==='127.0.0.1');
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:900}});
    const page=await context.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>{
      const url=route.request().url();
      if(url.startsWith(base))return route.continue();
      if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
        return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
      return route.abort();
    });
    const navigate=button=>Promise.all([page.waitForNavigation(),button.click()]);
    const setMode=async mode=>assert.equal((await context.request.post(control,{data:mode})).status(),204);
    const section=page.locator('section[aria-label="Health-aware Policy"]');
    const proxy=page.locator('#proxy-health');
    const mode=page.locator('#health-policy-mode'), age=page.locator('#health-policy-age'), min=page.locator('#health-policy-min');
    const check=()=>navigate(proxy.getByRole('button',{name:'Check Proxies Now'}));
    await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
    assert.equal(await mode.count(),0);
    await page.goto(base+'/fixed-subscriptions/new');
    assert.equal(await mode.inputValue(),'off');assert.equal(await age.inputValue(),'172800');assert.equal(await min.inputValue(),'2');
    await mode.selectOption('exclude-unhealthy');
    assert(await section.getByText(/while Proxy Health is Off or unavailable/).isVisible());
    for(const choice of ['3600','21600','86400','172800','604800'])await age.selectOption(choice);
    await age.selectOption('172800');
    await page.locator('#subscription-name').fill('Health Policy Browser');
    await page.locator('#yaml-source').selectOption('custom');
    await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
    const uuid='11111111-1111-4111-8111-111111111111';
    const input=['8.8.8.8','8.8.4.4','1.1.1.1'].map((host,i)=>`US|${String.fromCharCode(65+i)}|vless://${uuid}@${host}:443?type=tcp`).join('\n');
    await page.locator('#batch_nodes').fill(input);await page.locator('#policy_country_groups_type').selectOption('fallback');
    await navigate(page.locator('#generate-yaml'));
    const fixed=await page.locator('.fixed-url').inputValue();
    const read=async()=>{const r=await context.request.get(fixed);assert.equal(r.status(),200);return r.text();};
    const initial=await read();
    assert.equal(await section.locator('[data-health-policy-result]').textContent(),'unavailable');
    await setMode('proxy-engine-compatible');await setMode('proxy-middle-failure');
    await proxy.locator('#proxy-mode').selectOption('manual');await navigate(proxy.getByRole('button',{name:'Save Proxy Settings'}));
    for(const count of [1,2]) {await check();assert.equal(await read(),initial);assert.equal(await section.locator('[data-health-policy-excluded]').textContent(),'0');}
    await check();
    const filtered=await read();assert.notEqual(filtered,initial);
    const rootSection=key=>{
      const lines=filtered.replaceAll("'",'').replaceAll('"','').split('\n');
      const start=lines.findIndex(line=>line===key+':');assert(start>=0);
      let end=start+1;while(end<lines.length && !/^[a-z][a-z-]*:/.test(lines[end]))end++;
      return lines.slice(start+1,end).join('\n');
    };
    const groups=rootSection('proxy-groups');
    const country=groups.slice(groups.indexOf('name: 🇺🇸 美国节点'));
    assert(country.includes('🇺🇸 A') && country.includes('🇺🇸 C') && !country.includes('🇺🇸 B'));
    assert(rootSection('proxies').includes('name: 🇺🇸 B'));
    assert(groups.slice(groups.indexOf('name: 🚀 手动切换'),groups.indexOf('name: 🇺🇸 美国节点')).includes('🇺🇸 B'));
    assert.equal(await section.locator('[data-health-policy-filtered]').textContent(),'1');
    assert.equal(await section.locator('[data-health-policy-excluded]').textContent(),'1');
    assert.equal(await section.locator('[data-health-policy-result]').textContent(),'updated');
    await setMode('proxy-success');await check();assert.equal(await read(),initial);
    await setMode('proxy-two-failures');for(let i=0;i<3;i++)await check();
    assert.equal(await read(),initial);assert.equal(await section.locator('[data-health-policy-result]').textContent(),'fail-open');
    assert.equal(await section.locator('[data-health-policy-fail-open]').textContent(),'1');
    // Invalid POST must restore every editable value without changing the saved YAML.
    await age.selectOption('21600');await min.fill('17');await page.locator('#process-form').evaluate(form=>form.noValidate=true);
    await navigate(page.locator('#generate-yaml'));
    assert.equal(await age.inputValue(),'21600');assert.equal(await min.inputValue(),'17');
    assert.equal(await mode.inputValue(),'exclude-unhealthy');assert.equal(await page.locator('#batch_nodes').inputValue(),input);
    assert(await page.getByText(/Unable to save/).isVisible());assert.equal(await read(),initial);
    await min.fill('2');await navigate(page.locator('#generate-yaml'));
    const summary=await section.locator('[aria-label="Health-aware Policy Summary"]').evaluate(el=>el.outerHTML);
    for(const secret of [uuid,'8.8.8.8','vless://',new URL(fixed).pathname,'PRIVATE'])assert(!summary.includes(secret));
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert(await mode.isVisible() && await age.isVisible() && await min.isVisible());
      if(process.env.HEALTH_POLICY_SCREENSHOT_DIR){
        fs.mkdirSync(process.env.HEALTH_POLICY_SCREENSHOT_DIR,{recursive:true});
        await section.screenshot({path:path.join(process.env.HEALTH_POLICY_SCREENSHOT_DIR,`health-policy-${width}.png`)});
      }
    }
    const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));
    for(const secret of [uuid,'8.8.8.8',new URL(fixed).pathname,'health_policy'])assert(!storage.includes(secret));
    await page.goto(base);assert.equal(await mode.count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS Health-aware Policy browser: Off/48h/2 defaults, warning, freshness choices, Suspect retained, fresh Unhealthy excluded, manual/top-level retained, recovery, per-group fail-open, invalid POST restoration, stable /s, redacted summary, 1440/390 no overflow');
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
