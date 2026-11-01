/* ===== B61 #1493 · Retrieval Candidate + Knowledge Ceiling Projection v1 ===== */
(function(){
'use strict';

function getLocatorProgress(){
  if(typeof window!=='undefined' && window.__smLocatorProgressR1V1) return window.__smLocatorProgressR1V1;
  if(typeof globalThis!=='undefined' && globalThis.__smLocatorProgressR1V1) return globalThis.__smLocatorProgressR1V1;
  if(typeof global!=='undefined' && global.__smLocatorProgressR1V1) return global.__smLocatorProgressR1V1;
  if(typeof require!=='undefined'){
    try{
      if(typeof global!=='undefined' && typeof global.window==='undefined') global.window = global;
      if(typeof global!=='undefined' && typeof global.globalThis==='undefined') global.globalThis = global;
      // Attempt to load the accepted module (IIFE sets window.__smLocatorProgressR1V1)
      try{ require('./storymemory-locator-progress-v1.js'); }catch(e){ try{ require(require('path').join(__dirname,'storymemory-locator-progress-v1.js')); }catch(_){} }
      if(typeof window!=='undefined' && window.__smLocatorProgressR1V1) return window.__smLocatorProgressR1V1;
      if(typeof globalThis!=='undefined' && globalThis.__smLocatorProgressR1V1) return globalThis.__smLocatorProgressR1V1;
      if(typeof global!=='undefined' && global.__smLocatorProgressR1V1) return global.__smLocatorProgressR1V1;
    }catch(e){}
  }
  return null;
}

function requireLocatorProgress(){
  var R1=getLocatorProgress();
  if(!R1) throw new Error('LOCATOR_PROGRESS_UNAVAILABLE');
  if(!R1.compareLocators || !R1.locatorWorkFamily || !R1.isLocatorCompatibleWithWork) throw new Error('LOCATOR_PROGRESS_INCOMPLETE');
  return R1;
}

function isFutureLocator(locator, ceiling, workKey){
  var R1=requireLocatorProgress();
  if(!locator || !ceiling) return false;
  if(!R1.isLocatorCompatibleWithWork(locator, workKey)) return true;
  if(R1.locatorWorkFamily(locator)!==R1.locatorWorkFamily(ceiling)) return true;
  return R1.compareLocators(locator, ceiling)>0;
}

function buildProjection(options){
  var R1=requireLocatorProgress();
  var compareLocators=R1.compareLocators;
  var locatorWorkFamily=R1.locatorWorkFamily;
  var isLocatorCompatibleWithWork=R1.isLocatorCompatibleWithWork;

  options=options||{};
  var query=String(options.query||'');
  var workKey=options.workKey||null;
  var knowledgeCeilingLocator=options.knowledgeCeilingLocator||null;
  var furthestReadLocator=options.furthestReadLocator||knowledgeCeilingLocator;
  var spoilerPolicy=options.spoilerPolicy||'HARD_NO_FUTURE';
  var policyVersion=options.policyVersion||'storymemory-b61-ceiling:v1';
  var keywordCandidates=Array.isArray(options.keywordCandidates)? options.keywordCandidates.slice(): [];
  var annotationCandidates=Array.isArray(options.annotationCandidates)? options.annotationCandidates.slice(): [];
  var limit=options.limit!=null? Number(options.limit): 8;
  var maxBytes=options.maxBytes!=null? Number(options.maxBytes): 7000;
  limit=Math.max(1, Math.min(32, limit));
  maxBytes=Math.max(512, Math.min(20000, maxBytes));

  var candidateCount = keywordCandidates.length + annotationCandidates.length;
  var futureFilteredCount=0;
  var duplicateFilteredCount=0;
  var workMismatchCount=0;
  var eligibleKeyword=[];
  var eligibleAnnotation=[];

  var missingRequiredCeiling=false;
  if(workKey && !knowledgeCeilingLocator){
    missingRequiredCeiling=true;
  }

  for(var i=0;i<keywordCandidates.length;i++){
    var kc=keywordCandidates[i];
    var loc=kc.canonical_locator||kc.canonicalLocator||kc.locator||'';
    var candWork=String(kc.work_key||kc.workKey||'');
    /* B61 #1897 · FIX B · early foreign-work rejection. A keyword candidate
       from another work family is unusable in this work's packet and is
       rejected HERE, at projection, instead of surviving into
       buildBoundedCompanionPacketV1 and being dropped by the late family guard.
       The packet guard is retained as defense in depth. */
    if(workKey && candWork && candWork!==String(workKey)){
      workMismatchCount++;
      continue;
    }
    if(missingRequiredCeiling){
      futureFilteredCount++;
      continue;
    }
    if(!knowledgeCeilingLocator){
      futureFilteredCount++;
      continue;
    }
    var isFuture=false;
    try{ isFuture=isFutureLocator(loc, knowledgeCeilingLocator, workKey); }catch(e){ isFuture=true; }
    if(isFuture){
      futureFilteredCount++;
      continue;
    }
    eligibleKeyword.push(kc);
  }

  for(var j=0;j<annotationCandidates.length;j++){
    var ac=annotationCandidates[j];
    var aloc=ac.canonical_locator||ac.canonicalLocator||ac.locator||'';
    var aWork=String(ac.work_key||ac.workKey||'');
    /* B61 #1897 · FIX B · early foreign-work rejection for annotations too. */
    if(workKey && aWork && aWork!==String(workKey)){
      workMismatchCount++;
      continue;
    }
    if(missingRequiredCeiling){
      futureFilteredCount++;
      continue;
    }
    if(!knowledgeCeilingLocator){
      futureFilteredCount++;
      continue;
    }
    var isFuture2=false;
    try{ isFuture2=isFutureLocator(aloc, knowledgeCeilingLocator, workKey); }catch(e){ isFuture2=true; }
    if(isFuture2){
      futureFilteredCount++;
      continue;
    }
    eligibleAnnotation.push(ac);
  }

  var boundedKeyword = eligibleKeyword.slice(0, limit);
  var boundedAnnotation = eligibleAnnotation.slice(0, limit);

  var seen=new Map();
  var deduped=[];
  var allForDedup = boundedKeyword.concat(boundedAnnotation);
  for(var k=0;k<allForDedup.length;k++){
    var cand=allForDedup[k];
    var key=(String(cand.source_kind||cand._source||'unknown')+'|'+String(cand.canonical_locator||cand.canonicalLocator||cand.locator||'')+'|'+String(cand.client_record_id||cand.clientRecordId||cand.id||''));
    if(!seen.has(key)){
      seen.set(key, true);
      deduped.push(cand);
    } else {
      duplicateFilteredCount++;
    }
  }

  var projectionCandidates = deduped.slice(0, limit);

  var totalBytes=0;
  var boundedByBytes=[];
  for(var b=0;b<projectionCandidates.length;b++){
    var c=projectionCandidates[b];
    var s=JSON.stringify(c);
    if(totalBytes + s.length > maxBytes) break;
    totalBytes+=s.length;
    boundedByBytes.push(c);
  }
  var boundedCandidates = boundedByBytes;
  var boundedBytes = totalBytes<=maxBytes;

  var diagnostics={
    candidate_count: candidateCount,
    eligible_count: eligibleKeyword.length + eligibleAnnotation.length,
    future_filtered_count: futureFilteredCount,
    work_mismatch_count: workMismatchCount,
    duplicate_filtered_count: duplicateFilteredCount,
    projection_count: boundedCandidates.length,
    reason_codes: [],
    policy_version: policyVersion
  };
  if(missingRequiredCeiling) diagnostics.reason_codes.push('MISSING_REQUIRED_CEILING');
  if(futureFilteredCount>0) diagnostics.reason_codes.push('FUTURE_FILTERED');
  if(workMismatchCount>0) diagnostics.reason_codes.push('WORK_MISMATCH');
  if(duplicateFilteredCount>0) diagnostics.reason_codes.push('DUPLICATE_FILTERED');
  if(diagnostics.eligible_count===0 && candidateCount>0) diagnostics.reason_codes.push('ALL_FILTERED');

  var projection={
    version: '1',
    workKey: workKey,
    knowledge_ceiling_locator: knowledgeCeilingLocator,
    furthest_read_locator: furthestReadLocator,
    spoiler_policy: spoilerPolicy,
    policy_version: policyVersion,
    candidates: boundedCandidates.map(function(c){
      return {
        source_kind: String(c.source_kind||c._source||'unknown'),
        canonical_locator: c.canonical_locator||c.canonicalLocator||c.locator||'',
        work_key: c.work_key||c.workKey||workKey,
        unit_key: c.unit_key||c.unitKey||null,
        language: c.language||null,
        snippet: c.snippet||c.text||'',
        score: c.score!=null? c.score : undefined,
        client_record_id: c.client_record_id||c.clientRecordId||null,
        kind: c.kind||null,
        subtype: c.subtype||null,
        resource_ref: c.canonical_locator||c.canonicalLocator||c.locator||'',
        mapping_type: c.mapping_type||null,
        mapping_note: c.mapping_note||null,
        raw_locator: c.raw_locator||null,
        raw_texts: c.raw_texts||null
      };
    }),
    diagnostics: diagnostics,
    bounded: boundedCandidates.length<=limit && boundedBytes,
    bytes: totalBytes,
    missing_required_ceiling: missingRequiredCeiling
  };

  return projection;
}

function isMissingRequiredCeiling(workKey, knowledgeCeilingLocator){
  return !!(workKey && !knowledgeCeilingLocator);
}

if(typeof window!=='undefined'){
  window.__smRetrievalCeilingProjectionV1={
    buildProjection: buildProjection,
    isFutureLocator: isFutureLocator,
    isMissingRequiredCeiling: isMissingRequiredCeiling
  };
}
if(typeof module!=='undefined' && module.exports){
  module.exports={
    buildProjection: buildProjection,
    isFutureLocator: isFutureLocator,
    isMissingRequiredCeiling: isMissingRequiredCeiling
  };
}
})();
