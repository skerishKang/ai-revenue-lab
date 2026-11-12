/* #7573 읽기 화면 이동 레인 — 키보드 ←/→ 페이지 이동, 장 끝 이어 읽기,
   "<책> ▾" 칩의 장 번호 격자, 새로 열 때 첫 화면 홈 유지.
   index.html 에서는 이 파일을 불러오는 줄과 칩 클릭 한 줄만 바꾼다.
   장 순서와 장 수는 index.html 의 기존 자료(VOLUMES·VOLUME_CHAPTERS)를 그대로 읽는다. */
(function(){
'use strict';
if(window.BookAI7573NavigationV1)return;

/* ---- 순수 규칙(시험 가능) ---- */
function volumeList(){
  try{return (typeof VOLUMES!=='undefined'&&Array.isArray(VOLUMES))?VOLUMES.slice():[];}
  catch(_){return[];}
}
function chapterCountOf(volume){
  try{return (typeof VOLUME_CHAPTERS!=='undefined'&&VOLUME_CHAPTERS[volume])?Number(VOLUME_CHAPTERS[volume]):0;}
  catch(_){return 0;}
}
function currentBibleContext(){
  try{
    if(typeof __smCurrentReaderKind==='undefined'||__smCurrentReaderKind!=='bible')return null;
    var m=String(typeof __smCurrentReaderLabel==='string'?__smCurrentReaderLabel:'').match(/^(.+?)\s+(\d+)장$/);
    if(!m)return null;
    var volume=m[1],chapter=Number(m[2]),count=chapterCountOf(volume);
    if(!count||chapter<1||chapter>count)return null;
    return {volume:volume,chapter:chapter,count:count,index:volumeList().indexOf(volume)};
  }catch(_){return null;}
}
function nextChapterAfter(volume,chapter){
  var list=volumeList(),i=list.indexOf(volume);
  if(i<0||chapter<1)return null;
  var count=chapterCountOf(volume);
  if(!count||chapter>=count+1)return null;
  if(chapter<count)return {volume:volume,chapter:chapter+1};
  if(i>=list.length-1)return null; /* 요한계시록 끝: 멈춤 */
  var next=list[i+1];
  return chapterCountOf(next)?{volume:next,chapter:1}:null;
}
function prevChapterBefore(volume,chapter){
  var list=volumeList(),i=list.indexOf(volume);
  if(i<0||(chapter===1&&i===0))return null; /* 창세기 1장: 멈춤 */
  if(!chapterCountOf(volume))return null;
  if(chapter>1)return {volume:volume,chapter:chapter-1};
  if(i<=0)return null;
  var prev=list[i-1],count=chapterCountOf(prev);
  return count?{volume:prev,chapter:count}:null;
}

/* ---- 실제 이동 ---- */
var landing=null; /* 'first' | 'last' — 본문 묶음이 새 장으로 묶인 뒤에 적용한다 */
function readerScreenActive(){
  var r=document.getElementById('reader');
  return !!(r&&r.classList.contains('active'));
}
function openBibleChapter(volume,chapter,land){
  var count=chapterCountOf(volume);
  if(!count||chapter<1||chapter>count)return false;
  landing=land||null;
  try{setReaderContext({kind:'bible',book:'성경',volume:volume,chapter:chapter,chapterCount:count});}
  catch(_){landing=null;return false;}
  try{showScreen('reader');}catch(_){}
  if(landing)scheduleLanding();
  return true;
}
/* setReaderContext 는 새 장의 저장된 위치를 먼저 복원하므로, 이어 읽기가 요구하는
   "다음 장 첫 페이지 / 이전 장 마지막 페이지"는 본문이 묶인 뒤에 다시 적용한다. */
function scheduleLanding(){
  var want=landing;
  if(!want)return;
  var tries=0;
  var tick=function(){
    if(landing!==want)return;
    var bound=false;
    try{
      var st=__smDynamicReaderState;
      bound=!!(st&&Array.isArray(st.passages)&&st.passages.length>0);
    }catch(_){}
    if(!bound&&++tries<40){setTimeout(tick,150);return;}
    landing=null;
    try{applyLanding(want);}catch(_){}
  };
  setTimeout(tick,150);
}
function applyLanding(want){
  var inner=document.querySelector('.paper-inner');
  if(typeof readerViewMode==='string'&&readerViewMode==='flow'){
    if(inner)requestAnimationFrame(function(){
      inner.style.scrollBehavior='auto';
      inner.scrollTop=want==='last'?inner.scrollHeight:0;
      inner.style.scrollBehavior='';
    });
    return;
  }
  var total=Array.isArray(READER_PAGES)?READER_PAGES.length:0;
  if(!total)return;
  readerPageIndex=want==='last'?total-1:0;
  renderReaderPage(0);
}
function neighbourAndTurn(step){
  var ctx=currentBibleContext();
  if(!ctx)return false;
  if(step>0){
    var n=nextChapterAfter(ctx.volume,ctx.chapter);
    return n?openBibleChapter(n.volume,n.chapter,'first'):false;
  }
  var p=prevChapterBefore(ctx.volume,ctx.chapter);
  return p?openBibleChapter(p.volume,p.chapter,'last'):false;
}

/* 페이지 버튼: 장의 끝에서는 같은 버튼이 이웃 장으로 이어 읽기를 한다 */
var originalAnimateTurn=window.animateReaderPageTurn;
window.animateReaderPageTurn=function(step){
  try{
    if(readerScreenActive()&&currentBibleContext()
      &&!(typeof readerViewMode==='string'&&readerViewMode==='flow')){
      var total=Array.isArray(READER_PAGES)?READER_PAGES.length:0;
      if(total&&step>0&&readerPageIndex>=total-1){neighbourAndTurn(1);return;}
      if(total&&step<0&&readerPageIndex<=0){neighbourAndTurn(-1);return;}
    }
  }catch(_){}
  return originalAnimateTurn.apply(this,arguments);
};

/* 키보드 ←/→ : 읽기 화면에서 입력창에 포커스가 없을 때만 */
function typingTarget(t){
  try{return !!(t&&t.closest&&t.closest('input,textarea,select,[contenteditable="true"],[contenteditable="plaintext-only"]'));}
  catch(_){return false;}
}
function flowStep(step){
  var inner=document.querySelector('.paper-inner');
  if(!inner)return;
  var max=Math.max(0,inner.scrollHeight-inner.clientHeight);
  if(step>0){
    if(inner.scrollTop>=max-1){neighbourAndTurn(1);return;}
    inner.scrollTop=Math.min(max,inner.scrollTop+inner.clientHeight);
  }else{
    if(inner.scrollTop<=1){neighbourAndTurn(-1);return;}
    inner.scrollTop=Math.max(0,inner.scrollTop-inner.clientHeight);
  }
}
document.addEventListener('keydown',function(e){
  if(e.key!=='ArrowLeft'&&e.key!=='ArrowRight')return;
  if(e.ctrlKey||e.altKey||e.metaKey)return;
  if(!readerScreenActive())return;
  if(gridOpen())return;
  if(document.body.classList.contains('reader-settings-open'))return;
  if(typingTarget(e.target))return;
  e.preventDefault();
  var step=e.key==='ArrowRight'?1:-1;
  if(typeof readerViewMode==='string'&&readerViewMode==='flow'){flowStep(step);return;}
  window.animateReaderPageTurn(step);
});

/* ---- 스크롤 보기 본문 끝의 "다음 장" 링크 ---- */
function syncFlowLink(body){
  if(!body.querySelector('.reader-flow-section'))return;
  var ctx=currentBibleContext();
  var n=ctx?nextChapterAfter(ctx.volume,ctx.chapter):null;
  var link=body.querySelector('.sm7573-next-chapter');
  if(!n){if(link)link.remove();return;}
  if(!link){
    link=document.createElement('button');
    link.type='button';
    link.className='sm7573-next-chapter';
    link.addEventListener('click',function(){neighbourAndTurn(1);});
    body.append(link);
  }
  var label='다음 장 · '+n.volume+' '+n.chapter+'장 →';
  if(link.textContent!==label)link.textContent=label;
}
function enablePageButtons(){
  var reader=document.getElementById('reader');
  if(!reader||!reader.classList.contains('active'))return;
  var prev=document.getElementById('pageTurnPrev');
  var next=document.getElementById('pageTurnNext');
  /* 장의 끝에서는 버튼이 이웃 장으로 이어 읽기를 하므로 막지 않는다.
     스크롤 보기에서는 버튼 대신 본문 끝의 "다음 장" 링크를 쓴다. */
  if(prev)prev.disabled=false;
  if(next)next.disabled=false;
}
function syncAfterRender(){
  var body=document.getElementById('readerPageBody');
  if(!body)return;
  if(typeof readerViewMode==='string'&&readerViewMode==='flow'){
    syncFlowLink(body);
    return;
  }
  var stale=body.querySelector('.sm7573-next-chapter');
  if(stale)stale.remove();
  enablePageButtons();
}
var originalApplyView=window.applyReaderViewMode;
window.applyReaderViewMode=function(mode,options){
  var r=originalApplyView.apply(this,arguments);
  try{syncAfterRender();}catch(_){}
  return r;
};
var originalRenderPage=window.renderReaderPage;
window.renderReaderPage=function(){
  var r=originalRenderPage.apply(this,arguments);
  try{syncAfterRender();}catch(_){}
  return r;
};

/* ---- "<책> ▾" 칩의 장 번호 격자 ---- */
function gridOpen(){return !!document.getElementById('sm7573ChapterGrid');}
function closeGrid(){
  var o=document.getElementById('sm7573ChapterGrid');
  if(o)o.remove();
}
function openGrid(){
  var ctx=currentBibleContext();
  if(!ctx)return false;
  closeGrid();
  var ov=document.createElement('div');
  ov.id='sm7573ChapterGrid';
  ov.className='sm7573-grid-overlay';
  var card=document.createElement('div');
  card.className='sm7573-grid-card';
  card.setAttribute('role','dialog');
  card.setAttribute('aria-modal','true');
  card.setAttribute('aria-label',ctx.volume+' 장 선택');
  var head=document.createElement('div');
  head.className='sm7573-grid-head';
  var title=document.createElement('strong');
  title.textContent=ctx.volume;
  var count=document.createElement('span');
  count.className='sm7573-grid-count';
  count.textContent=ctx.count+'장';
  var other=document.createElement('button');
  other.type='button';
  other.className='sm7573-grid-otherbooks';
  other.textContent='다른 책';
  other.addEventListener('click',function(){
    closeGrid();
    try{exitReaderContext();}catch(_){}
  });
  var x=document.createElement('button');
  x.type='button';
  x.className='sm7573-grid-x';
  x.setAttribute('aria-label','닫기');
  x.textContent='×';
  x.addEventListener('click',closeGrid);
  head.append(title,count,other,x);
  var cells=document.createElement('div');
  cells.className='sm7573-grid-cells';
  for(var i=1;i<=ctx.count;i++){
    var b=document.createElement('button');
    b.type='button';
    b.className='sm7573-grid-cell'+(i===ctx.chapter?' on':'');
    b.textContent=String(i);
    b.setAttribute('aria-label',ctx.volume+' '+i+'장'+(i===ctx.chapter?' · 지금 장':''));
    if(i===ctx.chapter)b.setAttribute('aria-current','true');
    b.addEventListener('click',function(n){
      return function(){
        closeGrid();
        openBibleChapter(ctx.volume,n,'first');
      };
    }(i));
    cells.append(b);
  }
  card.append(head,cells);
  ov.append(card);
  ov.addEventListener('click',function(e){if(e.target===ov)closeGrid();});
  document.body.append(ov);
  return true;
}
document.addEventListener('keydown',function(e){
  if(e.key!=='Escape'||!gridOpen())return;
  e.preventDefault();
  e.stopPropagation();
  closeGrid();
},true);

/* 칩 클릭: 성경은 격자를 띄우고 읽기 화면에 머문다. 다른 책은 기존 동작을 유지한다. */
window.storyMemoryChapterChipClickV1=function(){
  if(openGrid())return;
  try{exitReaderContext();}catch(_){}
};

window.BookAI7573NavigationV1=Object.freeze({
  nextChapterAfter:nextChapterAfter,
  prevChapterBefore:prevChapterBefore,
  currentBibleContext:currentBibleContext,
  openBibleChapter:openBibleChapter,
  openGrid:openGrid,
  closeGrid:closeGrid,
  gridOpen:gridOpen
});
})();
