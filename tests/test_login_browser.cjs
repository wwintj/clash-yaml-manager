/* Focused login acceptance in run_preview_browser's existing disposable app. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1');
assert(process.env.BOOTSTRAP_CSS_PATH);
const artifacts = process.env.UI_ARTIFACT_DIR || '/private/tmp/clash-login-ui';
fs.mkdirSync(artifacts, {recursive:true});
const matrix = [[320,568],[375,667],[390,844],[768,1024],[1440,900],[1920,1080]];
const audit = [];
const originalPassword = process.env.PREVIEW_TEST_PASSWORD;
assert(originalPassword);
async function navigate(page, action) { await Promise.all([page.waitForNavigation(), action()]); }
async function check(page, state, width, height) {
  const details = await page.evaluate(() => {
    const rect = e => {const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};};
    const panel=document.querySelector('.login-panel'), heading=panel.querySelector('h1');
    const shell=document.querySelector('.app-shell');
    const buttonStyle=getComputedStyle(panel.querySelector('[type=submit]'));
    const luminance=color=>color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
    const lights=[luminance(buttonStyle.color),luminance(buttonStyle.backgroundColor)].sort((a,b)=>a-b);
    return {overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
      buttonContrast:(lights[1]+.05)/(lights[0]+.05),
      panel:rect(panel),shell:rect(shell),title:rect(heading),titleLine:parseFloat(getComputedStyle(heading).lineHeight),
      viewport:document.documentElement.clientWidth,control:rect(document.querySelector('#password')),
      button:rect(panel.querySelector('[type=submit]')),
      messages:[...panel.querySelectorAll('[role=alert],[role=status]')].map(e=>({rect:rect(e),clipped:e.scrollWidth>e.clientWidth})),
      maxWidth:getComputedStyle(panel).maxWidth,text:panel.innerText,headings:document.querySelectorAll('h1').length};
  });
  assert.equal(details.overflow,0,`${state} ${width}: page overflow`);
  assert.equal(details.maxWidth,'400px');assert.equal(details.headings,1);
  assert(details.panel.left>=16 && details.panel.right<=details.viewport-16);
  assert(details.panel.width<=400 && details.control.width>0);
  for (const r of [details.button,details.control,...details.messages.map(m=>m.rect)])
    assert(r.left>=details.panel.left && r.right<=details.panel.right,`${state}: card content overflow`);
  assert(details.messages.every(m=>!m.clipped),`${state}: clipped message`);
  assert(Math.abs(details.button.height-44)<=1);
  assert(details.buttonContrast>=4.5,'Sign in text contrast');
  if(state==='normal') {
    assert(details.title.height<=details.titleLine+1,`${width}: unexpected title wrapping`);
    assert(Math.abs((details.panel.top+details.panel.bottom-details.shell.top-details.shell.bottom)/2)<=1,'Card centered in available shell');
    assert(details.panel.bottom<=height,'Normal card vertically visible');
  }
  for(const removed of ['Private VPS Tool','ONLINE','ACCESS PASSWORD','ERROR LOG','SUCCESS','Enter the management password to continue.'])
    assert(!details.text.includes(removed));
  audit.push({state,width,height,...details});
  if([390,1440].includes(width) && ['normal','error','success','csrf'].includes(state))
    await page.screenshot({path:path.join(artifacts,`login-${state}-${width}.png`),fullPage:true});
}
async function changePassword(context, page, current, next) {
  const token=await page.locator('[name=csrf_token]').first().inputValue();
  const response=await context.request.post(base+'/change-password',{form:{csrf_token:token,current_password:current,new_password:next,confirm_password:next},maxRedirects:0});
  assert.equal(response.status(),302);
  await page.goto(base);
  assert(await page.getByRole('status').filter({hasText:'Password updated. Log in again with the new password.'}).isVisible());
}
(async()=>{
  const browser=await chromium.launch({headless:true});
  try {
    for(const [width,height] of matrix) {
      const context=await browser.newContext({viewport:{width,height}}),page=await context.newPage(),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.route('**/*',route=>{
        const url=route.request().url();
        if(url.startsWith(base))return route.continue();
        if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css'))
          return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
        if(url.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'))
          return route.fulfill({path:process.env.BOOTSTRAP_JS_PATH,contentType:'text/javascript'});
        return route.abort();
      });
      await page.goto(base);
      const password=page.getByLabel('Password',{exact:true}),button=page.getByRole('button',{name:'Sign in',exact:true});
      assert(await password.evaluate(e=>document.activeElement===e && e.autocomplete==='current-password' && e.required));
      assert.equal(await password.getAttribute('name'),'password');
      await check(page,'normal',width,height);
      await page.keyboard.press('Tab');assert(await button.evaluate(e=>document.activeElement===e));
      assert(await button.evaluate(e=>parseFloat(getComputedStyle(e).outlineWidth)>=2));
      await page.keyboard.press('Shift+Tab');assert(await password.evaluate(e=>document.activeElement===e));
      assert(await password.evaluate(e=>parseFloat(getComputedStyle(e).outlineWidth)>=2));
      await page.keyboard.type('TEST_ONLY_INCORRECT_PASSWORD');
      await navigate(page,()=>page.keyboard.press('Enter'));
      assert.equal(await page.getByRole('alert').innerText(),'Login failed. Incorrect password.');
      assert.equal(await password.inputValue(),'');
      await check(page,'error',width,height);
      // One inert rendered-HTML fixture exercises long and multiple errors without new routes.
      const errorHtml=await page.content();
      await page.route(base+'/__login-long-message',route=>route.fulfill({body:errorHtml.replace('Login failed. Incorrect password.','Long message '+ 'x'.repeat(600)+'</li><li>Second error.'),contentType:'text/html'}));
      await page.goto(base+'/__login-long-message');await check(page,'long-errors',width,height);
      await page.goto(base);
      await page.locator('[name=csrf_token]').first().evaluate(e=>{e.value='invalid';});
      await password.fill('TEST_ONLY_CSRF_PASSWORD');
      await navigate(page,()=>password.press('Enter'));
      assert(await page.getByRole('status').filter({hasText:'Log in again; any saved draft will be restored after login.'}).isVisible());
      await check(page,'csrf',width,height);
      await password.fill(originalPassword);await navigate(page,()=>password.press('Enter'));
      for(const text of ['Clash YAML Manager','Change Password','Logout','Generate YAML','Fixed Subscriptions','Settings'])
        assert((await page.locator('.app-header').innerText()).includes(text));
      assert.equal(await page.locator('.login-panel').count(),0);
      // Exercise the actual success path; only the disposable app's password is changed.
      const temporaryPassword='TEST_ONLY_LOGIN_SUCCESS_PASSWORD';
      await changePassword(context,page,originalPassword,temporaryPassword);
      await check(page,'success',width,height);
      assert(await password.evaluate(e=>document.activeElement===e));
      await password.fill(temporaryPassword);await navigate(page,()=>password.press('Enter'));
      await changePassword(context,page,temporaryPassword,originalPassword);
      assert.deepEqual(errors,[]);await context.close();
    }
    // 200% desktop zoom reflow equivalent: half CSS viewport, doubled pixel density.
    const zoom=await browser.newContext({viewport:{width:720,height:450},deviceScaleFactor:2}),page=await zoom.newPage();
    await page.route('**/*',r=>r.request().url().startsWith(base)?r.continue():r.request().url().endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')?r.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'}):r.abort());
    await page.goto(base);await check(page,'zoom-reflow',720,450);await zoom.close();
    const limited=await browser.newContext(),retry=await limited.newPage();
    await retry.route('**/*',r=>r.request().url().startsWith(base)?r.continue():r.request().url().endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')?r.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'}):r.abort());
    await retry.goto(base);
    for(let i=0;i<5;i++) {
      await retry.locator('#password').fill('TEST_ONLY_RATE_LIMIT_PASSWORD');
      await navigate(retry,()=>retry.locator('#password').press('Enter'));
    }
    assert.equal(await retry.getByRole('alert').innerText(),'Too many login attempts. Try again in 900 seconds.');
    await check(retry,'rate-limit',1280,720);await limited.close();
    fs.writeFileSync(path.join(artifacts,'login-geometry.json'),JSON.stringify(audit,null,2));
    console.log(`PASS Login UI: ${audit.length} state/viewport checks; keyboard, Enter, real CSRF / success / rate-limit paths; screenshots: ${artifacts}`);
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
