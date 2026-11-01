const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.B61_CHROME_PATH});
 try{
  const page=await browser.newPage();
  await page.goto(process.env.B61_BASE_URL||'http://127.0.0.1:18844/');
  await page.addScriptTag({url:'/bookai-local-db.js'});
  const result=await page.evaluate(async()=>{
   const key='storymemory.userMemories.v1', second='storymemory.annotations.v2';
   localStorage.setItem(key,'legacy');localStorage.setItem(second,'["original"]');
   await BookAILocalDB.set(key,'indexeddb-newer');let error='';
   try{await BookAILocalDB.migrate(localStorage)}catch(e){error=e.message}
   return {error,legacy:localStorage.getItem(key),value:await BookAILocalDB.get(key),second:await BookAILocalDB.get(second)};
  });
  assert.equal(result.error,'migration_conflict');assert.equal(result.legacy,'legacy');
  assert.equal(result.value,'indexeddb-newer');assert.equal(result.second,null);
  console.log('PASS: conflicting migration aborts atomically and keeps both originals');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
