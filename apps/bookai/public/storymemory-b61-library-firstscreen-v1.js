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
  var motionLabel=document.createElement('span');
  motionLabel.className='overflow-label';motionLabel.textContent='BOOK MOTION';
  menu.append(motionLabel);
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
  if(motion)menu.append(motion);
  var orderLabel=document.createElement('span');
  orderLabel.className='overflow-label';orderLabel.textContent='SHELF ORDER';
  var order=document.getElementById('libraryOrderToggle');
  if(order){menu.append(orderLabel,order);}
  else{
    var retries=0;
    var waitOrder=setInterval(function(){
      var el=document.getElementById('libraryOrderToggle');
      if(el){clearInterval(waitOrder);menu.append(orderLabel,el);}
      else if(++retries>40)clearInterval(waitOrder);
    },100);
  }

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
})();
