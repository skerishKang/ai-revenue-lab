/* ===== B61 #1337 · StoryMemory Annotation Store v1 · behavior-preserving extraction ===== */
(function(){
'use strict';
var KEY='storymemory.annotations.v1';
var KINDS={highlight:1,underline:1,memo:1,bookmark:1};
var COLORS={yellow:1,mint:1,pink:1,blue:1};
var LOC_RE=/^[a-z0-9][a-z0-9-]*(:[A-Za-z0-9][A-Za-z0-9.\-]*)+$/;
var MAX_ITEMS=500,MAX_NOTE=2000,MAX_TEXT=600;
function unitOf(loc){var p=String(loc).split(':');return p[0]==='bible'?p.slice(0,4).join(':'):p.slice(0,3).join(':');}
function sanitizeItem(raw){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))return null;
  if(!KINDS[raw.kind])return null;
  if(typeof raw.locator!=='string'||!LOC_RE.test(raw.locator))return null;
  var it={id:typeof raw.id==='string'&&raw.id?raw.id.slice(0,64):'an'+Date.now().toString(36)+Math.random().toString(36).slice(2,7),
    kind:raw.kind,locator:raw.locator.slice(0,160),
    unit:typeof raw.unit==='string'&&LOC_RE.test(raw.unit)?raw.unit.slice(0,160):unitOf(raw.locator),
    createdAt:Number.isFinite(+raw.createdAt)?+raw.createdAt:Date.now()};
  if(raw.kind!=='bookmark'){
    var s=Math.trunc(Number(raw.start)),e=Math.trunc(Number(raw.end));
    if(!Number.isFinite(s)||!Number.isFinite(e)||s<0||e<=s||e>8000)return null;
    if(typeof raw.text!=='string'||!raw.text.trim())return null;
    it.start=s;it.end=e;it.text=raw.text.slice(0,MAX_TEXT);
    if(raw.kind==='highlight')it.color=COLORS[raw.color]?raw.color:'yellow';
    if(raw.kind==='memo')it.note=typeof raw.note==='string'?raw.note.slice(0,MAX_NOTE):'';
  }
  return it;
}
function save(list){try{localStorage.setItem(KEY,JSON.stringify({version:1,items:list}));}catch(_){}}
function load(){
  var current=[];
  var raw=null;try{raw=localStorage.getItem(KEY);}catch(_){return current;}
  if(raw===null)return current;
  var parsed=null;try{parsed=JSON.parse(raw);}catch(_){parsed=null;}
  var ok=parsed&&typeof parsed==='object'&&!Array.isArray(parsed)&&parsed.version===1&&Array.isArray(parsed.items);
  if(!ok){try{localStorage.removeItem(KEY);}catch(_){}return current;}
  var clean=parsed.items.map(sanitizeItem).filter(Boolean);
  current=clean.slice(-MAX_ITEMS);
  if(clean.length!==parsed.items.length||parsed.items.length>MAX_ITEMS)save(current);
  return current;
}
window.__smAnnotationStoreModuleV1={
  version:'1',key:KEY,
  KINDS:KINDS,COLORS:COLORS,LOC_RE:LOC_RE,
  MAX_ITEMS:MAX_ITEMS,MAX_NOTE:MAX_NOTE,MAX_TEXT:MAX_TEXT,
  unitOf:unitOf,sanitizeItem:sanitizeItem,load:load,save:save
};
})();
