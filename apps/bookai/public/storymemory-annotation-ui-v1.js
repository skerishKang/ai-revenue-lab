/* ===== B61 #1129 · StoryMemory Annotation Layer v1 · bookmark exact-locator bridge ===== */
(function(){
'use strict';
var STORE=window.__smAnnotationStoreModuleV1;
if(!STORE)throw new Error('StoryMemory annotation store module missing');
var KEY=STORE.key;
var KINDS=STORE.KINDS;
var COLORS=STORE.COLORS;
var LOC_RE=STORE.LOC_RE;
var MAX_ITEMS=STORE.MAX_ITEMS,MAX_NOTE=STORE.MAX_NOTE,MAX_TEXT=STORE.MAX_TEXT;
var items=[],undoSlot=null,eraseMode=false,pendingSel=null;
function esc(s){return (window.CSS&&CSS.escape)?CSS.escape(String(s)):String(s).replace(/["\\]/g,'\\$&');}
var unitOf=STORE.unitOf;
var sanitizeItem=STORE.sanitizeItem;
function load(){items=STORE.load();}
function save(){STORE.save(items);syncAnnotationPanel();}

function storyMemoryGetExactBookmarkMemory(locator){
  loadUserMemories();
  var ms=__smUserMemories||[];
  for(var i=0;i<ms.length;i++){
    var m=ms[i];
    if(m.subtype==='bookmark'&&m.canonicalLocator===locator)return m;
  }
  return null;
}
function storyMemorySetExactBookmarkMemory(locator,active,metadata){
  loadUserMemories();
  var existing=storyMemoryGetExactBookmarkMemory(locator);
  if(existing){
    if(!active){
      deleteUserMemory(existing.id);
      return null;
    }
    Object.assign(existing,metadata||{});
    markMemoryClientUpdated(existing);
    saveUserMemories();
    return existing;
  }
  if(!active)return null;
  var ms=__smUserMemories||[];
  var mem={
    id:'mem-'+Date.now().toString(36)+Math.random().toString(36).slice(2,7),
    kind:'note',
    subtype:'bookmark',
    canonicalLocator:locator,
    sourceSequence:metadata&&metadata.sourceSequence||null,
    unitKey:metadata&&metadata.unitKey||null,
    semanticPage:metadata&&metadata.semanticPage||null,
    contentVersionKey:metadata&&metadata.contentVersionKey||null,
    sourcePreview:metadata&&metadata.sourcePreview||null,
    context:metadata&&metadata.context||null,
    title:metadata&&metadata.title||locator,
    body:'',
    clientUpdatedAt:Date.now()
  };
  markMemoryClientUpdated(mem);
  ms.push(mem);
  saveUserMemories();
  return mem;
}
function syncBookmarkMemory(locator,active,metadata){
  storyMemorySetExactBookmarkMemory(locator,active,metadata||{});
}
function byId(id){for(var i=0;i<items.length;i++)if(items[i].id===id)return items[i];return null;}
function smalTextNodes(el){
  var out=[],w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT,{acceptNode:function(n){
    if(n.parentElement&&n.parentElement.closest&&n.parentElement.closest('.vn,.smal-badge'))return NodeFilter.FILTER_REJECT;
    return NodeFilter.FILTER_ACCEPT;
  }});
  for(var n=w.nextNode();n;n=w.nextNode())out.push(n);
  return out;
}
function smalText(el){return smalTextNodes(el).map(function(n){return n.nodeValue;}).join('');}
function anchorFrom(el,r){
  var text=smalText(el),quote=r.toString();
  var vnh=el.querySelector('.vn');
  if(vnh){var vt=vnh.textContent;if(quote.slice(0,vt.length)===vt)quote=quote.slice(vt.length);}
  if(!quote.trim())return null;
  var idx=text.indexOf(quote);
  if(idx<0){
    var pr=document.createRange();pr.selectNodeContents(el);
    try{pr.setEnd(r.startContainer,r.startOffset);}catch(_){return null;}
    var s=pr.toString(),vn=el.querySelector('.vn'),base=(vn&&s.indexOf(vn.textContent)===0)?vn.textContent.length:0;
    var start0=Math.max(0,s.length-base);idx=text.indexOf(quote,start0);
    if(idx<0)idx=text.indexOf(quote);
    if(idx<0)return null;
  }
  return {start:idx,end:idx+quote.length,text:quote};
}
function boundSelection(){
  var sel=window.getSelection();
  if(!sel||!sel.rangeCount||sel.isCollapsed)return null;
  if(!(window.storyMemoryIsAuthoritativeReaderMode&&storyMemoryIsAuthoritativeReaderMode()))return null;
  var r=sel.getRangeAt(0);
  var node=r.commonAncestorContainer.nodeType===1?r.commonAncestorContainer:r.commonAncestorContainer.parentElement;
  var el=node&&node.closest?node.closest('#readerPageBody [data-source-locator]'):null;
  if(!el||!el.contains(r.startContainer)||!el.contains(r.endContainer))return null;
  var a=anchorFrom(el,r);
  return a?{el:el,locator:el.getAttribute('data-source-locator'),start:a.start,end:a.end,text:a.text,rect:r.getBoundingClientRect()}:null;
}
function wrapRange(el,a,b,id,cls){
  var nodes=smalTextNodes(el),acc=0,segs=[];
  for(var i=0;i<nodes.length;i++){
    var n=nodes[i],len=n.nodeValue.length,s=acc,e=acc+len;acc=e;
    if(e<=a||s>=b)continue;
    segs.push({node:n,x:Math.max(a,s)-s,y:Math.min(b,e)-s});
  }
  if(!segs.length)return null;
  var marks=[];
  segs.forEach(function(seg){
    var node=seg.node;
    if(seg.y<node.nodeValue.length)node.splitText(seg.y);
    var target=node;
    if(seg.x>0)target=node.splitText(seg.x);
    var mark=document.createElement('mark');
    mark.className='smal '+cls;mark.dataset.smalId=id;
    target.parentNode.replaceChild(mark,target);mark.appendChild(target);
    marks.push(mark);
  });
  return marks[marks.length-1]||null;
}
function applyItem(it){
  var el=document.querySelector('#readerPageBody [data-source-locator="'+esc(it.locator)+'"]');
  if(!el)return;
  if(el.querySelector('[data-smal-id="'+esc(it.id)+'"]'))return;
  if(smalText(el).slice(it.start,it.end)!==it.text)return;
  var cls=it.kind==='highlight'?'smal-hl-'+(it.color||'yellow'):it.kind==='underline'?'smal-ul':'smal-memo';
  var last=wrapRange(el,it.start,it.end,it.id,cls);
  if(last&&it.kind==='memo'){
    var badge=document.createElement('button');
    badge.type='button';badge.className='smal-badge';badge.dataset.smalId=it.id;
    badge.title='메모 보기';badge.setAttribute('aria-label','메모 보기');
    last.parentNode.insertBefore(badge,last.nextSibling);
  }
}
function syncAnnotationPanel(){
  var host=document.getElementById('annotationMemoryList');
  var source=document.querySelector('#readerPageBody [data-source-locator]');
  if(!host||!source)return;
  var unit=unitOf(source.getAttribute('data-source-locator'));
  var current=items.filter(function(it){return it.unit===unit&&(it.kind==='highlight'||it.kind==='underline');});
  var legacy=[];
  try{legacy=__smAnnotations.filter(function(a){return a.context===__smCurrentReaderLabel;});}catch(_){}
  var hc=document.getElementById('highlightCount'),uc=document.getElementById('underlineCount');
  if(hc)hc.textContent=String(legacy.filter(function(a){return String(a.type||'').startsWith('hl-');}).length+current.filter(function(a){return a.kind==='highlight';}).length);
  if(uc)uc.textContent=String(legacy.filter(function(a){return a.type==='annot-line';}).length+current.filter(function(a){return a.kind==='underline';}).length);
  host.querySelectorAll('.smal-memory-entry').forEach(function(el){el.remove();});
  var empty=host.querySelector('.annotation-empty');if(empty)empty.hidden=current.length>0;
  current.slice().reverse().forEach(function(it){
    var wrap=document.createElement('div');wrap.className='annotation-memory-entry-wrap smal-memory-entry';
    var entry=document.createElement('div');entry.className='annotation-memory-entry';
    var kind=document.createElement('b');kind.textContent=it.kind==='highlight'?'형광펜':'밑줄';
    var quote=document.createElement('span');quote.textContent=it.text;
    var ref=document.createElement('small');var book=(document.getElementById('readerVolumeTitle')||{}).textContent||'';var chapter=(document.getElementById('readerChapterTitle')||{}).textContent||'';var verse=it.locator.indexOf('bible:')===0?it.locator.split(':').pop()+'절':'';ref.textContent=[book,chapter,verse].filter(Boolean).join(' · ');
    entry.append(kind,quote,ref);
    var actions=document.createElement('div');actions.className='annotation-entry-actions';
    var del=document.createElement('button');del.type='button';del.title='표시 삭제';del.setAttribute('aria-label','표시 삭제');del.textContent='×';
    del.addEventListener('click',function(){removeItem(it.id);});
    actions.append(del);wrap.append(entry,actions);host.append(wrap);
  });
}
function renderAll(){
  items.forEach(function(it){if(it.kind!=='bookmark')applyItem(it);});
  syncHeader();syncAnnotationPanel();
}
var renderTimer=null,busy=false;
function scheduleRender(){
  if(renderTimer)clearTimeout(renderTimer);
  renderTimer=setTimeout(function(){renderTimer=null;if(!busy){busy=true;renderAll();busy=false;}},60);
}
function unwrapId(id){
  document.querySelectorAll('#readerPageBody [data-smal-id="'+esc(id)+'"]').forEach(function(m){
    var p=m.parentNode;if(!p)return;
    while(m.firstChild)p.insertBefore(m.firstChild,m);
    p.removeChild(m);
  });
  var body=document.getElementById('readerPageBody');if(body&&body.normalize)body.normalize();
}
function pushUndo(slot){undoSlot=slot;syncToolbar();}
function doUndo(){
  if(!undoSlot)return;
  var op=undoSlot;undoSlot=null;
  if(op.kind==='add'){
    var i=items.findIndex(function(x){return x.id===op.id;});
    if(i>=0)items.splice(i,1);
    unwrapId(op.id);save();
  }else if(op.kind==='remove'){
    items.push(op.item);save();
    busy=true;applyItem(op.item);busy=false;
  }else if(op.kind==='edit'){
    var t=byId(op.id);if(t){t.note=op.prevNote;save();}
  }else if(op.kind==='bookmark'){
    var j=items.findIndex(function(x){return x.id===op.id;});
    if(j>=0){
      items.splice(j,1);
      syncBookmarkMemory(op.item.locator,false);
    }else{
      items.push(op.item);
      syncBookmarkMemory(op.item.locator,true,{
        unitKey:op.item.unit,
        context:op.item.label||''
      });
    }
    save();syncHeader();
  }
  syncToolbar();
  if(window.showVoiceToast)showVoiceToast('↶ 실행 취소');
}
function removeItem(id){
  var i=items.findIndex(function(x){return x.id===id;});
  if(i<0)return;
  var it=items.splice(i,1)[0];
  unwrapId(id);save();pushUndo({kind:'remove',item:it});
  scheduleRender();
}
function addItem(kind,c,extra){
  var it={id:'an'+Date.now().toString(36)+Math.random().toString(36).slice(2,7),kind:kind,locator:c.locator,unit:unitOf(c.locator),start:c.start,end:c.end,text:c.text.slice(0,MAX_TEXT),createdAt:Date.now()};
  if(kind==='highlight')it.color=COLORS[extra&&extra.color]?extra.color:'yellow';
  if(kind==='memo')it.note=(extra&&typeof extra.note==='string')?extra.note.slice(0,MAX_NOTE):'';
  items.push(it);
  if(items.length>MAX_ITEMS)items=items.slice(-MAX_ITEMS);
  save();busy=true;applyItem(it);busy=false;
  pushUndo({kind:'add',id:it.id});
  syncHeader();
  return it;
}
function toggleBookmark(){
  var el=document.querySelector('#readerPageBody [data-source-locator]');
  if(!el||!(window.storyMemoryIsAuthoritativeReaderMode&&storyMemoryIsAuthoritativeReaderMode()))return;
  var locator=el.getAttribute('data-source-locator');
  if(!locator)return;
  var ex=null;items.forEach(function(x){if(x.kind==='bookmark'&&x.locator===locator)ex=x;});
  if(ex){
    items=items.filter(function(x){return x!==ex;});
    save();pushUndo({kind:'bookmark',id:ex.id,item:ex});
    syncBookmarkMemory(ex.locator,false);
    if(window.showVoiceToast)showVoiceToast('책갈피 해제');
  }else{
    var bk={id:'bk'+Date.now().toString(36),kind:'bookmark',locator:locator,unit:unitOf(locator),label:(document.getElementById('readerChapterTitle')||{}).textContent||unitOf(locator),createdAt:Date.now()};
    items.push(bk);save();pushUndo({kind:'bookmark',id:bk.id,item:bk});
    syncBookmarkMemory(locator,true,{
      unitKey:unitOf(locator),
      context:(document.getElementById('readerChapterTitle')||{}).textContent||'',
      sourcePreview:null
    });
    if(window.showVoiceToast)showVoiceToast('🔖 책갈피 저장 · '+locator);
  }
  syncHeader();
}
function isBookmarked(){
  var el=document.querySelector('#readerPageBody [data-source-locator]');
  if(!el)return false;
  var locator=el.getAttribute('data-source-locator');
  if(!locator)return false;
  var hit=false;
  items.forEach(function(x){if(x.kind==='bookmark'&&x.locator===locator)hit=true;});
  return hit;
}
var toolbar,bkBtn,pop,ta;
function buildUI(){
  var stage=document.querySelector('#reader .reader-stage')||document.getElementById('reader');
  toolbar=document.createElement('div');toolbar.id='smalToolbar';toolbar.setAttribute('role','toolbar');toolbar.setAttribute('aria-label','표시 도구');
  ['yellow','mint','pink','blue'].forEach(function(c){
    var d=document.createElement('button');d.type='button';d.className='smal-dot';d.dataset.smalColor=c;
    d.title='형광펜 · '+c;d.setAttribute('aria-label','형광펜 '+c);
    d.style.background={yellow:'#ffe066',mint:'#7ed6a8',pink:'#f48fb1',blue:'#89b4f0'}[c];
    d.onclick=function(){if(pendingSel){addItem('highlight',pendingSel,{color:c});hideToolbar();}};
    toolbar.appendChild(d);
  });
  toolbar.appendChild(sep());
  var ul=btn('밑줄','smal-ul-btn');ul.onclick=function(){if(pendingSel){addItem('underline',pendingSel);hideToolbar();}};
  var me=btn('메모','smal-memo-btn');me.onclick=function(){if(pendingSel)openPop({mode:'create',sel:pendingSel});};
  toolbar.append(ul,me);
  document.body.appendChild(toolbar);
  toolbar.addEventListener('mousedown',function(e){e.preventDefault();});
  var dock=document.createElement('div');dock.className='smal-dock';dock.id='smalDock';
  bkBtn=document.createElement('button');
  bkBtn.type='button';bkBtn.id='smalBookmarkBtn';bkBtn.textContent='🔖';
  bkBtn.title='책갈피';bkBtn.setAttribute('aria-label','책갈피');bkBtn.setAttribute('aria-pressed','false');
  bkBtn.onclick=toggleBookmark;
  var er=document.createElement('button');
  er.type='button';er.id='smalEraseBtn';er.textContent='🧽';
  er.title='지우개';er.setAttribute('aria-label','지우개 모드');er.setAttribute('aria-pressed','false');
  er.onclick=function(){eraseMode=!eraseMode;document.body.classList.toggle('smal-erase',eraseMode);syncToolbar();hideToolbar();};
  var un=document.createElement('button');
  un.type='button';un.id='smalUndoBtn';un.textContent='↶';
  un.title='실행 취소';un.setAttribute('aria-label','실행 취소');un.disabled=true;
  un.onclick=function(){doUndo();};
  dock.append(bkBtn,er,un);
  /* B61-1613 D1: desktop Companion entry. The mobile dock (Memory/Read/AI)
     is hidden on desktop, and the AI panel otherwise has no visible opener.
     Toggles the same body.ai-open sheet state as the mobile dock / selection
     AI action. Hidden on compact widths via reachability stylesheet. */
  var aiB=document.createElement('button');
  aiB.type='button';aiB.id='smalAiBtn';aiB.textContent='✦';
  aiB.title='AI Companion';aiB.setAttribute('aria-label','AI Companion 열기');aiB.setAttribute('aria-pressed','false');
  aiB.onclick=function(){
    var open=!document.body.classList.contains('ai-open');
    document.body.classList.toggle('ai-open',open);
    /* B61-1684: independent Memory/AI state on desktop; exclusive only in compact sheets */
    if(open&&typeof __smReaderCompactMode==='function'&&__smReaderCompactMode())document.body.classList.remove('memory-open');
    aiB.setAttribute('aria-pressed',String(open));
    aiB.setAttribute('aria-label',open?'AI Companion 닫기':'AI Companion 열기');
    if(open){var inp=document.getElementById('askInput');if(inp)inp.focus();}
  };
  dock.appendChild(aiB);
  /* Keep pressed/label state honest when the sheet closes via ×, scrim,
     Escape, or the mobile dock (all outside this module). */
  try{
    new MutationObserver(function(){
      var open=document.body.classList.contains('ai-open');
      aiB.setAttribute('aria-pressed',String(open));
      aiB.setAttribute('aria-label',open?'AI Companion 닫기':'AI Companion 열기');
    }).observe(document.body,{attributes:true,attributeFilter:['class']});
  }catch(_){}
  if(stage)stage.appendChild(dock);
  pop=document.createElement('div');pop.id='smalPop';pop.setAttribute('role','dialog');pop.setAttribute('aria-label','메모');
  var q=document.createElement('div');q.className='smal-pop-quote';q.id='smalPopQuote';
  ta=document.createElement('textarea');ta.id='smalPopNote';if(Number.isFinite(MAX_NOTE))ta.maxLength=MAX_NOTE;ta.placeholder='이 구절에 대한 메모…';ta.setAttribute('aria-label','메모 내용');
  var acts=document.createElement('div');acts.className='smal-pop-actions';
  var del=document.createElement('button');del.type='button';del.className='smal-pop-del';del.id='smalPopDel';del.textContent='삭제';
  var cancel=document.createElement('button');cancel.type='button';cancel.className='smal-pop-cancel';cancel.textContent='취소';
  var ok=document.createElement('button');ok.type='button';ok.className='smal-pop-save';ok.id='smalPopSave';ok.textContent='저장';
  acts.append(del,cancel,ok);pop.append(q,ta,acts);document.body.appendChild(pop);
  pop.addEventListener('mousedown',function(e){if(e.target===ta)e.stopPropagation();});
  cancel.onclick=closePop;
  ok.onclick=function(){
    if(pop._mode==='create'&&pop._sel){addItem('memo',pop._sel,{note:ta.value.trim()});if(window.showVoiceToast)showVoiceToast('메모 저장');}
    else if(pop._mode==='edit'){
      var it=byId(pop._id);
      if(it){pushUndo({kind:'edit',id:it.id,prevNote:it.note});it.note=ta.value.trim().slice(0,MAX_NOTE);save();}
    }
    closePop();
  };
  del.onclick=function(){if(pop._id)removeItem(pop._id);closePop();};
  var body=document.getElementById('readerPageBody');
  if(body){
    body.addEventListener('click',function(e){
      var badge=e.target.closest?e.target.closest('.smal-badge'):null;
      var mark=e.target.closest?e.target.closest('mark.smal'):null;
      var host=badge||mark;if(!host)return;
      var id=host.dataset.smalId;if(!id)return;
      if(eraseMode){e.preventDefault();e.stopPropagation();removeItem(id);return;}
      var it=byId(id);
      if(it&&it.kind==='memo'){e.preventDefault();e.stopPropagation();openPop({mode:'edit',id:id,rect:host.getBoundingClientRect()});}
    },true);
    new MutationObserver(scheduleRender).observe(body,{childList:true,subtree:true});
  }
}
function sep(){var s=document.createElement('span');s.className='smal-sep';return s;}
function btn(label,cls){var b=document.createElement('button');b.type='button';b.className='smal-tb'+(cls?' '+cls:'');b.textContent=label;b.setAttribute('aria-label',label);return b;}
function showToolbar(rect){
  closePop();
  var lst=document.getElementById('selectionToolbar');if(lst)lst.classList.remove('show');
  toolbar.classList.add('show');
  var w=toolbar.offsetWidth||280;
  toolbar.style.left=Math.max(8,Math.min(innerWidth-w-8,rect.left+rect.width/2-w/2))+'px';
  toolbar.style.top=Math.max(58,rect.top-52)+'px';
  syncToolbar();
}
function hideToolbar(){toolbar.classList.remove('show');document.body.classList.remove('smal-bound');pendingSel=null;}
function syncToolbar(){
  var un=document.getElementById('smalUndoBtn');if(un)un.disabled=!undoSlot;
  var er=document.getElementById('smalEraseBtn');if(er)er.setAttribute('aria-pressed',String(eraseMode));
}
function syncHeader(){if(bkBtn)bkBtn.setAttribute('aria-pressed',String(isBookmarked()));}
function openPop(opts){
  if(!pop)return;
  hideToolbar();
  pop._mode=opts.mode;pop._id=opts.id||null;pop._sel=opts.sel||null;
  var it=opts.mode==='edit'?byId(opts.id):null;
  document.getElementById('smalPopQuote').textContent=it?it.text:(opts.sel?opts.sel.text:'');
  ta.value=it?(it.note||''):'';
  document.getElementById('smalPopDel').style.display=it?'':'none';
  pop.classList.add('show');
  var rect=opts.mode==='edit'&&opts.rect?opts.rect:(opts.sel?opts.sel.rect:null);
  var pw=pop.offsetWidth||300,ph=pop.offsetHeight||160;
  var x=rect?Math.max(8,Math.min(innerWidth-pw-8,rect.left)):(innerWidth/2-pw/2);
  var y=rect?(rect.bottom+10+ph>innerHeight?Math.max(8,rect.top-ph-10):rect.bottom+10):120;
  pop.style.left=x+'px';pop.style.top=y+'px';
  setTimeout(function(){ta.focus();},0);
}
function closePop(){if(pop)pop.classList.remove('show');}
function init(){
  load();buildUI();
  var paper=document.getElementById('paper');
  if(paper){
    var cap=function(){
      setTimeout(function(){
        var c=boundSelection();
        if(c){pendingSel=c;document.body.classList.add('smal-bound');showToolbar(c.rect);}
        else{hideToolbar();}
      },10);
    };
    paper.addEventListener('mouseup',cap);
    paper.addEventListener('touchend',cap);
  }
  document.addEventListener('mousedown',function(e){
    if(toolbar&&toolbar.contains(e.target))return;
    if(pop&&pop.contains(e.target))return;
    if(!e.target.closest||!e.target.closest('#smalToolbar,#smalPop')){hideToolbar();closePop();}
  });
  document.addEventListener('keydown',function(e){
    if((e.ctrlKey||e.metaKey)&&(e.key==='z'||e.key==='Z')){
      var t=e.target;
      if(t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'))return;
      var reader=document.getElementById('reader');
      if(reader&&reader.classList.contains('active')&&undoSlot){e.preventDefault();doUndo();}
    }
    if(e.key==='Escape'){if(pop&&pop.classList.contains('show'))closePop();else if(eraseMode){eraseMode=false;document.body.classList.remove('smal-erase');syncToolbar();}}
  });
  window.addEventListener('resize',function(){hideToolbar();closePop();});
  renderAll();
  window.__smAnnotationLayerV1={
    version:'1',key:KEY,
    reload:function(){items.forEach(function(it){unwrapId(it.id);});load();renderAll();syncAnnotationPanel();},
  list:function(){return JSON.parse(JSON.stringify(items));},
    count:function(){return items.length;},
    addItem:function(kind,locator,start,end,text,extra){return addItem(kind,{locator:locator,start:start,end:end,text:text},extra);},
    removeItem:removeItem,undo:doUndo,toggleBookmark:toggleBookmark,
    setErase:function(on){eraseMode=!!on;document.body.classList.toggle('smal-erase',eraseMode);syncToolbar();},
    renderAll:function(){busy=true;renderAll();busy=false;},
    undoPending:function(){return undoSlot?undoSlot.kind:null;},
    storyMemoryGetExactBookmarkMemory:storyMemoryGetExactBookmarkMemory,
    storyMemorySetExactBookmarkMemory:storyMemorySetExactBookmarkMemory,
    syncBookmarkMemory:syncBookmarkMemory
  };
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
