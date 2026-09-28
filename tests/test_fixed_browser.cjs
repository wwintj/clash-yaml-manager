/* Real Flask CRUD and anonymous subscription reads; isolated runner only. */
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1');
const link = 'vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900}, permissions:['clipboard-read','clipboard-write']});
    const anonymous = await browser.newContext();
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      const url = route.request().url();
      if (url.startsWith(base)) return route.continue();
      if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
        return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
      return route.abort();
    });
    async function clickNavigate(locator) { await Promise.all([page.waitForNavigation(),locator.click()]); }
    async function publicRead(url, status) {
      const response = await anonymous.request.get(url);
      assert.equal(response.status(), status);
      return response.text();
    }
    const nav = () => clickNavigate(page.getByRole('link',{name:'Fixed Subscriptions',exact:true}));
    await page.goto(base); await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await Promise.all([page.waitForNavigation(), page.locator('#password').press('Enter')]);
    await page.locator('#batch_nodes').fill('temporary draft kept');
    await page.waitForTimeout(350);
    await nav();
    // Generate may flush its pending draft on pagehide. Snapshot after leaving it.
    const draft = await page.evaluate(() => localStorage.getItem('clash-yaml-manager.draft.v1'));
    assert.equal(JSON.parse(draft).batch, 'temporary draft kept');
    assert(await page.getByText('No fixed subscriptions yet.').isVisible());
    await clickNavigate(page.getByRole('link',{name:'Create Fixed Subscription',exact:true}));
    await page.locator('#subscription-name').fill('My Home Proxy');
    assert.equal(await page.locator('#url-prefix').inputValue(),'my-home-proxy');
    await page.locator('#yaml-source').selectOption('custom');
    await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules:\n- MATCH,DIRECT\n')});
    await page.locator('#batch_nodes').fill('UNKNOWN|Mystery|' + link);
    await page.locator('.aux-name').fill('Tokyo'); await page.locator('.aux-link').fill(link);
    await page.locator('[name=special_groups]').first().check();
    await page.locator('#parse-nodes').click();
    await page.waitForFunction(() => document.getElementById('parse-summary').textContent.includes('2 nodes detected'));
    await page.locator('.preview-name input').first().fill('Edited Mystery');
    await page.locator('.preview-action').first().click();
    await page.waitForFunction(() => !document.getElementById('parse-nodes').disabled);
    await clickNavigate(page.locator('#generate-yaml'));
    let url = await page.locator('.fixed-url').inputValue();
    assert(/\/s\/my-home-proxy-fs_[A-Za-z0-9_-]{22}$/.test(url));
    const first = await publicRead(url,200); assert(first.includes('Edited Mystery') && first.includes('其他节点'));
    await page.locator('.copy-fixed-url').click();
    await page.getByText('Copied',{exact:true}).waitFor();
    assert(await page.evaluate(() => navigator.clipboard.readText()) === url);
    assert.equal(await page.locator('#yaml-source').inputValue(),'custom');
    assert.equal(await page.locator('.aux-name').inputValue(),'Tokyo');
    assert(await page.locator('[name=special_groups]').first().isChecked());
    assert(await page.getByText('Current custom YAML: saved. Leave the upload empty to keep it.').isVisible());
    await page.locator('#subscription-name').fill('Renamed');
    await page.locator('#batch_nodes').fill('US|Updated|' + link);
    await clickNavigate(page.locator('#generate-yaml'));
    assert(await page.locator('.fixed-url').inputValue() === url);
    const updated = await publicRead(url,200); assert(updated.includes('Updated') && updated !== first);
    await page.locator('#batch_nodes').fill('not a valid node');
    await clickNavigate(page.locator('#generate-yaml'));
    assert(await page.getByText(/Unable to save/).isVisible());
    assert(await publicRead(url,200) === updated);
    await nav();
    assert(await page.getByText('Renamed',{exact:true}).isVisible());
    for (const width of [1440,390]) {
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      assert(await page.getByRole('button',{name:'Copy URL',exact:true}).isVisible());
      assert(await page.getByRole('button',{name:'Delete',exact:true}).isVisible());
      if (process.env.FIXED_SCREENSHOT_DIR)
        await page.screenshot({path:path.join(process.env.FIXED_SCREENSHOT_DIR,`fixed-${width}.png`),fullPage:true});
    }
    await clickNavigate(page.getByRole('button',{name:'Disable',exact:true})); await publicRead(url,404);
    await clickNavigate(page.getByRole('button',{name:'Enable',exact:true})); await publicRead(url,200);
    page.once('dialog', dialog => dialog.dismiss());
    await page.getByRole('button',{name:'Regenerate Link',exact:true}).click(); await publicRead(url,200);
    page.once('dialog', dialog => dialog.accept());
    await clickNavigate(page.getByRole('button',{name:'Regenerate Link',exact:true}));
    const replacement = await page.locator('.fixed-url').inputValue(); assert(replacement !== url);
    await publicRead(url,404); await publicRead(replacement,200);
    page.once('dialog', dialog => dialog.accept());
    await clickNavigate(page.getByRole('button',{name:'Delete',exact:true})); await publicRead(replacement,404);
    assert(await page.getByText('Fixed subscription deleted.',{exact:true}).isVisible());
    assert.equal(await page.evaluate(() => localStorage.getItem('clash-yaml-manager.draft.v1')),draft);
    assert.deepEqual(errors,[]);
    console.log('PASS Fixed browser: custom source, overrides, auxiliary/policies restore, Copy, stable URL edit, failed save, disable/enable, confirmed regenerate/delete, anonymous reads, desktop/mobile, isolated draft');
    await anonymous.close(); await context.close();
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
