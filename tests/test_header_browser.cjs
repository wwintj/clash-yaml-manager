/* Compact authenticated chrome in the existing disposable Flask/Bootstrap harness. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname==='127.0.0.1');
assert(process.env.BOOTSTRAP_CSS_PATH && process.env.BOOTSTRAP_JS_PATH);
const artifacts = process.env.UI_ARTIFACT_DIR || '/private/tmp/clash-header-ui';
fs.mkdirSync(artifacts,{recursive:true});
const matrix = [[320,568],[375,667],[390,844],[768,1024],[1024,768],[1440,900],[1920,1080]];
const routes = [['generate','/'],['fixed','/fixed-subscriptions'],['settings','/settings']];
const audit=[];
async function navigate(page,action) {await Promise.all([page.waitForNavigation(),action()]);}
async function check(page,name,width,height) {
  const data=await page.evaluate(()=>{
    const header=document.querySelector('.app-header'), nav=header.querySelector('[aria-label="Main navigation"]');
    const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
    const title=header.querySelector('h1'),actions=header.querySelector('.app-header-actions');
    const links=[...nav.querySelectorAll('a')].map(e=>{
      const s=getComputedStyle(e),range=document.createRange();range.selectNodeContents(e);
      return {href:e.getAttribute('href'),label:e.textContent.trim(),active:e.getAttribute('aria-current'),rect:rect(e),
        textFits:range.getBoundingClientRect().width<=e.getBoundingClientRect().width-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)+1};
    });
    return {overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,header:rect(header),
      title:rect(title),actions:rect(actions),links,headerText:header.innerText,titleFont:parseFloat(getComputedStyle(title).fontSize),
      titleWeight:getComputedStyle(title).fontWeight,h1Count:document.querySelectorAll('h1').length,
      topChrome:header.nextElementSibling.getBoundingClientRect().top-header.getBoundingClientRect().top,
      accountButtons:[...actions.querySelectorAll('button')].map(e=>({rect:rect(e),utility:e.classList.contains('btn-sm')}))};
  });
  assert.equal(data.overflow,0,`${name} ${width}: page overflow`);assert.equal(data.h1Count,1);
  assert.equal(data.titleWeight,'600');assert(data.titleFont>=20 && data.titleFont<=24);
  assert(data.header.left>=16 && data.header.right<=width-16);
  assert(data.title.bottom<=data.actions.top || data.title.right<=data.actions.left,'Title must not crowd account actions');
  if(width<=575) assert(data.actions.top>=data.title.bottom,'Mobile title has its own row');
  for(const word of ['YAML NODE MANAGEMENT','Service','ONLINE','Mode','Parser','VMESS','Backend','FLASK'])
    assert(!data.headerText.includes(word),`Removed header metadata: ${word}`);
  assert.deepEqual(data.links.map(l=>l.href),routes.map(r=>r[1]));
  assert.deepEqual(data.links.filter(l=>l.active==='page').map(l=>l.href),[routes.find(r=>r[0]===name)[1]]);
  for(const l of data.links) assert(l.textFits && l.rect.left>=data.header.left && l.rect.right<=data.header.right);
  for(const button of data.accountButtons) {
    assert(button.utility);assert(Math.abs(button.rect.height-(width<=575?40:32))<=1);
    assert(button.rect.left>=data.header.left && button.rect.right<=data.header.right);
  }
  audit.push({name,width,height,...data});
  if([320,390,1440].includes(width)) {
    const mask=[page.locator('.fixed-url, #download-url')];
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({mask,path:path.join(artifacts,`header-${name}-${width}.png`)});
    await page.locator('.app-header').screenshot({path:path.join(artifacts,`header-${name}-${width}-detail.png`)});
  }
}
async function keyboard(page) {
  const trigger=page.getByRole('button',{name:'Change Password',exact:true});
  await trigger.focus();
  assert(await trigger.evaluate(e=>parseFloat(getComputedStyle(e).outlineWidth)>=2));
  await Promise.all([page.evaluate(()=>new Promise(resolve=>document.getElementById('changePasswordModal').addEventListener('shown.bs.modal',()=>resolve(true),{once:true}))),trigger.press('Enter')]);
  const modal=page.locator('#changePasswordModal');assert(await modal.isVisible());
  const current=modal.getByLabel('Current password',{exact:true}),next=modal.getByLabel('New password',{exact:true});
  await current.focus();await page.keyboard.press('Tab');assert(await next.evaluate(e=>document.activeElement===e));
  await page.keyboard.press('Shift+Tab');assert(await current.evaluate(e=>document.activeElement===e));
  // Required fields keep Enter from posting an empty password-change form.
  await current.press('Enter');assert(await modal.isVisible());
  await Promise.all([page.evaluate(()=>new Promise(resolve=>document.getElementById('changePasswordModal').addEventListener('hidden.bs.modal',()=>resolve(true),{once:true}))),page.keyboard.press('Escape')]);
  assert(await trigger.evaluate(e=>document.activeElement===e));
  const targets=[page.getByRole('button',{name:'Logout',exact:true}),...['Generate YAML','Fixed Subscriptions','Settings'].map(name=>page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name,exact:true}))];
  for(const target of targets) {
    await page.keyboard.press('Tab');assert(await target.evaluate(e=>document.activeElement===e));
    assert(await target.evaluate(e=>parseFloat(getComputedStyle(e).outlineWidth)>=2));
  }
  await page.keyboard.press('Shift+Tab');assert(await targets[2].evaluate(e=>document.activeElement===e));
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    for(const [width,height] of matrix) {
      const context=await browser.newContext({viewport:{width,height}}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*',route=>{
        const url=route.request().url();if(url.startsWith(base))return route.continue();
        if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css'))return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
        if(url.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'))return route.fulfill({path:process.env.BOOTSTRAP_JS_PATH,contentType:'text/javascript'});
        return route.abort();
      });
      await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
      await navigate(page,()=>page.locator('#password').press('Enter'));
      for(const [name,url] of routes) {
        const response=await page.goto(base+url);assert.equal(response.status(),200);
        await check(page,name,width,height);await keyboard(page);
        const active=page.getByRole('navigation',{name:'Main navigation'}).locator(`a[href="${url}"]`);
        const before=await active.boundingBox();await active.evaluate(e=>e.removeAttribute('aria-current'));
        const after=await active.boundingBox();assert.deepEqual(after,before,'Active style must not change link geometry');
        await active.evaluate(e=>e.setAttribute('aria-current','page'));
      }
      const post=page.waitForRequest(r=>new URL(r.url()).pathname==='/logout' && r.method()==='POST');
      await navigate(page,()=>page.getByRole('button',{name:'Logout',exact:true}).click());
      assert(new URLSearchParams((await post).postData()).get('csrf_token'),'Logout carries CSRF');
      assert(await page.getByRole('button',{name:'Sign in',exact:true}).isVisible());
      assert.equal((await context.request.get(base+'/settings',{maxRedirects:0})).status(),302);
      assert.deepEqual(errors,[]);await context.close();
    }
    fs.writeFileSync(path.join(artifacts,'header-geometry.json'),JSON.stringify(audit,null,2));
    console.log(`PASS Header UI: ${audit.length} page/viewport checks; integrated nav, scoped metadata removal, active geometry, modal Enter/Tab/Escape, Logout POST + CSRF; screenshots: ${artifacts}`);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
