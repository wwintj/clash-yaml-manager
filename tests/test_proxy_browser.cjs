/* Full proxy UI with a controlled engine; no real binary or public probe. */
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
const control = process.env.EXTERNAL_TEST_CONTROL;
assert(base && new URL(base).hostname === '127.0.0.1');
assert(control && new URL(control).hostname === '127.0.0.1');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900}});
    const page = await context.newPage();
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>{
      const url=route.request().url();
      if (url.startsWith(base)) return route.continue();
      if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
        return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
      return route.abort();
    });
    const setMode=async mode=>assert.equal((await context.request.post(control,{data:mode})).status(),204);
    const navigate=async button=>Promise.all([page.waitForNavigation(),button.click()]);
    const output=async url=>{
      const response=await context.request.get(url); assert.equal(response.status(),200);
      return response.text();
    };
    await page.goto(base); await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
    await page.goto(base+'/fixed-subscriptions/new');
    await page.locator('#subscription-name').fill('Proxy Validation Browser');
    await page.locator('#yaml-source').selectOption('custom');
    await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',
      buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
    const uuid='11111111-1111-4111-8111-111111111111';
    await page.locator('#batch_nodes').fill('US|'+('Long proxy node '.repeat(18))+
      '|vless://'+uuid+'@8.8.8.8:443?type=tcp');
    await navigate(page.locator('#generate-yaml'));
    const fixedUrl=await page.locator('.fixed-url').inputValue();
    const yaml=await output(fixedUrl);
    const section=page.locator('#proxy-health');
    const proxyStatus=()=>section.locator('td[data-label="Proxy"] .health-badge');
    const endpointStatus=()=>section.locator('td[data-label="Endpoint"] .health-badge');
    assert(await section.getByText('NOT INSTALLED',{exact:true}).isVisible());
    assert.equal(await section.locator('#proxy-mode').inputValue(),'off');
    assert.equal(await section.getByRole('button',{name:'Check Proxies Now'}).count(),0);
    assert.equal(await proxyStatus().textContent(),'UNKNOWN');
    await section.locator('#proxy-mode').selectOption('automatic');
    assert(await section.locator('#proxy-interval').isVisible());
    await section.locator('#proxy-interval').selectOption('900');
    await navigate(section.getByRole('button',{name:'Save Proxy Settings'}));
    assert.equal(await section.locator('#proxy-mode').inputValue(),'automatic');
    assert((await section.getByText(/Next Automatic Check:/).textContent()).includes('UTC'));
    assert((await section.getByText(/Last Trigger:/).textContent()).includes('Scheduler Result: —'));
    assert(await section.getByText(/Automatic proxy checks require a compatible managed engine/).isVisible());
    assert(await section.getByRole('button',{name:'Check Proxies Now'}).isDisabled());
    await section.locator('#proxy-mode').selectOption('manual');
    await navigate(section.getByRole('button',{name:'Save Proxy Settings'}));
    assert(await section.getByRole('button',{name:'Check Proxies Now'}).isDisabled());
    await setMode('proxy-engine-compatible');
    await page.reload();
    assert(await section.getByText('COMPATIBLE',{exact:true}).isVisible());
    assert(await section.getByText('CPU Level: v2 · Build: amd64-v2 · Preferred Build: amd64-v2',{exact:true}).isVisible());
    assert(await section.getByRole('button',{name:'Check Proxies Now'}).isEnabled());
    await setMode('proxy-success');
    await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
    assert.equal(await proxyStatus().textContent(),'HEALTHY');
    assert(await section.getByText('38 ms',{exact:true}).isVisible());
    assert.equal(await endpointStatus().textContent(),'UNKNOWN');
    const endpoint=page.locator('#node-health');
    await endpoint.locator('#health-mode').selectOption('manual');
    await navigate(endpoint.getByRole('button',{name:'Save Health Settings'}));
    await setMode('health-success');
    await navigate(endpoint.getByRole('button',{name:'Check Now',exact:true}));
    assert.equal(await endpointStatus().textContent(),'HEALTHY');
    await setMode('proxy-failure');
    for (const [count,status] of [[1,'SUSPECT'],[2,'SUSPECT'],[3,'UNHEALTHY']]) {
      await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
      assert.equal(await proxyStatus().textContent(),status);
      assert.equal(await section.locator('td[data-label="Proxy Failures"]').textContent(),String(count));
      assert.equal(await endpointStatus().textContent(),'HEALTHY');
      assert.equal(await page.locator('.fixed-url').inputValue(),fixedUrl);
      assert.equal(await output(fixedUrl),yaml);
    }
    await setMode('health-failure');
    for (let count=0;count<3;count++) await navigate(endpoint.getByRole('button',{name:'Check Now',exact:true}));
    await setMode('proxy-success');
    await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
    assert.equal(await proxyStatus().textContent(),'HEALTHY');
    assert.equal(await endpointStatus().textContent(),'UNHEALTHY');
    assert.equal(await section.locator('td[data-label="Proxy Failures"]').textContent(),'0');
    await setMode('proxy-unsupported');
    await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
    assert.equal(await proxyStatus().textContent(),'UNSUPPORTED');
    assert.equal(await section.locator('td[data-label="Proxy Failures"]').textContent(),'0');
    await setMode('proxy-run-error');
    await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
    assert.equal(await proxyStatus().textContent(),'UNSUPPORTED');
    assert(await section.getByText('Proxy probe engine could not complete this check.').isVisible());
    await section.locator('[name=global_url]').fill('https://probe.example/check');
    await section.locator('[name=global_expected_status]').fill('205');
    await section.locator('[name=global_timeout_ms]').selectOption('5000');
    await navigate(section.getByRole('button',{name:'Save Global Defaults'}));
    assert((await section.locator('.health-summary').textContent()).includes('https://probe.example/check'));
    await section.locator('#proxy-scope').selectOption('custom');
    assert(await section.locator('#proxy-custom-fields').isVisible());
    await section.locator('[name=custom_url]').fill('https://probe.example/custom');
    await section.locator('[name=custom_expected_status]').fill('204');
    await section.locator('[name=custom_timeout_ms]').selectOption('10000');
    await navigate(section.getByRole('button',{name:'Save Proxy Settings'}));
    assert((await section.locator('.health-summary').textContent()).includes('https://probe.example/custom'));
    await setMode('proxy-success');
    await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
    assert.equal(await proxyStatus().textContent(),'HEALTHY');
    await section.locator('#proxy-mode').selectOption('automatic');
    await section.locator('#proxy-interval').selectOption('900');
    await navigate(section.getByRole('button',{name:'Save Proxy Settings'}));
    await navigate(section.getByRole('button',{name:'Check Proxies Now'}));
    assert((await section.getByText(/Last Trigger:/).textContent()).includes('manual · Scheduler Result: success'));
    for (const width of [1440,390]) {
      assert(await section.locator('#proxy-interval').isVisible());
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert(await section.locator('.proxy-engine-card').isVisible());
      assert(await section.locator('#proxy-defaults').isVisible());
      assert(await section.locator('#proxy-settings').isVisible());
      assert(await section.locator('.health-summary').isVisible());
      assert(await section.locator('.proxy-health-table').isVisible());
    }
    const html=await section.evaluate(element=>element.outerHTML);
    for (const secret of [uuid,'8.8.8.8','vless://','vmess://',new URL(fixedUrl).pathname,'PRIVATE'])
      assert(!html.includes(secret));
    const browserStorage=await page.evaluate(()=>JSON.stringify({
      local:{...localStorage},session:{...sessionStorage}}));
    for (const secret of [uuid,'8.8.8.8',new URL(fixedUrl).pathname,'PRIVATE'])
      assert(!browserStorage.includes(secret));
    assert.equal(await page.locator('.fixed-url').inputValue(),fixedUrl);
    assert.equal(await output(fixedUrl),yaml);
    assert.deepEqual(errors,[]);
    console.log('PASS Proxy browser: optional engine, Off/Manual/Automatic 15m, global/custom HTTPS settings, Healthy/Suspect/Unhealthy/Unsupported/Engine Error, independent Endpoint statuses, stable Fixed URL, 1440/390 layout and redaction');
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
