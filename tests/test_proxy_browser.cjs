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
    const proxyStatus=()=>section.locator('td[data-label="代理"] .health-badge');
    const endpointStatus=()=>section.locator('td[data-label="端點"] .health-badge');
    assert(await section.getByText('未安裝',{exact:true}).isVisible());
    assert.equal(await section.locator('#proxy-mode').inputValue(),'off');
    assert.equal(await section.getByRole('button',{name:'立即檢查代理'}).count(),0);
    assert.equal(await proxyStatus().textContent(),'未知');
    await section.locator('#proxy-mode').selectOption('automatic');
    assert(await section.locator('#proxy-interval').isVisible());
    await section.locator('#proxy-interval').selectOption('900');
    await navigate(section.getByRole('button',{name:'儲存代理設定'}));
    assert.equal(await section.locator('#proxy-mode').inputValue(),'automatic');
    assert((await section.getByText(/下次自動檢查：/).textContent()).includes('UTC'));
    assert((await section.getByText(/上次觸發：/).textContent()).includes('排程結果：—'));
    assert(await section.getByText(/自動代理檢查需要相容的受管引擎/).isVisible());
    assert(await section.getByRole('button',{name:'立即檢查代理'}).isDisabled());
    await section.locator('#proxy-mode').selectOption('manual');
    await navigate(section.getByRole('button',{name:'儲存代理設定'}));
    assert(await section.getByRole('button',{name:'立即檢查代理'}).isDisabled());
    await setMode('proxy-engine-compatible');
    await page.reload();
    assert(await section.getByText('相容',{exact:true}).isVisible());
    assert(await section.getByText('CPU 等級：v2 · 建置：amd64-v2 · 建議建置：amd64-v2',{exact:true}).isVisible());
    assert(await section.getByRole('button',{name:'立即檢查代理'}).isEnabled());
    await setMode('proxy-success');
    await navigate(section.getByRole('button',{name:'立即檢查代理'}));
    assert.equal(await proxyStatus().textContent(),'健康');
    assert(await section.getByText('38 ms',{exact:true}).isVisible());
    assert.equal(await endpointStatus().textContent(),'未知');
    const endpoint=page.locator('#node-health');
    await endpoint.locator('#health-mode').selectOption('manual');
    await navigate(endpoint.getByRole('button',{name:'儲存健康檢查設定'}));
    await setMode('health-success');
    await navigate(endpoint.getByRole('button',{name:'立即檢查',exact:true}));
    assert.equal(await endpointStatus().textContent(),'健康');
    await setMode('proxy-failure');
    for (const [count,status] of [[1,'可疑'],[2,'可疑'],[3,'不健康']]) {
      await navigate(section.getByRole('button',{name:'立即檢查代理'}));
      assert.equal(await proxyStatus().textContent(),status);
      assert.equal(await section.locator('td[data-label="代理失敗次數"]').textContent(),String(count));
      assert.equal(await endpointStatus().textContent(),'健康');
      assert.equal(await page.locator('.fixed-url').inputValue(),fixedUrl);
      assert.equal(await output(fixedUrl),yaml);
    }
    await setMode('health-failure');
    for (let count=0;count<3;count++) await navigate(endpoint.getByRole('button',{name:'立即檢查',exact:true}));
    await setMode('proxy-success');
    await navigate(section.getByRole('button',{name:'立即檢查代理'}));
    assert.equal(await proxyStatus().textContent(),'健康');
    assert.equal(await endpointStatus().textContent(),'不健康');
    assert.equal(await section.locator('td[data-label="代理失敗次數"]').textContent(),'0');
    await setMode('proxy-unsupported');
    await navigate(section.getByRole('button',{name:'立即檢查代理'}));
    assert.equal(await proxyStatus().textContent(),'不支援');
    assert.equal(await section.locator('td[data-label="代理失敗次數"]').textContent(),'0');
    await setMode('proxy-run-error');
    await navigate(section.getByRole('button',{name:'立即檢查代理'}));
    assert.equal(await proxyStatus().textContent(),'不支援');
    assert(await section.getByText('代理探測引擎無法完成此次檢查。').isVisible());
    const editPage=page.url();
    await page.goto(base+'/settings#health');
    const defaults=page.locator('#health');
    await defaults.locator('[name=global_url]').fill('https://probe.example/check');
    await defaults.locator('[name=global_expected_status]').fill('205');
    await defaults.locator('[name=global_timeout_ms]').selectOption('5000');
    await navigate(defaults.getByRole('button',{name:'儲存全域預設值'}));
    assert(page.url().endsWith('/settings#health'));
    await page.goto(editPage);
    assert((await section.locator('.health-summary').textContent()).includes('https://probe.example/check'));
    await section.locator('#proxy-scope').selectOption('custom');
    assert(await section.locator('#proxy-custom-fields').isVisible());
    await section.locator('[name=custom_url]').fill('https://probe.example/custom');
    await section.locator('[name=custom_expected_status]').fill('204');
    await section.locator('[name=custom_timeout_ms]').selectOption('10000');
    await navigate(section.getByRole('button',{name:'儲存代理設定'}));
    assert((await section.locator('.health-summary').textContent()).includes('https://probe.example/custom'));
    await setMode('proxy-success');
    await navigate(section.getByRole('button',{name:'立即檢查代理'}));
    assert.equal(await proxyStatus().textContent(),'健康');
    await section.locator('#proxy-mode').selectOption('automatic');
    await section.locator('#proxy-interval').selectOption('900');
    await navigate(section.getByRole('button',{name:'儲存代理設定'}));
    await navigate(section.getByRole('button',{name:'立即檢查代理'}));
    assert((await section.getByText(/上次觸發：/).textContent()).includes('手動 · 排程結果：成功'));
    for (const width of [1440,390]) {
      assert(await section.locator('#proxy-interval').isVisible());
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert(await section.locator('.proxy-engine-card').first().isVisible());
      assert.equal(await section.locator('#proxy-defaults').count(),0);
      assert(await section.locator('#global-proxy-summary').isVisible());
      assert(await section.getByRole('link',{name:'前往設定中的全域預設值'}).isVisible());
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
