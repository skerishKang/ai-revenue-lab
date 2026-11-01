// B61 #6471: anonymous sync must not send local reading data to the remote API.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.B61_CHROME_PATH?{executablePath:process.env.B61_CHROME_PATH}:{})});
  try{
    const page=await browser.newPage({viewport:{width:390,height:844}});
    let remoteRequests=0;
    await page.route('**/rest/v1/**',async route=>{remoteRequests++;await route.abort();});
    await page.goto(process.env.B61_BASE_URL||'http://127.0.0.1:18765/',{waitUntil:'load'});
    await page.waitForFunction(()=>typeof window.storyMemorySyncNow==='function'&&window.storyMemoryRemote);
    const result=await page.evaluate(async()=>{
      const sentinel=JSON.stringify(['TEST_ONLY_SYNTHETIC_PIN']);
      localStorage.setItem('storymemory.pinnedEntities.v1',sentinel);
      let code='';
      try{await window.storyMemorySyncNow();}catch(e){code=String(e&&e.message||e);}
      return {code,preserved:localStorage.getItem('storymemory.pinnedEntities.v1')===sentinel};
    });
    assert.equal(result.code,'AUTH_REQUIRED');
    assert.equal(result.preserved,true);
    assert.equal(remoteRequests,0);
    console.log('PASS: anonymous sync rejects before remote request and preserves local pin');
  }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
