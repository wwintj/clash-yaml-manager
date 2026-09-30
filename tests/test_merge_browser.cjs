/* Real Generate/Diff/Draft behavior, isolated loopback Flask only. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname==='127.0.0.1');
const key='clash-yaml-manager.draft.v1';
const link='vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
const batch='US|Browser-new|'+link;
const source='# retained source comment\nproxies:\n  - name: old-a # retained old node\n    type: trojan\n    server: old.example\n    port: 443\n    password: "TEST_ONLY"\nproxy-groups:\n  - {name: Manual, type: select, proxies: [old-a]}\nrules: [MATCH,DIRECT]\n';

async function setup(browser,width) {
 const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage();
 const posts=[],errors=[];
 page.on('request',r=>{if(r.method()==='POST')posts.push(new URL(r.url()).pathname);});
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const url=route.request().url();
  if(url.startsWith(base))return route.continue();
  if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
   return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
  return route.abort();
 });
 await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
 await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
 return {page,context,posts,errors,count:path=>posts.filter(p=>p===path).length};
}

(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  for(const width of [1440,390]) {
   const {page,context,errors,count}=await setup(browser,width);
   const mode=page.locator('#node-update-mode'),status=page.locator('#yaml-diff-status');
   assert(await mode.isVisible());assert.equal(await mode.inputValue(),'replace');
   assert((await page.locator('#node-update-help').textContent()).includes('keep source proxies and append submitted nodes'));
   await page.locator('#batch_nodes').fill(batch);await page.locator('#yaml-source').selectOption('custom');
   const upload=()=>page.locator('[name=yaml_file]').setInputFiles({name:'custom.yaml',mimeType:'application/yaml',buffer:Buffer.from(source)});
   const preview=async expected=>{
    const pending=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/preview-yaml-diff');
    await page.locator('#preview-yaml-diff').click();const response=await pending;
    assert.equal(response.status(),expected||200);
    assert.equal(response.headers()['cache-control'],'no-store');
    await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
    return response.json();
   };
   await upload();const replace=await preview();assert(replace.changed && /^-.*old-a/m.test(replace.diff));
   await mode.selectOption('merge');assert.equal(await status.textContent(),'Inputs changed; preview again.');
   assert.equal(await page.locator('#yaml-diff-code').textContent(),'');
   const merge=await preview();assert(merge.changed && merge.summary.old_node_count===1 && merge.summary.new_node_count===1);
   assert(!/^-.*old-a/m.test(merge.diff));assert(merge.diff.includes('Browser-new'));assert.equal(count('/process'),0);
   let draft=JSON.parse(await page.evaluate(k=>localStorage.getItem(k),key));assert.equal(draft.node_update_mode,'merge');
   await page.reload();assert.equal(await mode.inputValue(),'merge');
   assert.equal(await page.locator('#batch_nodes').inputValue(),batch);
   await page.locator('#preview-yaml-diff').click();assert((await status.textContent()).includes('Custom YAML needs to be selected again.'));
   // Legacy drafts keep other input but cannot opt into Merge.
   await page.evaluate(k=>{const value=JSON.parse(localStorage.getItem(k));delete value.node_update_mode;localStorage.setItem(k,JSON.stringify(value));},key);
   await page.reload();assert.equal(await mode.inputValue(),'replace');assert.equal(await page.locator('#batch_nodes').inputValue(),batch);
   await mode.selectOption('merge');await upload();
   // Mode changes invalidate an in-flight response too.
   let release,seen;
   const held=new Promise(resolve=>{release=resolve;}),intercepted=new Promise(resolve=>{seen=resolve;});
   await page.route('**/api/preview-yaml-diff',async route=>{const response=await route.fetch();seen();await held;await route.fulfill({response});});
   await page.locator('#preview-yaml-diff').click();await intercepted;await mode.selectOption('replace');release();
   await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
   assert.equal(await status.textContent(),'Inputs changed; preview again.');assert.equal(await page.locator('#yaml-diff-code').textContent(),'');
   await page.unroute('**/api/preview-yaml-diff');await mode.selectOption('merge');
   await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
   assert.equal(await mode.inputValue(),'merge');assert.equal(count('/process'),1);
   const download=await context.request.get(await page.locator('#download-url').inputValue());assert(download.ok());
   const generated=await download.text();
   for(const fragment of ['name: old-a # retained old node','type: trojan','password: "TEST_ONLY"','proxies: [old-a]','Browser-new'])assert(generated.includes(fragment),fragment);
   // Collision is visible; server redisplays valid Merge even without a draft.
   await page.locator('[name=yaml_file]').setInputFiles({name:'merged.yaml',mimeType:'application/yaml',buffer:Buffer.from(generated)});
   await preview(400);assert((await status.textContent()).includes('Node name already exists in source YAML.'));
   await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
   assert.equal(await mode.inputValue(),'merge');assert(await page.getByText('Node name already exists in source YAML.',{exact:true}).isVisible());
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await mode.locator('..').screenshot({path:`/private/tmp/clash-merge-${width}.png`});
   page.once('dialog',dialog=>dialog.accept());await page.locator('.clear-draft').first().click();
   assert.equal(await mode.inputValue(),'replace');assert.equal(await page.locator('#batch_nodes').inputValue(),'');
   assert.equal(await page.evaluate(k=>localStorage.getItem(k),key),null);
   assert.deepEqual(errors,[]);await context.close();
   // A separate context generates Merge directly without Parse or Diff.
   const direct=await setup(browser,width);
   await direct.page.locator('#node-update-mode').selectOption('merge');
   await direct.page.locator('#yaml-source').selectOption('custom');
   await direct.page.locator('[name=yaml_file]').setInputFiles({name:'custom.yaml',mimeType:'application/yaml',buffer:Buffer.from(source)});
   await direct.page.locator('#batch_nodes').fill(batch);
   await Promise.all([direct.page.waitForNavigation(),direct.page.locator('#generate-yaml').click()]);
   assert.equal(direct.count('/api/preview-yaml-diff'),0);assert.equal(direct.count('/parse-nodes'),0);assert.equal(direct.count('/process'),1);
   const raw=await (await direct.context.request.get(await direct.page.locator('#download-url').inputValue())).text();
   assert(raw.includes('old-a') && raw.includes('Browser-new'));
   await direct.page.goto(base+'/fixed-subscriptions/new');assert.equal(await direct.page.locator('#node-update-mode').count(),0);
   assert.deepEqual(direct.errors,[]);await direct.context.close();
   console.log(`Merge browser PASS: ${width}px; default/selector/preview/generate/direct/draft/legacy/clear/custom/collision/stale/no-overflow/Fixed absence`);
  }
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
