(function(){
  var KEY='storymemory.readerSettings.v1';
  var DEFAULTS={version:1,font:'noto-sans-kr',fontSize:'base',lineHeight:'relaxed',theme:'default',englishMode:'show',verseNumbers:true};
  var FONTS={
    'noto-sans-kr':'"Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif',
    'pretendard-system':'"Pretendard","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif',
    'serif':'"Noto Serif KR","Source Han Serif KR",Georgia,"Times New Roman",serif'};
  var ENUM={font:['noto-sans-kr','pretendard-system','serif'],fontSize:['sm','base','lg','xl'],lineHeight:['tight','relaxed','loose'],theme:['default','light','sepia','dark'],englishMode:['show','compact','hide']};
  var PAPERS={'default':null,light:'#ffffff',sepia:'#f2e8d5',dark:'#262019'};
  var LABELS={
    font:[['noto-sans-kr','산세리프'],['pretendard-system','시스템'],['serif','세리프']],
    fontSize:[['sm','작게'],['base','기본'],['lg','크게'],['xl','매우 크게']],
    lineHeight:[['tight','좁게'],['relaxed','기본'],['loose','넓게']],
    englishMode:[['show','한영 함께'],['compact','영어 작게'],['hide','한글만']],
    verseNumbers:[[true,'표시'],[false,'숨김']]};
  function sanitize(raw){
    var s={};
    if(!raw||typeof raw!=='object'||raw.version!==1)return null;
    for(var k in DEFAULTS){
      if(k==='version')continue;
      if(k==='verseNumbers'){s[k]=(raw[k]===false)?false:true;continue;}
      s[k]=(ENUM[k]&&ENUM[k].indexOf(raw[k])>=0)?raw[k]:DEFAULTS[k];
    }
    s.version=1;return s;
  }
  function load(){
    try{var raw=BookAIStorage.getItem(KEY);if(!raw)return null;return sanitize(JSON.parse(raw));}
    catch(e){try{BookAIStorage.removeItem(KEY);}catch(e2){}return null;}
  }
  function save(){try{BookAIStorage.setItem(KEY,JSON.stringify(state));}catch(e){}}
  var state=load()||JSON.parse(JSON.stringify(DEFAULTS));
  function apply(){
    var root=document.documentElement,body=document.body;
    root.style.setProperty('--font-bible',FONTS[state.font]);
    if(state.font==='serif'&&!document.getElementById('sm-serif-font-link')){
      var l=document.createElement('link');l.id='sm-serif-font-link';l.rel='stylesheet';
      l.href='https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600&display=swap';
      document.head.appendChild(l);
    }
    body.classList.toggle('smr-fs-sm',state.fontSize==='sm');
    body.classList.toggle('smr-fs-lg',state.fontSize==='lg');
    body.classList.toggle('smr-fs-xl',state.fontSize==='xl');
    body.classList.toggle('smr-lh-tight',state.lineHeight==='tight');
    body.classList.toggle('smr-lh-loose',state.lineHeight==='loose');
    body.classList.toggle('smr-en-compact',state.englishMode==='compact');
    body.classList.toggle('smr-en-hide',state.englishMode==='hide');
    body.classList.toggle('smr-vn-hide',state.verseNumbers===false);
    body.classList.remove('smr-theme-light','smr-theme-sepia','smr-theme-dark');
    if(state.theme!=='default')body.classList.add('smr-theme-'+state.theme);
    var paper=PAPERS[state.theme];
    if(paper)root.style.setProperty('--reader-paper',paper);
    else root.style.removeProperty('--reader-paper');
    syncPanel();
  }
  function segRow(label,field){
    var row=document.createElement('div');row.className='srsg-row';
    var lb=document.createElement('div');lb.className='srsg-label';lb.textContent=label;row.appendChild(lb);
    var seg=document.createElement('div');seg.className='srsg-seg';seg.dataset.field=field;seg.setAttribute('role','group');seg.setAttribute('aria-label',label);
    LABELS[field].forEach(function(opt){
      var b=document.createElement('button');b.type='button';b.dataset.value=String(opt[0]);b.textContent=opt[1];
      b.setAttribute('aria-pressed',String(state[field]===opt[0]));
      b.onclick=function(){state[field]=opt[0];save();apply();};
      seg.appendChild(b);
    });
    row.appendChild(seg);return row;
  }
  function themeRow(){
    var row=document.createElement('div');row.className='srsg-row';
    var lb=document.createElement('div');lb.className='srsg-label';lb.textContent='테마 · 배경';row.appendChild(lb);
    var seg=document.createElement('div');seg.className='srsg-sw';seg.dataset.field='theme';
    [['default','현재(#fffdf8)','#fffdf8'],['light','밝게','#ffffff'],['sepia','세피아','#f2e8d5'],['dark','어둡게','#262019']].forEach(function(t){
      var b=document.createElement('button');b.type='button';b.dataset.value=t[0];b.title=t[1];b.setAttribute('aria-label',t[1]);
      b.style.background=t[2];
      b.onclick=function(){state.theme=t[0];save();apply();};
      seg.appendChild(b);
    });
    row.appendChild(seg);return row;
  }
  var panel=null;
  function syncPanel(){
    if(!panel)return;
    panel.querySelectorAll('.srsg-seg,.srsg-sw').forEach(function(seg){
      var field=seg.dataset.field;
      seg.querySelectorAll('button').forEach(function(b){
        var v=b.dataset.value;
        if(field==='verseNumbers')v=(v==='true');
        var on=(state[field]===v);
        b.classList.toggle('on',on);
        b.setAttribute('aria-pressed',String(on));
      });
    });
  }
  function buildUI(){
    var stage=document.querySelector('#reader .reader-stage')||document.getElementById('reader');
    if(!stage)return;
    if(stage.querySelector('.srsg-btn'))return;
    var gear=document.createElement('button');
    gear.type='button';gear.className='srsg-btn';gear.title='읽기 설정';gear.setAttribute('aria-label','읽기 설정');
    gear.textContent='⚙';
    panel=document.createElement('div');panel.className='srsg-panel';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','읽기 설정');
    var head=document.createElement('div');head.className='srsg-head';
    var hb=document.createElement('b');hb.textContent='읽기 설정';
    var hx=document.createElement('button');hx.type='button';hx.className='srsg-x';hx.setAttribute('aria-label','설정 닫기');hx.textContent='×';
    function closeSettings(restoreFocus){
      document.body.classList.remove('smr-open');
      if(restoreFocus){var trigger=document.getElementById('smalOverflowBtn');if(trigger)trigger.focus();}
    }
    hx.onclick=function(){closeSettings(true);};
    head.appendChild(hb);head.appendChild(hx);panel.appendChild(head);
    panel.appendChild(segRow('글꼴','font'));
    panel.appendChild(segRow('글자 크기','fontSize'));
    panel.appendChild(segRow('줄 간격','lineHeight'));
    panel.appendChild(themeRow());
    panel.appendChild(segRow('본문 언어','englishMode'));
    panel.appendChild(segRow('절 번호','verseNumbers'));
    var reset=document.createElement('button');reset.type='button';reset.className='srsg-reset';reset.textContent='기본값으로 초기화';
    reset.onclick=function(){state=JSON.parse(JSON.stringify(DEFAULTS));try{BookAIStorage.removeItem(KEY);}catch(e){}apply();};
    panel.appendChild(reset);
    gear.onclick=function(e){
      e.stopPropagation();
      var opening=!document.body.classList.contains('smr-open');
      document.body.classList.toggle('smr-open',opening);
      if(opening)hx.focus();
    };
    panel.addEventListener('keydown',function(e){
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeSettings(true);}
    });
    panel.addEventListener('click',function(e){e.stopPropagation();});
    document.addEventListener('click',function(){document.body.classList.remove('smr-open');});
    /* B61 #1936 D: bottom-right consolidation — single overflow toggle replaces the
       five always-visible controls (gear + 4 smal-dock buttons from
       storymemory-annotation-ui-v1.js, which must stay byte-identical per the #1895
       hash pin). All five actions live in the menu; existing onclick handlers are
       reused verbatim (dock nodes reparented, gear wrapped for menu-close only).
       No new control framework, no new state store. Menu z:62 clears .srsg-panel
       (z:61); max-height/overflow reuse the .srsg-panel pattern. */
    var ovBtn=document.createElement('button');
    ovBtn.type='button';ovBtn.id='smalOverflowBtn';ovBtn.className='smal-overflow-btn';
    ovBtn.textContent='⋯';ovBtn.title='읽기 도구 더보기';ovBtn.setAttribute('aria-label','읽기 도구 더보기');
    ovBtn.setAttribute('aria-haspopup','true');ovBtn.setAttribute('aria-expanded','false');
    var ovMenu=document.createElement('div');
    ovMenu.id='smalOverflowMenu';ovMenu.className='smal-overflow-menu';
    ovMenu.setAttribute('role','menu');ovMenu.setAttribute('aria-label','읽기 도구');
    function smOvRow(b,icon,label){
      b.classList.add('smal-ov-item');
      b.innerHTML='';
      var ic=document.createElement('span');ic.className='smal-ov-ic';ic.textContent=icon;ic.setAttribute('aria-hidden','true');
      var lb=document.createElement('span');lb.className='smal-ov-lb';lb.textContent=label;
      b.append(ic,lb);return b;
    }
    function smOvClose(refocus){
      if(!document.body.classList.contains('smal-overflow-open'))return;
      document.body.classList.remove('smal-overflow-open');
      ovBtn.setAttribute('aria-expanded','false');
      if(refocus!==false){
        var a=document.activeElement;
        if(!a||a===document.body||ovMenu.contains(a))ovBtn.focus();
      }
    }
    function smOvOpen(){
      document.body.classList.add('smal-overflow-open');
      ovBtn.setAttribute('aria-expanded','true');
      var f=ovMenu.querySelector('button:not(:disabled)');if(f)f.focus();
    }
    ovBtn.onclick=function(){
      if(document.body.classList.contains('smal-overflow-open'))smOvClose(false);
      else smOvOpen();
    };
    /* Non-gear selections bubble here and close the menu; the gear stops
       propagation in its own (reused) handler and closes explicitly. */
    ovMenu.addEventListener('click',function(e){
      var t=e.target&&e.target.closest?e.target.closest('button'):null;
      if(!t||!ovMenu.contains(t))return;
      if(t.classList.contains('srsg-btn'))return;
      document.body.classList.remove('smal-overflow-open');
      ovBtn.setAttribute('aria-expanded','false');
      var tag=(document.activeElement||{}).tagName;
      if(tag!=='INPUT'&&tag!=='TEXTAREA')ovBtn.focus();
    });
    document.addEventListener('click',function(e){
      if(!document.body.classList.contains('smal-overflow-open'))return;
      if(ovMenu.contains(e.target)||e.target===ovBtn||ovBtn.contains(e.target))return;
      smOvClose(false);
    });
    document.addEventListener('keydown',function(e){
      if(e.key==='Escape'&&document.body.classList.contains('smal-overflow-open')){smOvClose();return;}
      if(!document.body.classList.contains('smal-overflow-open'))return;
      var items=Array.prototype.slice.call(ovMenu.querySelectorAll('button:not(:disabled)'));
      if(!items.length)return;
      var ix=items.indexOf(document.activeElement);
      if(e.key==='ArrowDown'){e.preventDefault();(items[ix+1]||items[0]).focus();}
      else if(e.key==='ArrowUp'){e.preventDefault();(items[ix-1]||items[items.length-1]).focus();}
      else if(e.key==='Home'){e.preventDefault();items[0].focus();}
      else if(e.key==='End'){e.preventDefault();items[items.length-1].focus();}
      else if(e.key==='Tab'){
        var first=items[0],last=items[items.length-1];
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
      }
    });
    /* Adopt the gear now (owned here); the four dock buttons are adopted once the
       annotation module has built them (it runs after this module). Nodes keep
       their ids, aria state and onclick handlers. */
    smOvRow(gear,'⚙','읽기 설정');
    var smOvGear0=gear.onclick;
    gear.onclick=function(e){if(smOvGear0)smOvGear0.call(this,e);smOvClose(false);};
    ovMenu.appendChild(gear);
    var smOvTries=0;
    function smOvAdopt(){
      var bk=document.getElementById('smalBookmarkBtn');
      var er=document.getElementById('smalEraseBtn');
      var un=document.getElementById('smalUndoBtn');
      var ai=document.getElementById('smalAiBtn');
      if(!(bk&&er&&un&&ai)){if(++smOvTries<20)setTimeout(smOvAdopt,50);return;}
      smOvRow(bk,'🔖','책갈피');smOvRow(er,'🧽','지우개 모드');
      smOvRow(un,'↶','실행 취소');smOvRow(ai,'✦','AI Companion');
      ovMenu.append(bk,er,un,gear,ai);
      ovMenu.dataset.done='1';
    }
    setTimeout(smOvAdopt,0);
    stage.appendChild(ovBtn);stage.appendChild(ovMenu);stage.appendChild(panel);
    syncPanel();
  }
  function init(){buildUI();apply();window.__smReaderSettingsV1={version:'1',key:KEY,defaults:DEFAULTS,get:function(){return JSON.parse(JSON.stringify(state));},apply:apply};}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
