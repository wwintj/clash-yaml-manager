/* Authenticated feedback through real forms in the disposable Flask harness. */
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname==='127.0.0.1');
const artifacts=process.env.UI_ARTIFACT_DIR || '/private/tmp/clash-feedback-ui';
fs.mkdirSync(artifacts,{recursive:true});
const matrix=[[1440,900],[390,844],[320,568]],audit=[];
const globalError='.app-shell > .terminal-alert.error',globalSuccess='.app-shell > .terminal-alert.success';
async function navigate(page,action){return Promise.all([page.waitForNavigation(),action()]);}
async function check(page,state,width,height,selector,messages,multiple=false){
 const alert=page.locator(selector);assert.equal(await alert.count(),1);assert(await alert.isVisible());
 assert.equal(await alert.getAttribute('role'),state==='success'?'status':'alert');
 const text=await alert.innerText();for(const message of messages)assert(text.includes(message));
 assert.equal(await alert.locator('.panel-subtitle').count(),0);
 assert(!text.includes('ERROR LOG')&&!text.includes('SUCCESS'));
 assert.equal(await alert.locator('li').count(),multiple?messages.length:0);
 assert.equal(await alert.locator('p').count(),multiple?0:1);
 assert.equal(await alert.locator('[role]').count(),0,'The alert owns the live-region role');
 const geometry=await alert.evaluate(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {left:r.left,right:r.right,height:r.height,text:e.innerText,overflow:e.scrollWidth-e.clientWidth,padding:s.padding,border:s.borderColor,background:s.backgroundColor};});
 assert(geometry.left>=16 && geometry.right<=width-16);assert.equal(geometry.overflow,0);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth===document.documentElement.clientWidth));
 assert.equal(await page.locator('.app-header h1').innerText(),'Clash YAML Manager');
 assert.deepEqual(await page.locator('.app-header nav a').evaluateAll(links=>links.map(a=>a.getAttribute('href'))),['/','/fixed-subscriptions','/settings']);
 audit.push({state,width,viewportHeight:height,...geometry});
 await page.evaluate(()=>window.scrollTo(0,0));
 const mask=[page.locator('.fixed-url,#download-url,#batch_nodes,.aux-link')];
 await page.screenshot({mask,path:path.join(artifacts,`feedback-${state}-${width}.png`)});
 await alert.screenshot({path:path.join(artifacts,`feedback-${state}-${width}-detail.png`)});
}
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const [width,height] of matrix){
   const context=await browser.newContext({viewport:{width,height}}),page=await context.newPage(),errors=[],dialogs=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss();});
   await page.route('**/*',route=>{
    const url=route.request().url();if(url.startsWith(base))return route.continue();
    if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css'))return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
    if(url.endsWith('/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js'))return route.fulfill({path:process.env.BOOTSTRAP_JS_PATH,contentType:'text/javascript'});
    return route.abort();
   });
   await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
   await navigate(page,()=>page.locator('#password').press('Enter'));
   await page.locator('#batch_nodes').fill('');
   const [single]=await navigate(page,()=>page.locator('#generate-yaml').click());assert.equal(single.status(),400);
   await check(page,'error',width,height,globalError,['No valid new nodes provided.']);
   // Actual parser errors stay distinct; neither unsupported input is echoed.
   await page.locator('#batch_nodes').fill('PRIVATE_BAD_NODE_ONE\nPRIVATE_BAD_NODE_TWO');
   const [multiple]=await navigate(page,()=>page.locator('#generate-yaml').click());assert.equal(multiple.status(),400);
   await check(page,'multiple-errors',width,height,globalError,['Line 1: Unsupported protocol.','Line 2: Unsupported protocol.'],true);
   assert(!(await page.locator(globalError).innerText()).includes('PRIVATE_BAD_NODE'));
   // Inert rendered-HTML fixture, matching the existing login long-message audit.
   // Server escaping is separately tested at Flask/Jinja's HTML boundary.
   const original=await page.content(),long='Long feedback '+ 'x'.repeat(900),markup='<img src=x onerror=alert(1)>';
   const fixture=original.replace('Line 1: Unsupported protocol.',long).replace('Line 2: Unsupported protocol.','&lt;img src=x onerror=alert(1)&gt;');
   await page.route(base+'/__feedback-long-message',route=>route.fulfill({body:fixture,contentType:'text/html'}));
   await page.goto(base+'/__feedback-long-message');
   await check(page,'long-errors',width,height,globalError,[long,markup],true);
   assert.equal(await page.locator(globalError+' img, '+globalError+' script').count(),0);
   await page.goto(base);await page.locator('#yaml-source').selectOption('custom');
   await page.locator('[name=yaml_file]').setInputFiles({name:'feedback.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
   await page.locator('#batch_nodes').fill('US|Feedback Node|vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp');
   await navigate(page,()=>page.locator('#generate-yaml').click());
   assert.equal(await page.locator(globalSuccess).count(),0,'Generated result owns its contextual feedback');
   assert(await page.locator('#generate-result').getByText('Generation Complete',{exact:true}).isVisible());
   assert(await page.locator('#generate-result .panel-subtitle').filter({hasText:/^Temporary Link$/}).isVisible());
   assert(await page.getByRole('heading',{name:'Generate Result',exact:true}).isVisible());
   assert(await page.getByRole('heading',{name:'YAML Changes',exact:true,includeHidden:true}).count()===1);
   const result=page.locator('#generate-result .terminal-alert.success');assert.equal(await result.getAttribute('role'),'status');
   assert((await result.innerText()).includes('YAML generated. Download it or remove the temporary files.'));
   // Delete only this synthetic temporary upload/output through the actual UI.
   await navigate(page,()=>page.getByRole('button',{name:'Delete Temp Files',exact:true}).click());
   await check(page,'success',width,height,globalSuccess,['Deleted 2 temporary server files.']);
   await page.waitForTimeout(300);assert(await page.locator(globalSuccess).isVisible(),'Feedback persists without auto-dismiss');
   await page.reload();assert.equal(await page.locator(globalSuccess).count(),0,'Original server one-shot notice behavior');
   assert.deepEqual(errors,[]);assert.deepEqual(dialogs,[]);await context.close();
  }
  fs.writeFileSync(path.join(artifacts,'feedback-geometry.json'),JSON.stringify(audit,null,2));
  console.log(`PASS Feedback UI: ${audit.length} state/viewport checks; real single/multiple parser errors, cleanup success, roles, persistent display, escaped long fixture, contextual Generation Complete, no overflow; screenshots: ${artifacts}`);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
