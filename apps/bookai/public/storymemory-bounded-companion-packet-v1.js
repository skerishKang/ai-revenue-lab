/* ===== B61 #1305 Slice B · Bounded Companion Packet — deterministic ceiling-aware composition ===== */
(function(){
'use strict';
var SPOILER_POLICY='hard_no_future';
function buildBoundedCompanionPacketV1(opts){
  opts=opts||{};
  var rc=window.storyMemoryGetReaderContextV1?window.storyMemoryGetReaderContextV1():null;
  var wk=rc?rc.current_work_key:null;
  var auth=rc?!!rc.authoritative_reader:false;
  var progress=wk&&window.storyMemoryGetReadingProgressV1?window.storyMemoryGetReadingProgressV1(wk):null;
  var ceiling=progress?progress.knowledge_ceiling_locator:null;
  var boundary_available=!!ceiling;
  var cmp=window.storyMemoryCompareLocatorV1?window.storyMemoryCompareLocatorV1:function(){return 0;};
  /* B61 #1515 · retrieval override seam (bounded, validated, fail-closed).
     When the retrieval adapter supplies projection-eligible passages, use ONLY
     those after re-validating each against the trusted ceiling. DOM-derived
     passages are NOT merged in this mode. Absent override → legacy DOM path. */
  var retrievalOverride=(opts && Array.isArray(opts.sourcePassagesOverride))? opts.sourcePassagesOverride : null;
  var retrievalMode=retrievalOverride!==null;
  var retrievalOverrideAllowed=[];
  var retrievalOverrideFiltered=0;
  if(retrievalMode){
    if(!boundary_available) throw new Error('boundary_unavailable');
    var ovIsCompat=window.storyMemoryIsLocatorCompatibleWithWorkV1||function(){return true;};
    var ovFamOf=window.storyMemoryLocatorWorkFamilyV1||function(){return null;};
    for(var ovi=0;ovi<retrievalOverride.length;ovi++){
      var ovp=retrievalOverride[ovi]||{};
      var ovloc=ovp.canonical_locator||ovp.canonicalLocator||ovp.locator||'';
      if(!ovloc){retrievalOverrideFiltered++;continue;}
      if(!ovIsCompat(ovloc,wk)){retrievalOverrideFiltered++;continue;}
      if(ceiling && ovFamOf(ovloc)!==ovFamOf(ceiling)){retrievalOverrideFiltered++;continue;}
      if(ceiling && cmp(ovloc,ceiling)>0){retrievalOverrideFiltered++;continue;}
      retrievalOverrideAllowed.push({canonical_locator:ovloc, sequence:(Number.isFinite(Number(ovp.sequence))?Number(ovp.sequence):null), text:String(ovp.text||ovp.ko||ovp.en||'').slice(0,2000), language:ovp.language||null});
    }
    if(!retrievalOverrideAllowed.length) throw new Error('retrieval_override_empty');
  }
  var rawPassages=[];
  if(!retrievalMode && window.storyMemoryBuildAIContextPacketV1){
    var base=window.storyMemoryBuildAIContextPacketV1();
    rawPassages=base.source_passages||[];
  }
  var allowedPassages=retrievalMode? retrievalOverrideAllowed : [];
  var filteredFutureSourceCount=0;
  var filteredNoLocatorSourceCount=0;
  var isCompat=window.storyMemoryIsLocatorCompatibleWithWorkV1||function(){return true;};
  var famOf=window.storyMemoryLocatorWorkFamilyV1||function(){return null;};
  for(var i=0;i<rawPassages.length;i++){
    var p=rawPassages[i];
    var loc=p&&(p.canonical_locator||p.canonicalLocator||p.locator||'');
    if(!loc){filteredNoLocatorSourceCount++;continue;}
    if(!boundary_available){filteredFutureSourceCount++;continue;}
    if(!isCompat(loc,wk)){filteredFutureSourceCount++;continue;}
    if(ceiling && famOf(loc)!==famOf(ceiling)){filteredFutureSourceCount++;continue;}
    if(cmp(loc,ceiling)<=0){allowedPassages.push(p);}
    else{filteredFutureSourceCount++;}
  }
  /* B61 #1804 · prior-page model-visible grounding. For the live companion path
     (no retrieval override), consult the deterministic in-ceiling corpus
     projection and MERGE eligible already-read candidates into the model-visible
     source passages (current page first, deduped, bounded to the worker's
     MAX_ENGINE_CONTEXT of 8 refs). The co-reader relevance gate then scores the
     merged evidence so ALLOW is grounded in refs the model can actually see. */
  var MAX_GROUNDING_REFS=8;
  var groundingEligible=0;
  var groundingMerged=0;
  if(!retrievalMode && opts.query && window.storyMemoryProjectPriorGroundingV1){
    try{
      var priorCandidates=window.storyMemoryProjectPriorGroundingV1(String(opts.query), wk);
      if(Array.isArray(priorCandidates) && priorCandidates.length){
        groundingEligible=priorCandidates.length;
        var have={};
        for(var mi=0;mi<allowedPassages.length;mi++){
          var ml=allowedPassages[mi]&&(allowedPassages[mi].canonical_locator||allowedPassages[mi].canonicalLocator||allowedPassages[mi].locator||'');
          if(ml) have[ml]=true;
        }
        for(var pi=0; pi<priorCandidates.length && allowedPassages.length<MAX_GROUNDING_REFS; pi++){
          var pc=priorCandidates[pi];
          var ploc=pc&&(pc.canonical_locator||pc.canonicalLocator||pc.locator||'');
          if(!ploc || have[ploc]) continue;
          have[ploc]=true;
          allowedPassages.push({
            canonical_locator:ploc,
            sequence:Number.isFinite(Number(pc.sequence))?Number(pc.sequence):null,
            text:String(pc.snippet||pc.text||pc.ko||pc.en||'').slice(0,2000),
            language:pc.language||null
          });
          groundingMerged++;
        }
      }
    }catch(_){}
  }
  var rawAnnotations=[];
  try{
    if(window.__smAnnotationLayerV1 && typeof window.__smAnnotationLayerV1.list==='function'){
      rawAnnotations=window.__smAnnotationLayerV1.list()||[];
    }else{
      var v=BookAIStorage.getItem('storymemory.annotations.v1');
      if(v){var p=JSON.parse(v); if(p&&p.version===1&&Array.isArray(p.items)) rawAnnotations=p.items;}
    }
  }catch(_){rawAnnotations=[];}
  var currentUnitKey=rc?rc.current_unit_key:null;
  function unitOfAnn(loc){ try{ var p=String(loc).split(':'); return p[0]==='bible'? p.slice(0,4).join(':') : p.slice(0,3).join(':'); }catch(_){ return null; } }
  var allowedAnnotations=[];
  var filteredFutureAnnCount=0;
  var filteredNoLocatorAnnCount=0;
  var filteredWrongUnitAnnCount=0;
  for(var j=0;j<rawAnnotations.length;j++){
    var a=rawAnnotations[j];
    if(!a||typeof a!=='object')continue;
    if(!['highlight','underline','memo','bookmark'].includes(a.kind))continue;
    var aloc=a.locator||a.canonical_locator||'';
    if(!aloc){filteredNoLocatorAnnCount++;continue;}
    if(!isCompat(aloc,wk)){filteredWrongUnitAnnCount++;continue;}
    if(ceiling && famOf(aloc)!==famOf(ceiling)){filteredWrongUnitAnnCount++;continue;}
    var derivedUnit=null; try{ derivedUnit=unitOfAnn(aloc); }catch(_){}
    if(currentUnitKey && derivedUnit && derivedUnit!==currentUnitKey){filteredWrongUnitAnnCount++;continue;}
    if(!boundary_available){filteredFutureAnnCount++;continue;}
    if(cmp(aloc,ceiling)<=0){
      allowedAnnotations.push({id:String(a.id||''),kind:String(a.kind),locator:String(aloc),unit:String(a.unit||derivedUnit||''),text:String(a.text||'').slice(0,2000),color:a.color?String(a.color):null,note:a.note?String(a.note).slice(0,2000):null,createdAt:Number.isFinite(Number(a.createdAt))?Number(a.createdAt):null});
    }
    else{filteredFutureAnnCount++;}
  }
  allowedAnnotations.sort(function(a,b){var c=String(a.locator).localeCompare(String(b.locator));return c!==0?c:String(a.id).localeCompare(String(b.id));});
  var selected_included=false;
  var selected_reasons=[];
  var selectedOverride=opts.selectedOverride&&typeof opts.selectedOverride==='object'?opts.selectedOverride:null;
  var selLoc=selectedOverride?String(selectedOverride.locator||selectedOverride.canonical_locator||'')||null:(rc?rc.selected_locator:null);
  var selText=selectedOverride?String(selectedOverride.text||selectedOverride.quote||'').slice(0,2000):(rc?rc.selected_text:null);
  if(!auth){
    selected_reasons.push('non_authoritative_reader');
    selLoc=null;selText=null;
  }else if(!boundary_available){
    selected_reasons.push('boundary_unavailable');
    selLoc=null;selText=null;
  }else if(!selLoc){
    if(selText){selected_reasons.push('no_selected_locator');}
    selText=null;
  }else if(!isCompat(selLoc,wk) || (ceiling && famOf(selLoc)!==famOf(ceiling))){
    selected_reasons.push('selected_incompatible_work');
    selLoc=null;selText=null;
  }else if(cmp(selLoc,ceiling)>0){
    selected_reasons.push('selected_beyond_ceiling');
    selLoc=null;selText=null;
  }else{
    selected_included=true;
  }
  var coReader=null;
  if(window.storyMemoryCoReaderDecisionV1){
    /* B61 #1724 · thread permitted evidence CONTENT (not just a count) so the
       co-reader can score relevance. In-ceiling passages + annotations only. */
    var evidenceContent=[];
    for(var epi=0;epi<allowedPassages.length;epi++){
      var ep=allowedPassages[epi]||{};
      evidenceContent.push({text:String(ep.text||ep.ko||ep.en||''), snippet:''});
    }
    for(var eai=0;eai<allowedAnnotations.length;eai++){
      var ea=allowedAnnotations[eai]||{};
      evidenceContent.push({text:String(ea.text||ea.note||''), snippet:''});
    }
    coReader=window.storyMemoryCoReaderDecisionV1(opts.query||'',opts.targetLocator||selLoc||null,wk,evidenceContent);
  }else{
    coReader={decision:boundary_available?'ALLOW':'BLOCK',reason:boundary_available?'WITHIN_CEILING':'BOUNDARY_UNAVAILABLE',ceiling:ceiling||null};
  }
  var selected_packet=null;
  if(selected_included&&selLoc){
    selected_packet={selected_locator:selLoc,selected_text:(selText||'').slice(0,2000)||null};
  }
  var diagnostics={
    boundary_available:boundary_available,
    spoiler_policy:SPOILER_POLICY,
    retrieval_mode:retrievalMode,
    override_received:retrievalMode?retrievalOverride.length:0,
    override_allowed:retrievalOverrideAllowed.length,
    override_filtered:retrievalOverrideFiltered,
    allowed_source_count:allowedPassages.length,
    filtered_future_source_count:filteredFutureSourceCount,
    filtered_no_locator_source_count:filteredNoLocatorSourceCount,
    allowed_annotation_count:allowedAnnotations.length,
    filtered_future_annotation_count:filteredFutureAnnCount,
    filtered_no_locator_annotation_count:filteredNoLocatorAnnCount,
    filtered_wrong_unit_annotation_count:filteredWrongUnitAnnCount,
    selected_included:selected_included,
    selected_reasons:selected_reasons,
    grounding_eligible_count:groundingEligible,
    grounding_merged_count:groundingMerged
  };
  var packet={
    version:'1',
    mode:'storymemory_bounded_companion',
    source_scope:'ceiling_filtered',
    reader_context:rc,
    reading_progress:progress?{furthest_read_locator:progress.furthest_read_locator,knowledge_ceiling_locator:progress.knowledge_ceiling_locator,updatedAt:progress.updatedAt}:null,
    annotation_context:{version:'1',work_key:wk,unit_key:currentUnitKey,annotations:allowedAnnotations,count:allowedAnnotations.length},
    source_passages:allowedPassages,
    selected:selected_packet,
    diagnostics:diagnostics,
    co_reader_decision:coReader
  };
  return packet;
}
window.storyMemoryBuildBoundedCompanionPacketV1=buildBoundedCompanionPacketV1;
window.__smBoundedCompanionPacketV1={SPOILER_POLICY:SPOILER_POLICY};
})();
