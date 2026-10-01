/* Run via run_preview_browser.py: real DOM + real Flask, disposable test data. */
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1', 'Use the isolated loopback test runner');
const batch = [
  'US|GIA-Test|vless://11111111-1111-4111-8111-111111111111@192.0.2.10:443?security=tls&type=ws&sni=example.com&host=example.com&path=%2Fws',
  'Tokyo-Test|vless://22222222-2222-4222-8222-222222222222@198.51.100.20:443?security=tls&type=tcp',
  'vless://33333333-3333-4333-8333-333333333333@203.0.113.30:443?security=tls&type=tcp#Singapore-Test',
  'UNKNOWN|Mystery-Test|vless://44444444-4444-4444-8444-444444444444@192.0.2.40:443?security=tls&type=tcp'
].join('\n');
const summary = '4 nodes detected · 3 ready · 1 warning · 0 errors';
const warning = 'Country unknown. Choose a country or generate in the Other Nodes group.';
const near = (a, b) => assert(Math.abs(a - b) <= 1, `${a} differs from ${b}`);

async function geometry(page) {
  return page.locator('.preview-node').evaluateAll(rows => rows.map(row => {
    const rect = node => {
      const r = node.getBoundingClientRect();
      return {x:r.x, y:r.y, width:r.width, height:r.height, right:r.right};
    };
    const fields = [...row.children].map(rect);
    return {row:rect(row), fields, columns:getComputedStyle(row).gridTemplateColumns.split(' ').length,
      overflow:row.scrollWidth > row.clientWidth + 1,
      actionLineHeight:parseFloat(getComputedStyle(row.querySelector('.preview-action')).lineHeight),
      controls:[...row.querySelectorAll('input, select, button')].map(rect),
      wraps:getComputedStyle(row.querySelector('.preview-info')).overflowWrap};
  }));
}

async function test_preview_warning_does_not_collapse_columns(page, width) {
  const rows = await geometry(page);
  assert.equal(rows.length, 4);
  const ready = rows[0], unknown = rows[3];
  for (const row of rows) {
    assert(!row.overflow, 'Preview row overflows');
    assert.equal(row.wraps, 'anywhere');
    for (const control of row.controls) {
      assert(control.width > 0 && control.height > 0);
      assert(control.x >= row.row.x - 1 && control.right <= row.row.right + 1, 'Control clipped');
    }
    for (let i = 0; i < 4; i++) near(row.fields[i].width, ready.fields[i].width);
    near(row.fields[3].height, ready.fields[3].height);
    assert(row.fields[3].height < row.row.height, 'Action stretches to row height');
    assert(row.fields[3].height < row.actionLineHeight * 3, 'Action must retain a normal single-line height');
    if (width >= 1200) {
      assert.equal(row.columns, 4);
      assert(row.fields[0].width >= 180 && row.fields[1].width >= 280 && row.fields[2].width >= 220);
      for (const field of row.fields) near(field.y, row.fields[0].y);
    } else if (width >= 768) {
      assert.equal(row.columns, 2);
      near(row.fields[0].y, row.fields[1].y);
      near(row.fields[2].y, row.fields[3].y);
      near(row.fields[0].x, row.fields[2].x);
      near(row.fields[1].x, row.fields[3].x);
      assert(row.fields[2].y > row.fields[0].y);
      assert(row.fields[1].width >= 250);
    } else {
      assert.equal(row.columns, 1);
      for (let i = 0; i < 4; i++) {
        near(row.fields[i].x, row.row.x);
        near(row.fields[i].width, row.row.width);
        if (i) assert(row.fields[i].y >= row.fields[i-1].y + row.fields[i-1].height);
      }
    }
  }
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Page horizontal overflow');
  assert(unknown.fields[2].height > ready.fields[2].height, 'Warning text must remain visible');
  // Stress any long message and emulate regional indicators rendered as letters.
  await page.locator('.preview-info small').last().evaluate(node => node.textContent += 'W'.repeat(400));
  await page.locator('.preview-country option').evaluateAll(options => options.forEach(option => {
    option.textContent = option.textContent.replace(/[\u{1F1E6}-\u{1F1FF}]/gu,
      flag => String.fromCharCode(flag.codePointAt(0) - 0x1F1E6 + 65));
  }));
  const stressed = (await geometry(page))[3];
  assert(!stressed.overflow);
  for (const i of [0, 1, 3]) near(stressed.fields[i].width, unknown.fields[i].width);
  near(stressed.fields[3].height, unknown.fields[3].height);
  await page.locator('.preview-info small').last().evaluate((node, text) => node.textContent = text, warning);
}

