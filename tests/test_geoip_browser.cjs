/* Test-only synthetic reader. No third-party MMDB, real lookup or DNS. */
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;assert(base && new URL(base).hostname==='127.0.0.1');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
   const url=route.request().url();if(url.startsWith(base))return route.continue();
   if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')&&process.env.BOOTSTRAP_CSS_PATH)
    return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
   return route.abort();
  });
  const nav=button=>Promise.all([page.waitForNavigation(),button.click()]);
  const upload=async data=>{
   await page.locator('#geoip-file').setInputFiles({name:'admin.mmdb',mimeType:'application/octet-stream',buffer:Buffer.from(data)});
   await nav(page.getByRole('button',{name:'Upload / Replace'}));
  };
  const widths=async label=>{
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    if(process.env.GEOIP_SCREENSHOT_DIR){
     fs.mkdirSync(process.env.GEOIP_SCREENSHOT_DIR,{recursive:true});
     const section=page.locator(label==='settings'?'section[aria-label="GeoIP Database"]':'section[aria-label="Country Detection"]');
     await section.screenshot({path:path.join(process.env.GEOIP_SCREENSHOT_DIR,`${label}-${width}.png`)});
    }
   }
  };
  await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
  await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
  assert.equal(await page.locator('#country-geoip').inputValue(),'off');
  assert(await page.getByText(/No GeoIP database is installed/).isVisible());
  await page.getByRole('navigation',{name:'Main navigation'}).getByRole('link',{name:'Settings',exact:true}).click();
  assert.equal(await page.locator('[data-geoip-status]').textContent(),'Not installed');
  await upload('PRIVATE invalid');
  assert(await page.getByText(/Unable to upload GeoIP database/).isVisible());
  assert.equal(await page.locator('[data-geoip-status]').textContent(),'Not installed');
  await upload('SYNTHETIC:SG');
  assert.equal(await page.locator('[data-geoip-status]').textContent(),'Ready');
  assert.equal(await page.locator('[data-geoip-type]').textContent(),'Synthetic-Country');
  assert.match(await page.locator('[data-geoip-checksum]').textContent(),/^[a-f0-9]{12}$/);
  const checksum=await page.locator('[data-geoip-checksum]').textContent();
  await upload('PRIVATE invalid replacement');assert.equal(await page.locator('[data-geoip-checksum]').textContent(),checksum);
  await widths('settings');
  await page.goto(base);await page.locator('#country-geoip').selectOption('literal-ip');
  const uuid='11111111-1111-4111-8111-111111111111';const link=`vless://${uuid}@8.8.8.8:443?type=tcp`;
  const input=`Opaque|${link}\nTaiwan-01|${link.replace('8.8.8.8','1.1.1.1')}\nOpaque-domain|${link.replace('8.8.8.8','node.example.com')}`;
  await page.locator('#batch_nodes').fill(input);await page.locator('#parse-nodes').click();
  await page.waitForFunction(()=>document.querySelector('#parse-preview').textContent.includes('Source: GeoIP'));
  assert(await page.locator('#parse-preview').getByText('Source: GeoIP',{exact:true}).isVisible());
  assert(await page.locator('#parse-preview').getByText('Source: Name Detection',{exact:true}).isVisible());
  assert(await page.locator('#parse-preview').getByText('Source: Unknown',{exact:true}).isVisible());
  const preview=await page.locator('#parse-preview').textContent();assert(!preview.includes('8.8.8.8')&&!preview.includes(uuid));
  await nav(page.locator('#generate-yaml'));
  const temporary=await page.locator('#download-url').inputValue();assert(temporary.includes('/t/'));
  const output=await context.request.get(temporary);assert.equal(output.status(),200);assert((await output.text()).includes('🇸🇬 Opaque'));
  assert.equal(await page.locator('#country-geoip').inputValue(),'off');
  const draft=await page.evaluate(()=>localStorage.getItem('clash-yaml-manager.draft.v1'));
  assert(!draft.includes('country_geoip')&&!draft.includes('literal-ip'));
  await page.goto(base+'/fixed-subscriptions/new');
  assert.equal(await page.locator('#country-geoip').inputValue(),'off');
  await page.locator('#subscription-name').fill('GeoIP Browser');await page.locator('#country-geoip').selectOption('literal-ip');
  await page.locator('#yaml-source').selectOption('custom');
  await page.locator('[name=yaml_file]').setInputFiles({name:'base.yaml',mimeType:'application/yaml',buffer:Buffer.from('proxy-groups: []\nrules: ["MATCH,DIRECT"]\n')});
  await page.locator('#batch_nodes').fill('Opaque|'+link);await page.locator('#policy_country_groups_type').selectOption('fallback');
  await nav(page.locator('#generate-yaml'));const edit=page.url(),fixed=await page.locator('.fixed-url').inputValue();
  const read=async()=>{const response=await context.request.get(fixed);assert.equal(response.status(),200);return response.text();};
  const old=await read();assert(old.includes('🇸🇬 Opaque'));assert.equal(await page.locator('#country-geoip').inputValue(),'literal-ip');
  await widths('fixed');
  await page.goto(base+'/settings');await upload('SYNTHETIC:TW');assert.equal(await read(),old);
  await page.goto(edit);assert.equal(await page.locator('#country-geoip').inputValue(),'literal-ip');await nav(page.locator('#generate-yaml'));
  assert((await read()).includes('🇹🇼 Opaque'));assert.equal(await page.locator('.fixed-url').inputValue(),fixed);
  await page.goto(base+'/settings');await nav(page.getByRole('button',{name:'Remove Database'}));
  assert.equal(await page.locator('[data-geoip-status]').textContent(),'Not installed');
  await page.goto(edit);assert.equal(await page.locator('#country-geoip').inputValue(),'literal-ip');
  assert(await page.getByText(/No GeoIP database is installed/).isVisible());
  await page.locator('#batch_nodes').fill('invalid');await nav(page.locator('#generate-yaml'));
  assert(await page.getByText(/Unable to save/).isVisible());assert.equal(await page.locator('#country-geoip').inputValue(),'literal-ip');
  await page.locator('#batch_nodes').fill('Opaque|'+link);await nav(page.locator('#generate-yaml'));
  assert((await read()).includes('🌐 Opaque'));assert.equal(await page.locator('.fixed-url').inputValue(),fixed);
  const anonymous=await browser.newContext();const response=await anonymous.request.get(base+'/settings',{maxRedirects:0});assert.equal(response.status(),302);await anonymous.close();
  assert.deepEqual(errors,[]);console.log('PASS GeoIP browser: authenticated Settings, missing/Ready, invalid replacement retains DB, Off default, GeoIP/Name/Unknown Preview, ephemeral /t, saved Fixed mode, next-save classification, remove warning, error recovery, stable /s, 1440/390 no overflow');
  await context.close();
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
