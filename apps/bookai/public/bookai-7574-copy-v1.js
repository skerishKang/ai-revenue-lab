/* bookai #7574 — 화면 문구·표시 다듬기 (이슈 7574 항목 2·3·4·7)
   2. 새 사용자에게 예시 기억(본문에서 자동 수집한 개체 기억)이 숫자로 보이지 않게:
      오늘 화면의 복습 수·미리보기는 사용자가 직접 만든 기억(메모·표시·AI 저장)만 센다.
      개체 원장(ledger) 자체는 기억 패널의 흐름·관계 기능이 그대로 쓰므로 지우지 않고
      오늘 화면 집계에서만 제외한다(숨김).
   3. AI 첫 안내 문구를 읽기 방식에 맞춘다. 찾아보며 읽기(전체 참고)에서는
      "아직 읽지 않은 내용은 보여주지 않습니다" 문구를 보여주지 않는다.
   4. AI 오류 말풍선에는 오류 문구와 "다시 시도"만 남긴다.
      (✓ 확인 배지·출처 줄·"기억에 저장" 버튼은 오류 말풍선에서 뗀다.)
   이 파일은 화면 안내 문구만 다룬다. 프롬프트·스포일러 방지 로직은 고치지 않는다. */
(function(){
  'use strict';

  /* ---- 2. 오늘 화면: 사용자가 만든 기억만 집계 ---- */
  var origTodayRecallItems=(typeof todayRecallItems==='function')?todayRecallItems:null;
  if(origTodayRecallItems){
    todayRecallItems=function(){
      return origTodayRecallItems().filter(function(item){return item.kind!=='entity';});
    };
    window.todayRecallItems=todayRecallItems;
  }

  function userDueCount(){
    try{return todayRecallItems().length;}catch(_){return 0;}
  }

  var origRenderTodayHome=(typeof renderTodayHome==='function')?renderTodayHome:null;
  if(origRenderTodayHome){
    renderTodayHome=function(){
      origRenderTodayHome.apply(this,arguments);
      try{
        var due=userDueCount();
        var count=document.getElementById('todayRecallCount');
        if(count)count.textContent=String(due);
        var entry=document.getElementById('todayEntryCount');
        if(entry)entry.textContent=String(due);
        var preview=document.getElementById('todayRecallPreview');
        var copy=document.getElementById('todayRecallCopy');
        if(!preview||!copy)return;
        if(due>0){
          var item=todayRecallItems()[0];
          preview.innerHTML='<b>다음 기억 · '+(item.title?String(item.title).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}):'')+'</b><strong>'+String(item.cue||item.prompt||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];})+'</strong><small>'+String(item.context||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];})+'</small>';
          copy.textContent='지금 떠올릴 기억 '+due+'개가 있습니다. 먼저 기억하고, 그 다음 원문을 확인합니다.';
        }else{
          preview.innerHTML='<b>복습 완료</b><strong>오늘의 복습을 마쳤습니다.</strong><small>새 기억이 쌓이면 복습 목록이 다시 만들어집니다.</small>';
          copy.textContent='지금 당장 복습할 기억이 없습니다.';
        }
      }catch(_){}
    };
    window.renderTodayHome=renderTodayHome;
  }

  /* ---- 3. AI 첫 안내: 읽기 방식에 맞는 문구 ---- */
  var GUIDE_BROWSE='지금 읽는 책의 내용과 저장한 기억을 함께 사용해 답합니다.';
  var GUIDE_FIRST_READ='지금까지 읽은 범위와 저장한 기억만 사용해 답합니다. 아직 읽지 않은 내용은 보여주지 않습니다.';
  function currentWorkKey(){
    try{
      var rc=(window.storyMemoryGetReaderContextV1&&window.storyMemoryGetReaderContextV1())||null;
      return (rc&&rc.current_work_key)||'bible-web';
    }catch(_){return 'bible-web';}
  }
  function updateCompanionGuideCopy(){
    var p=document.querySelector('#companionEmptyState p');
    if(!p)return;
    var mode=null;
    try{mode=window.storyMemoryGetReadingModeV1?window.storyMemoryGetReadingModeV1(currentWorkKey()):null;}catch(_){mode=null;}
    p.textContent=(mode==='first_read')?GUIDE_FIRST_READ:GUIDE_BROWSE;
  }
  var origSetReadingMode=window.storyMemorySetReadingModeV1;
  if(typeof origSetReadingMode==='function'){
    window.storyMemorySetReadingModeV1=function(workKey,mode){
      var r=origSetReadingMode(workKey,mode);
      updateCompanionGuideCopy();
      return r;
    };
  }
  var origSetReaderContext=(typeof setReaderContext==='function')?setReaderContext:null;
  if(origSetReaderContext){
    setReaderContext=function(){
      var r=origSetReaderContext.apply(this,arguments);
      updateCompanionGuideCopy();
      return r;
    };
    window.setReaderContext=setReaderContext;
  }

  /* ---- 4. AI 오류 말풍선: 오류 문구와 다시 시도만 ---- */
  var prevAppend=window.appendAIMessage;
  if(typeof prevAppend==='function'){
    var stripErrorExtras=function(node){
      if(!node)return;
      ['.verified','.source','.save-ai-memory','.ai-persona-chip'].forEach(function(sel){
        node.querySelectorAll(sel).forEach(function(el){el.remove();});
      });
    };
    window.appendAIMessage=function(title,body,source,meta){
      var node=prevAppend(title,body,source,meta);
      try{if(meta&&meta.error)stripErrorExtras(node);}catch(_){}
      return node;
    };
  }

  /* ---- 최초 1회 적용 ---- */
  function initialApply(){
    try{if(origRenderTodayHome)renderTodayHome();}catch(_){}
    try{updateCompanionGuideCopy();}catch(_){}
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',initialApply,{once:true});
  }else{
    initialApply();
  }
  window.addEventListener('bookai-ready',initialApply,{once:true});
})();
