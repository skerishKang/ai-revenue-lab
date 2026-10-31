/* ===== B61 #1478 · Annotation Search Foundation v1 · deterministic local search =====
   Reuses accepted contracts:
   - storymemory.annotations.v2 (primary) / v1 (legacy)
   - storymemory.userMemories.v1 (bookmark subtype)
   - storymemory.syncTombstones.v1 (deleted/tombstone exclusion)
   - #1426 locator resolver for safe book/chapter derivation
   No network, no AI, no schema mutation.
*/
(function(root){
'use strict';

var ANNOTATION_KEYS = ['storymemory.annotations.v2','storymemory.annotations.v1'];
var MEMORY_KEY = 'storymemory.userMemories.v1';
var TOMBSTONE_KEY = 'storymemory.syncTombstones.v1';

var LOC_RE = /^[a-z0-9][a-z0-9-]*(:[A-Za-z0-9][A-Za-z0-9.\-]*)+$/;

// Reuse unitOf from #1426 and annotation store
function unitOf(loc){
  var p = String(loc).split(':');
  if(p[0]==='bible') return p.slice(0,4).join(':'); // legacy legacy, but #1478 prefers padded unit for navigation
  return p.slice(0,3).join(':');
}

// Safe derivation for navigation_target and work/unit filters
function deriveWorkUnit(locator){
  var loc = String(locator||'');
  if(loc.indexOf('bible:web:')===0){
    var parts = loc.split(':'); // bible, web, BOOK, chapter, verse
    var book = parts[2]||null;
    var ch = parseInt(parts[3],10);
    var work_key = 'bible-web';
    var unit_key = null;
    if(book && Number.isFinite(ch)) unit_key = 'book:'+book+':chapter:'+String(ch).padStart(3,'0');
    return {work_key:work_key, unit_key:unit_key, book:book, chapter: Number.isFinite(ch)?ch:null};
  }
  // six-work: iliad:book:01:s1:row:001  -> work iliad, unit iliad:book:01
  var seg = loc.split(':');
  var wk = seg[0]||null;
  var uk = unitOf(loc);
  // Special case for bible legacy legacy:bible... treat as bible-web as well
  if(wk==='legacy' && loc.indexOf('legacy:bible')===0){
    return {work_key:'bible-demo-work', unit_key: uk, book:null, chapter:null};
  }
  return {work_key: wk, unit_key: uk, book: null, chapter: null};
}

function safeReadJson(key, storage){
  try{
    var s = storage ? storage.getItem(key) : (typeof localStorage!=='undefined'? localStorage.getItem(key):null);
    if(s===null) return null;
    return JSON.parse(s);
  }catch(_){ return null; }
}

function loadAnnotationsFromStorage(storage){
  var acc = [];
  for(var i=0;i<ANNOTATION_KEYS.length;i++){
    var parsed = safeReadJson(ANNOTATION_KEYS[i], storage);
    if(Array.isArray(parsed)){
      // dist/index.html stores __smAnnotations as array directly, not {version,items}
      // annotation-store-v1 stores {version:1,items:[]} — handle both
      acc = acc.concat(parsed);
    } else if(parsed && Array.isArray(parsed.items)){
      acc = acc.concat(parsed.items);
    }
  }
  // Deduplicate by id (keep last)
  var byId = new Map();
  acc.forEach(function(it){ if(it && it.id) byId.set(it.id, it); else if(it) byId.set('_'+Math.random(), it); });
  return Array.from(byId.values());
}

function loadBookmarkMemoriesFromStorage(storage){
  var parsed = safeReadJson(MEMORY_KEY, storage);
  if(!Array.isArray(parsed)) return [];
  return parsed.filter(function(m){ return m && m.subtype==='bookmark'; });
}

function loadTombstones(storage){
  var parsed = safeReadJson(TOMBSTONE_KEY, storage);
  if(!Array.isArray(parsed)) return [];
  return parsed;
}

function isTombstoned(clientRecordId, tombstones){
  if(!clientRecordId) return false;
  for(var i=0;i<tombstones.length;i++){
    if(tombstones[i] && tombstones[i].clientRecordId===clientRecordId) return true;
  }
  return false;
}

// Normalize search query (case-insensitive substring)
function normalizeQuery(q){
  if(q===null || q===undefined) return '';
  var s = String(q).trim();
  return s;
}

function matchesText(item, query){
  if(!query) return true;
  var q = query.toLowerCase();
  // Search over text fields safely
  var hay = [];
  if(item.text) hay.push(String(item.text));
  if(item.note) hay.push(String(item.note));
  if(item.title) hay.push(String(item.title));
  if(item.body) hay.push(String(item.body));
  if(item.quote) hay.push(String(item.quote));
  if(item.locator) hay.push(String(item.locator));
  if(item.canonicalLocator) hay.push(String(item.canonicalLocator));
  if(item.canonical_locator) hay.push(String(item.canonical_locator));
  var joined = hay.join(' ').toLowerCase();
  return joined.indexOf(q)!==-1;
}

function snippetFor(item, maxLen){
  maxLen = maxLen||120;
  var src = item.text || item.note || item.body || item.quote || item.title || '';
  src = String(src).replace(/\s+/g,' ').trim();
  if(src.length>maxLen) return src.slice(0, maxLen-1)+' …';
  return src;
}

function stableSort(results){
  // Deterministic: updatedAt/clientUpdatedAt desc, createdAt desc, locator asc, id asc
  return results.sort(function(a,b){
    var at = Number(a.updated_at || a.clientUpdatedAt || a.createdAt || a.created_at || 0);
    var bt = Number(b.updated_at || b.clientUpdatedAt || b.createdAt || b.created_at || 0);
    if(at!==bt) return bt - at;
    var act = Number(a.createdAt||a.created_at||0);
    var bct = Number(b.createdAt||b.created_at||0);
    if(act!==bct) return bct - act;
    var al = String(a.canonical_locator||a.canonicalLocator||a.locator||'');
    var bl = String(b.canonical_locator||b.canonicalLocator||b.locator||'');
    if(al!==bl) return al.localeCompare(bl);
    var aid = String(a.client_record_id||a.clientRecordId||a.id||'');
    var bid = String(b.client_record_id||b.clientRecordId||b.id||'');
    return aid.localeCompare(bid);
  });
}

function dedupByLocatorKind(results){
  // SAME_LOCATOR_DUPLICATE_MAX =1 : collapse same locator+kind to single most recent (already sorted)
  // For bookmark, annotation bookmark and memory bookmark share same locator and both are kind bookmark — dedup by kind|locator only
  var seen = new Map();
  var out = [];
  for(var i=0;i<results.length;i++){
    var r = results[i];
    var key = String(r.kind||'') + '|' + String(r.canonical_locator||r.canonicalLocator||r.locator||'');
    if(!seen.has(key)){
      seen.set(key, true);
      out.push(r);
    }
  }
  return out;
}

function searchAnnotations(options, storageOrAdapter){
  options = options || {};
  var query = normalizeQuery(options.query || options.text || options.q || '');
  var kindFilter = options.kind || null; // highlight|underline|memo|bookmark|note
  var subtypeFilter = options.subtype || null;
  var locatorFilter = options.canonical_locator || options.canonicalLocator || options.locator || null;
  var workFilter = options.work_key || options.workKey || null;
  var unitFilter = options.unit_key || options.unitKey || null;
  var bookFilter = options.book || null; // USFM
  var chapterFilter = options.chapter!=null? Number(options.chapter):null;
  var bookmarkOnly = !!options.bookmarkOnly;
  var highlightOnly = !!options.highlightOnly;
  var noteOnly = !!options.noteOnly;

  // Allow adapter override for tests: storageOrAdapter may be {getItem}
  var storage = null;
  var adapterAnnotations = null;
  var adapterMemories = null;
  var adapterTombstones = null;
  if(storageOrAdapter && typeof storageOrAdapter.getAnnotations==='function'){
    adapterAnnotations = storageOrAdapter.getAnnotations();
    adapterMemories = typeof storageOrAdapter.getBookmarkMemories==='function'? storageOrAdapter.getBookmarkMemories():[];
    adapterTombstones = typeof storageOrAdapter.getTombstones==='function'? storageOrAdapter.getTombstones():[];
  } else {
    storage = storageOrAdapter || null;
  }

  var annotations = adapterAnnotations!==null? adapterAnnotations : loadAnnotationsFromStorage(storage);
  var bookmarkMems = adapterMemories!==null? adapterMemories : loadBookmarkMemoriesFromStorage(storage);
  var tombstones = adapterTombstones!==null? adapterTombstones : loadTombstones(storage);

  // Build unified candidates
  var candidates = [];

  // Process annotations
  for(var i=0;i<annotations.length;i++){
    var it = annotations[i];
    if(!it) continue;
    // Exclude erased highlights: in existing UI, erased = removed from array, so not present.
    // But if highlight has internal erased flag (not in current schema) we treat as excluded if kind missing
    if(!it.kind) continue;
    if(!it.locator || !LOC_RE.test(it.locator)) continue;
    // Tombstone check via clientRecordId / client_record_id
    var cr = it.clientRecordId || it.client_record_id || null;
    if(isTombstoned(cr, tombstones)) continue;
    // If tombstone via id fallback (legacy annotations without clientRecordId): check id tombstone kind annotation
    if(isTombstoned(it.id, tombstones)) continue; // defensive
    // Map annotation kinds to searchable kinds
    // highlight: hl-* and highlight
    var kindNorm = it.kind;
    // normalize highlight colors: hl-yellow etc -> highlight
    if(String(kindNorm).indexOf('hl-')===0) kindNorm = 'highlight';
    if(kindNorm==='memo') kindNorm = 'note'; // alias note search expects note
    // Build result envelope preserving migration-safe identity
    var derived = deriveWorkUnit(it.locator);
    var work_key = derived.work_key;
    var unit_key = it.unit || derived.unit_key;
    var clientId = cr || it.id; // fallback
    var navTarget = derived.unit_key || unit_key || null;
    // For bible, navigation should be chapter unit
    if(derived.work_key==='bible-web' && derived.unit_key) navTarget = derived.unit_key;

    candidates.push({
      id: it.id,
      kind: kindNorm,
      original_kind: it.kind,
      subtype: it.subtype || null,
      locator: it.locator,
      canonical_locator: it.locator,
      canonicalLocator: it.locator,
      client_record_id: cr,
      clientRecordId: cr,
      work_key: work_key,
      unit_key: unit_key,
      book: derived.book,
      chapter: derived.chapter,
      createdAt: it.createdAt || it.created_at || null,
      created_at: it.createdAt || it.created_at || null,
      updated_at: it.clientUpdatedAt || it.updatedAt || it.createdAt || null,
      clientUpdatedAt: it.clientUpdatedAt || null,
      text: it.text || null,
      note: it.note || null,
      color: it.color || null,
      navigation_target: navTarget,
      snippet: snippetFor(it),
      _source: 'annotation',
      _raw: it
    });
  }

  // Process bookmark memories (subtype bookmark)
  for(var j=0;j<bookmarkMems.length;j++){
    var bm = bookmarkMems[j];
    if(!bm) continue;
    var bmCr = bm.clientRecordId || bm.client_record_id || null;
    if(isTombstoned(bmCr, tombstones)) continue;
    if(isTombstoned(bm.id, tombstones)) continue;
    var bLoc = bm.canonicalLocator || bm.canonical_locator || bm.locator || null;
    if(!bLoc || !LOC_RE.test(bLoc)) continue;
    var derived2 = deriveWorkUnit(bLoc);
    var wk2 = derived2.work_key || bm.work_key || 'bible-web';
    var uk2 = bm.unitKey || bm.unit_key || derived2.unit_key;
    var nav2 = uk2 || derived2.unit_key || null;
    if(derived2.work_key==='bible-web' && derived2.unit_key) nav2 = derived2.unit_key;
    candidates.push({
      id: bm.id,
      kind: 'bookmark',
      original_kind: bm.kind || 'note',
      subtype: 'bookmark',
      locator: bLoc,
      canonical_locator: bLoc,
      canonicalLocator: bLoc,
      client_record_id: bmCr,
      clientRecordId: bmCr,
      work_key: wk2,
      unit_key: uk2,
      book: derived2.book,
      chapter: derived2.chapter,
      createdAt: bm.createdAt || bm.created_at || null,
      created_at: bm.createdAt || bm.created_at || null,
      updated_at: bm.clientUpdatedAt || bm.updatedAt || bm.createdAt || null,
      clientUpdatedAt: bm.clientUpdatedAt || null,
      title: bm.title || null,
      body: bm.body || null,
      context: bm.context || null,
      navigation_target: nav2,
      snippet: snippetFor({text: bm.title || bLoc}),
      _source: 'bookmark-memory',
      _raw: bm
    });
  }

  // Apply filters
  var filtered = candidates.filter(function(r){
    // Text query
    if(query && !matchesText(r, query)) return false;
    // Kind filter
    if(kindFilter){
      if(String(kindFilter).toLowerCase()!==String(r.kind).toLowerCase()) return false;
    }
    if(subtypeFilter){
      if(String(subtypeFilter).toLowerCase()!==String(r.subtype||'').toLowerCase()) return false;
    }
    if(bookmarkOnly && r.kind!=='bookmark') return false;
    if(highlightOnly && r.kind!=='highlight') return false;
    if(noteOnly && !(r.kind==='note' || r.original_kind==='memo' || r.kind==='note')) return false;
    // Locator filter exact
    if(locatorFilter){
      var lf = String(locatorFilter);
      if(r.canonical_locator!==lf && r.locator!==lf) return false;
    }
    // Work/unit filter
    if(workFilter && String(workFilter)!==String(r.work_key)) return false;
    if(unitFilter && String(unitFilter)!==String(r.unit_key)) return false;
    if(bookFilter){
      var bf = String(bookFilter).toUpperCase();
      if(!r.book || String(r.book).toUpperCase()!==bf) return false;
    }
    if(Number.isFinite(chapterFilter)){
      if(r.chapter===null || Number(r.chapter)!==Number(chapterFilter)) return false;
    }
    // Invalid filter safety: if filter is malformed locator, treat as not matching rather than throw
    return true;
  });

  // Stable sort
  stableSort(filtered);

  // Dedup same locator (max 1)
  var deduped = dedupByLocatorKind(filtered);

  // Ensure deterministic ordering after dedup (already sorted, dedup keeps first most recent)
  return deduped;
}

var api = {
  version: '1',
  ANNOTATION_KEYS: ANNOTATION_KEYS,
  MEMORY_KEY: MEMORY_KEY,
  TOMBSTONE_KEY: TOMBSTONE_KEY,
  LOC_RE: LOC_RE,
  unitOf: unitOf,
  deriveWorkUnit: deriveWorkUnit,
  search: searchAnnotations,
  loadAnnotationsFromStorage: loadAnnotationsFromStorage,
  loadBookmarkMemoriesFromStorage: loadBookmarkMemoriesFromStorage,
  loadTombstones: loadTombstones
};

if(typeof module!=='undefined' && module.exports) module.exports = api;
if(typeof window!=='undefined'){
  window.storyMemoryAnnotationSearchV1 = api;
  window.__smAnnotationSearchV1 = api;
}

return api;
})(typeof globalThis!=='undefined'? globalThis : typeof window!=='undefined'? window : this);
