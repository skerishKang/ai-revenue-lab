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
function resultLabel(row){
  var parts=String(row&&row.canonical_locator||'').split(':');
  if(parts[0]==='bible'&&parts.length>=5)return escapeLabel(parts[2],Number(parts[3]),Number(parts[4]));
  return row&&((row.display_title||row.title)||'본문 검색 결과')||'본문 검색 결과';
}
function referenceLike(value){return /\d|장|절|:/.test(String(value||''))}
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
  var unit=await fetchChapter(parsed.book,parsed.chapter);
  var passage=parsed.verse==null?(unit.passages||[])[0]:parser.matchPassage(parsed,unit);
  if(!passage){setStatus('해당 절을 찾지 못했어요. 절 번호를 확인해 주세요.');return}
  var verse=Number(String(passage.canonical_locator||'').split(':').pop())||null;
  var label=escapeLabel(parsed.book,parsed.chapter,parsed.verse);
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
async function loadBibleBlocks(onProgress,signal){
  var manifest=await getIndexManifest(signal);var shards=manifest.shards;
  if(!shards.length)throw new Error('BIBLE_SEARCH_INDEX_EMPTY');
  var completed=shards.reduce(function(n,shard){return n+(loadedIndexShards[shard.path]?1:0)},0);
  if(onProgress)onProgress(completed,shards.length);
  var next=0;var failure=null;
  async function worker(){
    while(next<shards.length&&!failure&&!signal?.aborted){
      var shard=shards[next++];if(loadedIndexShards[shard.path])continue;
      try{
        var response=await fetch('./content/bible-web/search-index/'+shard.path,{credentials:'same-origin',signal:signal});
        if(!response.ok)throw new Error('BIBLE_SEARCH_SHARD_UNAVAILABLE');
        loadedIndexShards[shard.path]=blocksFromShard(await response.json());completed++;
        if(onProgress)onProgress(completed,shards.length);
      }catch(error){failure=error;break}
    }
  }
  await worker();
  if(signal?.aborted)throw new DOMException('Search cancelled','AbortError');
  if(failure)throw failure;
  if(completed!==shards.length)throw new Error('BIBLE_SEARCH_INDEX_INCOMPLETE');
  return shards.flatMap(function(shard){return loadedIndexShards[shard.path]||[]});
}
async function showTextResults(query){
  if(!window.__smStaticKeywordSearchV1||typeof window.__smStaticKeywordSearchV1.staticKeywordSearch!=='function'){
    setStatus('본문 검색을 시작할 수 없어요. 화면을 새로고침해 주세요.');return;
  }
  searchController=new AbortController();submit.disabled=true;input.disabled=true;cancelButton.hidden=false;retryButton.hidden=true;
  try{
    var blocks=await loadBibleBlocks(function(done,total){setStatus('성경 검색 색인을 불러오는 중이에요 ('+done+' / '+total+' 묶음)')},searchController.signal);
    setStatus('성경 본문 '+blocks.length.toLocaleString()+'개 구절에서 검색하고 있어요.');
    var result=window.__smStaticKeywordSearchV1.staticKeywordSearch(query,{workKey:'bible-web',blocks:blocks,limit:8});
    clearResults();
    if(!result.results||!result.results.length){setStatus('검색 결과가 없어요. 다른 단어로 다시 찾아보세요.');return}
    result.results.forEach(function(row){appendResult(resultLabel(row),row.snippet||row.ko||row.en,row.canonical_locator,'본문 결과 열기')});
    setStatus(result.total.toLocaleString()+'개 결과 중 '+result.results.length+'개를 표시합니다. 결과를 누르면 해당 구절로 이동합니다.');
  }catch(error){
    if(error&&error.name==='AbortError')setStatus('색인 불러오기를 취소했어요. 다시 검색하면 이어서 불러옵니다.');
    else{setStatus('성경 검색 색인을 불러오지 못했어요. 연결을 확인한 뒤 다시 시도해 주세요.');retryButton.hidden=false}
  }finally{submit.disabled=false;input.disabled=false}
  cancelButton.hidden=true;searchController=null;
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
async function openSearchResult(locator){
  if(!locator)return;
  if(!returnSnapshot)returnSnapshot=captureReturnSnapshot();
  if(!returnSnapshot){setStatus('성경을 읽는 화면에서 검색 결과를 열어 주세요.');return}
  previewActive=true;suppressProgressWrites();returnButton.hidden=false;panel.open=false;submit.disabled=true;
  var parts=String(locator).split(':');var code=parts[2];var chapter=Number(parts[3]);
  try{
    setReaderContext({kind:'bible',book:'성경',volume:bookNameForCode(code),chapter:chapter,chapterCount:chapterCounts[code]||16});
    showScreen('reader');
    var page=await waitForReaderPassage(locator);
    readerPageIndex=page;
    if(typeof readerViewMode==='string'&&readerViewMode==='flow')applyReaderViewMode('flow',{restore:false});
    else renderReaderPage(0);
    if(typeof highlightWhenReady==='function')highlightWhenReady(locator,Number(parts[4])||null,0);
    setStatus('검색 결과를 미리 보고 있어요. 원래 읽던 위치는 그대로 저장되어 있습니다.');
  }catch(_){
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
  event.preventDefault();var query=String(input.value||'').trim();clearResults();
  if(!query){setStatus('구절이나 본문 검색어를 입력해 주세요.');return}
  if(previewActive){setStatus('먼저 원래 읽던 위치로 돌아가 주세요.');return}
  var parsed=parser.parseReference(query,bookAliases,chapterCounts);
  if(parsed.ok){submit.disabled=true;setStatus('구절을 확인하고 있어요.');try{await showReference(parsed)}catch(_){setStatus('해당 장 본문을 불러오지 못했어요. 연결을 확인해 주세요.')}finally{submit.disabled=false}return}
  if(referenceLike(query)){setStatus(referenceError(parsed));return}
  setStatus('성경 본문 검색을 준비하고 있어요. 첫 검색은 본문을 불러오느라 시간이 걸릴 수 있습니다.');
  await showTextResults(query);
});
returnButton.addEventListener('click',returnToReadingPosition);
cancelButton.addEventListener('click',function(){if(searchController)searchController.abort()});
retryButton.addEventListener('click',function(){retryButton.hidden=true;form.requestSubmit()});
if(typeof setReaderContext==='function'){
  var originalSetReaderContext=setReaderContext;
  setReaderContext=function(){var result=originalSetReaderContext.apply(this,arguments);syncPanelVisibility();return result};
}
syncPanelVisibility();
window.storyMemoryBibleSearchV1={parseReference:parser.parseReference,loadBibleBlocks:loadBibleBlocks,openSearchResult:openSearchResult,returnToReadingPosition:returnToReadingPosition};
})();
