/* Fixed list enhancements in a disposable Flask copy; all resources stay local. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.PREVIEW_TEST_URL;
const control = process.env.FIXED_UX_TEST_CONTROL;
assert(base && new URL(base).hostname === '127.0.0.1');
assert(control && new URL(control).hostname === '127.0.0.1');
assert(process.env.BOOTSTRAP_CSS_PATH, 'Use the cached Bootstrap CSS; do not contact a CDN');
const artifacts = process.env.FIXED_UX_ARTIFACT_DIR || '/private/tmp/clash-fixed-ux';
fs.mkdirSync(artifacts, {recursive:true});
const widths = [1440,1280,1024,768,430,390,360];
const longPrefix = 'long-' + 'p'.repeat(59);
const alpha = 'alpha-first', beta = 'beta-disabled', gamma = 'gamma-active';
const alphaTie = 'alpha-second', tokyo = 'tokyo-unicode';
// Independent fixture expectations, including numeric 10 vs 2 and stable ties.
const sortGroups = {
  'updated-desc':[[longPrefix],[gamma],[alpha,beta,alphaTie],[tokyo]],
  'updated-asc':[[tokyo],[alpha,beta,alphaTie],[gamma],[longPrefix]],
  'name-asc':[[alpha,alphaTie],[beta],[gamma],[longPrefix],[tokyo]],
  'name-desc':[[tokyo],[longPrefix],[gamma],[beta],[alpha,alphaTie]],
  'nodes-desc':[[beta],[tokyo,longPrefix],[alpha,alphaTie],[gamma]],
  'nodes-asc':[[gamma],[alpha,alphaTie],[tokyo,longPrefix],[beta]]
};
let orders;
const defaultSubset = prefixes => orders['updated-desc'].filter(prefix => prefixes.includes(prefix));
const audit = {responsive:[],sort:[],search:[],health:[],copy:{},noJS:{},performance:{}};

async function resources(context) {
  await context.route('**/*', route => {
    const url = route.request().url();
    if (url.startsWith(base)) return route.continue();
    if (url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css'))
      return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH, contentType:'text/css'});
    if (url.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js') && process.env.BOOTSTRAP_JS_PATH)
      return route.fulfill({path:process.env.BOOTSTRAP_JS_PATH, contentType:'text/javascript'});
    return route.abort();
  });
}
async function login(page) {
  await page.goto(base);
  await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
}
const rows = page => page.locator('.fixed-table tbody tr[data-name]');
const row = (page,prefix) => page.locator(`.fixed-table tbody tr[data-prefix="${prefix}"]`);
const visibleOrder = page => rows(page).evaluateAll(elements => elements.filter(e => !e.hidden).map(e => e.dataset.prefix));
async function matching(page, expected) {
  assert.deepEqual(await visibleOrder(page), expected);
  const total = await rows(page).count();
  assert.equal((await page.locator('#fixed-result-count').textContent()).trim(),
    `${expected.length === total ? total : `${expected.length} of ${total}`} ${total===1?'subscription':'subscriptions'}`);
}
async function clear(page) {
  if (await page.locator('#fixed-clear').isEnabled()) await page.locator('#fixed-clear').click();
  assert.equal(await page.locator('#fixed-search').inputValue(),'');
  assert.equal(await page.locator('#fixed-status').inputValue(),'all');
  assert.equal(await page.locator('#fixed-sort').inputValue(),'updated-desc');
}
async function shot(page, name, width) {
  await page.setViewportSize({width,height:900});
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({path:path.join(artifacts,`${name}-${width}.png`)});
  await page.screenshot({path:path.join(artifacts,`${name}-${width}-full.png`),fullPage:true});
  if (await rows(page).count() && !await page.locator('.fixed-list-region').isHidden()) {
    const target = name==='fixed-health-warning' ? row(page,gamma) : row(page,longPrefix);
    if (await target.isVisible())
      await target.screenshot({path:path.join(artifacts,`${name}-${width}-row.png`)});
  }
}
async function privacy(page, fixture) {
  const observed = await page.evaluate(() => {
    const documentCopy = document.documentElement.cloneNode(true);
    documentCopy.querySelectorAll('.fixed-url').forEach(input => input.removeAttribute('value'));
    return {html:documentCopy.outerHTML, storage:JSON.stringify({local:{...localStorage},session:{...sessionStorage}}),
      datasets:[...document.querySelectorAll('.fixed-table tbody tr[data-name]')].map(e => ({...e.dataset})),
      forbidden:document.querySelectorAll('[data-token],[data-public-url],[data-source-url],[data-node-uri],[data-health-node-name]').length};
  });
  assert.equal(observed.forbidden,0);
  for (const secret of fixture.secrets) {
    assert(!observed.html.includes(secret),'Private node/source/health data must not appear in list HTML');
    assert(!observed.storage.includes(secret),'Private data must not enter browser storage');
  }
  for (const item of observed.datasets) {
    assert.deepEqual(Object.keys(item).sort(),['name','nodeCount','prefix','status','updated']);
    assert(!Object.values(item).some(value => value.includes('fs_') || value.includes('://')));
  }
  for (const entry of fixture.entries) {
    const token = entry.url.split('fs_')[1];
    assert(!observed.html.includes(token),'Bearer token remains only in the existing authenticated URL input');
    assert(!observed.storage.includes(token));
  }
}
async function layout(page,width) {
  await page.setViewportSize({width,height:900});
  const detail = await page.evaluate(() => {
    const visible = element => element.getClientRects().length && !element.closest('[hidden]');
    const boxes = [...document.querySelectorAll('#fixed-toolbar input,#fixed-toolbar select,#fixed-clear')].filter(visible)
      .map(e => ({id:e.id,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}));
    const buttons = [...document.querySelectorAll('.fixed-actions .btn,.copy-fixed-url,#fixed-clear')].filter(visible).map(e => {
      const r=e.getBoundingClientRect(), range=document.createRange();range.selectNodeContents(e);const text=range.getBoundingClientRect();
      return {text:e.innerText,height:r.height,width:r.width,standard:e.tagName==='A',
        center:Math.abs((text.top+text.bottom-r.top-r.bottom)/2),fits:text.width<=r.width+1};
    });
    const names = [...document.querySelectorAll('.fixed-name')].filter(visible).map(e=>({scroll:e.scrollWidth,width:e.clientWidth}));
    return {overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
      viewport:innerWidth,boxes,buttons,names,language:document.documentElement.lang};
  });
  assert.equal(detail.overflow,0,`Fixed list document overflow at ${width}`);
  assert.equal(detail.language,'en');
  assert(detail.boxes.every(e=>e.left>=0 && e.right<=width+1),'Toolbar controls stay in the viewport');
  for (const button of detail.buttons) {
    assert(button.center<=2,`Button centered at ${width}: ${button.text}`);
    assert(button.fits,`Button text not clipped: ${button.text}`);
    const expected=button.standard?(width<=575?44:40):(width<=575?40:32);
    assert(Math.abs(button.height-expected)<=1,`Action density at ${width}: ${button.text}`);
    assert(button.width>0);
  }
  if(width<=767) {
    assert(await rows(page).evaluateAll(elements=>elements.filter(e=>!e.hidden).every(e=>getComputedStyle(e).display==='block')));
    assert(await rows(page).evaluateAll(elements=>elements.filter(e=>!e.hidden).every(e=>e.getBoundingClientRect().right<=innerWidth+1)));
  }
  audit.responsive.push({width,...detail});
}

