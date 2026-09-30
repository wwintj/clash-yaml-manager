/* Controlled Telegram transport only; all browser requests confined to fixtures. */
const assert=require('node:assert/strict');const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL, control=process.env.EXTERNAL_TEST_CONTROL;
const token='123456789:TEST_ONLY_BOT_TOKEN_abcdefghijklmnopqrstuvwxyz', chat='-1009876543210';
(async()=>{const browser=await chromium.launch({headless:true});try{
 const context=await browser.newContext(),page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const url=route.request().url();if(url.startsWith(base))return route.continue();
  if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')&&process.env.BOOTSTRAP_CSS_PATH)return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
  return route.abort();
 });
 const fixture=async mode=>assert.equal((await context.request.post(control,{data:'notifications-'+mode})).status(),204);
 const count=async()=>Number(await(await context.request.get(new URL('notification-count',control).href)).text());
 const submit=async id=>{await Promise.all([page.waitForNavigation(),page.locator('#'+id+' button[type=submit]').click()]);assert(page.url().endsWith('/settings#notifications'));};
 const verify=async()=>{
  assert.equal(await page.locator('#telegram-token').inputValue(),'');assert.equal(await page.locator('#telegram-chat').inputValue(),'');
  const html=await page.content();for(const secret of [token,chat,'PRIVATE_NOTIFICATION_STATE_SECRET',process.env.PREVIEW_TEST_PASSWORD])assert(!html.includes(secret));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 };
 await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
 await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
 for(const width of [1440,390]){
  await fixture('clear');await page.setViewportSize({width,height:900});await page.goto(base+'/settings?fixture=default&width='+width+'#notifications');
  assert.equal(await page.locator('.settings-nav a').count(),5);
  assert((await page.locator('#notifications').textContent()).includes('Disabled'));
  assert(await page.locator('#notification-test button').isDisabled());await verify();assert.equal(await count(),0);
  await page.locator('#telegram-token').fill(token);await page.locator('#telegram-chat').fill(chat);
  await page.locator('#notification-settings [name=enabled]').check();
  await page.locator('#notification-settings [name=source_refresh]').uncheck();await submit('notification-settings');
  assert((await page.locator('#notifications').textContent()).includes('Enabled'));
  assert((await page.locator('#notifications').textContent()).includes('••••3210'));
  assert.equal(await page.locator('#notification-settings [name=source_refresh]').isChecked(),false);
  await verify();assert.equal(await count(),0);
  await page.locator('#notification-settings [name=enabled]').uncheck();await submit('notification-settings');
  assert(await page.locator('#notification-test button').isEnabled());await verify();assert.equal(await count(),0);
  await submit('notification-test');assert((await page.locator('body').textContent()).includes('Telegram test notification sent.'));
  assert.equal(await count(),1);await verify();
  await fixture('network');await submit('notification-test');assert((await page.locator('body').textContent()).includes('Telegram test failed.'));
  assert((await page.locator('#notifications').textContent()).includes('network'));assert.equal(await count(),2);await verify();
  await submit('notification-remove');assert((await page.locator('#notifications').textContent()).includes('Not configured'));
  assert(await page.locator('#notification-test button').isDisabled());assert.equal(await count(),2);await verify();
  await fixture('corrupt');await page.goto(base+'/settings?fixture=corrupt&width='+width+'#notifications');
  assert((await page.locator('#notifications').textContent()).includes('Configuration unavailable'));
  assert.equal(await page.locator('#notifications input, #notifications form').count(),0);
  for(const section of ['overview','geoip','health','runtime'])assert.equal(await page.locator('#'+section).count(),1);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert(!(await page.content()).includes('PRIVATE_NOTIFICATION_STATE_SECRET'));
 }
 await fixture('clear');assert.deepEqual(errors,[]);await context.close();
 console.log('Notifications browser PASS: 1440px / 390px; private masked settings, toggles, controlled test outcomes, removal, corruption');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
