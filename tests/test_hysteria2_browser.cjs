/* Real Hysteria2 Parse/Generate/Diff/download; isolated loopback, synthetic secrets. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
// Reconstruct the public unified diff without another package or generator code.
function applyPatch(source, patch) {
 const original=source.match(/[^\n]*\n|[^\n]+$/g)||[], output=[];
 let pos=0, previous='';
 for(const line of (patch.match(/[^\n]*\n|[^\n]+$/g)||[]).slice(2)) {
  if(line.startsWith('@@ ')) {
   const match=line.match(/^@@ -(\d+)(?:,(\d+))? \+/);
   const start=Number(match[1])-(match[2]==='0'?0:1);
   output.push(...original.slice(pos,start));pos=start;
  } else if(line.startsWith('\\ No newline')) {
   if(['+',' '].includes(previous)&&output.length) output[output.length-1]=output.at(-1).slice(0,-1);
  } else if([' ','+','-'].includes(line[0])) {
   previous=line[0];if([' ','+'].includes(previous))output.push(line.slice(1));
   if([' ','-'].includes(previous))pos++;
  }
 }
 return output.concat(original.slice(pos)).join('');
}
const base=process.env.PREVIEW_TEST_URL;
assert(base && new URL(base).hostname==='127.0.0.1');
const password='TEST_ONLY_browser:@/ 密';
const oldSS='ss://'+Buffer.from('aes-256-gcm:'+password+'@example.com:443').toString('base64url');
const obfs='TEST_ONLY_browser_obfs+ 密';
const hy2='hysteria2://'+encodeURIComponent(password)+'@example.com:443/?obfs=gecko&obfs-password='+encodeURIComponent(obfs);
const alias='hy2://'+encodeURIComponent(password)+'@example.com';
const sentinel='<script>alert(1)</script>';
const trojan='trojan://'+encodeURIComponent(password)+'@example.com:443';
const vless='vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp';
const vmess='vmess://'+Buffer.from(JSON.stringify({add:'example.com',port:443,id:'TEST_ONLY_uuid',ps:'US-VM'})).toString('base64');
const source='proxies: [{name: old-a, type: ss, server: old.example, port: 443, cipher: aes-256-gcm, password: TEST_ONLY_old}]\nproxy-groups: [{name: Custom, type: select, proxies: [old-a, DIRECT]}]\nrules: [MATCH,DIRECT]\n';
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const width of [1440,390]){
   const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[],dialogs=[];
   page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss();});
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>{
    const url=route.request().url();if(url.startsWith(base))return route.continue();
    if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css') && process.env.BOOTSTRAP_CSS_PATH)
     return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
    return route.abort();
   });
   await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
   await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
   assert.equal(await page.locator('.app-header .status-protocols').count(),0);
   assert((await page.locator('#batch_nodes').locator('..').innerText()).includes('VMess / VLESS / Trojan / Shadowsocks / Hysteria2'));
   const auxPlaceholder=await page.locator('.aux-link').first().getAttribute('placeholder');
   assert(auxPlaceholder.includes('hysteria2://') && auxPlaceholder.includes('hy2://'));
   await page.locator('#batch_nodes').fill(vmess+'\n'+trojan+'#Tokyo-TJ\nSG|VL|'+vless+'\n'+hy2+'#'+encodeURIComponent(password)+'\n'+hy2+'#'+encodeURIComponent(sentinel)+'\n'+oldSS+'#London-SS');
   await page.locator('.aux-country').first().selectOption('TW');
   await page.locator('.aux-name').first().fill('Aux-HY2');
   await page.locator('.aux-link').first().fill(alias+'#Ignored');
   let response=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await page.locator('#parse-nodes').click();const parsed=await(await response).json();
   assert(!JSON.stringify(parsed).includes(password));
   await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
   assert.equal(await page.locator('.preview-node').count(),7);
   assert(!(await page.locator('#parse-preview').innerHTML()).includes(password));
   assert((await page.locator('#parse-preview').innerText()).includes('Hysteria2'));
   await page.locator('#parse-preview').screenshot({path:`/private/tmp/clash-hysteria2-${width}.png`});
   const names=await page.locator('.preview-name input').evaluateAll(inputs=>inputs.map(n=>n.value));
   assert(names.includes(sentinel));assert.equal(await page.locator('#parse-preview script').count(),0);
   assert(names.some(n=>n.includes('[password hidden]')) && !names.some(n=>n.includes(password)));
   // Preview edits use the same node keys and feed Generate.
   await page.locator('.preview-name input').nth(3).fill('Edited-HY2');
   await page.locator('.preview-country select').nth(3).selectOption('JP');
   await page.locator('#yaml-source').selectOption('custom');
   for(const mode of ['replace','merge']){
    await page.locator('#node-update-mode').selectOption(mode);
    await page.locator('[name=yaml_file]').setInputFiles({name:'custom.yaml',mimeType:'application/yaml',buffer:Buffer.from(source)});
    response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/preview-yaml-diff');
    await page.locator('#preview-yaml-diff').click();const diffResponse=await response;
    assert.equal(diffResponse.status(),200);const diff=await diffResponse.json();
    assert(diff.diff.includes('password:') && diff.diff.includes('type: hysteria2'));
    await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
    assert((await page.locator('#yaml-diff-code').textContent()).includes(sentinel));
    assert.equal(await page.locator('#yaml-diff-code script').count(),0);
    await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
    const download=await context.request.get(await page.locator('#download-url').inputValue());assert(download.ok());
    const generated=await download.text();
    assert.equal(applyPatch(source,diff.diff),generated);
    assert(generated.includes('Edited-HY2') && generated.includes('Aux-HY2') && generated.includes('type: hysteria2'));
    assert(generated.includes(password));assert.equal(generated.includes('name: old-a'),mode==='merge');
    assert.equal((generated.match(/type: hysteria2/g)||[]).length,3);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   }
   // Invalid query stays private; long accepted auth does not widen the document.
   await page.locator('#batch_nodes').fill('Safe|'+hy2+'&ech=TEST_ONLY_invalid');
   response=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await page.locator('#parse-nodes').click();const invalid=await(await response).json();
   assert(invalid.errors.length && !JSON.stringify(invalid).includes(password) && !JSON.stringify(invalid).includes(obfs));
   await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
   await page.locator('#batch_nodes').fill('Long|hy2://'+('a'.repeat(6000))+'@example.com');
   response=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await page.locator('#parse-nodes').click();assert.equal((await(await response).json()).errors.length,0);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   // Fixed Manual save/edit and uploaded external source through actual UI.
   await page.goto(base+'/fixed-subscriptions/new');
   await page.locator('#subscription-name').fill('HY2 Browser '+width);
   await page.locator('#yaml-source').selectOption('custom');
   await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxies: []\nproxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
   await page.locator('#batch_nodes').fill('US|Manual-HY2|'+hy2);
   await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
   const fixedURL=await page.locator('.fixed-url').inputValue();
   assert((await(await context.request.get(fixedURL)).text()).includes('type: hysteria2'));
   await page.locator('#batch_nodes').fill('JP|Edited-HY2|'+alias);
   await page.getByRole('button',{name:'Add Uploaded Source',exact:true}).click();
   await page.locator('.source-name').fill('HY2 uploaded');
   await page.locator('.source-file').setInputFiles({name:'hy2.txt',mimeType:'text/plain',buffer:Buffer.from(hy2+'#Singapore-Remote')});
   await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
   assert.equal(await page.locator('.fixed-url').inputValue(),fixedURL);
   const fixedOutput=await(await context.request.get(fixedURL)).text();
   assert(fixedOutput.includes('Edited-HY2') && fixedOutput.includes('Singapore-Remote'));
   assert.equal((fixedOutput.match(/type: hysteria2/g)||[]).length,2);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   assert.deepEqual(dialogs,[]);assert.deepEqual(errors,[]);await context.close();
   console.log(`Hysteria2 browser PASS: ${width}px; helpers/mixed/aux/parse-redaction/edits/diff/replace/merge/exact-download/xss/no-overflow`);
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
