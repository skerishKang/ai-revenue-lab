(()=>{
  const keys=['cover','work-order','roles','evidence','gates','decision','mobile'];
  const tabs=[...document.querySelectorAll('[role="tab"][data-state]')];
  const panels=[...document.querySelectorAll('[role="tabpanel"][data-state]')];
  const activate=(key,focus=false)=>{
    if(!keys.includes(key))return;
    tabs.forEach(tab=>{
      const selected=tab.dataset.state===key;
      tab.setAttribute('aria-selected',String(selected));
      tab.tabIndex=selected?0:-1;
      if(selected&&focus)tab.focus();
    });
    panels.forEach(panel=>{
      const selected=panel.dataset.state===key;
      panel.hidden=!selected;
      panel.classList.toggle('active',selected);
    });
  };
  tabs.forEach((tab,index)=>{
    tab.addEventListener('click',()=>activate(tab.dataset.state));
    tab.addEventListener('keydown',event=>{
      let next=null;
      if(event.key==='ArrowRight')next=(index+1)%tabs.length;
      if(event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;
      if(event.key==='Home')next=0;
      if(event.key==='End')next=tabs.length-1;
      if(next!==null){event.preventDefault();activate(tabs[next].dataset.state,true);}
    });
  });

  const root=document.querySelector('#control-motion');
  const seal=document.querySelector('#control-record-seal');
  const replay=document.querySelector('#replay-control-record');
  const status=document.querySelector('#motion-status');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const complete=()=>{
    root.classList.remove('running');
    root.classList.add('complete');
    root.dataset.motionState='complete';
    status.textContent=reduced.matches?'complete · reduced motion':'complete · human-approved control record';
  };
  const run=()=>{
    if(reduced.matches){complete();return;}
    const x=scrollX;
    const y=scrollY;
    root.classList.remove('running','complete');
    root.dataset.motionState='idle';
    void root.offsetWidth;
    root.classList.add('running');
    root.dataset.motionState='running';
    status.textContent='running · work order to controlled decision';
    scrollTo(x,y);
  };
  replay.addEventListener('click',run);
  seal.addEventListener('animationend',event=>{
    if(event.target!==seal||event.animationName!=='controlSeal')return;
    complete();
  });
  reduced.addEventListener?.('change',event=>{if(event.matches)complete();});
  activate('cover');
})();
