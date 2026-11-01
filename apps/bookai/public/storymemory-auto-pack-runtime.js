(function(root,factory){
  const api=factory(root||globalThis);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){
    root.STORYMEMORY_AUTO_PACK_CONTRACT=api.STORYMEMORY_AUTO_PACK_CONTRACT;
    root.createStoryMemoryAutoPackRuntime=api.createStoryMemoryAutoPackRuntime;
    root.createStoryMemoryNeonAutoPackRegistryWriter=api.createStoryMemoryNeonAutoPackRegistryWriter;
    root.storyMemoryAutoPack=root.storyMemoryAutoPack||api.createStoryMemoryAutoPackRuntime({
      universalRuntime:root.storyMemoryUniversalSource||null,
      marketplaceRuntime:root.storyMemoryPackMarketplace||null,
      storage:root.localStorage||null
    });
    root.installStoryMemoryAutoPackGeneratorProvider=fn=>root.storyMemoryAutoPack?.setGeneratorProvider(fn);
    if(root.document?.documentElement)root.document.documentElement.dataset.storymemoryAutoPack='v1.0.0';
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';

  const CONTRACT=Object.freeze({
    schema:'storymemory-auto-pack-generation-1.0',version:'1.0.0',packSchema:'storymemory-precision-pack-1.0',
    generationModes:['quick','deep'],defaultVisibility:'private',defaultTrustTier:'auto-generated',
    maxEvidenceBlocks:8,maxEvidenceChars:7000,maxAliasRows:16,maxHintsPerRow:8,maxKnowledgeRows:24,
    hardPolicyKeys:['trustMode','revealAnswers','allowFuture','citationRequired','strictUnknown','spoilerBoundary','workbookReveal'],
    publicAutoPublish:false,sourceBodyInGeneratedPack:false,paidProcessingImplemented:false
  });
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const lower=v=>String(v??'').trim().toLowerCase();
  const nowIso=()=>new Date().toISOString();
  const uniq=a=>[...new Set((a||[]).map(x=>String(x||'').trim()).filter(Boolean))];
  const clip=(v,n=500)=>{const s=String(v??'').replace(/\s+/g,' ').trim();return s.length>n?s.slice(0,n-1)+'…':s};
  const hashString=value=>{let h=0x811c9dc5;const s=String(value??'');for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,0x01000193)>>>0}return h.toString(16).padStart(8,'0')};
  const safeId=v=>String(v||'source').toLowerCase().replace(/[^a-z0-9._:-]+/g,'-').replace(/^-+|-+$/g,'').slice(0,80)||'source';
  const scoreOf=r=>Number(r?.score||0)||0;
  const sourceLocatorScheme=s=>String(s?.metadata?.locatorScheme||s?.metadata?.locator_scheme||s?.structure?.kind||s?.sourceType||'').toLowerCase();

  function packArtifactFingerprint(pack){
    const body={schema:pack?.schema||CONTRACT.packSchema,id:pack?.id||pack?.packId||'',version:pack?.version||'0.0.0',kind:pack?.kind||'companion',compatibility:pack?.compatibility||{},payload:pack?.payload||{},metadata:pack?.metadata||{}};
    return `fnv1a:${hashString(JSON.stringify(body))}`;
  }
  function containsForbiddenSourceBody(value,path='root'){
    if(value==null)return null;
    if(Array.isArray(value)){for(let i=0;i<value.length;i++){const hit=containsForbiddenSourceBody(value[i],`${path}[${i}]`);if(hit)return hit}return null}
    if(typeof value!=='object')return null;
    for(const [k,v] of Object.entries(value)){
      const key=lower(k).replace(/[_-]/g,'');
      if(['sourcetext','fulltext','rawtext','sourcebody','fullsource','documentbody','transcriptbody','verbatimtext'].includes(key))return `${path}.${k}`;
      const hit=containsForbiddenSourceBody(v,`${path}.${k}`);if(hit)return hit;
    }
    return null;
  }
  function normalizeAliases(rows=[]){
    const out=[];
    for(const row of Array.isArray(rows)?rows:[]){
      const from=clip(row?.from||row?.alias||'',120);const to=uniq(Array.isArray(row?.to)?row.to:Array.isArray(row?.targets)?row.targets:[row?.to]).map(x=>clip(x,120)).slice(0,CONTRACT.maxHintsPerRow);
      if(from&&to.length)out.push({from,to,metadata:{...(row?.metadata||{})}});
      if(out.length>=CONTRACT.maxAliasRows)break;
    }
    return out;
  }
  function normalizeSearchHints(rows=[]){
    const out=[];
    for(const row of Array.isArray(rows)?rows:[]){
      if(typeof row==='string')continue;
      const when=clip(row?.when||row?.query||'',180);const hints=uniq(row?.hints||[]).map(x=>clip(x,120)).slice(0,CONTRACT.maxHintsPerRow);
      if(when&&hints.length)out.push({when,hints});
      if(out.length>=CONTRACT.maxAliasRows)break;
    }
    return out;
  }
  function sanitizePolicies(policies={}){
    const allowed={};const blocked=[];
    if(!policies||typeof policies!=='object')return {allowed,blocked};
    for(const [key,val] of Object.entries(policies)){
      if(CONTRACT.hardPolicyKeys.includes(key)){blocked.push(key);continue;}
      if(['answerStyle','citationPreference','terminology','domainInstructions','hintStrategy','retrievalPreference'].includes(key))allowed[key]=clone(val);
    }
    return {allowed,blocked};
  }
  function normalizeKnowledge(rows=[],allowedLocators=new Set()){
    const out=[];
    for(const row of Array.isArray(rows)?rows:[]){
      const refs=uniq([...(row?.sourceRefs||[]),...(row?.evidenceLocators||[]),row?.locator]).filter(x=>allowedLocators.has(x));
      if(!refs.length)continue;
      const summary=clip(row?.summary||row?.label||row?.name||'',500);if(!summary)continue;
      out.push({id:clip(row?.id||row?.key||`knowledge-${out.length+1}`,120),type:clip(row?.type||'knowledge',80),key:clip(row?.key||row?.id||'',120),label:clip(row?.label||row?.name||'',180),aliases:uniq(row?.aliases||[]).map(x=>clip(x,120)).slice(0,12),summary,sourceRefs:refs,metadata:{...(row?.metadata||{})}});
      if(out.length>=CONTRACT.maxKnowledgeRows)break;
    }
    return out;
  }
  function sanitizeProposal(proposal={},mode='quick',allowedLocators=new Set()){
    const forbidden=containsForbiddenSourceBody(proposal);if(forbidden)throw new Error(`AUTO_PACK_SOURCE_BODY_FORBIDDEN:${forbidden}`);
    const aliases=normalizeAliases(proposal.aliases||proposal.payload?.aliases||[]);
    const searchHints=normalizeSearchHints(proposal.searchHints||proposal.payload?.searchHints||[]);
    const {allowed:policies,blocked:blockedPolicyKeys}=sanitizePolicies(proposal.policies||proposal.payload?.policies||{});
    const knowledge=mode==='deep'?normalizeKnowledge(proposal.knowledge||proposal.payload?.knowledge||[],allowedLocators):[];
    if(!aliases.length&&!searchHints.length&&!knowledge.length&&!Object.keys(policies).length)throw new Error('AUTO_PACK_EMPTY_SAFE_PROPOSAL');
    return {name:clip(proposal.name||'',180),aliases,searchHints,knowledge,policies,blockedPolicyKeys};
  }
  function qualityMetrics(retrieval,expectedLocator=null){
    const relevant=Array.isArray(retrieval?.relevantEvidence)?retrieval.relevantEvidence:[];
    return {relevantCount:relevant.length,topScore:relevant.reduce((m,x)=>Math.max(m,scoreOf(x)),0),expectedLocator:expectedLocator||null,expectedLocatorHit:expectedLocator?relevant.some(x=>x.locator===expectedLocator):null,locators:relevant.map(x=>x.locator),packQueryHintsUsed:Boolean(retrieval?.policy?.packQueryHintsUsed)};
  }
  function improvement(before,after){
    const exactGain=before.expectedLocatorHit===false&&after.expectedLocatorHit===true;
    const relevanceGain=after.relevantCount>before.relevantCount;
    const scoreGain=after.topScore>=before.topScore+2;
    return {improved:Boolean(exactGain||relevanceGain||scoreGain),exactGain,relevanceGain,scoreGain,deltaRelevant:after.relevantCount-before.relevantCount,deltaTopScore:after.topScore-before.topScore};
  }

  function createArtifactStore(storage,key='storymemory.autoPacks.v1'){
    const mem=[];
    const read=()=>{if(!storage)return mem.slice();try{const v=JSON.parse(storage.getItem(key)||'[]');return Array.isArray(v)?v:[]}catch(_){return []}};
    const write=rows=>{if(storage){try{storage.setItem(key,JSON.stringify(rows))}catch(_){}}else{mem.splice(0,mem.length,...rows)}return rows};
    return {list:()=>clone(read()),get:id=>clone(read().find(x=>x.pack?.id===id)||null),save:record=>{const rows=read();const i=rows.findIndex(x=>x.pack?.id===record.pack?.id);if(i>=0)rows[i]=clone(record);else rows.unshift(clone(record));write(rows.slice(0,50));return clone(record)},remove:id=>{const rows=read().filter(x=>x.pack?.id!==id);write(rows);return true}};
  }

  function createStoryMemoryNeonAutoPackRegistryWriter({remoteAdapter,getUserId}={}){
    if(!remoteAdapter||typeof remoteAdapter.request!=='function')throw new Error('STORYMEMORY_REMOTE_ADAPTER_REQUIRED');
    const uid=async()=>{const v=typeof getUserId==='function'?await getUserId():getUserId;if(!v)throw new Error('AUTO_PACK_REGISTRY_USER_ID_REQUIRED');return String(v)};
    return Object.freeze({
      async saveDraft({listing,version}){
        const userId=await uid();if(!listing||!version)throw new Error('AUTO_PACK_DRAFT_METADATA_REQUIRED');
        if(listing.visibility!=='private'||listing.publicationStatus!=='draft')throw new Error('AUTO_PACK_DRAFT_MUST_BE_PRIVATE');
        if(!version.artifactUri)throw new Error('AUTO_PACK_DURABLE_ARTIFACT_URI_REQUIRED');
        if(listing.sourceTextIncluded===true)throw new Error('AUTO_PACK_SOURCE_BODY_FORBIDDEN');
        const reg={pack_id:listing.packId,name:listing.name,pack_type:listing.packType,creator_id:userId,publisher_name:listing.publisherName||'',summary:listing.summary||'',visibility:'private',pricing_mode:'free',publication_status:'draft',latest_version:version.version,source_text_included:false,rights_declaration:listing.rightsDeclaration||{},compatibility_summary:listing.compatibilitySummary||{},permissions:listing.permissions||{},processing_disclosure:listing.processingDisclosure||{},listing_metadata:listing.listingMetadata||{}};
        const ver={pack_id:listing.packId,version:version.version,schema_version:CONTRACT.packSchema,artifact_uri:version.artifactUri,artifact_fingerprint:version.artifactFingerprint,declared_trust_tier:'auto-generated',source_match_mode:version.sourceMatchMode||'exact-fingerprint',compatibility:version.compatibility||{},rights:version.rights||{},changelog:version.changelog||'Auto-generated private draft',parent_version:null};
        await remoteAdapter.request('pack_registry',{method:'POST',query:{on_conflict:'pack_id'},body:reg,prefer:'resolution=merge-duplicates,return=minimal'});
        await remoteAdapter.request('pack_versions',{method:'POST',query:{on_conflict:'pack_id,version'},body:ver,prefer:'resolution=merge-duplicates,return=minimal'});
        return {packId:listing.packId,version:version.version,visibility:'private',publicationStatus:'draft',payloadStoredInDb:false};
      }
    });
  }

  function createStoryMemoryAutoPackRuntime({universalRuntime=null,marketplaceRuntime=null,storage=null,generatorProvider=null,registryWriter=null,clock=nowIso}={}){
    let rt=universalRuntime||root.storyMemoryUniversalSource||null;
    let market=marketplaceRuntime||root.storyMemoryPackMarketplace||null;
    let provider=typeof generatorProvider==='function'?generatorProvider:null;
    let writer=registryWriter&&typeof registryWriter.saveDraft==='function'?registryWriter:null;
    const artifacts=createArtifactStore(storage);const signals=[];const listeners=new Set();
    const emit=(type,payload={})=>{const e={type,at:clock(),...clone(payload)};for(const fn of listeners){try{fn(e)}catch(_){}}return e};
    const ensureRt=()=>{if(!rt)throw new Error('UNIVERSAL_RUNTIME_REQUIRED');return rt};
    function setUniversalRuntime(v){rt=v||null;return Boolean(rt)}
    function setMarketplaceRuntime(v){market=v||null;return Boolean(market)}
    function setGeneratorProvider(fn){provider=typeof fn==='function'?fn:null;return Boolean(provider)}
    function setRegistryWriter(v){writer=v&&typeof v.saveDraft==='function'?v:null;return Boolean(writer)}
    function onChange(fn){if(typeof fn==='function')listeners.add(fn);return()=>listeners.delete(fn)}
    function recordSignal(signal={}){const row={sourceId:String(signal.sourceId||''),question:clip(signal.question||'',800),kind:lower(signal.kind||'correction'),at:signal.at||clock(),details:clone(signal.details||{})};signals.unshift(row);if(signals.length>200)signals.length=200;emit('PRECISION_SIGNAL',row);return clone(row)}
    function evaluateNeed({sourceId,question='',explicitRequest=false,retrieval=null,trustMode=null,sameNameCollision=false,citationInsufficient=false}={}){
      const reasons=[];if(explicitRequest)reasons.push('EXPLICIT_USER_REQUEST');
      const recent=signals.filter(x=>x.sourceId===String(sourceId)&&(!question||x.question===String(question))).slice(0,20);
      const corrections=recent.filter(x=>['correction','wrong-answer','retrieval-failure'].includes(x.kind)).length;
      if(corrections>=2)reasons.push('REPEATED_CORRECTION');
      if(retrieval&&(!Array.isArray(retrieval.relevantEvidence)||retrieval.relevantEvidence.length===0))reasons.push('LOW_RETRIEVAL_CONFIDENCE');
      if(sameNameCollision)reasons.push('SAME_NAME_COLLISION');if(citationInsufficient)reasons.push('CITATION_INSUFFICIENCY');
      if(String(trustMode||'').toUpperCase()==='STRICT')reasons.push('STRICT_HIGH_ACCURACY_NEED');
      return {needed:reasons.length>0,reasons:uniq(reasons),recentSignals:recent.length,correctionCount:corrections};
    }
    async function analyzeBaseline({sourceId,question,locator=null,expectedLocator=null,trustMode=null}={}){
      const runtime=ensureRt();const retrieval=await runtime.retrieve({sourceId,query:String(question||''),locator,trustMode});return {retrieval,metrics:qualityMetrics(retrieval,expectedLocator)};
    }
    function boundedGenerationRequest({source,question,mode,baseline,need,failureSignals=[],confirmedAliases=[],queryHints=[]}={}){
      const rows=(baseline?.retrieval?.evidence||[]).slice(0,CONTRACT.maxEvidenceBlocks);let chars=0;const evidence=[];
      for(const r of rows){const text=clip(r.text||'',650);if(evidence.length&&chars+text.length>CONTRACT.maxEvidenceChars)continue;chars+=text.length;evidence.push({locator:r.locator,ordinal:r.ordinal,title:clip(r.title||'',180),text,score:scoreOf(r),relevant:Boolean(r.relevant),metadata:{unitKey:r.metadata?.unitKey||null,unitOrdinal:r.metadata?.unitOrdinal||null,sequence:r.metadata?.sequence??null}})}
      return {schema:CONTRACT.schema,operation:'GENERATE_PRIVATE_AUTO_PACK',mode,question:clip(question,900),source:{sourceId:source.sourceId,sourceType:source.sourceType,title:source.title,revision:source.revision,fingerprint:source.fingerprint,language:source.language,locatorScheme:sourceLocatorScheme(source),rightsMode:source.rightsMode,ownerScope:source.ownerScope,trustMode:source.trustMode},failure:{reasons:need.reasons,signals:clone(failureSignals).slice(0,8),baseline:clone(baseline.metrics)},confirmedAliases:clone(confirmedAliases).slice(0,CONTRACT.maxAliasRows),queryHints:uniq(queryHints).slice(0,16),evidence,policy:{fullSourceSent:false,maxEvidenceBlocks:CONTRACT.maxEvidenceBlocks,maxEvidenceChars:CONTRACT.maxEvidenceChars,defaultVisibility:'private',autoPublish:false,sourceBodyAllowed:false,hardTrustRulesOverrideable:false}};
    }
    async function getProposal(request,{confirmedAliases=[],queryHints=[]}={}){
      if(provider){const result=await provider(clone(request));if(!result||typeof result!=='object')throw new Error('AUTO_PACK_GENERATOR_INVALID_RESULT');return result}
      const aliases=normalizeAliases(confirmedAliases);const hints=queryHints.length?[{when:request.question,hints:uniq(queryHints)}]:[];
      if(aliases.length||hints.length)return {name:'Confirmed correction helper',aliases,searchHints:hints,metadata:{fallback:'confirmed-user-correction'}};
      throw new Error('AUTO_PACK_GENERATOR_PROVIDER_REQUIRED');
    }
    function buildPack({source,question,mode,safeProposal,request}={}){
      const seed=JSON.stringify({source:source.fingerprint,question,mode,aliases:safeProposal.aliases,searchHints:safeProposal.searchHints,knowledge:safeProposal.knowledge,policies:safeProposal.policies});
      const id=`pack:auto:${safeId(source.sourceId)}:${hashString(seed)}`;
      const kind=mode==='deep'&&safeProposal.knowledge.length?'companion':Object.keys(safeProposal.policies).length?'companion':'search';
      const pack={schema:CONTRACT.packSchema,id,name:safeProposal.name||`Auto Precision · ${clip(source.title||source.sourceId,70)}`,kind,version:'0.1.0',priority:15,creator:'user:auto',trustTier:'auto-generated',compatibility:{mode:'exact-fingerprint',sourceFingerprint:source.fingerprint,sourceRevision:source.revision,language:source.language,locatorScheme:sourceLocatorScheme(source)},rights:{declaration:'Private derived precision metadata generated from bounded authorized Source analysis; no Source body included',sourceTextIncluded:false,visibility:'private'},payload:{aliases:safeProposal.aliases,searchHints:safeProposal.searchHints,...(safeProposal.knowledge.length?{knowledge:safeProposal.knowledge}:{}),...(Object.keys(safeProposal.policies).length?{policies:safeProposal.policies}:{})},metadata:{generationMode:mode,generatedBy:'storymemory-auto-pack',publicationDefault:'private',autoGenerated:true,marketplaceEligible:false,sourceBodyIncluded:false,processingDisclosure:{boundedSourceAnalysis:true,fullSourceSent:false,evidenceBlocks:request.evidence.length,evidenceChars:request.evidence.reduce((n,x)=>n+x.text.length,0),provider:provider?'external-hook':'confirmed-correction-fallback'},triggerReasons:request.failure.reasons,blockedPolicyKeys:safeProposal.blockedPolicyKeys,questionHash:`fnv1a:${hashString(question)}`}};
      pack.artifactFingerprint=packArtifactFingerprint(pack);return pack;
    }
    function listingForPrivatePack(pack,source,{artifactUri=''}={}){
      return {listing:{packId:pack.id,name:pack.name,packType:pack.kind,creatorId:pack.creator,publisherName:'',summary:`Private auto-generated precision helper for ${source.title||source.sourceId}`,visibility:'private',pricingMode:'free',publicationStatus:'draft',latestVersion:pack.version,sourceTextIncluded:false,rightsDeclaration:{...pack.rights,privateSource:source.ownerScope==='private'},compatibilitySummary:clone(pack.compatibility),permissions:{sourceAccess:'required'},processingDisclosure:clone(pack.metadata?.processingDisclosure||{}),listingMetadata:{autoGenerated:true,sourceBodyIncluded:false}},version:{packId:pack.id,version:pack.version,artifactUri:String(artifactUri||''),artifactFingerprint:pack.artifactFingerprint,declaredTrustTier:'auto-generated',sourceMatchMode:pack.compatibility.mode,compatibility:clone(pack.compatibility),rights:clone(pack.rights),changelog:'Auto-generated private draft'}};
    }
    async function generate(options={}){
      const runtime=ensureRt();const sourceId=String(options.sourceId||runtime.getPosition?.()?.sourceId||'');if(!sourceId)throw new Error('AUTO_PACK_SOURCE_REQUIRED');
      const question=String(options.question||'').trim();if(!question)throw new Error('AUTO_PACK_QUESTION_REQUIRED');
      const source=runtime.getSource(sourceId);if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const mode=lower(options.mode||'quick');if(!CONTRACT.generationModes.includes(mode))throw new Error('AUTO_PACK_MODE_INVALID');if(mode==='deep'&&options.deepConfirmed!==true)throw new Error('AUTO_PACK_DEEP_EXPLICIT_CONFIRMATION_REQUIRED');
      const baseline=await analyzeBaseline({sourceId,question,locator:options.locator||null,expectedLocator:options.expectedLocator||null,trustMode:options.trustMode||null});
      const need=evaluateNeed({sourceId,question,explicitRequest:options.explicitRequest===true,retrieval:baseline.retrieval,trustMode:options.trustMode||source.trustMode,sameNameCollision:options.sameNameCollision===true,citationInsufficient:options.citationInsufficient===true});
      if(!need.needed)return {status:'NOT_NEEDED',need,baseline:baseline.metrics};
      const request=boundedGenerationRequest({source,question,mode,baseline,need,failureSignals:options.failureSignals||[],confirmedAliases:options.confirmedAliases||[],queryHints:options.queryHints||[]});
      emit('AUTO_PACK_GENERATION_STARTED',{sourceId,questionHash:`fnv1a:${hashString(question)}`,mode,reasons:need.reasons});
      const proposal=await getProposal(request,{confirmedAliases:options.confirmedAliases||[],queryHints:options.queryHints||[]});
      const allowedLocators=new Set(request.evidence.map(x=>x.locator));const safeProposal=sanitizeProposal(proposal,mode,allowedLocators);const pack=buildPack({source,question,mode,safeProposal,request});
      const compatibility=runtime.checkPackCompatibility(sourceId,pack);if(!compatibility.compatible)throw new Error(compatibility.reason);
      const sourceBefore=runtime.getSource(sourceId);const attachedBefore=runtime.listAttachedPacks(sourceId).map(x=>x.id);let attached=false;
      try{
        runtime.attachPack(sourceId,pack);attached=true;
        const afterRetrieval=await runtime.retrieve({sourceId,query:question,locator:options.locator||null,trustMode:options.trustMode||null});const after=qualityMetrics(afterRetrieval,options.expectedLocator||null);const delta=improvement(baseline.metrics,after);
        if(!delta.improved&&options.keepWithoutImprovement!==true){runtime.detachPack(sourceId,pack.id);attached=false;emit('AUTO_PACK_REJECTED_NO_IMPROVEMENT',{packId:pack.id,sourceId,delta});return {status:'REJECTED_NO_IMPROVEMENT',need,request,pack,compatibility,before:baseline.metrics,after,delta,attached:false,persisted:false}}
        const record={schema:CONTRACT.schema,status:'READY_PRIVATE',pack,sourceId,sourceFingerprint:source.fingerprint,question:clip(question,900),need,before:baseline.metrics,after,delta,generatedAt:clock(),publication:{visibility:'private',status:'draft',autoPublished:false},sourceIntegrity:{fingerprintBefore:sourceBefore.fingerprint,fingerprintAfter:runtime.getSource(sourceId).fingerprint,unchanged:sourceBefore.fingerprint===runtime.getSource(sourceId).fingerprint},attachedBefore};
        if(options.persistLocal!==false)artifacts.save(record);
        if(market?.mergeCatalog){const draft=listingForPrivatePack(pack,source);market.mergeCatalog([{...draft.listing,versions:[draft.version],attestations:[]}])}
        emit('AUTO_PACK_READY_PRIVATE',{packId:pack.id,sourceId,delta});return {...clone(record),request,compatibility,attached:true,persistedLocal:options.persistLocal!==false};
      }catch(error){if(attached){try{runtime.detachPack(sourceId,pack.id)}catch(_){}}throw error}
    }
    async function persistDraft(packId,{artifactUri}={}){
      const record=artifacts.get(String(packId));if(!record)throw new Error('AUTO_PACK_LOCAL_ARTIFACT_NOT_FOUND');if(!writer)throw new Error('AUTO_PACK_REGISTRY_WRITER_REQUIRED');if(!artifactUri)throw new Error('AUTO_PACK_DURABLE_ARTIFACT_URI_REQUIRED');
      const source=ensureRt().getSource(record.sourceId);const draft=listingForPrivatePack(record.pack,source,{artifactUri});const out=await writer.saveDraft(draft);emit('AUTO_PACK_DRAFT_PERSISTED',{packId,artifactUri});return out;
    }
    function preparePublicReview(packId){const record=artifacts.get(String(packId));if(!record)throw new Error('AUTO_PACK_LOCAL_ARTIFACT_NOT_FOUND');return {packId,visibility:'public',publicationStatus:'pending_review',autoPublish:false,rightsReviewRequired:true,sourcePublicationImplied:false,trustTier:'auto-generated',verified:false}}
    function detach(packId,sourceId){const ok=ensureRt().detachPack(String(sourceId),String(packId));emit('AUTO_PACK_DETACHED',{packId:String(packId),sourceId:String(sourceId)});return ok}
    function discard(packId,{detachFrom=null}={}){if(detachFrom){try{ensureRt().detachPack(String(detachFrom),String(packId))}catch(_){}}artifacts.remove(String(packId));emit('AUTO_PACK_DISCARDED',{packId:String(packId)});return true}
    function status(){return {schema:CONTRACT.schema,version:CONTRACT.version,generatorProviderInstalled:Boolean(provider),registryWriterInstalled:Boolean(writer),universalRuntimeInstalled:Boolean(rt),marketplaceRuntimeInstalled:Boolean(market),generatedArtifactCount:artifacts.list().length,signalCount:signals.length,defaultVisibility:'private',autoPublish:false,sourceBodyInGeneratedPack:false}}
    return Object.freeze({contract:CONTRACT,setUniversalRuntime,setMarketplaceRuntime,setGeneratorProvider,setRegistryWriter,onChange,recordSignal,evaluateNeed,analyzeBaseline,generate,persistDraft,preparePublicReview,detach,discard,listGenerated:()=>artifacts.list(),getGenerated:id=>artifacts.get(String(id)),status,packArtifactFingerprint,sanitizeProposal,qualityMetrics,improvement});
  }

  return {STORYMEMORY_AUTO_PACK_CONTRACT:CONTRACT,createStoryMemoryAutoPackRuntime,createStoryMemoryNeonAutoPackRegistryWriter};
});
