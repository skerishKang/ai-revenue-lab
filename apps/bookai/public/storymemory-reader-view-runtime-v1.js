/* B61 #1337 R4 CENTRAL PREP/HOLD — behavior-preserving Reader view runtime extraction. */
(function(g){
  'use strict';
  const api={
    readerProgressStorageKey: function(){
 return 'storymemory.readerProgress.'+encodeURIComponent(__smCurrentReaderLabel);
},
    readStoredReaderProgress: function(){
 try{
   const p=JSON.parse(localStorage.getItem(readerProgressStorageKey())||'{}');
   return p&&typeof p==='object'?p:{};
 }catch(_){return {}}
},
    saveReaderProgress: function(extra={}){
 const inner=document.querySelector('.paper-inner');
 const max=Math.max(1,inner.scrollHeight-inner.clientHeight);
 const payload={
   mode:readerViewMode,
   page:readerPageIndex,
   scrollRatio:readerViewMode==='flow'?Math.max(0,Math.min(1,inner.scrollTop/max)):0,
   context:__smCurrentReaderLabel,
   updatedAt:Date.now(),
   ...extra
 };
 try{localStorage.setItem(readerProgressStorageKey(),JSON.stringify(payload))}catch(_){}
 if(typeof scheduleUnifiedPersist==='function')scheduleUnifiedPersist();
},
    syncReaderViewButtons: function(){
 document.querySelectorAll('[data-reader-view]').forEach(b=>b.classList.toggle('on',b.dataset.readerView===readerViewMode));
 document.getElementById('reader').classList.toggle('flow-mode',readerViewMode==='flow');
},
    flowSectionMarkup: function(html,index){
 return `<section class="reader-flow-section" data-flow-page="${index}"><span class="reader-flow-folio">PAGE ${String(index+1).padStart(2,'0')}</span>${html}</section>`;
},
    renderFlowReader: function({restoreRatio=null,focusPage=null}={}){
 const body=document.getElementById('readerPageBody');
 const inner=document.querySelector('.paper-inner');
 body.innerHTML=READER_PAGES.map(flowSectionMarkup).join('');
 wireReaderEntityInteractions();
 renderContextualQuestions();
 document.getElementById('readerPageCount').textContent='FLOW · '+(readerPageIndex+1)+' / '+READER_PAGES.length;
 document.getElementById('pageTurnPrev').disabled=true;
 document.getElementById('pageTurnNext').disabled=true;
 syncReaderViewButtons();
  restoreCurrentAnnotations();

  requestAnimationFrame(()=>{
    if(focusPage!==null){
      body.querySelector(`[data-flow-page="${focusPage}"]`)?.scrollIntoView({block:'start'});
    }else if(Number.isFinite(restoreRatio)){
      const max=Math.max(0,inner.scrollHeight-inner.clientHeight);
      const prevBehavior=inner.style.scrollBehavior;
      inner.style.scrollBehavior='auto';
      inner.scrollTop=max*restoreRatio;
      void inner.offsetHeight;
      inner.style.scrollBehavior=prevBehavior;
    }
    updateFlowProgress();
    try{ if(window.storyMemorySyncVisibleToProgressV1) window.storyMemorySyncVisibleToProgressV1(); }catch(_){}
  });
 },
    updateFlowProgress: function(){
 if(readerViewMode!=='flow')return;
 // A hidden Reader has no reliable layout/scroll geometry. During boot we
 // hydrate its data model while Library is visible, so do not overwrite the
 // persisted Flow position until Reader is actually on screen.
 if(!document.getElementById('reader')?.classList.contains('active'))return;
 const inner=document.querySelector('.paper-inner');
 const max=Math.max(1,inner.scrollHeight-inner.clientHeight);
 const ratio=Math.max(0,Math.min(1,inner.scrollTop/max));
 const innerRect=inner.getBoundingClientRect();
 let active=0,best=Infinity;
 document.querySelectorAll('.reader-flow-section').forEach((sec,i)=>{
   const d=Math.abs(sec.getBoundingClientRect().top-(innerRect.top+26));
   if(d<best){best=d;active=i}
 });
  readerPageIndex=active;
  document.getElementById('readerPageCount').textContent='FLOW · '+Math.round(ratio*100)+'%';
  document.documentElement.style.setProperty('--page-progress',(ratio*100)+'%');
  saveReaderProgress({scrollRatio:ratio});
  try{ if(window.storyMemorySyncVisibleToProgressV1) window.storyMemorySyncVisibleToProgressV1(); }catch(_){}
 },
    applyReaderViewMode: function(mode,{restore=false}={}){
 readerViewMode=mode==='flow'?'flow':'page';
 syncReaderViewButtons();
 const stored=restore?readStoredReaderProgress():{};
 if(readerViewMode==='flow'){
   renderFlowReader({restoreRatio:restore&&Number.isFinite(stored.scrollRatio)?stored.scrollRatio:null,focusPage:restore?null:readerPageIndex});
 }else{
   if(restore&&Number.isFinite(stored.page))readerPageIndex=Math.max(0,Math.min(READER_PAGES.length-1,stored.page));
   renderReaderPage(0);
 }
 // On restore, keep the persisted progress intact until the restored DOM
 // position is actually applied. Otherwise the temporary scrollTop=0
 // would overwrite the saved Flow ratio before requestAnimationFrame runs.
 if(!restore)saveReaderProgress();
},
    renderReaderPage: function(direction=0){
  if(readerViewMode==='flow'){renderFlowReader();return}
  const body=document.getElementById('readerPageBody');
  const paper=document.getElementById('paper');
  body.innerHTML=READER_PAGES[readerPageIndex];
  wireReaderEntityInteractions();
  renderContextualQuestions();
  document.getElementById('readerPageCount').textContent=`PAGE ${readerPageIndex+1} / ${READER_PAGES.length}`;
  document.getElementById('pageEdgeCurrent').textContent=String(readerPageIndex+1).padStart(2,'0');
  document.getElementById('pageEdgeTotal').textContent=String(READER_PAGES.length).padStart(2,'0');
  document.documentElement.style.setProperty('--page-progress',`${((readerPageIndex+1)/READER_PAGES.length)*100}%`);
  document.getElementById('pageTurnPrev').disabled=readerPageIndex===0;
  document.getElementById('pageTurnNext').disabled=readerPageIndex===READER_PAGES.length-1;
  paper.style.setProperty('--page-shift',(direction>=0?14:-14)+'px');
  paper.classList.remove('page-content-changing');
  void paper.offsetWidth;
  paper.classList.add('page-content-changing');
  setTimeout(()=>paper.classList.remove('page-content-changing'),560);
  document.querySelector('.paper-inner').scrollTop=0;
   restoreCurrentAnnotations();
   wireMemoryItems();
   wireSystemMemoryTimeline();
   syncAnnotationStats();
   renderAnnotationMemoryList();
   renderUserMemoryList();
   saveReaderProgress();
   try{ if(window.storyMemorySyncVisibleToProgressV1) window.storyMemorySyncVisibleToProgressV1(); }catch(_){}
 },
    changeReaderPage: function(step){
  const next=Math.max(0,Math.min(READER_PAGES.length-1,readerPageIndex+step));
  if(next===readerPageIndex)return false;
  readerPageIndex=next;
  renderReaderPage(step);
  return true;
},
    animateReaderPageTurn: function(step){
  if(readerViewMode==='flow')return;
  if((step>0&&readerPageIndex>=READER_PAGES.length-1)||(step<0&&readerPageIndex<=0))return;
  const d=step>0?1:-1;
  if(!__smPrepareCurl(d))return;
  const duration=__smCurlSettleMs();
  applyCurl(.015,d);
  requestAnimationFrame(()=>{
    __smSetCurlSettling(true,duration);
    requestAnimationFrame(()=>applyCurl(1,d));
  });
  setTimeout(()=>{
    changeReaderPage(step);
    __smCleanupCurl();
  },duration+35);
}
  };
  g.StoryMemoryReaderViewRuntimeV1=Object.freeze(api);
})(window);
