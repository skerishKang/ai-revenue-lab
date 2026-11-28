/* StoryMemory B61 #1844 — Library first screen repair (behavior-preserving).
   Moves MOTION and the ORDER action into a quiet ··· overflow menu and
   gives the selected-book CTA a reading-state-aware label.
   No shelf, reader, source-importer, or AI logic is modified. */
(function(){
  'use strict';
  var library=document.getElementById('library');
  if(!library)return;

  /* #1844: keep BOOKS / SOURCES / + in a dedicated shelf-local toolbar.
     The toolbar is intentionally a sibling of .shelf-wrap: source mode hides
     .shelf-wrap, and nesting the switch inside it would make the control vanish. */
  function mountShelfModeSwitch(){
    var switcher=library.querySelector('.source-mode-switch');
    if(!switcher)return false;
    var slot=library.querySelector('.library-shelf-toolbar');
    if(!slot){
      slot=document.createElement('div');
      slot.className='library-shelf-toolbar';
      slot.setAttribute('aria-label','Library view controls');
      library.append(slot);
    }
    if(switcher.parentNode!==slot)slot.append(switcher);
    switcher.dataset.libraryLocal='shelf';
    return true;
  }
  if(!mountShelfModeSwitch()){
    var switchRetries=0;
    var waitSwitch=setInterval(function(){
      if(mountShelfModeSwitch()||++switchRetries>40)clearInterval(waitSwitch);
    },100);
  }

  /* 1. ··· overflow menu: MOTION + shelf ORDER live here, not in primary chrome. */
  var btn=document.createElement('button');
  btn.type='button';btn.id='libOverflow';
  btn.setAttribute('aria-expanded','false');btn.setAttribute('aria-label','라이브러리 설정');
  btn.textContent='···';
  var menu=document.createElement('div');
  menu.className='lib-overflow-menu';menu.id='libOverflowMenu';
  btn.setAttribute('aria-haspopup','true');
  btn.setAttribute('aria-controls','libOverflowMenu');
  library.append(btn,menu);

  function closeMenu(){
    menu.classList.remove('open');
    btn.setAttribute('aria-expanded','false');
  }
  btn.addEventListener('click',function(e){
    e.stopPropagation();
    var open=menu.classList.toggle('open');
    btn.setAttribute('aria-expanded',open?'true':'false');
  });
  document.addEventListener('click',function(e){
    if(menu.classList.contains('open')&&!menu.contains(e.target)&&e.target!==btn)closeMenu();
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'&&menu.classList.contains('open'))closeMenu();
  });

  var motion=document.getElementById('motionControl');
  var feedback=document.createElement('button');
  feedback.type='button';feedback.className='bookai-feedback-menu-item';
  feedback.textContent='의견 보내기';
  feedback.addEventListener('click',function(){
    closeMenu();
    var trigger=document.getElementById('bookaiFeedbackOpen');
    if(trigger)trigger.click();
  });
  menu.append(feedback);

  /* 기존 계정·속도·순서 단추를 재사용한다. 네 줄 모두 동일한 목록이 된다. */
  var menuTries=0;
  function arrangeMenu(){
    var account=document.getElementById('bookaiAccountMenu');
    var order=document.getElementById('libraryOrderToggle');
    var motionToggle=motion&&motion.querySelector('#motionToggle');
    if(!(account&&motion&&order&&motionToggle)){
      if(++menuTries<60)setTimeout(arrangeMenu,100);
      return;
    }
    var motionText=motionToggle.querySelector('span');
    if(motionText)motionText.textContent='책 넘김 속도';
    [account,motionToggle,order,feedback].forEach(function(el){el.classList.add('sm-library-menu-item');});
    menu.append(account,motion,order,feedback);
    if(typeof storyMemorySyncLibraryOrderControl==='function')storyMemorySyncLibraryOrderControl();
    menu.dataset.ready='1';
  }
  arrangeMenu();

  /* 2. Selected-book CTA label follows reading state: NEW / READING / FINISHED. */
  function labelCta(){
    var open=document.getElementById('openBook');
    if(!open)return;
    if(typeof BOOKS==='undefined'||typeof selected==='undefined')return;
    if(typeof storyMemoryBookReadingState!=='function')return;
    var book=BOOKS[selected];
    if(!book)return;
    var s=storyMemoryBookReadingState(book);
    open.textContent=s.state==='reading'?'이어서 읽기':s.state==='complete'?'다시 읽기':'읽기 시작';
    open.dataset.readingState=s.state;
  }
  if(typeof storyMemorySyncLibraryContinueCard==='function'){
    var orig=storyMemorySyncLibraryContinueCard;
    window.storyMemorySyncLibraryContinueCard=function(){
      var r=orig.apply(this,arguments);
      labelCta();
      return r;
    };
    storyMemorySyncLibraryContinueCard=window.storyMemorySyncLibraryContinueCard;
  }
  labelCta();

  /* #8781: 좁은 표지에선 글자 크기를 조정하고, 긴 제목은 단어 사이에서만 줄바꿈. */
  var shelf=document.getElementById('shelfTrack');
  function fitCoverTitles(){
    if(!shelf)return;
    shelf.querySelectorAll('.book-rig:not(.motion-echo) .cover-copy strong').forEach(function(el){
      var rig=el.closest('.book-rig');
      if(!rig)return;
      var text=(el.textContent||'').replace(/\s+/g,' ').trim();
      var available=Math.max(52,Math.floor(rig.clientWidth*.78));
      var units=Array.from(text).reduce(function(sum,ch){
        return sum+(ch===' '?0.45:/[a-zA-Z0-9]/.test(ch)?0.63:1);
      },0);
      var font=Math.min(units<=3?28:22,available/Math.max(1,units));
      var wrap=font<13;
      if(wrap){
        var longest=Math.max(1,...text.split(/\s+/).map(function(word){return Array.from(word).length;}));
        font=Math.max(13,Math.min(17,available/longest));
      }
      el.style.setProperty('--sm-cover-title-size',font.toFixed(1)+'px');
      el.style.maxWidth=available+'px';
      el.style.whiteSpace=wrap?'normal':'nowrap';
    });
  }
  if(shelf){
    new MutationObserver(fitCoverTitles).observe(shelf,{childList:true});
    fitCoverTitles();
  }
})();