(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    // Include both sides of each breakpoint as well as the three requested sizes.
    for (const [width, height] of [[1440,900], [1024,768], [390,844], [1200,900], [1199,900], [768,900], [767,900]]) {
      const context = await browser.newContext({viewport:{width,height}});
      const page = await context.newPage();
      const posts = [];
      page.on('request', request => { if (request.method() === 'POST') posts.push(new URL(request.url()).pathname); });
      const count = route => posts.filter(value => value === route).length;
      await page.route('**/*', route => {
        const url = route.request().url();
        if (url.startsWith(base)) return route.continue();
        if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')) {
          return process.env.BOOTSTRAP_CSS_PATH ? route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH, contentType:'text/css'}) : route.continue();
        }
        return route.abort();
      });
      await page.goto(base);
      assert(await page.evaluate(() => [...document.styleSheets].some(s => s.href?.includes('bootstrap'))), 'Bootstrap CSS must load');
      await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
      await Promise.all([page.waitForNavigation(), page.locator('#password').press('Enter')]);
      await page.locator('#batch_nodes').fill(batch);
      async function parse(action) {
        const response = page.waitForResponse(r => new URL(r.url()).pathname === '/parse-nodes');
        await action();
        assert.equal((await response).status(), 200);
        await page.waitForFunction(() => !document.getElementById('parse-nodes').disabled);
      }
      await parse(() => page.locator('#parse-nodes').click());
      assert.equal(await page.locator('#parse-summary').textContent(), summary);
      assert.equal(await page.locator('.preview-info small').last().textContent(), warning);
      await test_preview_warning_does_not_collapse_columns(page, width);
      if (process.env.PREVIEW_SCREENSHOT_DIR && [1440,1024,390].includes(width)) {
        await page.locator('#parse-preview').screenshot({path:path.join(process.env.PREVIEW_SCREENSHOT_DIR, `preview-${width}.png`)});
      }
      const search = page.locator('.preview-country .country-search').last();
      for (const query of ['JP', 'Japan', '日本']) {
        await search.fill(query);
        assert.equal(await page.locator('.preview-country select').last().locator('option[value=JP]').count(), 1);
      }
      const parseCount = count('/parse-nodes');
      await search.press('Enter');
      await page.waitForTimeout(100);
      assert.equal(count('/process'), 0);
      assert.equal(count('/parse-nodes'), parseCount);
      assert.equal(await search.inputValue(), '日本');
      await page.locator('.preview-country select').last().selectOption('JP');
      await page.locator('.preview-name input').last().fill('Edited Mystery');
      await page.locator('.preview-action').last().focus();
      assert(await page.locator('.preview-action').last().evaluate(button => document.activeElement === button));
      await parse(() => page.locator('.preview-action').last().press('Enter'));
      assert.equal(await page.locator('#parse-summary').textContent(), '4 nodes detected · 4 ready · 0 warning · 0 errors');
      assert((await page.locator('.preview-name input').last().inputValue()).includes('Edited Mystery'));
      await page.locator('#add-node-row').click();
      assert.equal(await page.locator('#aux-node-rows .node-row').count(), 2);
      await page.locator('.remove-node-row').last().click();
      assert.equal(await page.locator('#aux-node-rows .node-row').count(), 1);
      assert.equal(count('/process'), 0);
      await Promise.all([page.waitForNavigation(), page.locator('#generate-yaml').click()]);
      assert.equal(count('/process'), 1);
      assert.equal(await page.locator('#download-url').count(), 1);
      assert.equal(await page.locator('#draft-status').textContent(), 'Draft restored');
      assert.equal(await page.locator('#batch_nodes').inputValue(), batch);
      await context.close();
      console.log(`PASS ${width}x${height}: warning column stability, wrapping, geometry, keyboard, overrides, generate and draft`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
