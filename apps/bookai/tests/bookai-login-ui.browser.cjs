const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});let signedIn=false,logout=0;
  await page.route('**/auth/session',r=>r.fulfill({json:{authenticated:signedIn}}));
  await page.route('**/auth/refresh',r=>r.fulfill({status:401,json:{error:'not_authenticated'}}));
  await page.route('**/auth/login',r=>r.fulfill({body:'login route reached'}));
  await page.route('**/auth/logout',r=>{logout++;signedIn=false;return r.fulfill({json:{ok:true}})});
  await page.goto((process.env.B61_BASE_URL||'http://127.0.0.1:18844/')+'?view=today');
  await page.waitForFunction(()=>window.BookAISession);
  await page.evaluate(()=>window.openStoryMemoryAuth());
  await page.waitForFunction(()=>document.getElementById('authGatePrimary').textContent==='파디엠으로 로그인');
  signedIn=true;await page.evaluate(()=>window.BookAISession.refresh());
  assert.equal(await page.locator('#authGatePrimary').textContent(),'로그아웃');
  await page.locator('#authGatePrimary').click();
  await page.waitForFunction(()=>document.getElementById('authGatePrimary').textContent==='파디엠으로 로그인');
  assert.equal(logout,1);assert.equal(await page.evaluate(()=>window.BookAISession.isAuthenticated()),false);
  await Promise.all([page.waitForURL('**/auth/login'),page.locator('#authGatePrimary').click()]);
  console.log('PASS: actual login UI login route, mock session and logout');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
