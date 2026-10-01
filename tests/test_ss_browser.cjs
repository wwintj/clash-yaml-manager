/* Real Shadowsocks Parse/Generate/Diff/download; isolated loopback, synthetic secrets. */
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
const ss='ss://'+Buffer.from('aes-256-gcm:'+password+'@example.com:443').toString('base64url');
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
   assert((await page.locator('#batch_nodes').locator('..').innerText()).includes('VMess / VLESS / Trojan / Shadowsocks'));
   assert((await page.locator('.aux-link').first().getAttribute('placeholder')).includes('ss://'));
   await page.locator('#batch_nodes').fill(vmess+'\n'+trojan+'#Tokyo-TJ\nSG|VL|'+vless+'\n'+ss+'#'+encodeURIComponent(password)+'\n'+ss+'#'+encodeURIComponent(sentinel));
   await page.locator('.aux-country').first().selectOption('TW');
   await page.locator('.aux-name').first().fill('Aux-SS');
   await page.locator('.aux-link').first().fill(ss+'#Ignored');
   let response=page.waitForResponse(r=>new URL(r.url()).pathname==='/parse-nodes');
   await page.locator('#parse-nodes').click();const parsed=await(await response).json();
   assert(!JSON.stringify(parsed).includes(password));
   await page.waitForFunction(()=>!document.getElementById('parse-nodes').disabled);
   assert.equal(await page.locator('.preview-node').count(),6);
   assert(!(await page.locator('#parse-preview').innerHTML()).includes(password));
   assert((await page.locator('#parse-preview').innerText()).includes('SS'));
   await page.locator('#parse-preview').screenshot({path:`/private/tmp/clash-ss-${width}.png`});
   const names=await page.locator('.preview-name input').evaluateAll(inputs=>inputs.map(n=>n.value));
   assert(names.includes(sentinel));assert.equal(await page.locator('#parse-preview script').count(),0);
   assert(names.some(n=>n.includes('[password hidden]')) && !names.some(n=>n.includes(password)));
   // Preview edits use the same node keys and feed Generate.
   await page.locator('.preview-name input').nth(3).fill('Edited-SS');
   await page.locator('.preview-country select').nth(3).selectOption('JP');
   await page.locator('#yaml-source').selectOption('custom');
   for(const mode of ['replace','merge']){
    await page.locator('#node-update-mode').selectOption(mode);
    await page.locator('[name=yaml_file]').setInputFiles({name:'custom.yaml',mimeType:'application/yaml',buffer:Buffer.from(source)});
    response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/preview-yaml-diff');
    await page.locator('#preview-yaml-diff').click();const diffResponse=await response;
    assert.equal(diffResponse.status(),200);const diff=await diffResponse.json();
    assert(diff.diff.includes('password:') && diff.diff.includes('type: ss'));
    await page.waitForFunction(()=>!document.getElementById('preview-yaml-diff').disabled);
    assert((await page.locator('#yaml-diff-code').textContent()).includes(sentinel));
    assert.equal(await page.locator('#yaml-diff-code script').count(),0);
    await Promise.all([page.waitForNavigation(),page.locator('#generate-yaml').click()]);
    const download=await context.request.get(await page.locator('#download-url').inputValue());assert(download.ok());
    const generated=await download.text();
    assert.equal(applyPatch(source,diff.diff),generated);
    assert(generated.includes('Edited-SS') && generated.includes('Aux-SS') && generated.includes('type: ss'));
    assert(generated.includes(password));assert.equal(generated.includes('name: old-a'),mode==='merge');
    assert.equal((generated.match(/type: ss/g)||[]).length,mode==='merge'?4:3);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   }
   assert.deepEqual(dialogs,[]);assert.deepEqual(errors,[]);await context.close();
   console.log(`Shadowsocks browser PASS: ${width}px; helpers/mixed/aux/parse-redaction/edits/diff/replace/merge/exact-download/xss/no-overflow`);
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
