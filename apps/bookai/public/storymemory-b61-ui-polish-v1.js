/* B61 #1715/#1684 · StoryMemory UI polish runtime v1.
   - Safe Markdown subset renderer for Companion answers (#1715 §1):
     escapes first, then transforms only **bold** *em* `code` lists blockquote.
     No raw HTML, no links, no hidden-prompt exposure.
   - Desktop Memory/AI panel state contract (#1684): independent open/close,
     persistent collapsed rails, reader-entry defaults, aria-expanded sync.
   Presentation/state only: no packet, prompt, boundary, route, or corpus change. */
(function(){
'use strict';
var d=document;

function escapeLocal(v){return String(v==null?'':v).replace(/[&<>"']/g,function(m){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[m]})}
function inlineMd(s){
  return s
    .replace(/`([^`]+)`/g,function(_,c){return '<code>'+c+'</code>'})
    .replace(/\*\*([^*]+)\*\*/g,function(_,c){return '<strong>'+c+'</strong>'})
    .replace(/(^|[^*])\*([^*\n]+)\*/g,function(_,p,c){return p+'<em>'+c+'</em>'})
    .replace(/(^|\s)_([^_\n]+)_/g,function(_,p,c){return p+'<em>'+c+'</em>'});
}
function renderCompanionMarkdown(text){
  var lines=escapeLocal(text).replace(/\r\n/g,'\n').split('\n');
  var out=[],para=[],list=null,quote=[];
  function flushPara(){if(para.length){out.push('<p>'+inlineMd(para.join(' '))+'</p>');para=[]}}
  function flushList(){if(list){out.push('<'+list.t+'>'+list.items.map(function(i){return '<li>'+inlineMd(i)+'</li>'}).join('')+'</'+list.t+'>');list=null}}
  function flushQuote(){if(quote.length){out.push('<blockquote>'+inlineMd(quote.join(' '))+'</blockquote>');quote=[]}}
  function flushAll(){flushPara();flushList();flushQuote()}
  lines.forEach(function(raw){
    var l=raw.trim();
    if(!l){flushAll();return}
    var q=l.match(/^&gt;\s?(.*)$/);
    if(q){flushPara();flushList();quote.push(q[1]);return}
    var ul=l.match(/^[-*]\s+(.*)$/);
    if(ul){flushPara();flushQuote();if(!list||list.t!=='ul'){flushList();list={t:'ul',items:[]}}list.items.push(ul[1]);return}
    var ol=l.match(/^\d+[.)]\s+(.*)$/);
    if(ol){flushPara();flushQuote();if(!list||list.t!=='ol'){flushList();list={t:'ol',items:[]}}list.items.push(ol[1]);return}
    flushList();flushQuote();para.push(l);
  });
  flushAll();
  return out.join('');
}
window.storyMemoryRenderCompanionMarkdownV1=renderCompanionMarkdown;

function compactMode(){
  try{return __smReaderCompactMode()}catch(_){return innerWidth<=768}
}
function isOpen(name){return d.body.classList.contains(name)}
function syncRailTabs(){
  var mt=d.getElementById('memoryRailTab'),at=d.getElementById('aiRailTab');
  if(mt){mt.setAttribute('aria-expanded',isOpen('memory-open')?'true':'false');mt.setAttribute('aria-label',isOpen('memory-open')?'Memory 패널 닫기':'Memory 패널 열기')}
  if(at){at.setAttribute('aria-expanded',isOpen('ai-open')?'true':'false');at.setAttribute('aria-label',isOpen('ai-open')?'AI Companion 패널 닫기':'AI Companion 패널 열기')}
}
function togglePanel(cls){
  d.body.classList.toggle(cls);
  if(!compactMode()&&cls==='ai-open'&&isOpen('ai-open')){/* independent state: do not close Memory */}
  syncRailTabs();
}
var mt=d.getElementById('memoryRailTab');
if(mt)mt.addEventListener('click',function(){togglePanel('memory-open')});
var at=d.getElementById('aiRailTab');
if(at)at.addEventListener('click',function(){togglePanel('ai-open')});

/* per-panel close: each sheet's × collapses only itself into its rail */
d.querySelectorAll('[data-close-sheet]').forEach(function(b){
  b.onclick=function(){
    if(b.closest('.memory-rail'))d.body.classList.remove('memory-open');
    else if(b.closest('.ai-panel'))d.body.classList.remove('ai-open');
    syncRailTabs();
  };
});

/* reader-entry defaults: wide desktop shows both panels; laptop shows
   Memory with the AI rail persistently discoverable. Mobile unchanged. */
var wasReader=false;
function applyReaderDefaults(){
  if(compactMode())return;
  d.body.classList.add('memory-open');
  d.body.classList.toggle('ai-open',innerWidth>=1200);
  syncRailTabs();
}
if(d.body.classList.contains('reader-mode'))applyReaderDefaults();
else wasReader=d.body.classList.contains('reader-mode');
new MutationObserver(function(){
  var isReader=d.body.classList.contains('reader-mode');
  if(isReader&&!wasReader)applyReaderDefaults();
  wasReader=isReader;
}).observe(d.body,{attributes:true,attributeFilter:['class']});
addEventListener('resize',syncRailTabs);
d.addEventListener('keydown',function(e){if(e.key==='Escape')setTimeout(syncRailTabs,0)},true);

/* closeSheets() legacy callers (scrim/pull-down) stay mobile-only paths;
   resync after any external class change. */
new MutationObserver(syncRailTabs).observe(d.body,{attributes:true,attributeFilter:['class']});
syncRailTabs();
window.__smB61UiPolishV1={version:'v1',markdown:'safe-subset',panelContract:'independent-rails'};
})();
