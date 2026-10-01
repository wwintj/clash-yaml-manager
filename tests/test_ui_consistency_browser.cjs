/* Full live-page UI contract in the disposable Flask harness. No real services. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1');
assert(process.env.BOOTSTRAP_JS_PATH, 'UI dialog audit needs cached Bootstrap 5.3.3 bundle via BOOTSTRAP_JS_PATH');
const artifacts = process.env.UI_ARTIFACT_DIR || '/private/tmp/clash-ui-v131';
fs.mkdirSync(artifacts, {recursive:true});
const widths = [1440,1280,1024,768,430,390,360];
const batch = 'US|UI Node|vless://11111111-1111-4111-8111-111111111111@8.8.8.8:443?type=tcp\nUNKNOWN|Mystery|trojan://TEST_ONLY_UI_PASSWORD@8.8.4.4:443';
const source = 'proxies: []\nproxy-groups: []\nrules: [MATCH,DIRECT]\nx-long-value: '+ 'W'.repeat(900)+'\n';
const audit = [];
const knownOldCopy = ['請輸入管理密碼', '每行支援', '新增多個節點', '勾選後', '修改管理密碼', '安全令牌已刷新', '节点解析失败', 'Policy 配置无效', '没有提供任何有效的新节点', 'Generate as 其他节点'];
async function navigate(page, action) { await Promise.all([page.waitForNavigation(),action()]); }
async function upload(page) {
  await page.locator('#yaml-source').selectOption('custom');
  await page.locator('[name=yaml_file]').setInputFiles({name:'ui.yaml',mimeType:'application/yaml',buffer:Buffer.from(source)});
}
async function action(page,id,route) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === route);
  await page.locator(id).click();
  const received = await response;
  await page.waitForFunction(id => !document.querySelector(id).disabled,id);
  return received;
}
async function check(page,name,width,shotSelector) {
  const details = await page.evaluate(() => {
    const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
    const bodyFont = getComputedStyle(document.body).fontFamily;
    const fonts = [...document.querySelectorAll('h1,h2,h3,h4,h5,label,.status-value,.badge,.health-badge,button,input,select,textarea,.panel-subtitle,.helper-text,.form-text')]
      .filter(e => visible(e) && !e.matches('[type=hidden],.mono,.aux-link,.fixed-url,textarea.terminal-input') && !e.closest('pre,code,.mono'))
      .filter(e => getComputedStyle(e).fontFamily !== bodyFont).map(e => ({tag:e.tagName,cls:e.className,font:getComputedStyle(e).fontFamily}));
    const navs = [...document.querySelectorAll('.ui-nav')].filter(visible).map(nav => {
      const links = [...nav.querySelectorAll('a')];
      return {label:nav.getAttribute('aria-label'),current:links.filter(a => a.hasAttribute('aria-current')).length,
        height:links.map(a => a.getBoundingClientRect().height),padding:links.map(a => getComputedStyle(a).paddingInline),
        usable:links.every(a => {const r=a.getBoundingClientRect();return r.width>0 && r.left>=0 && r.right<=document.documentElement.clientWidth;})};
    });
    const controls = [...document.querySelectorAll('input.form-control:not([type=hidden]),select.form-select')].filter(visible)
      .map(e => e.getBoundingClientRect().height);
    const buttons = [...document.querySelectorAll('.btn-terminal')].filter(visible).map(e => {
      const r=e.getBoundingClientRect(),s=getComputedStyle(e);
      const range=document.createRange();range.selectNodeContents(e);const text=range.getBoundingClientRect();
      return {label:e.innerText,center:Math.abs((text.top+text.bottom-r.top-r.bottom)/2),
        fits:text.width<=r.width-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)+1,
        height:r.height,display:s.display,align:s.alignItems,justify:s.justifyContent};
    });
    return {overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,fonts,navs,controls,buttons,
      language:document.documentElement.lang,text:document.body.innerText,
      shellPadding:parseFloat(getComputedStyle(document.querySelector('.app-shell')).paddingLeft)};
  });
  assert.equal(details.overflow,0,`${name} ${width}: page overflow`);
  assert.equal(details.language,'en');
  assert.deepEqual(details.fonts,[],`${name} ${width}: font mismatch`);
  assert(details.shellPadding>=16);
  for(const old of knownOldCopy) assert(!details.text.includes(old),`${name}: old UI copy ${old}`);
  for(const nav of details.navs) {
    assert.equal(nav.current,1,`${name}: active ${nav.label}`);
    assert(Math.max(...nav.height)-Math.min(...nav.height)<=1,`${name}: nav height`);
    assert.equal(new Set(nav.padding).size,1);assert(nav.usable);
  }
  if(details.controls.length) assert(Math.max(...details.controls)-Math.min(...details.controls)<=1,`${name}: input/select heights`);
  for(const button of details.buttons) {
    assert(button.center<=2,`${name}: text centering ${button.label}: ${button.center}`);
    assert(button.fits,`${name}: button text clipped ${button.label}`);
    assert(['inline-flex','flex'].includes(button.display));assert.equal(button.align,'center');assert.equal(button.justify,'center');
  }
  audit.push({page:name,width,overflow:details.overflow,navs:details.navs.map(n=>({label:n.label,height:n.height})),controls:details.controls.length,buttons:details.buttons.length});
  if([1440,390].includes(width) && shotSelector) {
    await page.screenshot({path:path.join(artifacts,`${name}-${width}-full.png`),fullPage:true});
    const target=page.locator(shotSelector).first();await target.scrollIntoViewIfNeeded();
    if(['generate','fixed-edit','fixed-create','fixed-list'].includes(name)) await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(artifacts,`${name}-${width}.png`)});
    // Section detail is readable even when the complete mobile page is very tall.
    await target.screenshot({path:path.join(artifacts,`${name}-${width}-detail.png`)});
  }
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  if(process.env.EXTERNAL_TEST_CONTROL) {
    const setup=await browser.newContext();await setup.request.post(process.env.EXTERNAL_TEST_CONTROL,{data:'notifications-clear'});await setup.close();
  }
  try {
    for(const width of widths) {
      const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*',route=>{
        const url=route.request().url();if(url.startsWith(base))return route.continue();
        if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
          return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
        if(url.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'))
          return route.fulfill({path:process.env.BOOTSTRAP_JS_PATH,contentType:'text/javascript'});
        return route.abort();
      });
      await page.goto(base);assert(await page.getByText('Enter the management password to continue.').isVisible());
      await check(page,'login',width,'.login-panel');
      await page.locator('#password').fill('UI_INCORRECT_PASSWORD');
      await navigate(page,()=>page.locator('#password').press('Enter'));
      assert(await page.getByText('Login failed. Incorrect password.').isVisible());await check(page,'login-error',width);
      await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
      await navigate(page,()=>page.locator('#password').press('Enter'));
      await check(page,'generate',width,'#process-form');
      const groupLabels=await page.locator('[name=special_groups]').evaluateAll(controls=>controls.map(e=>e.closest('label').innerText.trim()));
      assert.equal(groupLabels.length,8);assert(groupLabels.every(Boolean),'Every policy checkbox must have a visible label');
      // Real Bootstrap modal, keyboard focus, close and non-empty password copy.
      const trigger=page.getByRole('button',{name:'Change Password',exact:true});
      await Promise.all([page.evaluate(()=>new Promise(resolve=>document.getElementById('changePasswordModal').addEventListener('shown.bs.modal',()=>resolve(true),{once:true}))),trigger.click()]);
      await page.locator('#changePasswordModal').waitFor({state:'visible'});
      assert(await page.getByLabel('Current password',{exact:true}).isVisible());
      assert(await page.getByText('Any non-empty password is accepted. Spaces and Unicode are preserved.').isVisible());
      await page.getByLabel('Current password',{exact:true}).focus();
      assert(await page.getByLabel('Current password',{exact:true}).evaluate(e=>document.activeElement===e));
      assert(await page.getByLabel('Current password',{exact:true}).evaluate(e=>parseFloat(getComputedStyle(e).outlineWidth)>0));
      await check(page,'password-dialog',width,width===390?'#changePasswordModal':null);
      await Promise.all([page.evaluate(()=>new Promise(resolve=>document.getElementById('changePasswordModal').addEventListener('hidden.bs.modal',()=>resolve(true),{once:true}))),page.keyboard.press('Escape')]);
      await page.locator('#changePasswordModal').waitFor({state:'hidden'});
      assert(await trigger.evaluate(e=>document.activeElement===e));
      await page.locator('#batch_nodes').fill('PRIVATE_BAD_NODE');
      await action(page,'#parse-nodes','/parse-nodes');
      assert((await page.locator('.preview-info small').innerText()).includes('Unsupported protocol.'));
      await page.locator('#batch_nodes').fill(batch);await upload(page);
      await action(page,'#parse-nodes','/parse-nodes');
      assert((await page.locator('.preview-info small').last().innerText()).includes('Other Nodes group'));
      assert(!(await page.locator('#parse-preview').innerText()).includes('TEST_ONLY_UI_PASSWORD'));
      await check(page,'generate-parsed',width,'#parse-preview');
      const diff=await action(page,'#preview-yaml-diff','/api/preview-yaml-diff');assert.equal(diff.status(),200);
      const json=await diff.json();assert.equal(await page.locator('#yaml-diff-code').textContent(),json.diff);
      assert(await page.locator('#yaml-diff-text').evaluate(e=>e.scrollWidth>e.clientWidth && getComputedStyle(e).overflowX==='auto'));
      await check(page,'diff',width,'#yaml-diff-panel');
      await navigate(page,()=>page.locator('#generate-yaml').click());
      assert(await page.getByText('YAML generated. Download it or remove the temporary files.').isVisible());
      await check(page,'generate-result',width,'#generate-result');
      await page.goto(base+'/fixed-subscriptions');await check(page,'fixed-list-before',width);
      await page.goto(base+'/fixed-subscriptions/new');await check(page,'fixed-create',width,'#process-form');
      await page.locator('#subscription-name').fill(`UI audit ${width}`);await upload(page);await page.locator('#batch_nodes').fill(batch);
      await navigate(page,()=>page.locator('#generate-yaml').click());
      const edit=page.url();assert(edit.endsWith('/edit'));await check(page,'fixed-edit',width,'#process-form');
      await page.locator('#add-remote-source').click();await page.locator('#add-uploaded-source').click();
      await check(page,'fixed-source-editor',width,'#external-source-section');
      // Unsaved source cards exercise layout only; never fetch external sources.
      await page.goto(edit);
      for(const section of ['#node-health','#proxy-health']) await check(page,section.slice(1),width,section);
      await page.goto(base+'/fixed-subscriptions');await check(page,'fixed-list',width,'.fixed-table');
      const deletion=page.locator('form[data-confirm]').last().locator('button');
      let confirmation;page.once('dialog',async d=>{confirmation=d.message();await d.dismiss();});
      await deletion.click();assert(confirmation?.includes('Delete this fixed subscription?'));
      await page.goto(base+'/settings');
      if([1440,390].includes(width)) await page.screenshot({path:path.join(artifacts,`settings-navigation-${width}.png`)});
      for(const section of ['overview','geoip','health','runtime','notifications']) {
        const tab=page.getByRole('navigation',{name:'Settings sections'}).getByRole('link',{name:{overview:'Overview',geoip:'GeoIP',health:'Health',runtime:'Runtime',notifications:'Notifications'}[section],exact:true});
        await tab.click();await page.waitForFunction(section=>document.querySelector('.settings-nav a[href="#'+section+'"]').getAttribute('aria-current')==='location',section);assert.equal(await tab.getAttribute('aria-current'),'location');
        await check(page,`settings-${section}`,width,`#${section}`);
      }
      assert(await page.locator('#notification-test button').evaluate(e=>e.disabled));
      assert.deepEqual(errors,[]);await context.close();
      console.log(`PASS UI ${width}: all pages, nav/forms/fonts, active states, button geometry, language, focus, dialogs, no overflow`);
    }
    // Server-rendered English authentication/error/help and anchor forms without JS.
    const context=await browser.newContext({javaScriptEnabled:false}),page=await context.newPage();
    await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
    await navigate(page,()=>page.locator('#password').press('Enter'));
    await page.goto(base+'/settings');assert(await page.getByText('System Settings',{exact:true}).isVisible());
    await page.getByRole('navigation',{name:'Settings sections'}).getByRole('link',{name:'Runtime',exact:true}).click();
    assert(page.url().endsWith('#runtime'));await context.close();
    fs.writeFileSync(path.join(artifacts,'geometry.json'),JSON.stringify(audit,null,2));
    console.log(`PASS UI consistency: ${audit.length} live page/width checks; screenshots: ${artifacts}`);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
