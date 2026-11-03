/* B61 #6474 · Bible reference jump and full-text search. */
(function(){
'use strict';
var panel=document.getElementById('bibleSearchPanel');
var form=document.getElementById('bibleSearchForm');
var input=document.getElementById('bibleSearchInput');
var submit=document.getElementById('bibleSearchSubmit');
var status=document.getElementById('bibleSearchStatus');
var results=document.getElementById('bibleSearchResults');
var returnButton=document.getElementById('bibleSearchReturn');
if(!panel||!form||!input||!window.storyMemoryBibleReferenceV1||!window.__smLocatorResolverV1)return;

var resolver=window.__smLocatorResolverV1;
var parser=window.storyMemoryBibleReferenceV1;
var bookAliases=resolver.bookAliases||{};
var chapterCounts=resolver.chapterCounts||{};
var bibleBlocksPromise=null;
var previewActive=false;
var returnSnapshot=null;
var originalSaveReaderProgress=null;
var originalSyncVisibleProgress=null;
var originalSchedulePersist=null;

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
function compactBlocksFromUnit(unit,manifestUnit){
  var rows=unit.passages||[];var out=[];var code=String(unit.unit_key||manifestUnit.unit_key||'').split(':')[1]||'';
  var chapter=Number(String(unit.unit_key||manifestUnit.unit_key||'').split(':').pop())||0;
  rows.forEach(function(row){
    if(!row||!row.canonical_locator)return;
    var parts=String(row.canonical_locator).split(':');var ch=Number(parts[3])||chapter;var verse=Number(parts[4])||null;
    var ko=String(row.ko||'');var en=String(row.en||'');
    out.push({canonical_locator:String(row.canonical_locator),work_key:'bible-web',unit_key:String(unit.unit_key||manifestUnit.unit_key||''),unit_ordinal:Number(unit.unit_ordinal||manifestUnit.unit_ordinal)||0,sequence:Number(row.sequence)||0,ordinal:Number(row.sequence)||0,title:escapeLabel(code,ch,verse),text:ko||en,sourceText:en||ko,ko:ko,en:en});
  });
  return out;
}
async function loadBibleBlocks(onProgress){
  if(bibleBlocksPromise)return bibleBlocksPromise;
  bibleBlocksPromise=(async function(){
    var response=await fetch('./content/bible-web/manifest.json',{credentials:'same-origin'});
    if(!response.ok)throw new Error('BIBLE_MANIFEST_UNAVAILABLE');
    var manifest=await response.json();var units=Array.isArray(manifest.units)?manifest.units:[];
    if(!units.length)throw new Error('BIBLE_MANIFEST_EMPTY');
    var blocks=[];var next=0;var finished=0;var failure=null;
    async function worker(){
      while(next<units.length&&!failure){
        var index=next++;var entry=units[index];
        try{
          var unitResponse=await fetch('./content/bible-web/'+entry.path,{credentials:'same-origin'});
          if(!unitResponse.ok)throw new Error('BIBLE_UNIT_UNAVAILABLE');
          var unit=await unitResponse.json();blocks.push.apply(blocks,compactBlocksFromUnit(unit,entry));
        }catch(error){failure=error;break}
        finished++;
        if(onProgress&&(finished%60===0||finished===units.length))onProgress(finished,units.length);
      }
    }
    await Promise.all(Array.from({length:10},worker));
    if(failure)throw failure;
    return blocks;
  })().catch(function(error){bibleBlocksPromise=null;throw error});
  return bibleBlocksPromise;
}
async function showTextResults(query){
  if(!window.__smStaticKeywordSearchV1||typeof window.__smStaticKeywordSearchV1.staticKeywordSearch!=='function'){
    setStatus('본문 검색을 시작할 수 없어요. 화면을 새로고침해 주세요.');return;
  }
  submit.disabled=true;input.disabled=true;
  try{
    var blocks=await loadBibleBlocks(function(done,total){setStatus('성경 본문을 불러오는 중이에요 ('+done.toLocaleString()+' / '+total.toLocaleString()+')')});
    setStatus('성경 본문 '+blocks.length.toLocaleString()+'개 구절에서 검색하고 있어요.');
    var result=window.__smStaticKeywordSearchV1.staticKeywordSearch(query,{workKey:'bible-web',blocks:blocks,limit:8});
    clearResults();
    if(!result.results||!result.results.length){setStatus('검색 결과가 없어요. 다른 단어로 다시 찾아보세요.');return}
    result.results.forEach(function(row){appendResult(row.display_title||row.title,row.snippet||row.ko||row.en,row.canonical_locator,'본문 결과 열기')});
    setStatus(result.total.toLocaleString()+'개 결과 중 '+result.results.length+'개를 표시합니다. 결과를 누르면 해당 구절로 이동합니다.');
  }catch(error){
    setStatus('성경 본문을 검색하지 못했어요. 연결을 확인하고 다시 시도해 주세요.');
  }finally{submit.disabled=false;input.disabled=false}
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
if(typeof setReaderContext==='function'){
  var originalSetReaderContext=setReaderContext;
  setReaderContext=function(){var result=originalSetReaderContext.apply(this,arguments);syncPanelVisibility();return result};
}
syncPanelVisibility();
window.storyMemoryBibleSearchV1={parseReference:parser.parseReference,loadBibleBlocks:loadBibleBlocks,openSearchResult:openSearchResult,returnToReadingPosition:returnToReadingPosition};
})();
