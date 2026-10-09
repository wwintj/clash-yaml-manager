/* End-to-end source lifecycle against an isolated, controlled HTTP server. */
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
    const anonymous = await browser.newContext();
    const page = await context.newPage();
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*', route => {
      const url=route.request().url();
      if (url.startsWith(base)) return route.continue();
      if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
        return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
      return route.abort();
    });
    async function navigate(button) { await Promise.all([page.waitForNavigation(),button.click()]); }
    async function mode(value) { assert.equal((await anonymous.request.post(control,{data:value})).status(),204); }
    async function output(url) {
      const response=await anonymous.request.get(url); assert.equal(response.status(),200); return response.text();
    }
    await page.goto(base); await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
    await page.goto(base+'/fixed-subscriptions/new');
    const draft=await page.evaluate(()=>localStorage.getItem('clash-yaml-manager.draft.v1'));
    await page.locator('#subscription-name').fill('External Browser');
    await page.locator('#yaml-source').selectOption('custom');
    await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',
      buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
    await page.getByRole('button',{name:'Add Remote URL',exact:true}).click();
    await page.locator('.source-name').fill('Airport');
    await page.locator('.source-url').fill(process.env.EXTERNAL_TEST_URL);
    assert.equal(await page.locator('.source-refresh-interval').inputValue(),'');
    await navigate(page.locator('#generate-yaml'));
    const url=await page.locator('.fixed-url').inputValue();
    assert((await output(url)).includes('Tokyo initial'));
    assert.equal(await page.locator('.source-status').textContent(),'Ready');
    assert.equal(await page.locator('.next-refresh').textContent(),'—');
    await page.locator('.source-refresh-interval').selectOption('3600');
    await navigate(page.locator('#generate-yaml'));
    const scheduled=Number(await page.locator('.next-refresh').getAttribute('data-next-refresh'));
    assert(scheduled>Date.now()/1000+3500);
    assert((await page.locator('.next-refresh').textContent()).includes('UTC'));
    await navigate(page.getByRole('button',{name:'Refresh',exact:true}));
    assert.equal(await page.locator('.fixed-url').inputValue(),url);
    const rescheduled=Number(await page.locator('.next-refresh').getAttribute('data-next-refresh'));
    assert(rescheduled>scheduled);
    await page.locator('.source-history summary').click();
    assert(await page.locator('.source-history').getByText(/MANUAL · SUCCESS/).first().isVisible());
    await mode('failure');
    await navigate(page.getByRole('button',{name:'Refresh',exact:true}));
    assert.equal(await page.locator('.source-status').textContent(),'Cached');
    assert(await page.getByText('Using last successful data.',{exact:true}).isVisible());
    assert((await output(url)).includes('Tokyo initial'));
    // Cached remote data may be combined with changed manual input.
    await page.locator('#batch_nodes').fill('US|Manual changed|vless://test-uuid@192.0.2.2:443');
    await navigate(page.locator('#generate-yaml'));
    assert((await output(url)).includes('Manual changed'));
    assert.equal(await page.locator('.source-status').textContent(),'Cached');
    await mode('recovered');
    await navigate(page.getByRole('button',{name:'Refresh All Sources',exact:true}));
    assert.equal(await page.locator('.fixed-url').inputValue(),url);
    assert((await output(url)).includes('London recovered'));
    assert.equal(await page.locator('.source-status').textContent(),'Ready');
    await page.getByRole('button',{name:'Add Uploaded Source',exact:true}).click();
    const upload=page.locator('.external-source').last();
    assert.equal(await upload.locator('.source-refresh-interval').count(),0);
    await upload.locator('.source-name').fill('Office');
    await upload.locator('.source-file').setInputFiles({name:'office.yaml',mimeType:'application/yaml',
      buffer:Buffer.from('proxies:\n- name: Germany office\n  type: vmess\n  server: 203.0.113.1\n  port: 443\n  uuid: test-office\n')});
    await navigate(page.locator('#generate-yaml'));
    assert.equal(await page.locator('.fixed-url').inputValue(),url);
    const good=await output(url); assert(good.includes('Germany office') && good.includes('London recovered'));
    await page.locator('.source-file').setInputFiles({name:'bad.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxies: [')});
    await navigate(page.locator('#generate-yaml'));
    assert(await page.getByText(/Unable to save/).isVisible());
    assert.equal(await output(url),good);
    // Return to persisted settings; failed file content never replaces saved payload.
    await page.goto(page.url());
    assert(await page.getByText('Current source file: saved. Leave empty to keep it.',{exact:true}).isVisible());
    for (const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert(await page.getByRole('button',{name:'Refresh All Sources',exact:true}).isVisible());
      await page.locator('.source-history summary').first().click();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      if (process.env.FIXED_SCREENSHOT_DIR)
        await page.screenshot({path:path.join(process.env.FIXED_SCREENSHOT_DIR,`external-${width}.png`),fullPage:true});
    }
    const remote=page.locator('.external-source').first();
    await navigate(remote.getByRole('button',{name:'Disable Source',exact:true}));
    assert(!(await output(url)).includes('London recovered'));
    await navigate(page.locator('.external-source').first().getByRole('button',{name:'Enable Source',exact:true}));
    assert((await output(url)).includes('London recovered'));
    const cancelled=new Promise(resolve=>page.once('dialog',async dialog=>{await dialog.dismiss();resolve();}));
    await page.locator('.external-source').last().getByRole('button',{name:'Delete Source',exact:true}).click();
    await cancelled;
    assert((await output(url)).includes('Germany office'));
    page.once('dialog',dialog=>dialog.accept());
    await navigate(page.locator('.external-source').last().getByRole('button',{name:'Delete Source',exact:true}));
    assert(!(await output(url)).includes('Germany office'));
    assert.equal(await page.locator('.fixed-url').inputValue(),url);
    await page.locator('.source-refresh-interval').selectOption('');
    await navigate(page.locator('#generate-yaml'));
    assert.equal(await page.locator('.next-refresh').textContent(),'—');
    assert.equal(await page.locator('.fixed-url').inputValue(),url);
    assert.equal(await page.evaluate(()=>localStorage.getItem('clash-yaml-manager.draft.v1')),draft);
    assert(!(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).includes('PRIVATE'));
    assert.deepEqual(errors,[]);
    console.log('PASS External browser: Auto Off → 1h → save → next UTC → manual reschedule/history → Off; remote cache/recovery, upload, invalid replacement, disable/enable/delete, 1440/390 schedule/history layout, no secret browser storage');
    await context.close(); await anonymous.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
