/* ===== B61 #1307 · Context Harness Foundation v1 · read-only companion packet ===== */
(function(){
'use strict';
var MAX_SOURCE_PASSAGES=64, MAX_ANNOTATIONS=128, MAX_SELECTED_TEXT_CHARS=2000;
function isAuthoritative(){ try{ return !!(window.storyMemoryIsAuthoritativeReaderMode && window.storyMemoryIsAuthoritativeReaderMode()); }catch(_){ return false; } }
function safeReaderState(){ try{ if(typeof __smDynamicReaderState!=='undefined' && __smDynamicReaderState) return __smDynamicReaderState; }catch(_){} try{ if(window.__smDynamicReaderState) return window.__smDynamicReaderState; }catch(_){} return null; }
function currentPageIndex(){ try{ if(typeof readerPageIndex!=='undefined' && typeof readerPageIndex==='number') return readerPageIndex; }catch(_){} try{ if(typeof window.readerPageIndex==='number') return window.readerPageIndex; }catch(_){} return 0; }
function currentPageCount(){ try{ if(typeof READER_PAGES!=='undefined' && Array.isArray(READER_PAGES)) return READER_PAGES.length; }catch(_){} try{ if(Array.isArray(window.READER_PAGES)) return window.READER_PAGES.length; }catch(_){} var s=safeReaderState(); if(s && Array.isArray(s.pagePassages)) return s.pagePassages.length||1; return 1; }
function workKeyFromState(){ try{ if(window.storyMemoryReaderBindingStatus){ var bs=window.storyMemoryReaderBindingStatus(); if(bs && bs.workKey) return bs.workKey; } }catch(_){} try{ var s=safeReaderState(); if(s && s.work && s.work.work_key) return s.work.work_key; if(window.storyMemoryStaticWorkKey && s && s.content){ var k=window.storyMemoryStaticWorkKey(s.content); if(k) return k; if(s.content.id){ var k2=window.storyMemoryStaticWorkKey({id:s.content.id}); if(k2) return k2; } } }catch(_){} return null; }
function workTitle(){ try{ if(typeof __smCurrentReaderLabel==='string' && __smCurrentReaderLabel) return __smCurrentReaderLabel; }catch(_){} try{ var s=safeReaderState(); if(s && s.content && s.content.title) return s.content.title; }catch(_){} try{ if(typeof window.__smCurrentReaderLabel==='string' && window.__smCurrentReaderLabel) return window.__smCurrentReaderLabel; }catch(_){} var dom=document.getElementById('aiReadingContext')?.textContent||document.getElementById('readerVolumeTitle')?.textContent||''; return (dom||'').trim(); }
function unitOf(loc){ try{ var p=String(loc).split(':'); return p[0]==='bible'? p.slice(0,4).join(':') : p.slice(0,3).join(':'); }catch(_){ return null; } }
function canonicalUnitKey(){ try{ var locs=visibleLocators(); if(locs.length && locs[0]) return unitOf(locs[0]); }catch(_){} return null; }
function bookIdFromLocator(loc){ try{ var p=String(loc).split(':'); if(p[0]==='bible' && p[2]) return p[2]; if(p.length>=1) return p[0]; return null; }catch(_){ return null; } }
function visibleLocators(){ try{ var isFlow=false; try{ isFlow=typeof readerViewMode!=='undefined' && readerViewMode==='flow'; }catch(_){} var els=document.querySelectorAll('#readerPageBody [data-source-locator]'); var out=[]; if(isFlow){ var inner=document.querySelector('.paper-inner'); if(!inner) return []; var irect=inner.getBoundingClientRect(); els.forEach(function(el){ try{ var rect=el.getBoundingClientRect(); var visible=rect.bottom>irect.top+2 && rect.top<irect.bottom-2 && rect.height>0 && rect.width>0; if(!visible) return; var v=el.getAttribute('data-source-locator'); if(v) out.push(v); }catch(_){} }); return out; } els.forEach(function(el){ var v=el.getAttribute('data-source-locator'); if(v) out.push(v); }); return out; }catch(_){ return []; } }
function selectedInfo(){ try{ var sel=window.getSelection(); if(!sel || sel.isCollapsed || !sel.rangeCount) return {locator:null, text:'', lang:null}; if(!isAuthoritative()) return {locator:null, text:'', lang:null}; var range=sel.getRangeAt(0); var node=range.commonAncestorContainer.nodeType===1?range.commonAncestorContainer:range.commonAncestorContainer.parentElement; var el=node && node.closest ? node.closest('#readerPageBody [data-source-locator]') : null; if(!el) return {locator:null, text:'', lang:null}; var locator=el.getAttribute('data-source-locator')||null; var text=String(sel.toString()||'').slice(0, MAX_SELECTED_TEXT_CHARS); var hasKo=/[가-힣]/.test(text); var hasEn=/[A-Za-z]/.test(text); var lang=null; if(hasKo && !hasEn) lang='ko'; else if(!hasKo && hasEn) lang='en'; else if(hasKo && hasEn) lang=null; else if(text) lang=null; return {locator:locator, text:text, lang:lang}; }catch(_){ return {locator:null, text:'', lang:null}; } }
function passageTextsFromDOM(){ try{ var els=document.querySelectorAll('#readerPageBody [data-source-locator]'); var out=[]; els.forEach(function(el){ var loc=el.getAttribute('data-source-locator')||''; var seq=parseInt(el.getAttribute('data-source-sequence')||'0',10)||0;
      var clone=el.cloneNode(true);
      clone.querySelectorAll('.vn, .smal-badge, #smalToolbar, #smalPop, .selection-toolbar').forEach(function(n){ n.remove(); });
      clone.querySelectorAll('mark.smal').forEach(function(m){ var p=m.parentNode; while(m.firstChild) p.insertBefore(m.firstChild,m); p.removeChild(m); });
      if(clone.normalize) clone.normalize();
      var txt=(clone.textContent||'').replace(/\s+/g,' ').trim();
      if(!txt) return;
      out.push({canonical_locator:loc, sequence:seq, text:txt.slice(0,2000), language:'ko'});
    }); return out; }catch(_){ return []; } }
function passagesFromState(){ try{ var s=safeReaderState(); var idx=currentPageIndex(); if(s && isAuthoritative() && Array.isArray(s.pagePassages) && s.pagePassages[idx] && s.pagePassages[idx].length){ var page=s.pagePassages[idx]; var arr=page.map(function(p){ return {canonical_locator:p.canonicalLocator||p.canonical_locator||p.id||'', sequence:Number(p.sequence)||0, text:String(p.text||p.sourceText||'').slice(0,2000), language:p.language||'ko'}; }).filter(function(x){return x.canonical_locator && x.text;}); if(arr.length) return arr; } return passageTextsFromDOM(); }catch(_){ return passageTextsFromDOM(); } }
function getReaderContextV1(){
  var auth=isAuthoritative();
  var s=safeReaderState();
  var locs=auth?visibleLocators():[];
  var sel=selectedInfo();
  var unitKey=auth? canonicalUnitKey() : null;
  var bookId=null; if(auth && locs.length) bookId=bookIdFromLocator(locs[0]);
  return {
    version:'1',
    authoritative_reader: !!auth,
    mode: s? String(s.mode|| (auth?'authoritative':'fallback')) : (auth?'authoritative':'fallback'),
    current_work_key: auth? workKeyFromState() : null,
    current_work_title: workTitle(),
    current_book_id: bookId,
    current_unit_key: unitKey,
    current_unit_ordinal: (function(){ try{ var st=safeReaderState(); return st && Number.isFinite(Number(st.unitOrdinal))? Number(st.unitOrdinal): null; }catch(_){return null;}})(),
    current_page_index: currentPageIndex(),
    current_page_count: currentPageCount(),
    visible_locator_start: locs.length? locs[0] : null,
    visible_locator_end: locs.length? locs[locs.length-1] : null,
    visible_locators: locs.slice(0, MAX_SOURCE_PASSAGES),
    selected_locator: auth? (sel.locator||null) : null,
    selected_text: sel.text? sel.text.slice(0, MAX_SELECTED_TEXT_CHARS) : '',
    selected_text_ko: sel.lang==='ko' ? sel.text : '',
    selected_text_en: sel.lang==='en' ? sel.text : ''
  };
}
function getAnnotationContextV1(){
  var auth=isAuthoritative();
  var wk=auth? workKeyFromState(): null;
  var rc=getReaderContextV1();
  var unitKey=rc.current_unit_key;
  var visSet=null; try{ visSet=new Set(rc.visible_locators||[]); }catch(_){ visSet=new Set(); }
  var raw=[]; try{ if(window.__smAnnotationLayerV1 && typeof window.__smAnnotationLayerV1.list==='function'){ raw=window.__smAnnotationLayerV1.list()||[]; } else { var v=localStorage.getItem('storymemory.annotations.v1'); if(v){ var p=JSON.parse(v); if(p && p.version===1 && Array.isArray(p.items)) raw=p.items; else raw=[]; } } }catch(_){ raw=[]; }
  var filtered=[];
  if(!auth){ filtered=[]; }
  else {
    filtered=raw.filter(function(it){
      if(!it || typeof it!=='object') return false;
      if(!['highlight','underline','memo','bookmark'].includes(it.kind)) return false;
      var itUnit=null; try{ if(it.unit) itUnit=String(it.unit); else if(it.locator) itUnit=unitOf(it.locator); }catch(_){ itUnit=null; }
      if(unitKey){
        if(itUnit!==unitKey) return false;
      } else {
        if(it.locator && !visSet.has(String(it.locator))){
          var u2=null; try{ u2=unitOf(it.locator); }catch(_){}
          var curU=null; try{ if(rc.visible_locator_start) curU=unitOf(rc.visible_locator_start); }catch(_){}
          if(u2!==curU) return false;
        }
      }
      return true;
    }).slice(0, MAX_ANNOTATIONS).map(function(it){
      return {
        id:String(it.id||''),
        kind:String(it.kind),
        locator:String(it.locator||''),
        unit:String(it.unit||''),
        text: String(it.text||'').slice(0,2000),
        color: it.color? String(it.color): null,
        note: it.note? String(it.note).slice(0,2000): null,
        createdAt: Number.isFinite(Number(it.createdAt))? Number(it.createdAt): null
      };
    });
  }
  filtered.sort(function(a,b){ var c=String(a.locator).localeCompare(String(b.locator)); return c!==0?c: String(a.id).localeCompare(String(b.id)); });
  return {version:'1', work_key: wk, unit_key: unitKey, annotations: filtered, count: filtered.length};
}
function stableStringify(obj){
  if(obj===null || typeof obj!=='object') return JSON.stringify(obj);
  if(Array.isArray(obj)) return '['+ obj.map(stableStringify).join(',') +']';
  var keys=Object.keys(obj).sort();
  return '{'+ keys.map(function(k){ return JSON.stringify(k)+':'+stableStringify(obj[k]); }).join(',') +'}';
}
async function sha256Hex(str){
  var enc=new TextEncoder().encode(str);
  var buf=await crypto.subtle.digest('SHA-256', enc);
  var arr=new Uint8Array(buf); return Array.from(arr).map(function(b){ return b.toString(16).padStart(2,'0'); }).join('');
}
function buildAIContextPacketV1(){
  var rc=getReaderContextV1();
  var ac=getAnnotationContextV1();
  var passages=passagesFromState().slice(0, MAX_SOURCE_PASSAGES);
  passages.sort(function(a,b){ if(a.sequence!==b.sequence) return a.sequence-b.sequence; return String(a.canonical_locator).localeCompare(String(b.canonical_locator)); });
  var packet={
    version:'1',
    mode:'storymemory_reader_companion',
    source_scope:'visible_page',
    reader_context: rc,
    annotation_context: ac,
    source_passages: passages
  };
  return packet;
}
window.storyMemoryGetReaderContextV1=getReaderContextV1;
window.storyMemoryGetAnnotationContextV1=getAnnotationContextV1;
window.storyMemoryBuildAIContextPacketV1=buildAIContextPacketV1;
window.storyMemoryStableStringify=stableStringify;
window.storyMemoryPacketSha256=sha256Hex;
window.__smContextHarnessV1={MAX_SOURCE_PASSAGES:MAX_SOURCE_PASSAGES, MAX_ANNOTATIONS:MAX_ANNOTATIONS, MAX_SELECTED_TEXT_CHARS:MAX_SELECTED_TEXT_CHARS};
})();
