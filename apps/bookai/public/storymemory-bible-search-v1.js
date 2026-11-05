/* B61 #6474 · Bible reference jump and full-text search. */
(function(){
'use strict';
var panel=document.getElementById('bibleSearchPanel');
var form=document.getElementById('bibleSearchForm');
var input=document.getElementById('bibleSearchInput');
var submit=document.getElementById('bibleSearchSubmit');
var cancelButton=document.getElementById('bibleSearchCancel');
var retryButton=document.getElementById('bibleSearchRetry');
var status=document.getElementById('bibleSearchStatus');
var results=document.getElementById('bibleSearchResults');
var returnButton=document.getElementById('bibleSearchReturn');
if(!panel||!form||!input||!window.storyMemoryBibleReferenceV1||!window.__smLocatorResolverV1)return;

var resolver=window.__smLocatorResolverV1;
var parser=window.storyMemoryBibleReferenceV1;
var bookAliases=resolver.bookAliases||{};
var chapterCounts=resolver.chapterCounts||{};
var indexManifestPromise=null;
var loadedIndexShards=Object.create(null);
var searchController=null;
var previewActive=false;
var returnSnapshot=null;
var originalSaveReaderProgress=null;
var originalSyncVisibleProgress=null;
var originalSchedulePersist=null;
var originalPrefetchNeighbors=null;

function bookNameForCode(code){
  var map=window.storyMemoryBibleUsfmCodes||{};
  for(var name in map)if(Object.prototype.hasOwnProperty.call(map,name)&&map[name]===code)return name;
  return code;
}
function isBibleReader(){try{return typeof __smCurrentReaderKind!=='undefined'?__smCurrentReaderKind==='bible':true}catch(_){return true}}
function syncPanelVisibility(){panel.hidden=!isBibleReader()}
function setStatus(text){status.textContent=String(text||'')}
function clearResults(){results.replaceChildren()}
  function escapeLabel(code,chapter,verse){return bookNameForCode(code)+' '+chapter+'장'+(verse==null?'':' '+verse+'절')}
  function krvLabelForBlock(row){
    if(!row)return null;
    var raw=row.raw_locator;
    var r=Array.isArray(raw)?raw[0]:(raw||null);
    if(r&&r.book&&r.chapter!=null&&r.verse!=null)return bookNameForCode(String(r.book))+' '+Number(r.chapter)+'장 '+Number(r.verse)+'절';
    var parts=String(row.canonical_locator||'').split(':');
    if(parts[0]==='bible'&&parts.length>=5)return escapeLabel(parts[2],Number(parts[3]),Number(parts[4]));
    return null;
  }
  function resultLabel(row){
    var lbl=krvLabelForBlock(row);
    if(lbl)return lbl;
    return row&&((row.display_title||row.title)||'본문 검색 결과')||'본문 검색 결과';
  }
  // Reference gate: only when a book alias matched AND the input carries digits.
  // unknown_book / invalid_format fall through to full-text search (e.g. 장막, 유월절).
  function shouldTreatAsReference(query,parsed){
    if(!parsed)return false;
    if(parsed.ok)return true;
    var err=parsed.error;
    if(err==='invalid_chapter'||err==='ambiguous_book'||err==='invalid_verse')return true;
    // unknown_book / invalid_format / others -> text search
    return false;
  }
  var ORPHAN_VERSES={'ACT:8:37':1,'ACT:15:34':1,'ACT:24:7':1,'LUK:17:36':1};
  function orphanNote(parsed){
    var key=parsed.book+':'+parsed.chapter+':'+parsed.verse;
    if(ORPHAN_VERSES[key])return '이 판본 배열에는 없는 절이에요. 해당 절은 KRV에만 있고 WEB 대조본에는 빠져 있습니다.';
    return null;
  }
function chapterPath(code,chapter){return './content/bible-web/book-'+code+'-chapter-'+String(chapter).padStart(3,'0')+'.json'}
async function fetchChapter(code,chapter){
  var response=await fetch(chapterPath(code,chapter),{credentials:'same-origin'});
  if(!response.ok)throw new Error('CHAPTER_UNAVAILABLE');
  return response.json();
}
function referenceError(parsed){
  if(parsed.error==='unknown_book')return '책 이름을 찾지 못했어요. 책 이름이나 약어를 확인해 주세요.';
  if(parsed.error==='invalid_chapter')return '그 책에는 해당 장이 없어요. 장 번호를 확인해 주세요.';
  if(parsed.error==='ambiguous_book')return '책 약어가 여러 책과 겹쳐요. 책 이름을 더 정확히 입력해 주세요.';
  return '구절 형식을 확인해 주세요. 예: 요한복음 3장 16절 또는 요 3:16';
}
function appendResult(label,snippet,locator,buttonLabel){
  var li=document.createElement('li');
  var button=document.createElement('button');button.type='button';button.className='bible-search-result';
  var title=document.createElement('strong');title.textContent=label;
  var text=document.createElement('span');text.textContent=snippet||'본문을 열어 확인합니다.';
  button.append(title,text);
  if(buttonLabel)button.setAttribute('aria-label',buttonLabel+' · '+label);
  button.addEventListener('click',function(){openSearchResult(locator)});
  li.append(button);results.append(li);
}
  async function showReference(parsed){
    var orphanMsg=orphanNote(parsed);
    if(orphanMsg){ setStatus(orphanMsg); return; }
    var unit=await fetchChapter(parsed.book,parsed.chapter);
    var passage=parsed.verse==null?(unit.passages||[])[0]:parser.matchPassage(parsed,unit);
    if(!passage&&parsed.verse!=null){
      // KRV chapter-shift rows (e.g. KRV ROM 16:25-27 live in WEB ROM 14) are stored
      // under a neighbouring chapter. Probe +/-2 chapters before declaring the verse missing.
      var siblings=[parsed.chapter-2,parsed.chapter-1,parsed.chapter+1,parsed.chapter+2];
      for(var si=0;si<siblings.length&&!passage;si++){
        var sib=siblings[si];
        if(sib<1||sib>(chapterCounts[parsed.book]||0))continue;
        try{var altUnit=await fetchChapter(parsed.book,sib);passage=parser.matchPassage(parsed,altUnit);if(passage)unit=altUnit;}catch(_){}
      }
    }
    if(!passage){setStatus('해당 절을 찾지 못했어요. 절 번호를 확인해 주세요.');return}
    var krv=parser.krvLabelOf?parser.krvLabelOf(passage,parsed.book):null;
    var label=parsed.verse==null?bookNameForCode(parsed.book)+' '+parsed.chapter+'장':(krv?bookNameForCode(krv.book)+' '+krv.chapter+'장 '+(krv.verse!=null?krv.verse+'절':''):escapeLabel(parsed.book,parsed.chapter,parsed.verse));
    if(parsed.isRange&&parsed.rangeStart!=null&&parsed.rangeEnd!=null){
      label+=parsed.rangeEndChapter!=null&&parsed.rangeEndChapter!==parsed.chapter
        ?' ('+parsed.chapter+':'+parsed.rangeStart+'-'+parsed.rangeEndChapter+':'+parsed.rangeEnd+')'
        :' ('+parsed.chapter+':'+parsed.rangeStart+'-'+parsed.rangeEnd+')';
    }
    appendResult(label,String(passage.ko||passage.en||'').trim(),passage.canonical_locator,parsed.verse==null?'이 장으로 이동':'이 구절로 이동');
    setStatus(parsed.verse==null?'장 본문을 확인했어요. 결과를 누르면 이 장으로 이동합니다.':'구절을 찾았어요. 결과를 누르면 해당 본문으로 이동합니다.');
  }
function blocksFromShard(shard){
  if(!shard||shard.schema_version!==1||!Array.isArray(shard.units))throw new Error('BIBLE_SEARCH_SHARD_INVALID');
  var blocks=[];
  shard.units.forEach(function(unit){
    if(!Array.isArray(unit)||unit.length<6)return;
    var code=String(unit[0]||'');var chapter=Number(unit[1])||0;var unitOrdinal=Number(unit[2])||0;var unitLabel=String(unit[3]||'');var firstSequence=Number(unit[4])||0;
    var unitKey='book:'+code+':chapter:'+String(chapter).padStart(3,'0');
    (unit[5]||[]).forEach(function(row,index){
      if(!Array.isArray(row)||row.length<4)return;
      var verse=Number(row[0])||0;var sequence=firstSequence+index;var ko=String(row[2]||'');var en=String(row[3]||'');
      var locator='bible:web:'+code+':'+chapter+':'+verse;
      var title=String(((row[1]||'')+' '+unitLabel+' bible-web').trim());
      var extra=row[4]||null;
      blocks.push({canonical_locator:locator,work_key:'bible-web',unit_key:unitKey,unit_ordinal:unitOrdinal,sequence:sequence,ordinal:sequence,locator:locator,title:title,text:ko||en,sourceText:en||ko,ko:ko,en:en,raw_texts:extra?extra[0]:[ko],raw_locator:extra?extra[1]:[{book:code,chapter:chapter,verse:verse}],mapping_type:extra?extra[2]:'normal',mapping_note:extra?extra[3]:null});
    });
  });
  return blocks;
}
function getIndexManifest(signal){
  if(!indexManifestPromise){
    indexManifestPromise=fetch('./content/bible-web/search-index/manifest.json',{credentials:'same-origin',signal:signal}).then(function(response){if(!response.ok)throw new Error('BIBLE_SEARCH_MANIFEST_UNAVAILABLE');return response.json()}).then(function(manifest){if(manifest.schema_version!=='storymemory-bible-search-index-1'||!Array.isArray(manifest.shards))throw new Error('BIBLE_SEARCH_MANIFEST_INVALID');return manifest}).catch(function(error){indexManifestPromise=null;throw error});
  }
  return indexManifestPromise;
}
async function loadBibleBlocks(onProgress,signal,options){
  options=options||{};
  var laneLimit=Math.max(1,Math.min(4,Number(options.lanes)||4));
  var manifest=await getIndexManifest(signal);var shards=manifest.shards;
  if(!shards.length)throw new Error('BIBLE_SEARCH_INDEX_EMPTY');
  var completed=shards.reduce(function(n,shard){return n+(loadedIndexShards[shard.path]?1:0)},0);
  if(onProgress)onProgress(completed,shards.length);
  var next=0;var failure=null;
  var fetchFailed=null;
  async function worker(){
    while(next<shards.length&&!fetchFailed&&!signal?.aborted){
      var shard=shards[next++];if(loadedIndexShards[shard.path])continue;
      try{
        var response=await fetch('./content/bible-web/search-index/'+shard.path,{credentials:'same-origin',signal:signal});
        if(!response.ok)throw new Error('BIBLE_SEARCH_SHARD_UNAVAILABLE');
        loadedIndexShards[shard.path]=blocksFromShard(await response.json());completed++;
        if(onProgress)onProgress(completed,shards.length);
      }catch(error){fetchFailed=error;break}
    }
  }
  var laneCount=Math.min(laneLimit,shards.length);var lanes=[];
  for(var lane=0;lane<laneCount;lane++)lanes.push(worker());
  await Promise.all(lanes);
  if(signal?.aborted)throw new DOMException('Search cancelled','AbortError');
  if(fetchFailed)throw fetchFailed;
  if(completed!==shards.length)throw new Error('BIBLE_SEARCH_INDEX_INCOMPLETE');
  return shards.flatMap(function(shard){return loadedIndexShards[shard.path]||[]});
}
  async function showTextResults(query){
    if(!window.__smStaticKeywordSearchV1||typeof window.__smStaticKeywordSearchV1.staticKeywordSearch!=='function'){
      setStatus('본문 검색을 시작할 수 없어요. 화면을 새로고침해 주세요.');return;
    }
    searchController=new AbortController();submit.disabled=true;input.disabled=true;cancelButton.hidden=false;retryButton.hidden=true;
    try{
      var blocks=null;
      if(preloadedBlocksPromise){try{blocks=await preloadedBlocksPromise;}catch(_){blocks=null;}}
      if(!blocks||!blocks.length)blocks=await loadBibleBlocks(function(done,total){setStatus('성경 검색 색인을 불러오는 중이에요 ('+done+' / '+total+' 묶음)')},searchController.signal);
      setStatus('성경 본문 '+blocks.length.toLocaleString()+'개 구절에서 검색하고 있어요.');
      var result=window.__smStaticKeywordSearchV1.staticKeywordSearch(query,{workKey:'bible-web',blocks:blocks,limit:50});
      clearResults();
      if(!result.results||!result.results.length){setStatus('검색 결과가 없어요. 다른 단어로 다시 찾아보세요.');return}
      shownResultCount=0;
      result.results.slice(0,20).forEach(function(row){appendResult(resultLabel(row),row.snippet||row.ko||row.en,row.canonical_locator,'본문 결과 열기'); shownResultCount++;});
      lastTextResult=result;
      setStatus(result.total.toLocaleString()+'개 결과 중 '+shownResultCount+'개를 표시합니다. 결과를 누르면 해당 구절로 이동합니다.');
      if(result.total>20)ensureMoreButton();
    }catch(error){
      if(error&&error.name==='AbortError')setStatus('색인 불러오기를 취소했어요. 다시 검색하면 이어서 불러옵니다.');
      else{setStatus('성경 검색 색인을 불러오지 못했어요. 연결을 확인한 뒤 다시 시도해 주세요.');retryButton.hidden=false}
    }finally{submit.disabled=false;input.disabled=false}
    cancelButton.hidden=true;searchController=null;
  }
  var lastTextResult=null, shownResultCount=0, moreButton=null;
  function ensureMoreButton(){
    if(moreButton&&moreButton.isConnected)return;
    moreButton=document.createElement('button');moreButton.type='button';moreButton.textContent='더 보기';
    moreButton.className='bible-search-more';
    moreButton.addEventListener('click',function(){
      if(!lastTextResult)return;
      var slice=lastTextResult.results.slice(shownResultCount,shownResultCount+20);
      slice.forEach(function(row){appendResult(resultLabel(row),row.snippet||row.ko||row.en,row.canonical_locator,'본문 결과 열기'); shownResultCount++;});
      setStatus(lastTextResult.total.toLocaleString()+'개 결과 중 '+shownResultCount+'개를 표시합니다.');
      if(shownResultCount>=lastTextResult.results.length){moreButton.remove();moreButton=null;}
    });
    results.parentElement.insertBefore(moreButton,results.nextSibling);
  }
  var highlightGeneration=0;
  var preloadedBlocksPromise=null;
  var prefetchScheduled=false;
  var prefetchObserver=null;
  var PREFETCH_DELAY_MS=3000;
  var PREFETCH_INDEX_BATCH=800;
  function warnPrefetch(message,error){
    try{console.warn('[bible-search] '+message,String(error&&error.message||error||''));}catch(_){}
  }
  function prefetchSkipped(){
    if(window.__smBibleSearchNoPrefetch)return true; // test hook: keep the cold-start path deterministic
    var conn=navigator.connection;
    if(conn&&(conn.saveData||/(^|\-)2g$/.test(String(conn.effectiveType||''))))return true;
    if(document.hidden)return true;
    if(!isBibleReader())return true;
    return false;
  }
  function scheduleIdle(fn,timeout){
    var wait=Math.max(0,Number(timeout)||3000);
    if(typeof requestIdleCallback==='function'){
      try{return {kind:'idle',id:requestIdleCallback(fn,{timeout:wait})};}
      catch(error){warnPrefetch('requestIdleCallback schedule failed',error);}
    }
    return {kind:'timeout',id:setTimeout(fn,wait)};
  }
  function readerPassageReady(){
    try{return !!document.querySelector('#readerPageBody .sm-source-passage');}catch(_){return false;}
  }
  function schedulePrefetchAfterRender(){
    if(prefetchScheduled||preloadedBlocksPromise)return;
    prefetchScheduled=true;
    setTimeout(function(){
      if(prefetchSkipped()){prefetchScheduled=false;return;}
      scheduleIdle(function(){startIndexPrefetch();},3000);
    },PREFETCH_DELAY_MS);
  }
  function armIndexPrefetch(){
    try{
      if(preloadedBlocksPromise||prefetchScheduled||prefetchObserver)return;
      if(prefetchSkipped())return;
      if(readerPassageReady()){schedulePrefetchAfterRender();return;}
      if(typeof MutationObserver!=='function')return;
      prefetchObserver=new MutationObserver(function(){
        if(!readerPassageReady())return;
        try{prefetchObserver.disconnect();}catch(_){}
        prefetchObserver=null;
        if(prefetchSkipped())return;
        schedulePrefetchAfterRender();
      });
      prefetchObserver.observe(document,{childList:true,subtree:true});
    }catch(error){warnPrefetch('prefetch arm failed',error);}
  }
  async function buildPrefetchedIndex(blocks){
    var api=window.__smStaticKeywordSearchV1;
    if(!api||typeof api.indexBlocksRange!=='function'||typeof api.primeLexicalIndex!=='function'||typeof api.hasCachedIndex!=='function')return false;
    if(api.hasCachedIndex(blocks))return true;
    return new Promise(function(resolve){
      var postings=new Map();var cursor=0;
      function step(){
        try{
          var end=Math.min(blocks.length,cursor+PREFETCH_INDEX_BATCH);
          api.indexBlocksRange(blocks,postings,cursor,end);
          cursor=end;
          if(cursor<blocks.length){scheduleIdle(step,2000);return;}
          api.primeLexicalIndex(blocks,postings);
          resolve(true);
        }catch(error){warnPrefetch('index prefetch failed',error);resolve(false);}
      }
      scheduleIdle(step,2000);
    });
  }
  function startIndexPrefetch(){
    try{
      if(preloadedBlocksPromise||prefetchSkipped())return;
      var run=(async function(){
        var blocks=await loadBibleBlocks(null,null,{lanes:1});
        await buildPrefetchedIndex(blocks);
        return blocks;
      })();
      preloadedBlocksPromise=run.catch(function(error){
        warnPrefetch('prefetch failed',error);
        preloadedBlocksPromise=null;
        return null;
      });
    }catch(error){warnPrefetch('prefetch start failed',error);}
  }
function captureReturnSnapshot(){
  if(!isBibleReader())return null;
  var chapterText=document.getElementById('readerChapterTitle')?.textContent||'';
  var chapterMatch=chapterText.match(/\d+/);var volume=String(document.getElementById('readerVolumeTitle')?.textContent||'').trim();
  var chapter=chapterMatch?Number(chapterMatch[0]):1;
  var inner=document.querySelector('.paper-inner');
  return {context:{kind:'bible',book:'성경',volume:volume,chapter:chapter,chapterCount:(typeof VOLUME_CHAPTERS!=='undefined'&&VOLUME_CHAPTERS[volume])||chapterCounts[(window.storyMemoryBibleUsfmCodes||{})[volume]]||16},page:typeof readerPageIndex==='number'?readerPageIndex:0,mode:typeof readerViewMode==='string'?readerViewMode:'page',scrollTop:inner?inner.scrollTop:0};
}
function suppressProgressWrites(){
  if(typeof storyMemoryPrefetchReaderNeighbors==='function'&&!originalPrefetchNeighbors){
    originalPrefetchNeighbors=storyMemoryPrefetchReaderNeighbors;
    storyMemoryPrefetchReaderNeighbors=function(){if(previewActive)return Promise.resolve({applied:false,reason:'TEMP_SEARCH_PREVIEW'});return originalPrefetchNeighbors.apply(this,arguments)};
  }
  if(typeof saveReaderProgress==='function'&&!originalSaveReaderProgress){
    originalSaveReaderProgress=saveReaderProgress;
    saveReaderProgress=function(){if(previewActive)return;return originalSaveReaderProgress.apply(this,arguments)};
  }
  if(window.storyMemorySyncVisibleToProgressV1&&!originalSyncVisibleProgress){
    originalSyncVisibleProgress=window.storyMemorySyncVisibleToProgressV1;
    window.storyMemorySyncVisibleToProgressV1=function(){if(previewActive)return null;return originalSyncVisibleProgress.apply(this,arguments)};
  }
  if(typeof scheduleUnifiedPersist==='function'&&!originalSchedulePersist){
    originalSchedulePersist=scheduleUnifiedPersist;
    scheduleUnifiedPersist=function(){if(previewActive)return;return originalSchedulePersist.apply(this,arguments)};
  }
}
function waitForReaderPassage(locator){
  return new Promise(function(resolve,reject){
    var started=Date.now();
    (function poll(){
      var state=null;try{state=typeof __smDynamicReaderState!=='undefined'?__smDynamicReaderState:null}catch(_){}
      var groups=state&&state.pagePassages||[];var targetPage=-1;
      for(var i=0;i<groups.length;i++)for(var j=0;j<(groups[i]||[]).length;j++)if(String(groups[i][j].canonicalLocator||groups[i][j].canonical_locator||'')===locator)targetPage=i;
      if(targetPage>=0){resolve(targetPage);return}
      if(Date.now()-started>20000){reject(new Error('READER_PASSAGE_TIMEOUT'));return}
      setTimeout(poll,100);
    })();
  });
}
  function callHighlight(locator,verse){
    try{
      if(typeof highlightWhenReady==='function')highlightWhenReady(locator,verse,0);
      else if(window.__smV1823EvidenceUXV1&&typeof window.__smV1823EvidenceUXV1.highlightWhenReady==='function')window.__smV1823EvidenceUXV1.highlightWhenReady(locator,verse,0);
    }catch(_){}
  }
  async function openSearchResult(locator){
    if(!locator)return;
    var myGen=++highlightGeneration;
    if(!returnSnapshot)returnSnapshot=captureReturnSnapshot();
    if(!returnSnapshot){setStatus('성경을 읽는 화면에서 검색 결과를 열어 주세요.');return}
    previewActive=true;suppressProgressWrites();returnButton.hidden=false;panel.open=false;submit.disabled=true;
    var parts=String(locator).split(':');var code=parts[2];var chapter=Number(parts[3]);
    try{
      setReaderContext({kind:'bible',book:'성경',volume:bookNameForCode(code),chapter:chapter,chapterCount:chapterCounts[code]||16});
      showScreen('reader');
      var page=await waitForReaderPassage(locator);
      if(myGen!==highlightGeneration)return; // superseded by a newer click
      readerPageIndex=page;
      if(typeof readerViewMode==='string'&&readerViewMode==='flow')applyReaderViewMode('flow',{restore:false});
      else renderReaderPage(0);
      callHighlight(locator,Number(parts[4])||null);
      setStatus('검색 결과를 미리 보고 있어요. 원래 읽던 위치는 그대로 저장되어 있습니다.');
    }catch(_){
      if(myGen!==highlightGeneration)return;
      setStatus('해당 본문을 열지 못했어요. 검색을 다시 시도해 주세요.');
      await returnToReadingPosition();
    }finally{submit.disabled=false}
  }
function waitForChapterBinding(){
  return new Promise(function(resolve,reject){
    var started=Date.now();
    (function poll(){
      var state=null;try{state=typeof __smDynamicReaderState!=='undefined'?__smDynamicReaderState:null}catch(_){}
      if(state&&state.mode==='static'&&state.passages&&state.passages.length){resolve();return}
      if(Date.now()-started>20000){reject(new Error('READER_RESTORE_TIMEOUT'));return}
      setTimeout(poll,100);
    })();
  });
}
async function returnToReadingPosition(){
  if(!returnSnapshot)return;
  var saved=returnSnapshot;previewActive=true;suppressProgressWrites();returnButton.disabled=true;
  try{
    setReaderContext(saved.context);showScreen('reader');
    await waitForChapterBinding();
    readerViewMode=saved.mode==='flow'?'flow':'page';readerPageIndex=Math.max(0,Math.min(READER_PAGES.length-1,saved.page));
    applyReaderViewMode(readerViewMode,{restore:false});
    await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve)})});
    var inner=document.querySelector('.paper-inner');if(inner)inner.scrollTop=saved.scrollTop;
  }catch(_){setStatus('원래 읽던 위치를 복원하지 못했어요. 현재 장을 다시 열어 주세요.')}
  previewActive=false;returnSnapshot=null;returnButton.hidden=true;returnButton.disabled=false;
  if(originalSchedulePersist)originalSchedulePersist(0);
  if(originalPrefetchNeighbors)Promise.resolve().then(function(){return originalPrefetchNeighbors()}).catch(function(){});
  setStatus('원래 읽던 위치로 돌아왔어요.');
}
  form.addEventListener('submit',async function(event){
    event.preventDefault();var query=String(input.value||'').trim();clearResults();if(moreButton&&moreButton.isConnected){moreButton.remove();moreButton=null;}shownResultCount=0;lastTextResult=null;
    if(!query){setStatus('구절이나 본문 검색어를 입력해 주세요.');return}
    if(previewActive){setStatus('먼저 원래 읽던 위치로 돌아가 주세요.');return}
    var parsed=parser.parseReference(query,bookAliases,chapterCounts);
    if(shouldTreatAsReference(query,parsed)){
      if(parsed.ok){submit.disabled=true;setStatus('구절을 확인하고 있어요.');try{await showReference(parsed)}catch(_){setStatus('해당 장 본문을 불러오지 못했어요. 연결을 확인해 주세요.')}finally{submit.disabled=false}return}
      setStatus(referenceError(parsed));return;
    }
    setStatus('성경 본문 검색을 준비하고 있어요. 첫 검색은 본문을 불러오느라 시간이 걸릴 수 있습니다.');
    await showTextResults(query);
  });
returnButton.addEventListener('click',returnToReadingPosition);
cancelButton.addEventListener('click',function(){if(searchController)searchController.abort()});
retryButton.addEventListener('click',function(){retryButton.hidden=true;form.requestSubmit()});
  if(typeof setReaderContext==='function'){
    var originalSetReaderContext=setReaderContext;
    setReaderContext=function(){var result=originalSetReaderContext.apply(this,arguments);syncPanelVisibility();armIndexPrefetch();return result};
  }
  syncPanelVisibility();
  armIndexPrefetch();
  window.storyMemoryBibleSearchV1={parseReference:parser.parseReference,loadBibleBlocks:loadBibleBlocks,openSearchResult:openSearchResult,returnToReadingPosition:returnToReadingPosition,shouldTreatAsReference:shouldTreatAsReference,krvLabelForBlock:krvLabelForBlock,armIndexPrefetch:armIndexPrefetch,prefetchState:function(){return {scheduled:prefetchScheduled,started:!!preloadedBlocksPromise};}};
})();