(async()=>{
  const browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:900},permissions:['clipboard-read','clipboard-write']});
  const anonymous=await browser.newContext();
  const page=await context.newPage();
  const errors=[], consoleMessages=[], requests=[];
  let watchRequests=false;
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>consoleMessages.push(message.text()));
  page.on('request',request=>{if(watchRequests)requests.push(request.url());});
  await resources(context);
  const seed=async scenario=>{
    const response=await context.request.post(control,{data:scenario});
    assert.equal(response.status(),200);return response.json();
  };
  const snapshot=async()=>{const response=await context.request.get(control+'snapshot');assert.equal(response.status(),200);return response.json();};
  const publicRead=async(url,status)=>{const response=await anonymous.request.get(new URL(url,base).href);assert.equal(response.status(),status);return response.text();};
  const postNavigate=async(targetPage,button)=>{
    const target=await button.evaluate(e=>e.form.action);
    const response=targetPage.waitForResponse(r=>r.request().method()==='POST' && r.url()===target);
    await Promise.all([targetPage.waitForNavigation(),button.click()]);
    assert.equal((await response).status(),303);return target;
  };
  try {
    const unauthenticated=await anonymous.request.get(base+'/fixed-subscriptions',{maxRedirects:0});
    assert.equal(unauthenticated.status(),302);
    await seed('empty');await login(page);await page.goto(base+'/fixed-subscriptions');
    assert(await page.getByText('No fixed subscriptions yet.',{exact:true}).isVisible());
    assert(await page.getByRole('link',{name:'Create Fixed Subscription',exact:true}).isVisible());
    assert.equal((await page.locator('#fixed-result-count').textContent()).trim(),'0 subscriptions');
    for(const width of [1440,390])await shot(page,'fixed-empty',width);

    let fixture=await seed('populated');const before=await snapshot();
    // Registry JSON sorts internal IDs, so creation order is not the list contract.
    // Explicit key groups above define ordering; only ties use original server order.
    const original=fixture.entries.map(entry=>entry.prefix);
    orders=Object.fromEntries(Object.entries(sortGroups).map(([sort,groups])=>
      [sort,groups.flatMap(group=>original.filter(prefix=>group.includes(prefix)))]));
    const listResponse=await page.goto(base+'/fixed-subscriptions');assert.equal(listResponse.status(),200);
    assert.deepEqual(await snapshot(),before,'List GET does not create auxiliary health JSON or change registry');
    await matching(page,orders['updated-desc']);
    assert.equal(await page.locator('#fixed-search').getAttribute('type'),'search');
    assert.equal(await page.locator('#fixed-search').getAttribute('placeholder'),'Search subscriptions...');
    assert.equal(await page.getByLabel('Search subscriptions',{exact:true}).count(),1);
    assert.equal(await page.getByLabel('Status',{exact:true}).count(),1);
    assert.equal(await page.getByLabel('Sort',{exact:true}).count(),1);
    assert.equal(await page.locator('#fixed-result-count').getAttribute('aria-live'),'polite');
    assert.equal(await page.locator('#fixed-result-count').getAttribute('role'),'status');
    for(const entry of fixture.entries) {
      const item=row(page,entry.prefix);
      assert.equal((await item.locator('.fixed-source-count').textContent()).trim(),`External Sources: ${entry.sources}`);
      assert.equal((await item.locator('td[data-label="Status"] .badge').textContent()).trim(),entry.status==='active'?'Active':'Disabled');
      assert((await item.locator('td[data-label="Updated"]').textContent()).includes('UTC'));
      assert.equal((await item.locator('td[data-label="Last Access"]').textContent()).trim(),'Never');
      assert.equal(await item.locator('.fixed-url').inputValue(),new URL(entry.url,base).href);
      assert(await item.locator('.fixed-url').getAttribute('readonly')!==null);
      assert.equal(await item.locator('.copy-status').getAttribute('role'),'status');
      assert(!await item.getByRole('button',{name:'Check Now',exact:true}).count());
      assert(!await item.getByRole('button',{name:'Refresh Sources',exact:true}).count());
    }
    assert.equal(fixture.entries.find(e=>e.prefix===longPrefix).name.length,128);
    assert.equal(longPrefix.length,64);
    await privacy(page,fixture);
    for(const width of [1440,390])await shot(page,'fixed-populated',width);

    await page.setViewportSize({width:1440,height:900});await page.waitForTimeout(100);watchRequests=true;
    await page.locator('#fixed-search').fill('  aLPHa  ');await matching(page,defaultSubset([alpha,alphaTie]));
    audit.search.push('trim/case-insensitive subscription name');
    await page.locator('#fixed-status').selectOption('disabled');await matching(page,[alphaTie]);
    audit.search.push('combined name + disabled status');
    await clear(page);await matching(page,orders['updated-desc']);
    await page.locator('#fixed-status').selectOption('disabled');await matching(page,defaultSubset([beta,alphaTie]));
    await page.locator('#fixed-status').selectOption('active');await matching(page,[longPrefix,gamma,alpha,tokyo]);
    await clear(page);await page.locator('#fixed-search').fill(' BETA-DISABLED ');await matching(page,[beta]);
    audit.search.push('safe URL prefix');
    await clear(page);await page.locator('#fixed-search').fill('東京');await matching(page,[tokyo]);
    audit.search.push('Unicode name');
    for(const query of [fixture.entries[0].url.split('fs_')[1],new URL(fixture.entries[0].url,base).href,fixture.secrets[0]]) {
      await clear(page);await page.locator('#fixed-search').fill(query);await matching(page,[]);
      assert(await page.getByText('No subscriptions match your filters.',{exact:true}).isVisible());
      assert.equal(await page.getByText('No fixed subscriptions yet.',{exact:true}).count(),0);
    }
    audit.search.push('no token, full URL or node-secret search');
    for(const width of [1440,390])await shot(page,'fixed-filtered-empty',width);
    await clear(page);
    for(const [sort,expected] of Object.entries(orders)) {
      await page.locator('#fixed-sort').selectOption(sort);await matching(page,expected);
      audit.sort.push({sort,order:expected});
    }
    await clear(page);await page.locator('#fixed-search').fill('gamma');
    for(const width of [1440,390])await shot(page,'fixed-filtered',width);
    await clear(page);
    assert.deepEqual(requests,[],'Search/filter/sort/clear do not send requests');watchRequests=false;
    // Keyboard enhancement order and visible focus; colors never carry status alone.
    await page.locator('#fixed-search').focus();await page.keyboard.press('Tab');
    assert(await page.locator('#fixed-status').evaluate(e=>document.activeElement===e));
    await page.keyboard.press('Tab');assert(await page.locator('#fixed-sort').evaluate(e=>document.activeElement===e));
    await page.locator('#fixed-search').fill('gamma');await page.locator('#fixed-search').focus();
    for(const selector of ['#fixed-search','#fixed-status','#fixed-sort','#fixed-clear']) {
      await page.locator(selector).focus();
      assert(await page.locator(selector).evaluate(e=>parseFloat(getComputedStyle(e).outlineWidth)>=2),`Visible focus: ${selector}`);
    }
    await clear(page);assert(await page.locator('#fixed-search').evaluate(e=>document.activeElement===e));

    const second=rows(page).nth(1),first=rows(page).first();
    const secondUrl=await second.locator('.fixed-url').inputValue(),firstUrl=await first.locator('.fixed-url').inputValue();
    assert.notEqual(firstUrl,secondUrl);
    await second.locator('.copy-fixed-url').click();
    await second.getByRole('button',{name:'Copied',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),secondUrl);
    assert.equal((await second.locator('.copy-status').textContent()).trim(),'URL copied.');
    assert.equal((await first.locator('.copy-fixed-url').textContent()).trim(),'Copy URL');
    await first.locator('.copy-fixed-url').click();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),firstUrl);
    await page.waitForFunction(()=>[...document.querySelectorAll('.copy-fixed-url')].every(e=>e.textContent.trim()==='Copy URL'),null,{timeout:2600});
    assert.equal((await second.locator('.copy-status').textContent()).trim(),'');
    await page.evaluate(()=>Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async()=>{throw new Error('Synthetic clipboard rejection');}}));
    await second.locator('.copy-fixed-url').click();
    assert.equal((await second.locator('.copy-status').textContent()).trim(),'Copy failed — select the URL and copy manually.');
    assert(await second.locator('.fixed-url').evaluate(e=>document.activeElement===e && e.selectionStart===0 && e.selectionEnd===e.value.length));
    assert.equal((await second.locator('.copy-fixed-url').textContent()).trim(),'Copy URL');
    audit.copy={secondRow:true,independentRows:true,actualClipboard:true,reset:true,failureFallback:true};

    fixture=await seed('health');const healthBefore=await snapshot();
    assert.equal((await page.reload()).status(),200);
    assert.deepEqual(await snapshot(),healthBefore,'Healthy/stale fingerprint aggregation is observational only');
    const healthChecks=[
      [alpha,'Endpoint','Manual','2 healthy'],[beta,'Endpoint','Manual','1 suspect'],
      [gamma,'Endpoint','Automatic','1 unhealthy'],[alphaTie,'Endpoint','Manual','2 unknown'],
      [gamma,'Proxy','Automatic','1 unhealthy'],[alphaTie,'Proxy','Manual','2 unsupported'],
      [longPrefix,'Proxy','Manual','3 healthy'],[tokyo,'Endpoint','Off','Off'],[tokyo,'Proxy','Off','Off']
    ];
    for(const [prefix,type,mode,status] of healthChecks) {
      const summary=row(page,prefix).locator(type==='Endpoint'?'.fixed-endpoint-summary':'.fixed-proxy-summary');
      const text=await summary.textContent();assert(text.includes(mode),text);assert(text.includes(status),text);
      audit.health.push({prefix,type,mode,status});
    }
    await privacy(page,fixture);
    for(const width of widths)await layout(page,width);
    for(const width of [1440,390])await shot(page,'fixed-health-warning',width);
    fixture=await seed('corrupt');const corruptBefore=await snapshot();
    assert.equal((await page.reload()).status(),200);assert.deepEqual(await snapshot(),corruptBefore);
    assert.equal(await rows(page).count(),6);
    assert(await rows(page).evaluateAll(elements=>elements.every(e=>e.querySelector('.fixed-endpoint-summary').textContent.includes('Unavailable')&&e.querySelector('.fixed-proxy-summary').textContent.includes('Unavailable'))));
    await privacy(page,fixture);audit.health.push({corrupt:'Unavailable; list usable; bytes unchanged'});
    await seed('missing');const missingBefore=await snapshot();
    assert.equal((await page.reload()).status(),200);assert.deepEqual(await snapshot(),missingBefore);
    assert(await page.locator('.fixed-health-value').evaluateAll(elements=>elements.every(e=>e.textContent.trim()==='Off')));
    audit.health.push({missing:'Off; no file creation'});

    // Existing JS confirmation semantics stay in place before No-JS action checks.
    const cancelRow=row(page,gamma),oldGamma=await cancelRow.locator('.fixed-url').inputValue();
    for(const [button,message] of [['Regenerate Link','This will invalidate the old subscription URL.'],
      ['Delete','Delete this fixed subscription? Its URL will stop working permanently.']]) {
      let observed;
      page.once('dialog',async dialog=>{observed=dialog.message();await dialog.dismiss();});
      await cancelRow.getByRole('button',{name:button,exact:true}).click();
      assert.equal(observed,message);await publicRead(oldGamma,200);
    }
    const noJS=await browser.newContext({javaScriptEnabled:false,viewport:{width:390,height:900}});
    await resources(noJS);const noPage=await noJS.newPage();await login(noPage);
    await noPage.goto(base+'/fixed-subscriptions');assert.equal(await rows(noPage).count(),6);
    assert.deepEqual(await visibleOrder(noPage),fixture.entries.map(e=>e.prefix));
    assert(await noPage.locator('#fixed-toolbar').isHidden());
    await Promise.all([noPage.waitForNavigation(),noPage.getByRole('link',{name:'Create Fixed Subscription',exact:true}).click()]);
    assert(await noPage.locator('#subscription-name').isVisible());
    await noPage.goto(base+'/fixed-subscriptions');
    await Promise.all([noPage.waitForNavigation(),row(noPage,alpha).getByRole('link',{name:'Edit',exact:true}).click()]);
    assert(await noPage.getByRole('heading',{name:'Edit Fixed Subscription',exact:true}).isVisible());
    await noPage.goto(base+'/fixed-subscriptions');
    const alphaRow=()=>row(noPage,alpha),oldAlpha=await alphaRow().locator('.fixed-url').inputValue();
    const action=await alphaRow().getByRole('button',{name:'Disable',exact:true}).evaluate(e=>e.form.action);
    const secured=await noJS.request.post(action,{form:{csrf_token:'expired'},maxRedirects:0});
    assert.equal(secured.status(),303);await publicRead(oldAlpha,200);
    const missingToken=await noJS.request.post(action,{form:{},maxRedirects:0});
    assert.equal(missingToken.status(),303);await publicRead(oldAlpha,200);
    const unauthenticatedPost=await anonymous.request.post(action,{form:{csrf_token:'expired'},maxRedirects:0});
    assert.equal(unauthenticatedPost.status(),303);await publicRead(oldAlpha,200);
    await noPage.reload();
    await postNavigate(noPage,alphaRow().getByRole('button',{name:'Disable',exact:true}));await publicRead(oldAlpha,404);
    await postNavigate(noPage,alphaRow().getByRole('button',{name:'Enable',exact:true}));await publicRead(oldAlpha,200);
    assert.equal(await alphaRow().getByRole('button',{name:'Regenerate Link',exact:true}).evaluate(e=>e.form.dataset.confirm),'This will invalidate the old subscription URL.');
    await postNavigate(noPage,alphaRow().getByRole('button',{name:'Regenerate Link',exact:true}));
    const replacement=await alphaRow().locator('.fixed-url').inputValue();assert.notEqual(replacement,oldAlpha);
    await publicRead(oldAlpha,404);await publicRead(replacement,200);
    await postNavigate(noPage,alphaRow().getByRole('button',{name:'Delete',exact:true}));await publicRead(replacement,404);
    assert.equal(await rows(noPage).count(),5);
    audit.noJS={allRowsVisible:true,createAndEditNavigation:true,enableDisable:true,regenerate:true,delete:true,
      authenticated:true,csrfProtected:true,post303:true,scope:'List progressive enhancement; existing editor save/create and no-JS confirmations are unchanged'};
    await noJS.close();

    fixture=await seed('many');const renderStart=Date.now();await page.goto(base+'/fixed-subscriptions');
    assert.equal(await rows(page).count(),50);const renderMilliseconds=Date.now()-renderStart;
    await privacy(page,fixture);await page.waitForTimeout(100);requests.length=0;watchRequests=true;
    const filterMilliseconds=await page.evaluate(()=>{
      const start=performance.now(),input=document.getElementById('fixed-search');
      input.value='Subscription 4';input.dispatchEvent(new Event('input',{bubbles:true}));
      return performance.now()-start;
    });
    assert.equal((await visibleOrder(page)).length,10);
    await clear(page);
    const sortMilliseconds=await page.evaluate(()=>{
      const start=performance.now(),select=document.getElementById('fixed-sort');
      select.value='nodes-desc';select.dispatchEvent(new Event('change',{bubbles:true}));
      return performance.now()-start;
    });
    const counts=await rows(page).evaluateAll(elements=>elements.filter(e=>!e.hidden).map(e=>Number(e.dataset.nodeCount)));
    assert.equal(counts.length,50);assert(counts.every((value,index)=>index===0||counts[index-1]>=value));
    assert(filterMilliseconds<500 && sortMilliseconds<500,'50-row interactions remain immediate');
    assert.deepEqual(requests,[],'50-row keypress/filter/sort sends no network requests');watchRequests=false;
    audit.performance={subscriptions:50,renderMilliseconds,filterMilliseconds,sortMilliseconds,requests:requests.length};
    assert.deepEqual(errors,[]);
    for(const secret of fixture.secrets)assert(!consoleMessages.some(message=>message.includes(secret)));
    fs.writeFileSync(path.join(artifacts,'fixed-ux-audit.json'),JSON.stringify(audit,null,2));
    console.log('PASS Fixed UX browser: 6 stable sorts, safe name/prefix search, combined status/clear/count, sources/aggregate health/current+stale+missing+corrupt/privacy, multi-row clipboard/reset/fallback, authenticated CSRF POST303 actions/no-JS list, seven responsive widths, keyboard/labels/focus, 50-row immediate/no-request interaction');
  } finally {await anonymous.close();await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
