/* Real DOM + real Flask in the disposable runner. Never contact a VPS/provider. */
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const {createHash} = require('node:crypto');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const version = readFileSync(join(__dirname, '..', 'VERSION'), 'utf8').trim();
assert(/^\d+\.\d+\.\d+$/.test(version));
const base = process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname === '127.0.0.1');
const routePath = '/api/preview-yaml-diff';
const link = 'vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
const batch = 'US|OldTest|' + link;
const latest = 'US|LatestTest|' + link.replaceAll('11111111','22222222');
const sentinel = '<script>alert(1)</script><img data-diff-xss src=x> & Ω';
const source = 'proxies: [{name: old, type: vless, server: old.example, port: 443, uuid: fake}]\nproxy-groups: []\nrules: [MATCH,DIRECT]\nx-private: "'+sentinel+' '+ 'W'.repeat(5000)+'"\n';
async function setup(browser,width) {
  const context=await browser.newContext({viewport:{width,height:900}});
  const page=await context.newPage(), posts=[], processResponses=[], consoleSummary=[], pageErrors=[];
  page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
  const summary=message=>createHash('sha256').update(message).digest('hex');
  page.on('console',m=>{if(consoleSummary.length<8)consoleSummary.push({type:m.type(),message_sha256:summary(m.text())});});
  page.on('pageerror',e=>{if(pageErrors.length<8)pageErrors.push({name:e.name,message_sha256:summary(e.message)});});
  page.on('response',r=>{
    if(new URL(r.url()).pathname==='/process' && processResponses.length<8)processResponses.push({status:r.status(),
      content_type:r.headers()['content-type']?.split(';')[0],
      redirect_path:r.headers().location?new URL(r.headers().location,base).pathname:null});
  });
  page.on('dialog',async dialog=>{await dialog.dismiss();throw Error('Unexpected script/dialog execution');});
  await page.route('**/*',route=>{
    const url=route.request().url();
    if(url.startsWith(base))return route.continue();
    if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
      return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
    return route.abort();
  });
  await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
  async function diagnose(phase,navigation=null,force=false) {
    if(!force && process.env.BROWSER_DIAGNOSTICS!=='1')return;
    const dom=await page.evaluate(()=>{
      const result=document.getElementById('generate-result'), title=result?.querySelector('.panel-title-row .panel-subtitle')?.textContent?.trim();
      const body=Array.from(document.querySelectorAll('[role="alert"]')).slice(0,8).map(e=>e.textContent.slice(0,2048)).join('\n'), form=document.getElementById('process-form');
      const known=['需要重新選擇自訂 YAML 檔案。','No valid new nodes provided.',
        'Invalid Policy settings.','Session expired','Security token','Unsupported country code.'];
      const categories=[
        ['MODE_INVALID','Node Update Mode is invalid.'],
        ['POLICY_INVALID','Invalid Policy settings.'],
        ['SOURCE_SELECTION','需要重新選擇自訂 YAML 檔案。'],
        ['SOURCE_FORMAT','Unsupported file format.'],
        ['COUNTRY_SETTINGS','Country Detection settings are invalid.'],
        ['FORM_NODES','Invalid auxiliary nodes or edits.'],
        ['NODE_PARSE','Unable to parse the node.'],
        ['NO_NODES','No valid new nodes provided.'],
        ['DEFAULT_MISSING','default template is missing.'],
        ['UPLOAD_SAVE','Unable to save the file.'],
        ['YAML_FORMAT','Invalid YAML. Check indentation, quotes and duplicate keys.'],
        ['YAML_PROCESSING','Unable to process YAML.'],
        ['YAML_STRUCTURE','YAML root must be a mapping.'],
        ['YAML_REFERENCES','contains an invalid node or proxy group reference.'],
        ['YAML_CONFLICT','New node name conflicts with a proxy group'],
        ['CSRF_NOTICE','Security token refreshed.'],
        ['SESSION_NOTICE','Log in again;'],
      ].filter(([,message])=>body.includes(message)).map(([category])=>category);
      const enumValue=(id,allowed)=>{const value=document.getElementById(id)?.value;return allowed.includes(value)?value:'OTHER_OR_ABSENT';};
      return {download_count:document.querySelectorAll('#download-url').length,
        generate_result_present:!!result,generate_result_status:['就緒','Waiting'].includes(title)?title:'ABSENT_OR_OTHER',
        error_count:document.querySelectorAll('[role="alert"]').length,known_errors:known.filter(v=>body.includes(v)),
        business_error_categories:categories.length?categories:(body.trim()?['UNCLASSIFIED_ALERT']:[]),
        login_present:!!document.getElementById('password'),csrf_feedback_present:!!document.querySelector('[data-csrf-feedback]'),
        form_present:!!form,yaml_source:enumValue('yaml-source',['default','custom']),
        node_update_mode:enumValue('node-update-mode',['replace','merge'])};
    });
    console.log('DIAG_CLIENT '+JSON.stringify({version,suite:'yaml_diff',phase,viewport:page.viewportSize(),pathname:new URL(page.url()).pathname,
      navigation_status:navigation?.status()??null,process_count:posts.filter(p=>p==='/process').length,
      process_responses:processResponses,download_visible:await page.locator('#download-url').isVisible(),
      dom,console_summary:consoleSummary,page_errors:pageErrors}));
  }
  return {page,context,posts,diagnose,count:path=>posts.filter(p=>p===path).length};
}
async function generateChecked(fixture,phase,source) {
  const {page,diagnose}=fixture;
  const metadata={version,suite:'yaml_diff',viewport:page.viewportSize(),phase};
  let stage='form-preconditions',navigation=null;
  console.log('GENERATE_CHECK '+JSON.stringify({...metadata,stage}));
  try {
    const form=await page.evaluate(()=>{
      const value=(id,allowed)=>{const v=document.getElementById(id)?.value;return allowed.includes(v)?v:'OTHER_OR_ABSENT';};
      return {source:value('yaml-source',['default','custom']),mode:value('node-update-mode',['replace','merge']),
        country:value('country-geoip',['off','literal-ip']),
        country_policy:value('policy_country_groups_type',['preserve','select','url-test','fallback','load-balance']),
        special_policy:value('policy_special_groups_type',['preserve','select','url-test','fallback','load-balance']),
        batch_present:!!document.getElementById('batch_nodes')?.value.trim()};
    });
    console.log('GENERATE_CHECK '+JSON.stringify({...metadata,stage,form}));
    assert.deepEqual(form,{source,mode:'replace',country:'off',country_policy:'preserve',special_policy:'preserve',batch_present:true});
    stage='process-response';
    const results=await Promise.all([page.waitForNavigation(),
      page.waitForResponse(r=>r.request().method()==='POST' && new URL(r.url()).pathname==='/process'),
      page.locator('#generate-yaml').click()]);
    navigation=results[0];const response=results[1],status=response.status();
    const contentType=response.headers()['content-type']?.split(';')[0];
    const redirect=response.headers().location?new URL(response.headers().location,base).pathname:null;
    const httpClass=status===400?'VALIDATION_400':status===401?'AUTH_401':status===403?'FORBIDDEN_403':
      status>=500?'SERVER_5XX':status===302?'EXPECTED_REDIRECT':'UNEXPECTED_STATUS';
    console.log('GENERATE_CHECK '+JSON.stringify({...metadata,stage,status,http_class:httpClass,
      pathname:new URL(response.url()).pathname,content_type:contentType,redirect_path:redirect}));
    assert.equal(status,302,'Generate must return its successful 302 redirect');
    assert.equal(contentType,'text/html');assert.equal(redirect,'/');
    stage='result-navigation';
    assert.equal(navigation.status(),200);assert.equal(new URL(page.url()).pathname,'/');
    stage='download-visibility';
    assert.equal(await page.locator('#download-url').count(),1,'Generate download element must exist exactly once');
    assert(await page.locator('#download-url').isVisible());
    await diagnose(phase+':passed',navigation);
    console.log('GENERATE_CHECK '+JSON.stringify({...metadata,stage:'passed'}));
  } catch(error) {
    console.log('GENERATE_CHECK '+JSON.stringify({...metadata,stage,outcome:'failed'}));
    await diagnose(phase+':'+stage+':failed',navigation,true).catch(()=>{
      console.log('GENERATE_CHECK '+JSON.stringify({...metadata,stage,diagnostic_unavailable:true}));
    });
    throw error;
  }
}
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  for(const width of [1440,390]) {
   const fixture=await setup(browser,width);
   const {page,context,posts,count}=fixture;
   const button=page.locator('#preview-yaml-diff'), status=page.locator('#yaml-diff-status');
   assert(await button.isVisible());assert.equal(await button.getAttribute('type'),'button');
   async function preview(expected=200) {
    const pending=page.waitForResponse(r=>new URL(r.url()).pathname===routePath);
    await button.click();const response=await pending;
    assert.equal(response.status(),expected);assert.equal(response.headers()['cache-control'],'no-store');
    await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
    return response.json();
   }
   await page.locator('#batch_nodes').fill(batch);
   assert((await preview()).changed);assert.equal(await status.textContent(),'有變更');
   assert((await page.locator('#yaml-diff-code').textContent()).startsWith('--- source.yaml\n+++ generated.yaml\n'));
   assert.equal(count('/process'),0);
   const parsed=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await page.locator('#parse-nodes').click();await parsed;
   await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
   await page.locator('#batch_nodes').fill(latest);
   await preview();assert((await page.locator('#yaml-diff-code').textContent()).includes('LatestTest'));
   assert(!(await page.locator('#yaml-diff-code').textContent()).includes('OldTest'));
   await page.locator('#yaml-source').selectOption('custom');
   const missingCount=count(routePath);await button.click();
   assert((await status.textContent()).includes('需要重新選擇自訂 YAML 檔案。'));
   assert.equal(count(routePath),missingCount);assert.equal(count('/process'),0);
   async function upload(text) {await page.locator('[name=yaml_file]').setInputFiles({name:'custom.yaml',mimeType:'application/yaml',buffer:Buffer.from(text)});}
   await upload(source);const custom=await preview();
   assert(custom.diff.includes(sentinel));assert.equal(await page.locator('[data-diff-xss]').count(),0);
   assert.equal(await page.evaluate(()=>window.alertExecuted),undefined);
   const geometry=await page.locator('#yaml-diff-text').evaluate(pre=>({
     width:pre.clientWidth,scroll:pre.scrollWidth,overflow:getComputedStyle(pre).overflowX,
     space:getComputedStyle(pre).whiteSpace,font:getComputedStyle(pre).fontFamily,
     pageOverflow:document.documentElement.scrollWidth>innerWidth+1}));
   assert(geometry.scroll>geometry.width);assert.equal(geometry.overflow,'auto');assert.equal(geometry.space,'pre');
   assert(geometry.font.includes('monospace'));assert(!geometry.pageOverflow);
   await page.locator('#yaml-diff-panel').screenshot({path:`/private/tmp/clash-yaml-diff-${width}.png`});
   assert(!(await page.evaluate(()=>JSON.stringify({...localStorage}))).includes(sentinel));
   const before=count('/process');await page.locator('.aux-name').press('Enter');
   await page.waitForTimeout(80);assert.equal(count('/process'),before);
   // Hold a response after computing it, then edit. Old diff must not be displayed.
   let release,seen;
   const held=new Promise(resolve=>{release=resolve;}), intercepted=new Promise(resolve=>{seen=resolve;});
   await page.route('**/api/preview-yaml-diff',async route=>{const response=await route.fetch();seen();await held;await route.fulfill({response});});
   await button.click();await intercepted;
   await page.locator('#batch_nodes').fill(latest.replace('LatestTest','ChangedDuringPreview'));
   release();await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
   assert.equal(await status.textContent(),'輸入已變更，請重新預覽。');
   assert.equal(await page.locator('#yaml-diff-code').textContent(),'');await page.unroute('**/api/preview-yaml-diff');
   await page.locator('#batch_nodes').fill(latest);
   await generateChecked(fixture,'custom-generate','custom');
   assert.equal(count('/process'),before+1);
   const download=await context.request.get(await page.locator('#download-url').inputValue());
   assert(download.ok());const generated=await download.text();
   await upload(generated);const unchanged=await preview();
   assert(!unchanged.changed);assert.equal(unchanged.diff,'');assert.equal(await status.textContent(),'YAML 沒有變更。');
   assert(await page.locator('#yaml-diff-text').isHidden());
   await page.locator('#batch_nodes').fill('PRIVATE-invalid-uri');await preview(400);
   assert((await status.textContent()).includes('無法預覽'));
   await page.locator('#batch_nodes').fill(latest);
   await page.locator('#process-form [name=csrf_token]').evaluate(input=>{input.value='invalid';});
   // Reject a real POST after successful preflight refresh; no automatic replay.
   await page.route('**/api/preview-yaml-diff',route=>{
    const data=new URLSearchParams(route.request().postData());data.set('csrf_token','invalid');
    return route.continue({postData:data.toString(),headers:{...route.request().headers(),'content-type':'application/x-www-form-urlencoded'}});
   });
   await preview(400);assert((await status.textContent()).includes('請重新整理或重新登入'));
   await page.unroute('**/api/preview-yaml-diff');
   await page.reload();await button.click();assert((await status.textContent()).includes('需要重新選擇自訂 YAML 檔案。'));
   await upload(generated);
   const csrf=await page.locator('#process-form [name=csrf_token]').inputValue();
   await context.request.post(base+'/logout',{form:{csrf_token:csrf}});
   const anonymousHtml=await (await context.request.get(base)).text();
   const fresh=anonymousHtml.match(/name="csrf_token" value="([^"]+)"/)[1];
   await page.locator('#process-form [name=csrf_token]').evaluate((input,value)=>{input.value=value;},fresh);
   const prior=count(routePath),expired=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/csrf-token');
   await button.click();assert.equal((await expired).status(),401);
   await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
   assert((await status.textContent()).includes('登入已逾時'));assert.equal(count(routePath),prior);
   await context.close();
   // Independent normal generation never requires Diff Preview.
   const direct=await setup(browser,width);
   await direct.page.locator('#batch_nodes').fill(batch);
   await generateChecked(direct,'direct-generate','default');
   assert.equal(direct.count(routePath),0);assert.equal(direct.count('/process'),1);
   assert(await direct.page.locator('#download-url').isVisible());await direct.context.close();
   console.log(`YAML diff browser PASS: ${width}px; latest/default/custom/no-change/XSS/overflow/implicit-submit/CSRF/session/stale-response/direct Generate`);
  }
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
