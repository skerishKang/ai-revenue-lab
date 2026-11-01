/* B61 #1515 · Retrieval Preview Adapter v1 — browser wiring via ceiling projection */
(function(){
'use strict';
var AI_PATH='/api/storymemory-ai';

/* ===== B61 #1897 · FIX A · retrieval candidate selection order =====
   Old order: whole loaded corpus -> keyword top-N limit -> ceiling projection.
   An allowed in-ceiling prior candidate that ranked below the top-N cut was
   evicted by staticKeywordSearch BEFORE ceiling eligibility was evaluated, so
   a low-frequency allowed prior hit could be lost while future hits survived.
   New order: keyword matches -> current work/domain narrowing -> trusted
   ceiling eligibility -> deterministic bounded selection -> projection. The
   recall pool is widened to RECALL_LIMIT; buildProjection performs the ceiling
   + work-family eligibility test and then the bounded slice to its own limit,
    so unusable candidates no longer consume allowed quota. No learned retrieval
    stage, no similarity scoring, no learned re-ranking, no generic semantic
    ranking - #1477 lexical search is reused unchanged and its existing
    deterministic sort is intact. */
var RECALL_LIMIT=48;
var PROJECTION_LIMIT=8;

function getKeywordSearch(){
  if(typeof window!=='undefined' && window.__smStaticKeywordSearchV1) return window.__smStaticKeywordSearchV1;
  if(typeof window!=='undefined' && window.__smKeywordSearchV1) return window.__smKeywordSearchV1;
  return null;
}
function getAnnotationSearch(){
  if(typeof window!=='undefined' && window.__smAnnotationSearchV1) return window.__smAnnotationSearchV1;
  if(typeof window!=='undefined' && window.storyMemoryAnnotationSearchV1) return window.storyMemoryAnnotationSearchV1;
  return null;
}
function getProjection(){
  if(typeof window!=='undefined' && window.__smRetrievalCeilingProjectionV1) return window.__smRetrievalCeilingProjectionV1;
  return null;
}

async function loadBlocksForWorkBrowser(workKey){
  if(typeof window==='undefined' || !window.storyMemoryStatic) return null;
  try{
    var staticAdapter=window.storyMemoryStatic;
    var catalog=await staticAdapter.getCatalog();
    var entry=null;
    for(var i=0;i<catalog.works.length;i++) if(catalog.works[i].work_key===workKey) entry=catalog.works[i];
    if(!entry) return null;
    var manifestRes=await staticAdapter.getManifest(workKey);
    // Static adapter returns {entry,manifest}; accept bare manifest too.
    var manifest=(manifestRes && manifestRes.manifest) ? manifestRes.manifest : manifestRes;
    if(!manifest || !Array.isArray(manifest.units)) return null;
    // For retrieval, we need to load all units for the work to ensure keyword search finds all prior passages
    // But to keep bounded, we can load until we have enough blocks or use a limit
    var blocks=[];
    // Load all units for the work (for bible-web this is 1189 units, too many for browser)
    // Instead, load only needed units: for now, load first 5 units for test (GEN 1-5 for ceiling 5:1)
    // For general case, we should load all, but to keep network low, we can just load the units that contain the query term via a quick scan
    // Simpler: Use the keyword search's browser blocks injection path - we will build blocks by loading all units for the work via staticAdapter.loadUnit
    // For performance, we will load all units for the work in parallel with a limit
    var unitsToLoad=manifest.units.slice(0, Math.min(manifest.units.length, 20));
    var promises=[];
    for(var j=0;j<unitsToLoad.length;j++){
      (function(u){
        promises.push(staticAdapter.loadUnit({workKey:workKey, unitOrdinal: u.unit_ordinal}).then(function(bundle){
          var unit=bundle.unit;
          var passages=unit.passages||[];
          for(var k=0;k<passages.length;k++){
            var row=passages[k];
            blocks.push({
              canonical_locator: String(row.canonical_locator||''),
              work_key: workKey,
              unit_key: unit.unit_key||u.unit_key,
              unit_ordinal: unit.unit_ordinal||u.unit_ordinal,
              sequence: row.sequence!=null?Number(row.sequence): (blocks.length+1),
              ordinal: row.sequence!=null?Number(row.sequence): (blocks.length+1),
              locator: row.canonical_locator,
              title: String(((row.section_title||'')+' '+(unit.unit_label||u.label||'')+' '+workKey).trim()),
              text: String(row.ko||row.en||''),
              sourceText: String(row.en||row.ko||''),
              ko: String(row.ko||''),
              en: String(row.en||''),
              raw_texts: Array.isArray(row.raw_texts)?row.raw_texts.slice():[],
              raw_locator: row.raw_locator?JSON.parse(JSON.stringify(row.raw_locator)):null,
              mapping_type: row.mapping_type||null,
              mapping_note: row.mapping_note||null,
              raw: row,
              unit: unit,
              manifestUnit: u
            });
          }
        }).catch(function(){}));
      })(unitsToLoad[j]);
    }
    await Promise.all(promises);
    return blocks;
  }catch(e){ return null; }
}

async function retrieveForPreview(query, opts){
  opts=opts||{};
  var workKey=opts.workKey || (typeof window.storyMemoryGetReaderContextV1==='function' ? (window.storyMemoryGetReaderContextV1()||{}).current_work_key : null) || 'bible-web';
  var progress=null;
  try{ progress=typeof window.storyMemoryGetReadingProgressV1==='function' ? window.storyMemoryGetReadingProgressV1(workKey) : null; }catch(e){}
  var ceiling=progress ? progress.knowledge_ceiling_locator : null;
  var furthest=progress ? progress.furthest_read_locator : null;
  if(!ceiling){
    return {ok:false, error:'missing_required_ceiling', failClosed:true};
  }
  var keywordSearch=getKeywordSearch();
  var annotationSearch=getAnnotationSearch();
  var projectionMod=getProjection();
  if(!keywordSearch || !annotationSearch || !projectionMod){
    return {ok:false, error:'retrieval_modules_unavailable'};
  }
  var keywordCandidates=[];
  var annotationCandidates=[];
  try{
    var kwRes=null;
    // Browser product path: try blocks injection first
    if(typeof window!=='undefined' && window.storyMemoryStatic){
      var blocks=await loadBlocksForWorkBrowser(workKey);
      if(blocks && blocks.length){
        kwRes=keywordSearch.staticKeywordSearch(query, {blocks: blocks, workKey: workKey, limit:RECALL_LIMIT});
      } else {
        kwRes=keywordSearch.staticKeywordSearch(query, {workKey:workKey, limit:RECALL_LIMIT});
      }
    } else {
      kwRes=keywordSearch.staticKeywordSearch(query, {workKey:workKey, limit:RECALL_LIMIT});
    }
    if(kwRes && kwRes.status==='FOUND' && Array.isArray(kwRes.results)){
      for(var i=0;i<kwRes.results.length;i++){
        var r=kwRes.results[i];
        keywordCandidates.push({
          source_kind:'keyword',
          canonical_locator:r.canonical_locator,
          work_key:r.work_key,
          unit_key:r.unit_key,
          language:r.language,
          snippet:r.snippet,
          text:r.ko||r.en||r.snippet,
          score:r.score,
          mapping_type:r.mapping_type,
          mapping_note:r.mapping_note,
          raw_locator:r.raw_locator,
          raw_texts:r.raw_texts
        });
      }
    }
  }catch(e){}
  try{
    var annRes=annotationSearch.search({query:query}, null);
    if(Array.isArray(annRes)){
      for(var j=0;j<annRes.length;j++){
        var a=annRes[j];
        annotationCandidates.push({
          source_kind:'annotation',
          canonical_locator:a.canonical_locator||a.canonicalLocator||a.locator,
          work_key:a.work_key||workKey,
          unit_key:a.unit_key,
          language:null,
          snippet:a.snippet||a.text||a.note||'',
          text:a.text||a.note||'',
          client_record_id:a.client_record_id||a.clientRecordId||a.id,
          kind:a.kind,
          subtype:a.subtype,
          _raw:a
        });
      }
    }
  }catch(e){}

  var projection;
  try{
    projection=projectionMod.buildProjection({
      query:query,
      workKey:workKey,
      knowledgeCeilingLocator:ceiling,
      furthestReadLocator:furthest,
      keywordCandidates:keywordCandidates,
      annotationCandidates:annotationCandidates,
      limit:PROJECTION_LIMIT,
      maxBytes:7000
    });
  }catch(e){
    return {ok:false, error:'projection_failed', detail:String(e&&e.message||e)};
  }
  if(projection.missing_required_ceiling){
    return {ok:false, error:'missing_required_ceiling', failClosed:true, projection:projection};
  }
  /* B61 #1515 · deterministic spoiler refusal via accepted #1305 co-reader contract.
     Future-only retrieval (ALL_FILTERED with future hits) or a future-seeking
     query per the co-reader decision → accepted refusal copy, ZERO model call.
     No new classifier; no LLM involvement on this path. */
  var eligible=projection.candidates||[];
  var coReaderBlock=null;
  try{
    if(typeof window.storyMemoryCoReaderDecisionV1==='function'){
      /* B61 #1724 · relevance gate: pass permitted evidence CONTENT so the
         co-reader can require stem overlap before ALLOW (count is not enough). */
      var dec=window.storyMemoryCoReaderDecisionV1(query, null, workKey, eligible);
      if(dec && dec.decision==='BLOCK') coReaderBlock=dec;
    }
  }catch(e){}
  var futureOnly=((projection.diagnostics?Number(projection.diagnostics.future_filtered_count||0):0)>0) && eligible.length===0;
  if(coReaderBlock || futureOnly){
    var dec2=coReaderBlock||{reason:'HARD_NO_FUTURE', copy:'아직 읽지 않은 부분은 안내해 드릴 수 없어요. 현재까지 읽은 범위 안에서 함께 이야기 나눠요.', ceiling:ceiling};
    return {ok:true, refused:true, reason:String(dec2.reason||'HARD_NO_FUTURE'), copy:String(dec2.copy||''), decision:{decision:'BLOCK', reason:String(dec2.reason||'HARD_NO_FUTURE')}, query:query, workKey:workKey, projection:projection};
  }
  if(!eligible.length){
    return {ok:true, eligible:[], projection:projection, empty:true};
  }
  var packet=null;
  try{
    if(typeof window.storyMemoryBuildBoundedCompanionPacketV1!=='function') throw new Error('bounded_packet_unavailable');
    var sourcePassages=eligible.map(function(c){
      return {
        canonical_locator:c.canonical_locator,
        sequence:c.sequence||null,
        text:c.snippet||c.text||'',
        language:c.language||null
      };
    });
    packet=window.storyMemoryBuildBoundedCompanionPacketV1({query:query, sourcePassagesOverride: sourcePassages});
    if(!packet || !Array.isArray(packet.source_passages)){
      packet={
        version:'1',
        mode:'storymemory_bounded_companion',
        source_scope:'ceiling_filtered',
        reader_context: (typeof window.storyMemoryGetReaderContextV1==='function'? window.storyMemoryGetReaderContextV1(): null),
        reading_progress: {furthest_read_locator: furthest, knowledge_ceiling_locator: ceiling},
        annotation_context: {version:'1', work_key: workKey, unit_key: null, annotations: []},
        source_passages: sourcePassages,
        selected: null,
        diagnostics: {boundary_available:true, spoiler_policy:'hard_no_future'},
        co_reader_decision: {decision:'ALLOW', reason:'WITHIN_CEILING'}
      };
    }
  }catch(e){
    return {ok:false, error:'packet_build_failed', detail:String(e&&e.message||e)};
  }
  return {ok:true, eligible:eligible, projection:projection, packet:packet, query:query, workKey:workKey};
}

async function requestRetrievalPreview(query, opts){
  var prep=await retrieveForPreview(query, opts);
  if(!prep.ok){
    if(prep.failClosed) return {ok:false, error:'missing_required_ceiling', failClosed:true};
    return {ok:false, error:prep.error||'retrieval_failed'};
  }
  if(prep.refused){
    return {ok:true, answer:prep.copy, refused:true, reason:prep.reason, decision:prep.decision, eligible:[], projection:prep.projection, query:query, workKey:prep.workKey};
  }
  if(prep.empty){
    return {ok:true, answer:'', empty:true, eligible:[]};
  }
  var q=String(query||'').trim();
  var packet=prep.packet;
  var response;
  try{
    response=await fetch(AI_PATH,{method:'POST', headers:{'content-type':'application/json'}, credentials:'same-origin', body: JSON.stringify({question:q, packet:packet})});
  }catch(e){ return {ok:false, error:'network_failed'}; }
  var payload=null;
  try{ payload=await response.json(); }catch(e){ return {ok:false, error:'invalid_response'}; }
  if(!response.ok || !payload || payload.ok!==true || typeof payload.answer!=='string'){
    return {ok:false, error:payload&&payload.error||('http_'+response.status), status:response.status};
  }
  return {ok:true, answer:payload.answer, eligible:prep.eligible, projection:prep.projection, payload:payload};
}

/* ===== B61 #1804 · Prior-page model-visible grounding =====
   Deterministic in-ceiling corpus cache + projection used by the live companion
   packet path. Loads only units up to (and including) the knowledge ceiling's
   unit (bounded), caches blocks + a stem term index, and projects eligible
   prior-page candidates so the co-reader can ground ALLOW in model-visible refs. */
var __gBlocks=null, __gBlocksWorkKey=null, __gBlocksLoading=null, __gTermIndex=null, __gTermIndexWorkKey=null;
function storyMemorySeedGroundingBlocksV1(blocks, workKey){
  __gBlocks=Array.isArray(blocks)?blocks:null;
  __gBlocksWorkKey=(__gBlocks&&__gBlocks.length)?String(workKey||''):null;
  __gTermIndex=null; __gTermIndexWorkKey=null;
  return !!__gBlocks;
}
async function loadInCeilingBlocksForWork(workKey){
  if(typeof window==='undefined' || !window.storyMemoryStatic) return null;
  try{
    var staticAdapter=window.storyMemoryStatic;
    var catalog=await staticAdapter.getCatalog();
    var entry=null;
    for(var i=0;i<catalog.works.length;i++) if(catalog.works[i].work_key===workKey) entry=catalog.works[i];
    if(!entry) return null;
    var manifestRes=await staticAdapter.getManifest(workKey);
    var manifest=(manifestRes&&manifestRes.manifest)?manifestRes.manifest:manifestRes;
    if(!manifest || !Array.isArray(manifest.units)) return null;
    var progress=null;
    try{ progress=(typeof window.storyMemoryGetReadingProgressV1==='function')?window.storyMemoryGetReadingProgressV1(workKey):null; }catch(_){}
    var ceiling=progress?progress.knowledge_ceiling_locator:null;
    var cmp=window.storyMemoryCompareLocatorV1||null;
    var units=manifest.units;
    var blocks=[];
    var reachedCeiling=false;
    var limit=Math.min(units.length, 24);
    for(var j=0;j<limit;j++){
      var u=units[j];
      var bundle=null;
      try{ bundle=await staticAdapter.loadUnit({workKey:workKey, unitOrdinal:u.unit_ordinal}); }catch(_){ continue; }
      var unit=(bundle&&bundle.unit)?bundle.unit:null;
      var passages=(unit&&Array.isArray(unit.passages))?unit.passages:[];
      for(var k=0;k<passages.length;k++){
        var row=passages[k];
        var loc=String(row.canonical_locator||'');
        if(!loc) continue;
        blocks.push({
          canonical_locator: loc,
          work_key: workKey,
          unit_key: unit.unit_key||u.unit_key,
          unit_ordinal: unit.unit_ordinal||u.unit_ordinal,
          sequence: row.sequence!=null?Number(row.sequence):(blocks.length+1),
          ordinal: row.sequence!=null?Number(row.sequence):(blocks.length+1),
          locator: loc,
          title: String(((row.section_title||'')+' '+(unit.unit_label||u.label||'')+' '+workKey).trim()),
          text: String(row.ko||row.en||''),
          sourceText: String(row.en||row.ko||''),
          ko: String(row.ko||''),
          en: String(row.en||''),
          raw_texts: Array.isArray(row.raw_texts)?row.raw_texts.slice():[],
          raw_locator: row.raw_locator?JSON.parse(JSON.stringify(row.raw_locator)):null,
          mapping_type: row.mapping_type||null,
          mapping_note: row.mapping_note||null,
          raw: row,
          unit: unit,
          manifestUnit: u
        });
        if(ceiling && cmp){ try{ if(cmp(loc, ceiling)>=0) reachedCeiling=true; }catch(_){ if(loc===ceiling) reachedCeiling=true; } }
      }
      if(reachedCeiling) break;
    }
    return blocks.length?blocks:null;
  }catch(e){ return null; }
}
async function storyMemoryEnsureGroundingBlocksV1(workKey){
  if(!workKey) return null;
  if(__gBlocks && __gBlocksWorkKey===String(workKey)) return __gBlocks;
  if(__gBlocksLoading) { try{ return await __gBlocksLoading; }catch(_){ return null; } }
  __gBlocksLoading=(async function(){
    var blocks=await loadInCeilingBlocksForWork(workKey);
    if(blocks && blocks.length){ __gBlocks=blocks; __gBlocksWorkKey=String(workKey); __gTermIndex=null; __gTermIndexWorkKey=null; }
    return blocks||null;
  })();
  try{ return await __gBlocksLoading; } finally { __gBlocksLoading=null; }
}
function storyMemoryGroundingBlocksV1(workKey){
  return (__gBlocks && __gBlocksWorkKey===String(workKey))?__gBlocks:null;
}
function storyMemoryInCeilingTermIndexV1(workKey){
  var blocks=storyMemoryGroundingBlocksV1(workKey);
  if(!blocks || !blocks.length) return null;
  if(__gTermIndex && __gTermIndexWorkKey===String(workKey)) return __gTermIndex;
  var tokenizer=(window.__smStaticKeywordSearchV1&&typeof window.__smStaticKeywordSearchV1.tokenize==='function')?window.__smStaticKeywordSearchV1.tokenize:null;
  if(typeof tokenizer!=='function') return null;
  var ceiling=null;
  try{ ceiling=(typeof window.storyMemoryGetReadingProgressV1==='function')?window.storyMemoryGetReadingProgressV1(workKey):null; }catch(_){}
  var ceil=ceiling?ceiling.knowledge_ceiling_locator:null;
  var cmp=window.storyMemoryCompareLocatorV1||null;
  var idx=new Set();
  for(var i=0;i<blocks.length;i++){
    var b=blocks[i];
    if(ceil && cmp){ try{ if(cmp(b.canonical_locator, ceil)>0) continue; }catch(_){} }
    var terms=tokenizer(String(b.ko||b.text||''));
    if(!Array.isArray(terms)) continue;
    for(var j=0;j<terms.length;j++) idx.add(terms[j]);
  }
  __gTermIndex=idx; __gTermIndexWorkKey=String(workKey);
  return idx;
}
function storyMemoryProjectPriorGroundingV1(query, workKey){
  var blocks=storyMemoryGroundingBlocksV1(workKey);
  if(!blocks || !blocks.length) return [];
  var kw=(window.__smStaticKeywordSearchV1&&typeof window.__smStaticKeywordSearchV1.staticKeywordSearch==='function')?window.__smStaticKeywordSearchV1.staticKeywordSearch:null;
  if(typeof kw!=='function') return [];
  var res=null;
  try{ res=kw(String(query||''), {blocks:blocks, workKey:workKey, limit:RECALL_LIMIT}); }catch(_){ return []; }
  if(!res || res.status!=='FOUND' || !Array.isArray(res.results) || !res.results.length) return [];
  var projMod=window.__smRetrievalCeilingProjectionV1;
  if(!projMod || typeof projMod.buildProjection!=='function') return [];
  var progress=null;
  try{ progress=(typeof window.storyMemoryGetReadingProgressV1==='function')?window.storyMemoryGetReadingProgressV1(workKey):null; }catch(_){}
  var ceiling=progress?progress.knowledge_ceiling_locator:null;
  var furthest=progress?progress.furthest_read_locator:ceiling;
  if(!ceiling) return [];
  var candidates=res.results.map(function(r){
    return { source_kind:'keyword', canonical_locator:r.canonical_locator, work_key:r.work_key, unit_key:r.unit_key, language:r.language, snippet:r.snippet, text:r.ko||r.en||r.snippet, score:r.score };
  });
  var projection=null;
  try{
    projection=projMod.buildProjection({
      query:String(query||''),
      workKey:workKey,
      knowledgeCeilingLocator:ceiling,
      furthestReadLocator:furthest,
      keywordCandidates:candidates,
      annotationCandidates:[],
      limit:PROJECTION_LIMIT,
      maxBytes:7000
    });
  }catch(_){ return []; }
  var projected=(projection && Array.isArray(projection.candidates))?projection.candidates:[];
  /* B61 #1804 bounded correction 1 · eligible-evidence neighborhood. A lexical
     hit is often not self-sufficient (e.g. GEN 1:4 presumes the creation of
     light in 1:3 and the day/night naming in 1:5). Project the deterministic
     ±1 same-unit in-ceiling neighborhood around each accepted candidate so the
     model-visible refs carry the minimum local context that supports the
     answer. Constraints: every added ref <= knowledge ceiling, no future ref,
     bounded count (<=2 per candidate), deterministic, corpus-ordered. */
  var NEIGHBORHOOD_RADIUS=1;
  var MAX_NEIGHBORHOOD_PER_CANDIDATE=NEIGHBORHOOD_RADIUS*2;
  var cmp2=window.storyMemoryCompareLocatorV1||null;
  var blocks=storyMemoryGroundingBlocksV1(workKey);
  var byLoc={};
  var orderedSameUnit=[];
  if(blocks && blocks.length){
    for(var bi=0;bi<blocks.length;bi++){
      var bl=blocks[bi];
      var bloc=String(bl.canonical_locator||'');
      if(!bloc) continue;
      if(byLoc[bloc]===undefined) byLoc[bloc]=bl;
    }
  }
  var expanded=[];
  var seen={};
  var addedNeighbors=0;
  for(var ci=0;ci<projected.length;ci++){
    var cand=projected[ci];
    var cloc=String(cand.canonical_locator||'');
    var baseBlock=cloc?byLoc[cloc]:null;
    var unitKey=baseBlock?(baseBlock.unit_key||cand.unit_key||null):(cand.unit_key||null);
    var neighbors=[];
    if(baseBlock && unitKey && blocks && blocks.length){
      var idx=-1;
      for(var si=0;si<blocks.length;si++){ if(String(blocks[si].canonical_locator||'')===cloc){ idx=si; break; } }
      if(idx>=0){
        for(var d=-NEIGHBORHOOD_RADIUS;d<=NEIGHBORHOOD_RADIUS;d++){
          if(d===0) continue;
          var nidx=idx+d;
          if(nidx<0 || nidx>=blocks.length) continue;
          var nb=blocks[nidx];
          if(!nb) continue;
          if(String(nb.unit_key||'')!==String(unitKey)) continue;
          if(nb.canonical_locator===cloc) continue;
          var nloc=String(nb.canonical_locator||'');
          if(!nloc) continue;
          var future=false;
          if(ceiling && cmp2){ try{ future=cmp2(nloc, ceiling)>0; }catch(_){ future=false; } }
          if(future) continue;
          neighbors.push({ canonical_locator:nloc, unit_key:nb.unit_key||null, work_key:nb.work_key||workKey, language:'ko', snippet:String(nb.ko||nb.text||''), text:String(nb.ko||nb.en||''), sequence:(nb.sequence!=null?Number(nb.sequence):null), score:(cand.score!=null?cand.score-0.001:null) });
        }
      }
    }
    var entry={
      source_kind: String(cand.source_kind||'keyword'),
      canonical_locator: cloc,
      work_key: cand.work_key||workKey,
      unit_key: cand.unit_key||unitKey||null,
      language: cand.language||null,
      snippet: cand.snippet||cand.text||'',
      score: cand.score!=null?cand.score:null
    };
    var list=[entry].concat(neighbors.slice(0,MAX_NEIGHBORHOOD_PER_CANDIDATE));
    for(var li=0;li<list.length;li++){
      var e=list[li];
      var ek=String(e.canonical_locator||'');
      if(!ek || seen[ek]) continue;
      seen[ek]=true;
      if(li>0) addedNeighbors++;
      expanded.push(e);
    }
  }
  return expanded;
}
if(typeof window!=='undefined'){
  window.storyMemoryRetrieveForPreviewV1=retrieveForPreview;
  window.storyMemoryRequestRetrievalPreviewV1=requestRetrievalPreview;
  window.storyMemoryEnsureGroundingBlocksV1=storyMemoryEnsureGroundingBlocksV1;
  window.storyMemorySeedGroundingBlocksV1=storyMemorySeedGroundingBlocksV1;
  window.storyMemoryGroundingBlocksV1=storyMemoryGroundingBlocksV1;
  window.storyMemoryInCeilingTermIndexV1=storyMemoryInCeilingTermIndexV1;
  window.storyMemoryProjectPriorGroundingV1=storyMemoryProjectPriorGroundingV1;
  window.__smRetrievalAdapterV1={retrieveForPreview:retrieveForPreview, requestRetrievalPreview:requestRetrievalPreview, ensureGroundingBlocks:storyMemoryEnsureGroundingBlocksV1, seedGroundingBlocks:storyMemorySeedGroundingBlocksV1, groundingBlocks:storyMemoryGroundingBlocksV1, inCeilingTermIndex:storyMemoryInCeilingTermIndexV1, projectPriorGrounding:storyMemoryProjectPriorGroundingV1, RECALL_LIMIT:RECALL_LIMIT, PROJECTION_LIMIT:PROJECTION_LIMIT};
}
if(typeof module!=='undefined' && module.exports){
  module.exports={retrieveForPreview:retrieveForPreview, requestRetrievalPreview:requestRetrievalPreview, ensureGroundingBlocks:storyMemoryEnsureGroundingBlocksV1, seedGroundingBlocks:storyMemorySeedGroundingBlocksV1, groundingBlocks:storyMemoryGroundingBlocksV1, inCeilingTermIndex:storyMemoryInCeilingTermIndexV1, projectPriorGrounding:storyMemoryProjectPriorGroundingV1, loadInCeilingBlocksForWork:loadInCeilingBlocksForWork, RECALL_LIMIT:RECALL_LIMIT, PROJECTION_LIMIT:PROJECTION_LIMIT};
}
})();
