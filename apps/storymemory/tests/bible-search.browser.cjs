const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const baseUrl=process.env.B61_BASE_URL||'http://127.0.0.1:18793/';
const screenshotPath=process.env.B61_SCREENSHOT_PATH||'D:\\PADIEM\\b61-6474\\bible-search-390.png';
const repoRoot=path.resolve(__dirname,'../../..');
assert.ok(path.relative(repoRoot,path.resolve(screenshotPath)).startsWith('..'),'screenshot must be stored outside the repository');
fs.mkdirSync(path.dirname(screenshotPath),{recursive:true});

(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.B61_CHROME_PATH?{executablePath:process.env.B61_CHROME_PATH}:{})});
  const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
  page.setDefaultTimeout(20000);
  const browserErrors=[];
  const indexRequests=[];
  let expectedIndex503=0;
  page.on('pageerror',error=>browserErrors.push(error.message));
  page.on('console',message=>{
    if(message.type()!=='error')return;
    if(expectedIndex503>0&&message.text().includes('503 (Service Unavailable)')){expectedIndex503--;return}
    browserErrors.push(message.text());
  });
  page.on('request',request=>{if(request.url().includes('/content/bible-web/search-index/'))indexRequests.push(request.url())});
  try{
    await page.goto(baseUrl,{waitUntil:'load'});
    await page.locator('#library.active').waitFor();
    await page.locator('#openBook').click();
    await page.locator('#index.active').waitFor();
    await page.locator('#resume').click();
    await page.locator('#reader.active').waitFor();
    await page.locator('#readerPageBody .sm-source-passage').first().waitFor({timeout:30000});
    const panel=page.locator('#bibleSearchPanel');
    assert.equal(await panel.locator('input').count(),1);
    assert.equal(await panel.evaluate(el=>el.closest('.memory-rail')),null,'Bible search is separate from Memory search');
    await panel.locator('summary').click();
    await page.evaluate(()=>{
      if(readerViewMode!=='page')applyReaderViewMode('page',{restore:false});
      readerPageIndex=Math.min(1,Math.max(0,READER_PAGES.length-1));
      renderReaderPage(0);saveReaderProgress();
    });
    await page.waitForTimeout(120);
    const before=await page.evaluate(()=>({
      title:document.getElementById('readerVolumeTitle').textContent.trim(),
      chapter:document.getElementById('readerChapterTitle').textContent.trim(),
      page:readerPageIndex,
      progress:Object.fromEntries(Array.from({length:localStorage.length},(_,i)=>localStorage.key(i)).filter(k=>k&&k.startsWith('storymemory.readerProgress.')).map(k=>[k,localStorage.getItem(k)])),
      reading:localStorage.getItem('storymemory.readingProgress.v1')
    }));
    assert.equal(await page.locator('#memorySearchInput').getAttribute('aria-label'),'Memory 검색');
    async function openSearchPanel(){if(!(await panel.evaluate(el=>el.open)))await panel.locator('summary').click()}

    async function runRef(query,locator){
      await openSearchPanel();
      await page.locator('#bibleSearchInput').fill(query);
      await page.locator('#bibleSearchForm').press('Enter');
      try{await page.waitForFunction(()=>document.querySelectorAll('#bibleSearchResults .bible-search-result').length>0)}catch(error){throw new Error('reference result missing for '+query+'; status='+await page.locator('#bibleSearchStatus').innerText()+'; parsed='+JSON.stringify(await page.evaluate(q=>window.storyMemoryBibleSearchV1?.parseReference(q,window.__smLocatorResolverV1?.bookAliases,window.__smLocatorResolverV1?.chapterCounts),query))+'; '+error.message)}
      assert.equal(await page.locator('#readerVolumeTitle').innerText(),before.title,'search itself must not navigate');
      await page.locator('#bibleSearchResults .bible-search-result').first().click();
      await page.waitForFunction(expected=>!!document.querySelector('#readerPageBody [data-source-locator="'+expected+'"]'),locator,{timeout:30000});
      assert.equal(await page.locator('#bibleSearchReturn').isVisible(),true);
      await page.locator('#bibleSearchReturn').click();
      await page.waitForFunction(title=>document.getElementById('readerVolumeTitle').textContent.trim()===title&&document.getElementById('bibleSearchReturn').hidden,before.title,{timeout:30000});
      await page.waitForTimeout(80);
      const after=await page.evaluate(()=>({
        title:document.getElementById('readerVolumeTitle').textContent.trim(),
        chapter:document.getElementById('readerChapterTitle').textContent.trim(),
        page:readerPageIndex,
        progress:Object.fromEntries(Array.from({length:localStorage.length},(_,i)=>localStorage.key(i)).filter(k=>k&&k.startsWith('storymemory.readerProgress.')).map(k=>[k,localStorage.getItem(k)])),
        reading:localStorage.getItem('storymemory.readingProgress.v1')
      }));
      assert.deepEqual(after,before,'temporary result navigation must restore reading position and stored progress');
    }

    await runRef('요한복음 3장 16절','bible:web:JHN:3:16');
    await runRef('요 3:16','bible:web:JHN:3:16');
    await runRef('요3:16','bible:web:JHN:3:16');
    await runRef('요한복음 3장','bible:web:JHN:3:1');

    for(const [query,message] of [
      ['요한복음 30장','해당 장이 없어요'],
      ['요한복음 3장 999절','해당 절을 찾지 못했어요'],
      ['요한복옴 3:16','책 이름을 찾지 못했어요'],
      ['요한복음 삼장','구절 형식을 확인해 주세요']
    ]){
      await openSearchPanel();
      await page.locator('#bibleSearchInput').fill(query);
      await page.locator('#bibleSearchForm').press('Enter');
      await page.getByRole('status').filter({hasText:message}).waitFor();
      assert.equal(await page.locator('#bibleSearchResults .bible-search-result').count(),0);
      assert.equal(await page.locator('#readerVolumeTitle').innerText(),before.title);
    }

    assert.equal(indexRequests.length,0,'direct verse lookup must not request the full-text index');
    const searchChapterRequests=[];
    const trackSearchChapter=request=>{if(request.url().includes('/content/bible-web/book-'))searchChapterRequests.push(request.url())};
    page.on('request',trackSearchChapter);
    await openSearchPanel();
    await page.locator('#bibleSearchInput').fill('태초에');
    let markShardStarted;
    const shardStarted=new Promise(resolve=>{markShardStarted=resolve});
    const observeShard=request=>{if(request.url().endsWith('/search-index/shard-01.json'))markShardStarted()};
    page.on('request',observeShard);
    const indexPattern='**/content/bible-web/search-index/shard-*.json';
    const slowShard=async route=>{
      if(route.request().url().endsWith('/search-index/shard-01.json')){
        await new Promise(resolve=>setTimeout(resolve,2500));
        try{await route.continue()}catch(_){}
      }else await route.continue();
    };
    await page.route(indexPattern,slowShard);
    await page.locator('#bibleSearchForm').press('Enter');
    await shardStarted;
    await page.waitForFunction(()=>/묶음/.test(document.querySelector('#bibleSearchStatus')?.textContent||''));
    assert.equal(await page.locator('#bibleSearchCancel').isVisible(),true);
    await page.locator('#bibleSearchCancel').click();
    await page.getByRole('status').filter({hasText:'취소했어요'}).waitFor();
    assert.equal(await page.locator('#bibleSearchInput').isDisabled(),false);
    await page.unroute(indexPattern,slowShard);
    page.off('request',observeShard);

    let failFirstShard=true;
    const failOnce=async route=>{
      if(failFirstShard&&route.request().url().endsWith('/search-index/shard-12.json')){
        failFirstShard=false;
        expectedIndex503++;
        await route.fulfill({status:503,contentType:'text/plain',body:'temporary index error'});
      }else await route.continue();
    };
    await page.route(indexPattern,failOnce);
    await page.locator('#bibleSearchInput').fill('태초에');
    await page.locator('#bibleSearchForm').press('Enter');
    try{await page.locator('#bibleSearchRetry').waitFor({state:'visible'})}catch(error){throw new Error('retry control missing; status='+await page.locator('#bibleSearchStatus').innerText()+'; failFirstShard='+failFirstShard+'; requests='+JSON.stringify(indexRequests)+'; '+error.message)}
    assert.match(await page.locator('#bibleSearchStatus').innerText(),/다시 시도해 주세요/);
    await page.unroute(indexPattern,failOnce);
    await page.locator('#bibleSearchRetry').click();
    await page.waitForFunction(()=>/개 결과 중/.test(document.querySelector('#bibleSearchStatus')?.textContent||''),null,{timeout:180000});
    assert.match(await page.locator('#bibleSearchResults .bible-search-result').first().locator('strong').innerText(),/창세기 1장 1절/);
    const uniqueShards=new Set(indexRequests.filter(url=>/\/shard-\d+\.json$/.test(url)).map(url=>url.match(/shard-\d+\.json$/)[0]));
    assert.equal(uniqueShards.size,12,'a complete text search must load the 12 generated index shards');
    assert.ok(indexRequests.length<20,'search must fetch index shards, not the 1,189 chapter files');
    assert.deepEqual(searchChapterRequests,[],'finding text results must not load any chapter bodies');
    page.off('request',trackSearchChapter);
    const overflow=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
    assert.ok(overflow.document<=390&&overflow.body<=390,'390px view overflows horizontally: '+JSON.stringify(overflow));
    await page.screenshot({path:screenshotPath,fullPage:false});
    const previewChapterRequests=[];
    const trackPreviewChapter=request=>{if(request.url().includes('/content/bible-web/book-'))previewChapterRequests.push(new URL(request.url()).pathname.split('/').pop())};
    page.on('request',trackPreviewChapter);
    await page.locator('#bibleSearchResults .bible-search-result').first().click();
    await page.waitForFunction(()=>!!document.querySelector('#readerPageBody [data-source-locator="bible:web:GEN:1:1"]'),null,{timeout:30000});
    await page.waitForTimeout(200);
    assert.deepEqual([...new Set(previewChapterRequests)],['book-GEN-chapter-001.json'],'opening a text result should load only its chapter file');
    page.off('request',trackPreviewChapter);
    await page.locator('#bibleSearchReturn').click();
    await page.waitForFunction(title=>document.getElementById('readerVolumeTitle').textContent.trim()===title&&document.getElementById('bibleSearchReturn').hidden,before.title,{timeout:30000});

    if(browserErrors.length)throw new Error('browser console/page errors: '+browserErrors.join(' | '));
    console.log('PASS: 390px references, full-text search, cancel, failure retry, one-chapter preview and return');
    console.log('SCREENSHOT '+screenshotPath);
    console.log('PASS: browser console/page errors = 0');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
