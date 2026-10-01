/* Policy controls and saved YAML only; isolated Flask fixture, no real probes. */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900}});
    const page = await context.newPage();
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>{
      const url=route.request().url();
      if (url.startsWith(base)) return route.continue();
      if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
        return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
      return route.abort();
    });
    const nav=button=>Promise.all([page.waitForNavigation(),button.click()]);
    const country=page.locator('#policy_country_groups_type');
    const special=page.locator('#policy_special_groups_type');
    const prefix='#policy_country_groups_';
    const uuid='11111111-1111-4111-8111-111111111111';
    const link=`vless://${uuid}@example.com:443?type=tcp`;
    const input='US|Policy A|'+link+'\nUS|Policy B|'+link.replace('example.com','second.example');
    const widths=async label=>{
      for (const width of [1440,390]) {
        await page.setViewportSize({width,height:900});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),label+' overflow '+width);
        assert(await country.isVisible());assert(await special.isVisible());
        if (process.env.POLICY_SCREENSHOT_DIR) {
          fs.mkdirSync(process.env.POLICY_SCREENSHOT_DIR,{recursive:true});
          await page.screenshot({path:path.join(process.env.POLICY_SCREENSHOT_DIR,`policy-${label}-${width}.png`),fullPage:true});
          await page.locator('section[aria-label="Policy Engine"]').screenshot({path:path.join(process.env.POLICY_SCREENSHOT_DIR,`policy-section-${label}-${width}.png`)});
        }
      }
    };
    const visibility=async kind=>{
      await country.selectOption(kind);
      const auto=['url-test','fallback','load-balance'].includes(kind);
      assert.equal(await page.locator(prefix+'url').isVisible(),auto);
      assert.equal(await page.locator(prefix+'interval').isEnabled(),auto);
      assert.equal(await page.locator(prefix+'tolerance').isVisible(),kind==='url-test');
      assert.equal(await page.locator(prefix+'tolerance').isEnabled(),kind==='url-test');
      assert.equal(await page.locator(prefix+'strategy').isVisible(),kind==='load-balance');
    };
    await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
    assert.equal(await country.inputValue(),'preserve');assert.equal(await special.inputValue(),'preserve');
    for (const kind of ['select','url-test','fallback','load-balance','preserve']) await visibility(kind);
    await country.selectOption('url-test');await special.selectOption('fallback');
    await page.locator('#batch_nodes').fill(input);
    await page.locator(prefix+'url').fill('http://client.local/check');
    await widths('generate');
    // Bypass HTML constraints to verify server rejection and editable values.
    await page.locator(prefix+'interval').fill('0');
    await page.locator('#process-form').evaluate(form=>{form.noValidate=true;});
    await nav(page.locator('#generate-yaml'));
    assert.equal(await country.inputValue(),'url-test');assert.equal(await page.locator(prefix+'interval').inputValue(),'0');
    assert.equal(await page.locator(prefix+'url').inputValue(),'http://client.local/check');
    assert(await page.getByText(/Invalid Policy settings/).isVisible());
    const storage=await page.evaluate(()=>localStorage.getItem('clash-yaml-manager.draft.v1'));
    assert(!storage.includes('client.local') && !storage.includes('policy_country_groups'));
    await page.locator(prefix+'interval').fill('300');
    await nav(page.locator('#generate-yaml'));
    const temporary=await page.locator('#download-url').inputValue();assert(temporary.includes('/t/'));
    const generated=await context.request.get(temporary);assert.equal(generated.status(),200);
    assert((await generated.text()).includes('type: url-test'));
    assert.equal(await country.inputValue(),'preserve'); // No persistent temp Policy state.
    await page.goto(base+'/fixed-subscriptions/new');
    assert.equal(await country.inputValue(),'preserve');assert.equal(await special.inputValue(),'preserve');
    await page.locator('#subscription-name').fill('Policy Browser');
    await page.locator('#yaml-source').selectOption('custom');
    await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',buffer:Buffer.from(
      'proxy-groups:\n- name: "🇺🇸 美国节点"\n  type: select\n  proxies: [DIRECT]\n  icon: kept\nrules: ["MATCH,🇺🇸 美国节点"]\n')});
    await page.locator('#batch_nodes').fill(input);
    await country.selectOption('url-test');await special.selectOption('load-balance');
    await page.locator('[name=special_groups]').first().check();
    await page.locator(prefix+'url').fill('http://client.local/check');await page.locator(prefix+'interval').fill('600');
    await page.locator(prefix+'tolerance').fill('70');await page.locator(prefix+'lazy').selectOption('false');
    await nav(page.locator('#generate-yaml'));
    const fixed=await page.locator('.fixed-url').inputValue();
    const read=async()=>{const r=await context.request.get(fixed);assert.equal(r.status(),200);return r.text();};
    let yaml=await read();assert(yaml.includes('type: url-test')&&yaml.includes('interval: 600')&&yaml.includes('tolerance: 70'));
    assert.equal(await country.inputValue(),'url-test');assert.equal(await special.inputValue(),'load-balance');
    assert.equal(await page.locator(prefix+'url').inputValue(),'http://client.local/check');
    assert.equal(await page.locator(prefix+'lazy').inputValue(),'false');
    await widths('fixed');
    await page.locator('#batch_nodes').fill('invalid node');await nav(page.locator('#generate-yaml'));
    assert(await page.getByText(/Unable to save/).isVisible());
    assert.equal(await country.inputValue(),'url-test');assert.equal(await read(),yaml);
    await page.locator('#batch_nodes').fill(input);
    for (const kind of ['fallback','load-balance','select','preserve']) {
      await visibility(kind);await special.selectOption(kind);await nav(page.locator('#generate-yaml'));
      assert.equal(await page.locator('.fixed-url').inputValue(),fixed);
      assert.equal(await country.inputValue(),kind);
      yaml=await read();assert(yaml.includes('type: '+(kind==='preserve'?'select':kind)));
      if (kind==='load-balance') assert(yaml.includes('strategy: round-robin'));
      if (kind==='select'||kind==='preserve') assert(!/\n\s+(url|interval|tolerance|lazy|strategy):/.test(yaml));
    }
    assert.deepEqual(errors,[]);
    console.log('PASS Policy browser: Generate + Fixed defaults, type options, local URL, no temp policy persistence, rejection recovery, saved options, stable /s, transitions, 1440/390 no overflow');
    await context.close();
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
