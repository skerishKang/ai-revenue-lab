(()=>{
  const stateKeys=['cover','situation','signals','options','support','handoff','mobile'];
  const panels=[...document.querySelectorAll('[data-state]')];
  const tabs=[...document.querySelectorAll('[data-state-control]')];
  const stage=document.querySelector('#review-stage');
  function selectState(key,{focusTab=false}={}){
    const safeKey=stateKeys.includes(key)?key:'cover';
    panels.forEach(panel=>{const active=panel.dataset.state===safeKey;panel.hidden=!active;panel.classList.toggle('is-active',active);});
    tabs.forEach(tab=>{const active=tab.dataset.stateControl===safeKey;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;if(active&&focusTab)tab.focus({preventScroll:true});});
    document.body.dataset.activeState=safeKey;
    history.replaceState(null,'',`#${safeKey}`);
  }
  tabs.forEach((tab,index)=>{
    tab.addEventListener('click',()=>selectState(tab.dataset.stateControl));
    tab.addEventListener('keydown',event=>{
      if(!['ArrowRight','ArrowLeft','Home','End'].includes(event.key))return;
      event.preventDefault();
      let next=index;
      if(event.key==='ArrowRight')next=(index+1)%tabs.length;
      if(event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;
      if(event.key==='Home')next=0;
      if(event.key==='End')next=tabs.length-1;
      selectState(tabs[next].dataset.stateControl,{focusTab:true});
    });
  });
  document.querySelectorAll('.review-choice').forEach(button=>button.addEventListener('click',()=>{button.setAttribute('aria-pressed',String(button.getAttribute('aria-pressed')!=='true'));}));
  selectState(location.hash.slice(1));

  const board=document.querySelector('[data-motion-board]');
  const replay=document.querySelector('[data-motion-replay]');
  const finalSeal=document.querySelector('[data-final-seal]');
  const status=document.querySelector('[data-motion-status]');
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  function complete(){
    board.classList.remove('is-running');
    board.classList.add('is-complete');
    board.dataset.motionState='complete';
    status.textContent='HUMAN-REVIEWED SAFETY RESPONSE BRIEF · complete';
    board.dispatchEvent(new CustomEvent('briefmotioncomplete'));
  }
  function replayMotion(){
    const active=document.activeElement;
    const scroll={x:window.scrollX,y:window.scrollY};
    board.classList.remove('is-running','is-complete');
    board.dataset.motionState='idle';
    void board.offsetWidth;
    if(reduced()){complete();}
    else{board.classList.add('is-running');board.dataset.motionState='running';status.textContent='상황 기록을 사람 검토 안전대응 브리프로 연결 중';}
    requestAnimationFrame(()=>{window.scrollTo(scroll.x,scroll.y);if(active instanceof HTMLElement)active.focus({preventScroll:true});});
  }
  replay.addEventListener('click',replayMotion);
  finalSeal.addEventListener('animationend',event=>{
    if(event.animationName==='briefComplete'&&board.dataset.motionState==='running')complete();
  });
  window.__business36Review={selectState,replayMotion,complete,stateKeys};
})();
