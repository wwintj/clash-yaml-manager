/* Read-only deployment reporting, controlled metadata and 1440/390 px layouts. */
const assert=require('node:assert/strict');const {chromium}=require('playwright');
const base=process.env.PREVIEW_TEST_URL;
(async()=>{const browser=await chromium.launch({headless:true});try{
 const context=await browser.newContext();const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const url=route.request().url();if(url.startsWith(base))return route.continue();
  if(url.endsWith('/bootstrap@5.3.3/dist/css/bootstrap.min.css')&&process.env.BOOTSTRAP_CSS_PATH)return route.fulfill({path:process.env.BOOTSTRAP_CSS_PATH,contentType:'text/css'});
  return route.abort();
 });
 await page.goto(base);await page.locator('#password').fill(process.env.PREVIEW_TEST_PASSWORD);
 await Promise.all([page.waitForNavigation(),page.locator('#password').press('Enter')]);
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:900});
  for(const [mode,status] of [['absent','Not configured'],['configured','Configured'],['invalid','Metadata unavailable'],['manual','Not configured']]){
   assert.equal((await context.request.post(process.env.EXTERNAL_TEST_CONTROL,{data:'https-'+mode})).status(),204);
   await page.goto(base+'/settings?fixture='+mode+'&width='+width+'#runtime');
   assert.equal(await page.locator('[data-runtime=managed_https]').textContent(),status);
   assert.equal(await page.locator('[data-runtime=managed_domain]').count(),mode==='configured'?1:0);
   if(mode==='configured')assert.equal(await page.locator('[data-runtime=managed_domain]').textContent(),'example.com');
   assert.equal(await page.locator('[data-runtime=bind]').textContent(),['configured','manual'].includes(mode)?'Loopback only':'All interfaces');
   assert.equal(await page.locator('#runtime input, #runtime button, #runtime form').count(),0);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   const html=await page.content();for(const secret of ['PRIVATE_METADATA_SECRET','PRIVATE_EMAIL@example.com',process.env.PREVIEW_TEST_PASSWORD])assert(!html.includes(secret));
  }
 }
 await context.request.post(process.env.EXTERNAL_TEST_CONTROL,{data:'https-absent'});
 assert.deepEqual(errors,[]);await context.close();console.log('HTTPS settings browser PASS: 1440px / 390px; four states; no privileged controls');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
