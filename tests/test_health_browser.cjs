/* Manual reachability UI against deterministic test-only probe outcomes. */
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
const control = process.env.EXTERNAL_TEST_CONTROL;
assert(base && new URL(base).hostname === '127.0.0.1');
assert(control && new URL(control).hostname === '127.0.0.1');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = route.request().url();
      if (url.startsWith(base)) return route.continue();
      if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
        return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
      return route.abort();
    });
    async function navigate(button) { await Promise.all([page.waitForNavigation(),button.click()]); }
    async function mode(value) { assert.equal((await context.request.post(control,{data:value})).status(),204); }
    async function output(url) {
      const response = await context.request.get(url); assert.equal(response.status(),200); return response.text();
    }
    await page.goto(base); await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
    await page.goto(base+'/fixed-subscriptions/new');
    const storage = await page.evaluate(() => JSON.stringify({...localStorage,...sessionStorage}));
    await page.locator('#subscription-name').fill('Health Browser');
    await page.locator('#yaml-source').selectOption('custom');
    await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',
      buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
    const uuid = '11111111-1111-4111-8111-111111111111';
    await page.locator('#batch_nodes').fill('US|'+('Long health node '.repeat(18))+'|vless://'+uuid+'@8.8.8.8:443?type=tcp');
    await navigate(page.locator('#generate-yaml'));
    const url = await page.locator('.fixed-url').inputValue();
    const yaml = await output(url);
    const section = page.locator('#node-health');
    assert.equal(await section.locator('#health-mode').inputValue(),'off');
    assert.equal(await section.getByRole('button',{name:'立即檢查',exact:true}).count(),0);
    assert.equal(await section.locator('.health-badge').textContent(),'未知');
    assert(await section.getByText(/只檢查端點可達性/).isVisible());
    await section.locator('#health-mode').selectOption('automatic');
    assert(await section.locator('#health-interval').isVisible());
    await section.locator('#health-interval').selectOption('900');
    await navigate(section.getByRole('button',{name:'儲存健康檢查設定',exact:true}));
    assert.equal(await section.locator('#health-mode').inputValue(),'automatic');
    assert(await section.getByRole('button',{name:'立即檢查',exact:true}).isEnabled());
    assert((await section.getByText(/下次自動檢查：/).textContent()).includes('UTC'));
    assert((await section.getByText(/上次觸發：/).textContent()).includes('排程結果：—'));
    assert.equal(await section.locator('.health-badge').textContent(),'未知');
    await section.locator('#health-mode').selectOption('manual');
    await navigate(section.getByRole('button',{name:'儲存健康檢查設定',exact:true}));
    assert.equal(await section.locator('#health-mode').inputValue(),'manual');
    await mode('health-success');
    await navigate(section.getByRole('button',{name:'立即檢查',exact:true}));
    assert.equal(await section.locator('.health-badge').textContent(),'健康');
    assert(await section.getByText('38 ms',{exact:true}).isVisible());
    assert((await section.locator('.health-summary').textContent()).includes('健康 1'));
    await mode('health-failure');
    for (const [count,status] of [[1,'可疑'],[2,'可疑'],[3,'不健康']]) {
      await navigate(section.getByRole('button',{name:'立即檢查',exact:true}));
      assert.equal(await section.locator('.health-badge').textContent(),status);
      assert.equal(await section.locator('td[data-label="失敗次數"]').textContent(),String(count));
      assert.equal(await page.locator('.fixed-url').inputValue(),url);
      assert.equal(await output(url),yaml);
    }
    await mode('health-success');
    await navigate(section.getByRole('button',{name:'立即檢查',exact:true}));
    assert.equal(await section.locator('.health-badge').textContent(),'健康');
    assert.equal(await section.locator('td[data-label="失敗次數"]').textContent(),'0');
    await section.locator('#health-mode').selectOption('automatic');
    await section.locator('#health-interval').selectOption('900');
    await navigate(section.getByRole('button',{name:'儲存健康檢查設定',exact:true}));
    await navigate(section.getByRole('button',{name:'立即檢查',exact:true}));
    assert((await section.getByText(/上次觸發：/).textContent()).includes('手動 · 排程結果：成功'));
    for (const width of [1440,390]) {
      assert(await section.locator('#health-interval').isVisible());
      await page.setViewportSize({width,height:1000});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert(await section.getByRole('button',{name:'立即檢查',exact:true}).isVisible());
      if (process.env.FIXED_SCREENSHOT_DIR)
        await page.screenshot({path:path.join(process.env.FIXED_SCREENSHOT_DIR,`health-${width}.png`),fullPage:true});
    }
    const html = await section.evaluate(element => element.outerHTML);
    for (const secret of [uuid,'8.8.8.8','vless://','vmess://',new URL(url).pathname,'PRIVATE'])
      assert(!html.includes(secret));
    assert.equal(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage})),storage);
    await section.locator('#health-mode').selectOption('off');
    await navigate(section.getByRole('button',{name:'儲存健康檢查設定',exact:true}));
    assert.equal(await section.getByRole('button',{name:'立即檢查',exact:true}).count(),0);
    assert.equal(await page.locator('.fixed-url').inputValue(),url);
    assert.equal(await output(url),yaml);
    assert.deepEqual(errors,[]);
    console.log('PASS Health browser: Off/Unknown → Automatic/15m + Manual/Check Now, TCP-only explanation, summary/38ms, Suspect 1/2 → Unhealthy 3 → Healthy/0, unchanged Fixed URL/YAML, no endpoint/credential/fingerprint storage, long-name layout at 1440/390');
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
