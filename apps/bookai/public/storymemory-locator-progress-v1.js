/* ===== B61 #1337 R1 · Locator + Reading Progress private module ===== */
(function(){
'use strict';
var STORAGE_KEY='storymemory.readingProgress.v1';
var VERSION=1;
var BIBLE_BOOK_ORDER=['GEN','EXO','LEV','NUM','DEU','JOS','JDG','RUT','1SA','2SA','1KI','2KI','1CH','2CH','EZR','NEH','EST','JOB','PSA','PRO','ECC','SNG','ISA','JER','LAM','EZE','DAN','HOS','JOL','AMO','OBA','JON','MIC','NAM','HAB','ZEP','HAG','ZEC','MAL','MAT','MRK','LUK','JHN','ACT','ROM','1CO','2CO','GAL','EPH','PHP','COL','1TH','2TH','1TI','2TI','TIT','PHM','HEB','JAS','1PE','2PE','1JN','2JN','3JN','JUD','REV'];
var BOOK_ORDER_MAP={}; BIBLE_BOOK_ORDER.forEach(function(code,i){ BOOK_ORDER_MAP[code]=i; });
/* B61 #1897 · prerequisite fix · the shipped bible-web corpus spells Ezekiel
   EZK, which was the only book code absent from BIBLE_BOOK_ORDER. parseToken
   then returned kind 'str', the comparator fell back to localeCompare, and
   'EZK' < 'GEN' judged all 1273 Ezekiel passages INSIDE a GEN ceiling. Alias
   EZK to the EZE slot so it is classified kind 'book' and compared by book
   order. Product-local locator grammar only; core/engine/B14 untouched. */
if(BOOK_ORDER_MAP.hasOwnProperty('EZE')) BOOK_ORDER_MAP['EZK']=BOOK_ORDER_MAP['EZE'];
function isBibleBook(code){ return BOOK_ORDER_MAP.hasOwnProperty(code); }
var DIVINE_ORDER=['inferno','purgatorio','paradiso'];
var DIVINE_ORDER_MAP={}; DIVINE_ORDER.forEach(function(n,i){ DIVINE_ORDER_MAP[n]=i; DIVINE_ORDER_MAP[n.toLowerCase()]=i; });
function isDivineUnit(code){ return DIVINE_ORDER_MAP.hasOwnProperty(String(code).toLowerCase()); }
function locatorWorkFamily(locator){
  if(!locator) return null;
  var s=String(locator).toLowerCase();
  // Canonical StoryMemory locators use ':' as the structural delimiter.
  // Preserve '-' inside the work slug (e.g. paradise-lost, crime-and-punishment).
  var p=s.split(':');
  var first=p[0]||'';
  if(first==='bible') return 'bible-web';
  if(isBibleBook(first.toUpperCase())) return 'bible-web';
  if(first==='inferno'||first==='purgatorio'||first==='paradiso') return 'divine-comedy';
  var known={'iliad':'iliad','odyssey':'odyssey','aeneid':'aeneid','metamorphoses':'metamorphoses','paradise-lost':'paradise-lost','divine-comedy':'divine-comedy','crime-and-punishment':'crime-and-punishment','pride-and-prejudice':'pride-and-prejudice','alice-in-wonderland':'alice-in-wonderland'};
  if(known[first]) return known[first];
  return first;
}
function isLocatorCompatibleWithWork(locator, workKey){
  if(!locator || !workKey) return false;
  var fam=locatorWorkFamily(locator);
  var wk=String(workKey).toLowerCase();
  if(/^work[a-z0-9]*$/i.test(wk)) return true;
  if(wk==='bible-web' && fam==='bible-web') return true;
  if(fam===wk) return true;
  return false;
}
function parseToken(tok){
  if(/^\d+$/.test(tok)) return {kind:'num', val:parseInt(tok,10)};
  if(isBibleBook(tok)) return {kind:'book', val:BOOK_ORDER_MAP[tok], raw:tok};
  var low=String(tok).toLowerCase();
  if(isDivineUnit(low)) return {kind:'divine', val:DIVINE_ORDER_MAP[low], raw:tok};
  return {kind:'str', val:tok};
}
function compareLocators(a,b){
  if(!a && !b) return 0; if(!a) return -1; if(!b) return 1;
  var pa=String(a).split(/[:\-]/), pb=String(b).split(/[:\-]/);
  var n=Math.max(pa.length, pb.length);
  for(var i=0;i<n;i++){
    var ta=pa[i], tb=pb[i];
    if(ta===undefined) return -1; if(tb===undefined) return 1;
    var fa=parseToken(ta), fb=parseToken(tb);
    if(fa.kind!==fb.kind){
      var cmp=String(ta).localeCompare(String(tb)); if(cmp!==0) return cmp<0?-1:1; else continue;
    }
    if(fa.kind==='num'){ if(fa.val!==fb.val) return fa.val<fb.val?-1:1; }
    else if(fa.kind==='book'){ if(fa.val!==fb.val) return fa.val<fb.val?-1:1; }
    else if(fa.kind==='divine'){ if(fa.val!==fb.val) return fa.val<fb.val?-1:1; }
    else { var c=String(fa.val).localeCompare(String(fb.val)); if(c!==0) return c<0?-1:1; }
  }
  return 0;
}
function loadStore(){
  try{
    var raw=localStorage.getItem(STORAGE_KEY);
    if(raw===null) return {version:VERSION, works:{}};
    var p=JSON.parse(raw);
    if(!p || typeof p!=='object' || p.version!==VERSION || typeof p.works!=='object' || Array.isArray(p.works)) return {version:VERSION, works:{}};
    var out={version:VERSION, works:{}};
    for(var k in p.works){ if(!Object.prototype.hasOwnProperty.call(p.works,k)) continue; var v=p.works[k]; if(!v || typeof v!=='object') continue; if(typeof v.furthest_read_locator!=='string' || !v.furthest_read_locator) continue; if(typeof v.knowledge_ceiling_locator!=='string' || !v.knowledge_ceiling_locator) continue; var fr=String(v.furthest_read_locator), kc=String(v.knowledge_ceiling_locator); if(!isLocatorCompatibleWithWork(fr,k) || !isLocatorCompatibleWithWork(kc,k)) continue; if(locatorWorkFamily(fr)!==locatorWorkFamily(kc)) continue; if(fr!==kc) continue; out.works[k]={furthest_read_locator:fr, knowledge_ceiling_locator:kc, updatedAt: Number(v.updatedAt)||Date.now()}; }
    return out;
  }catch(_){ return {version:VERSION, works:{}}; }
}
function saveStore(store){
  try{ localStorage.setItem(STORAGE_KEY, JSON.stringify(store)); }catch(_){}
}
function getProgress(workKey){
  if(!workKey) return null;
  var s=loadStore(); var w=s.works[workKey]; return w ? {furthest_read_locator:w.furthest_read_locator, knowledge_ceiling_locator:w.knowledge_ceiling_locator, updatedAt:w.updatedAt} : null;
}
function advanceProgress(workKey, locator){
  if(!workKey || !locator) return null;
  if(!isLocatorCompatibleWithWork(locator, workKey)) return null;
  var s=loadStore();
  var cur=s.works[workKey]||null;
  if(!cur){
    s.works[workKey]={furthest_read_locator:String(locator), knowledge_ceiling_locator:String(locator), updatedAt:Date.now()};
    saveStore(s); return s.works[workKey];
  }
  var cmp=compareLocators(locator, cur.furthest_read_locator);
  if(cmp>0){
    cur.furthest_read_locator=String(locator);
    cur.knowledge_ceiling_locator=String(locator);
    cur.updatedAt=Date.now();
    saveStore(s);
  }
  return cur;
}
function resetProgress(workKey){
  if(!workKey) return;
  var s=loadStore(); if(s.works[workKey]){ delete s.works[workKey]; saveStore(s); }
}
function clearAllProgress(){ try{ localStorage.removeItem(STORAGE_KEY); }catch(_){} }
function getCeiling(workKey){
  var p=getProgress(workKey); return p ? p.knowledge_ceiling_locator : null;
}
function syncVisibleToProgress(){
  try{
    var rc=window.storyMemoryGetReaderContextV1 ? window.storyMemoryGetReaderContextV1() : null;
    if(!rc || !rc.authoritative_reader) return null;
    var wk=rc.current_work_key; if(!wk) return null;
    var latest=rc.visible_locator_end || rc.visible_locator_start; if(!latest) return null;
    return advanceProgress(wk, latest);
  }catch(_){ return null; }
}
window.storyMemoryReadingProgress={ STORAGE_KEY:STORAGE_KEY, VERSION:VERSION };
window.storyMemoryGetReadingProgressV1=getProgress;
window.storyMemoryAdvanceReadingProgressV1=advanceProgress;
window.storyMemoryResetReadingProgressV1=resetProgress;
window.storyMemoryClearReadingProgressV1=clearAllProgress;
window.storyMemoryGetKnowledgeCeilingV1=getCeiling;
window.storyMemoryCompareLocatorV1=compareLocators;
window.storyMemorySyncVisibleToProgressV1=syncVisibleToProgress;
window.storyMemoryLocatorWorkFamilyV1=locatorWorkFamily;
window.storyMemoryIsLocatorCompatibleWithWorkV1=isLocatorCompatibleWithWork;
window.__smLocatorProgressR1V1={
  STORAGE_KEY:STORAGE_KEY,
  VERSION:VERSION,
  BIBLE_BOOK_ORDER:BIBLE_BOOK_ORDER,
  locatorWorkFamily:locatorWorkFamily,
  isLocatorCompatibleWithWork:isLocatorCompatibleWithWork,
  compareLocators:compareLocators,
  getCeiling:getCeiling
};
})();
