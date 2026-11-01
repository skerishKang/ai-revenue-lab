(function(root,factory){
  const api=factory(root||globalThis);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){
    root.STORYMEMORY_UNIVERSAL_SOURCE_CONTRACT=api.STORYMEMORY_UNIVERSAL_SOURCE_CONTRACT;
    root.createStoryMemoryUniversalSourceRuntime=api.createStoryMemoryUniversalSourceRuntime;
    root.storyMemoryUniversalSource=root.storyMemoryUniversalSource||api.createStoryMemoryUniversalSourceRuntime({
      staticAdapter:root.storyMemoryStatic||null
    });

    // Non-invasive bridge from the existing Book Reader into the universal harness.
    // The current chat UI remains on the production hybrid path until SM-087 UI adaptation.
    if(root.document){
      const runtime=root.storyMemoryUniversalSource;
      runtime.setMemoryProvider(({source})=>{
        try{
          const store=JSON.parse(root.localStorage?.getItem('storymemory.store.v1')||'null');
          const rows=Array.isArray(store?.memories)?store.memories:[];
          const contentId=source?.metadata?.contentId||null;
          const contentTitle=source?.metadata?.contentTitle||source?.title||null;
          return rows.filter(row=>!contentId||row?.contentId===contentId||row?.context===contentTitle).map(row=>({
            id:row.id||row.clientRecordId||null,sourceId:source.sourceId,
            locator:row.canonicalLocator||row.sourcePassageId||null,
            title:row.title||row.context||'Memory',body:row.body||row.question||'',quote:row.quote||'',
            createdAt:row.createdAt?new Date(Number(row.createdAt)).toISOString():null,
            metadata:{contentId:row.contentId||null,unitOrdinal:row.unitOrdinal||null,sourceSequence:row.sourceSequence||null,authoritative:Boolean(row.authoritative)}
          }));
        }catch(_){return []}
      });

      root.storyMemoryUniversalEnsureCurrentBookSource=async function(options={}){
        const content=root.storyMemoryResumeContent?.()||root.storyMemoryReaderContentForContext?.({kind:'book',book:root.__smCurrentReaderLabel})||null;
        if(!content)throw new Error('CURRENT_READER_CONTENT_REQUIRED');
        const workKey=root.storyMemoryStaticWorkKey?.(content)||null;
        if(!workKey)throw new Error('CURRENT_READER_STATIC_WORK_REQUIRED');
        const exact=root.storyMemoryExactResumeSnapshot?.()||{};
        const unitOrdinal=Math.max(1,Number(options.unitOrdinal||exact.unitOrdinal)||1);
        const sourceType=content.kind==='bible'?'bible':'book';
        const sourceId=`${sourceType}:${workKey}`;
        let manifestBundle=null;
        try{manifestBundle=await root.storyMemoryStatic?.getManifest?.(workKey)}catch(_){}
        const manifest=manifestBundle?.manifest||null;
        const fingerprint=manifest?.provenance?.canonical_source_sha256||`${workKey}:${manifest?.passage_count||'unknown'}:${manifest?.unit_count||'unknown'}`;
        const existing=runtime.getSource(sourceId);
        const loaded=Array.isArray(existing?.structure?.loadedUnits)&&existing.structure.loadedUnits.map(Number).includes(unitOrdinal);
        if(!existing||!loaded||existing.fingerprint!==fingerprint){
          await runtime.ingest({
            sourceId,sourceType,title:content.title||manifest?.title||workKey,workKey,unitOrdinal,
            ownerScope:'public',rightsMode:'preloaded-authorized',revision:String(manifest?.schema_version||'storymemory-static-content-1.0'),
            fingerprint,language:'ko',metadata:{contentId:content.id||null,contentTitle:content.title||null,progressBounded:true,delivery:'static',unitOrdinal}
          });
        }
        const locator=options.locator||exact.canonicalLocator||null;
        if(locator){try{runtime.setPosition(sourceId,locator,{selection:options.selection||null})}catch(_){runtime.setActiveSource(sourceId,{selection:options.selection||null})}}
        else runtime.setActiveSource(sourceId,{selection:options.selection||null});
        return {source:runtime.getSource(sourceId),position:runtime.getPosition(),exactResume:exact};
      };

      root.storyMemoryBuildUniversalCurrentContext=async function(question,selection=null,options={}){
        const ensured=await root.storyMemoryUniversalEnsureCurrentBookSource({selection,...options});
        return runtime.buildContext({sourceId:ensured.source.sourceId,question:String(question||''),locator:ensured.position?.locator||null,selection,modelPriorHints:options.modelPriorHints||null,trustMode:options.trustMode||null,answerType:options.answerType||null,workbookMode:options.workbookMode||null,revealAnswers:options.revealAnswers===true});
      };
      root.storyMemorySubmitUniversalQuestion=async function(question,options={}){
        const ensured=await root.storyMemoryUniversalEnsureCurrentBookSource({selection:options.selection||null,...options});
        return runtime.answer({sourceId:ensured.source.sourceId,question:String(question||''),locator:ensured.position?.locator||null,selection:options.selection||null,modelPriorHints:options.modelPriorHints||null,trustMode:options.trustMode||null,answerType:options.answerType||null,workbookMode:options.workbookMode||null,revealAnswers:options.revealAnswers===true});
      };
      root.storyMemoryUniversalSetTrustMode=(sourceId,mode)=>runtime.setTrustMode(sourceId,mode);
      root.storyMemoryUniversalGetTrustMode=sourceId=>runtime.getTrustMode(sourceId);
      root.storyMemoryUniversalRecommendTrustMode=(sourceId,options={})=>runtime.recommendTrustMode(sourceId,options);
      root.storyMemoryUniversalSourceStatus=()=>runtime.status();
    }

    if(root.document?.documentElement){
      root.document.documentElement.dataset.storymemoryBuild='v3.4.3-precision-pack';
    }
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';

  const STORYMEMORY_UNIVERSAL_SOURCE_CONTRACT=Object.freeze({
    schema:'storymemory-universal-source-runtime-1.0',
    version:'1.4.0',
    packSchema:'storymemory-precision-pack-1.0',
    packKinds:Object.freeze(['knowledge','harness','search','companion']),
    packMatchModes:Object.freeze(['exact-fingerprint','source-id','work-revision']),
    trustModes:Object.freeze(['EXPLORE','GROUNDED','STRICT']),
    provenanceLabels:Object.freeze(['AI_NATIVE','SOURCE_GROUNDED','PACK_ASSISTED','VERIFIED','INTERPRETATION','UNCERTAIN']),
    states:Object.freeze(['RECEIVED','PARSING','STRUCTURING','SEARCH_READY','CONVERSATION_READY','ENRICHING','PRECISION_READY','FAILED_PARTIAL']),
    maxEvidenceBlocks:8,
    maxEvidenceChars:7000,
    maxMemories:6,
    maxAttachedPacks:4,
    maxTerms:16,
    maxSelectionChars:1400
  });

  const clampText=(value,max=900)=>{
    const s=String(value??'').replace(/\s+/g,' ').trim();
    return s.length>max?s.slice(0,Math.max(0,max-1))+'…':s;
  };
  const finite=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
  const normalizeId=v=>String(v??'').trim().replace(/[^a-zA-Z0-9._:-]+/g,'-').replace(/^-+|-+$/g,'').toLowerCase();
  const tokenize=value=>{
    const raw=String(value??'').toLowerCase();
    const parts=raw.match(/[a-z0-9가-힣]{2,}/g)||[];
    // A few one-syllable Korean nouns carry real disambiguation value (e.g. '개' in '아르고스 개').
    // Keep this allowlist deliberately tiny so particles do not flood the lexical index.
    for(const term of ['개','산','섬','왕','신']){
      const re=new RegExp(`(^|[\\s(])${term}($|[\\s?!.),])`);
      if(re.test(raw))parts.push(term);
    }
    return [...new Set(parts)].slice(0,STORYMEMORY_UNIVERSAL_SOURCE_CONTRACT.maxTerms);
  };
  const hashString=value=>{
    const s=String(value??'');
    let h1=0x811c9dc5;
    for(let i=0;i<s.length;i++){
      h1^=s.charCodeAt(i);
      h1=Math.imul(h1,0x01000193)>>>0;
    }
    return h1.toString(16).padStart(8,'0');
  };
  const canonicalFingerprint=spec=>String(spec?.fingerprint||spec?.sourceHash||spec?.revisionFingerprint||`fnv1a:${hashString(JSON.stringify({
    sourceId:spec?.sourceId||spec?.source_id||'',
    revision:spec?.revision||spec?.sourceRevision||'',
    title:spec?.title||'',
    type:spec?.sourceType||spec?.source_type||'',
    body:spec?.text||spec?.extractedText||spec?.transcript||''
  }))}`);

  function ensureBlock(block,index,source){
    const locator=String(block?.locator||block?.canonical_locator||`${source.sourceType}:${source.sourceId}:block:${index+1}`);
    const text=String(block?.text??block?.ko??block?.en??'').trim();
    return {
      id:String(block?.id||locator),
      locator,
      ordinal:finite(block?.ordinal)?Number(block.ordinal):index+1,
      text,
      sourceText:String(block?.sourceText??block?.source_text??block?.en??text),
      title:String(block?.title||block?.sectionTitle||block?.section_title||''),
      metadata:{...(block?.metadata||{})},
      raw:block
    };
  }

  function buildLexicalIndex(blocks){
    const postings=new Map();
    blocks.forEach((block,index)=>{
      const combined=`${block.title||''} ${block.text||''} ${block.sourceText||''}`.toLowerCase();
      // Query token count is bounded, but indexing must cover the whole block.
      // Reusing tokenize() here previously truncated every passage to its first 16 unique terms.
      const terms=combined.match(/[a-z0-9가-힣]{2,}/g)||[];
      for(const term of ['개','산','섬','왕','신']){
        const re=new RegExp(`(^|[\\s(])${term}($|[\\s?!.),])`);
        if(re.test(combined))terms.push(term);
      }
      [...new Set(terms)].forEach(term=>{
        if(!postings.has(term))postings.set(term,new Set());
        postings.get(term).add(index);
      });
    });
    return postings;
  }

  function lexicalSearch(source,query,{limit=8,maxOrdinal=null,currentLocator=null,preferEarliest=false}={}){
    const terms=tokenize(query);
    const candidates=new Set();
    for(const term of terms){
      const direct=source.lexicalIndex.get(term);
      if(direct)direct.forEach(i=>candidates.add(i));
      // Korean case particles and transliteration variants often attach to the same stem.
      // Prefix/containment expansion keeps retrieval source-native without a curated alias DB.
      for(const [indexed,rows] of source.lexicalIndex.entries()){
        if(indexed===term)continue;
        if(indexed.includes(term)||term.includes(indexed))rows.forEach(i=>candidates.add(i));
      }
    }
    const addAllAllowed=()=>source.blocks.forEach((block,i)=>{if(!finite(maxOrdinal)||Number(block.ordinal)<=Number(maxOrdinal))candidates.add(i)});
    if(!candidates.size)addAllAllowed();
    const exact=String(query||'').trim().toLowerCase();
    const current=source.locatorMap.get(String(currentLocator||''));
    const rows=[];
    const scoreCandidate=i=>{
      const block=source.blocks[i];
      if(!block)return;
      if(finite(maxOrdinal)&&Number(block.ordinal)>Number(maxOrdinal))return;
      const bodyHay=`${block.text||''} ${block.sourceText||''}`.toLowerCase();
      const titleHay=String(block.title||'').toLowerCase();
      const hay=`${titleHay} ${bodyHay}`;
      let score=0;
      for(const term of terms){
        if(bodyHay.includes(term))score+=10;
        else if(titleHay.includes(term))score+=3;
      }
      if(exact&&bodyHay.includes(exact))score+=25;
      else if(exact&&titleHay.includes(exact))score+=5;
      if(!preferEarliest){
        if(block.locator===currentLocator)score+=8;
        if(current&&finite(current.ordinal)&&finite(block.ordinal))score-=Math.min(8,Math.abs(block.ordinal-current.ordinal)*0.15);
      }
      rows.push({block,score});
    };
    candidates.forEach(scoreCandidate);
    // If exact postings existed only beyond the visible boundary, do not return an empty set.
    // Fall back to a bounded linear scan of visible blocks, which also catches attached particles.
    if(!rows.length&&source.blocks.length){
      candidates.clear();addAllAllowed();candidates.forEach(scoreCandidate);
    }
    rows.sort((a,b)=>b.score-a.score||a.block.ordinal-b.block.ordinal);
    return rows.slice(0,Math.max(1,Number(limit)||8)).map(x=>({...x.block,__score:x.score}));
  }

  function createDocumentAdapter(){
    return {
      type:'document',
      canHandle:spec=>['document','pdf','doc','docx','markdown','txt','worksheet','problem-set','workbook','contract','legal','official-record'].includes(String(spec?.sourceType||spec?.source_type||'').toLowerCase()),
      async ingest(spec){
        const sourceId=normalizeId(spec.sourceId||spec.source_id||spec.title||'document');
        const pages=Array.isArray(spec.pages)?spec.pages:null;
        const blocks=[];
        if(pages){
          pages.forEach((page,pageIndex)=>{
            const pageNo=finite(page?.page)?Number(page.page):pageIndex+1;
            const pageBlocks=Array.isArray(page?.blocks)?page.blocks:[{text:page?.text??''}];
            pageBlocks.forEach((block,blockIndex)=>blocks.push({
              locator:String(block?.locator||`doc:${sourceId}:page:${pageNo}:block:${blockIndex+1}`),
              ordinal:blocks.length+1,
              title:block?.title||page?.title||`Page ${pageNo}`,
              text:block?.text??'',
              sourceText:block?.sourceText??block?.text??'',
              metadata:{page:pageNo,block:blockIndex+1,sourceKind:String(spec.sourceType||'document').toLowerCase(),...(block?.metadata||{})}
            }));
          });
        }else{
          const raw=String(spec.extractedText??spec.text??'');
          raw.split(/\n\s*\n+/).map(x=>x.trim()).filter(Boolean).forEach((text,index)=>blocks.push({
            locator:`doc:${sourceId}:section:1:block:${index+1}`,
            ordinal:index+1,
            title:`Block ${index+1}`,
            text,sourceText:text,metadata:{section:1,block:index+1,sourceKind:String(spec.sourceType||'document').toLowerCase()}
          }));
        }
        if(!blocks.length)throw new Error('DOCUMENT_TEXT_REQUIRED');
        return {blocks,structure:{kind:'document',pageCount:pages?.length||null,blockCount:blocks.length}};
      }
    };
  }

  function createTranscriptAdapter(){
    return {
      type:'transcript',
      canHandle:spec=>['url','web','webpage','youtube','video','audio','transcript'].includes(String(spec?.sourceType||spec?.source_type||'').toLowerCase()),
      async ingest(spec){
        const sourceId=normalizeId(spec.sourceId||spec.source_id||spec.title||'media');
        let segments=Array.isArray(spec.segments)?spec.segments:Array.isArray(spec.transcriptSegments)?spec.transcriptSegments:null;
        if(!segments){
          const raw=String(spec.transcript??spec.extractedText??spec.text??'').trim();
          segments=raw?raw.split(/\n+/).map((text,index)=>({text,startMs:index*30000,endMs:(index+1)*30000})):[];
        }
        const blocks=segments.map((segment,index)=>{
          const start=finite(segment.startMs)?Number(segment.startMs):(finite(segment.start)?Math.round(Number(segment.start)*1000):index*30000);
          const end=finite(segment.endMs)?Number(segment.endMs):(finite(segment.end)?Math.round(Number(segment.end)*1000):start+30000);
          const locator=String(segment.locator||`url:${sourceId}:t:${Math.max(0,start)}-${Math.max(start,end)}`);
          return {locator,ordinal:index+1,title:segment.title||`Segment ${index+1}`,text:String(segment.text??''),sourceText:String(segment.sourceText??segment.text??''),metadata:{startMs:start,endMs:end,url:spec.url||null,sourceKind:String(spec.sourceType||'url').toLowerCase(),...(segment.metadata||{})}};
        }).filter(x=>x.text.trim());
        if(!blocks.length)throw new Error('TRANSCRIPT_OR_SNAPSHOT_REQUIRED');
        return {blocks,structure:{kind:'transcript',segmentCount:blocks.length,url:spec.url||null}};
      }
    };
  }

  function createBookAdapter(staticAdapter){
    return {
      type:'book',
      canHandle:spec=>['book','bible','scripture'].includes(String(spec?.sourceType||spec?.source_type||'').toLowerCase()),
      async ingest(spec){
        if(Array.isArray(spec.blocks)&&spec.blocks.length)return {blocks:spec.blocks,structure:{kind:'book',unitCount:spec.unitCount||null}};
        if(!staticAdapter||typeof staticAdapter.loadUnit!=='function')throw new Error('BOOK_STATIC_ADAPTER_REQUIRED');
        const workKey=spec.workKey||spec.work_key;
        if(!workKey)throw new Error('BOOK_WORK_KEY_REQUIRED');
        const requested=Array.isArray(spec.unitOrdinals)&&spec.unitOrdinals.length?spec.unitOrdinals:[Math.max(1,Number(spec.unitOrdinal)||1)];
        const blocks=[];
        let manifest=null;
        for(const unitOrdinal of requested){
          const bundle=await staticAdapter.loadUnit({workKey,unitOrdinal,language:spec.language||'ko'});
          manifest=bundle?.manifest||manifest;
          (bundle?.unit?.passages||[]).forEach(row=>blocks.push({
            locator:String(row.canonical_locator||`${workKey}:unit:${unitOrdinal}:block:${blocks.length+1}`),
            ordinal:finite(row.sequence)?Number(row.sequence):blocks.length+1,
            title:String(row.section_title||bundle?.unit?.unit_label||''),
            text:String(row.ko||row.en||''),
            sourceText:String(row.en||row.ko||''),
            metadata:{unitOrdinal:Number(unitOrdinal),unitKey:bundle?.unit?.unit_key||null,sequence:finite(row.sequence)?Number(row.sequence):null,sourceTextHash:row.source_text_hash||null,translationTextHash:row.translation_text_hash||null,workKey}
          }));
        }
        if(!blocks.length)throw new Error('BOOK_UNIT_EMPTY');
        return {blocks,structure:{kind:'book',workKey,loadedUnits:requested.map(Number),unitCount:manifest?.units?.length||null}};
      }
    };
  }

  function createStoryMemoryUniversalSourceRuntime({
    staticAdapter=null,
    provider=null,
    memoryProvider=null,
    retrievalPlanner=null,
    packVerifier=null,
    contract=STORYMEMORY_UNIVERSAL_SOURCE_CONTRACT
  }={}){
    const sources=new Map();
    const adapters=[];
    const stateListeners=new Set();
    const localMemories=[];
    const attachedPacks=new Map();
    const trustBySource=new Map();
    let activeSourceId=null;
    let activePosition=null;
    let modelProvider=typeof provider==='function'?provider:null;
    let externalMemoryProvider=typeof memoryProvider==='function'?memoryProvider:null;
    let externalRetrievalPlanner=typeof retrievalPlanner==='function'?retrievalPlanner:null;
    let externalPackVerifier=typeof packVerifier==='function'?packVerifier:null;

    const TRUST_POLICIES=Object.freeze({
      EXPLORE:Object.freeze({mode:'EXPLORE',modelPriorAllowed:true,citationRequired:false,strictUnknown:false,exactVerification:false,allowAiNative:true,retrievalDepth:'normal'}),
      GROUNDED:Object.freeze({mode:'GROUNDED',modelPriorAllowed:true,citationRequired:true,strictUnknown:false,exactVerification:true,allowAiNative:false,retrievalDepth:'grounded'}),
      STRICT:Object.freeze({mode:'STRICT',modelPriorAllowed:true,citationRequired:true,strictUnknown:true,exactVerification:true,allowAiNative:false,retrievalDepth:'strict'})
    });
    const VERIFIED_TIERS=new Set(['gold','verified','curated','expert','expert-verified','expert_verified','official','publisher','official/publisher','official-publisher']);

    const normalizeTrustMode=value=>{
      const mode=String(value||'').trim().toUpperCase();
      if(!contract.trustModes.includes(mode))throw new Error(`INVALID_TRUST_MODE:${value}`);
      return mode;
    };
    const normalizeTier=value=>String(value||'unverified').trim().toLowerCase().replace(/\s+/g,'-');
    const isVerifiedTier=value=>VERIFIED_TIERS.has(normalizeTier(value));
    const sourceProfile=source=>String(source?.metadata?.sourceProfile||source?.metadata?.domain||source?.metadata?.profile||'').toLowerCase();
    const isBookLike=source=>['book','bible','scripture'].includes(source?.sourceType);
    const isScripture=source=>['bible','scripture'].includes(source?.sourceType)||sourceProfile(source).includes('scripture')||sourceProfile(source).includes('bible');
    const isWorkbook=source=>['worksheet','problem-set','workbook'].includes(source?.sourceType)||['workbook','study','problem-set'].includes(sourceProfile(source));
    const isStrictDocument=source=>['contract','legal','official-record'].includes(source?.sourceType)||['contract','legal','official','official-record','administrative'].includes(sourceProfile(source))||source?.metadata?.strictRecommended===true;
    const isDocumentLike=source=>['document','pdf','doc','docx','markdown','txt','contract','legal','official-record'].includes(source?.sourceType)||isStrictDocument(source);
    const extractionQuality=source=>{
      const raw=source?.metadata?.extractionQuality;
      if(raw===undefined||raw===null||raw==='')return {status:'UNKNOWN',score:null,issues:[]};
      if(typeof raw==='number')return {status:raw>=0.9?'HIGH':raw>=0.7?'MEDIUM':'LOW',score:Number(raw),issues:[]};
      if(typeof raw==='object')return {status:String(raw.status||'UNKNOWN').toUpperCase(),score:finite(raw.score)?Number(raw.score):null,issues:Array.isArray(raw.issues)?raw.issues.map(String):[]};
      return {status:String(raw).toUpperCase(),score:null,issues:[]};
    };

    function recommendTrustMode(sourceOrId,{purpose=null}={}){
      const source=typeof sourceOrId==='string'?sources.get(sourceOrId):sourceOrId;
      if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceOrId}`);
      const p=String(purpose||source.metadata?.purpose||'').toLowerCase();
      if(source.metadata?.trustDefault)return normalizeTrustMode(source.metadata.trustDefault);
      if(isScripture(source)||isStrictDocument(source)||p.includes('strict')||p.includes('exact'))return 'STRICT';
      if(isWorkbook(source)||isDocumentLike(source)||['research','study','work','grounded'].some(x=>p.includes(x)))return 'GROUNDED';
      return 'EXPLORE';
    }
    function setTrustMode(sourceId,mode){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const normalized=normalizeTrustMode(mode);trustBySource.set(source.sourceId,normalized);return normalized;
    }
    function getTrustMode(sourceId=activeSourceId){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      return trustBySource.get(source.sourceId)||recommendTrustMode(source);
    }

    const registerSourceAdapter=adapter=>{
      if(!adapter||typeof adapter.canHandle!=='function'||typeof adapter.ingest!=='function')throw new Error('INVALID_SOURCE_ADAPTER');
      adapters.unshift(adapter);
      return adapter;
    };
    registerSourceAdapter(createTranscriptAdapter());
    registerSourceAdapter(createDocumentAdapter());
    registerSourceAdapter(createBookAdapter(staticAdapter));

    function emitState(source,state,detail=null){
      source.ingestState=state;
      const event={sourceId:source.sourceId,state,detail,at:new Date().toISOString()};
      source.stateHistory.push(event);
      stateListeners.forEach(fn=>{try{fn(event,source)}catch(_){}});
      return event;
    }

    async function ingest(spec={}){
      const sourceType=String(spec.sourceType||spec.source_type||'').toLowerCase();
      const sourceId=normalizeId(spec.sourceId||spec.source_id||spec.title||`${sourceType||'source'}-${Date.now()}`);
      if(!sourceType)throw new Error('SOURCE_TYPE_REQUIRED');
      const source={
        sourceId,sourceType,title:String(spec.title||sourceId),ownerScope:String(spec.ownerScope||spec.owner_scope||'user-private'),rightsMode:String(spec.rightsMode||spec.rights_mode||'user-supplied'),revision:String(spec.revision||spec.sourceRevision||'1'),fingerprint:canonicalFingerprint({...spec,sourceId,sourceType}),language:String(spec.language||'und'),metadata:{...(spec.metadata||{})},ingestState:'RECEIVED',stateHistory:[],precisionState:'BASE',packStateHistory:[],blocks:[],lexicalIndex:new Map(),locatorMap:new Map(),structure:null
      };
      emitState(source,'RECEIVED');
      const adapter=adapters.find(a=>a.canHandle({...spec,sourceType}));
      if(!adapter){emitState(source,'FAILED_PARTIAL',{reason:'NO_SOURCE_ADAPTER'});throw new Error(`NO_SOURCE_ADAPTER:${sourceType}`)}
      emitState(source,'PARSING',{adapter:adapter.type||'custom'});
      try{
        const parsed=await adapter.ingest({...spec,sourceId,sourceType},{runtime:api});
        emitState(source,'STRUCTURING',{blockCount:parsed?.blocks?.length||0});
        source.blocks=(parsed?.blocks||[]).map((block,index)=>ensureBlock(block,index,source)).filter(block=>block.text||block.sourceText);
        source.blocks.sort((a,b)=>a.ordinal-b.ordinal||a.locator.localeCompare(b.locator));
        source.structure=parsed?.structure||{kind:sourceType,blockCount:source.blocks.length};
        source.locatorMap=new Map(source.blocks.map(block=>[block.locator,block]));
        source.lexicalIndex=buildLexicalIndex(source.blocks);
        emitState(source,'SEARCH_READY',{terms:source.lexicalIndex.size,blocks:source.blocks.length});
        if(!source.blocks.length)throw new Error('SOURCE_HAS_NO_CONVERSATION_BLOCKS');
        const quality=extractionQuality(source);
        if((quality.status==='LOW'||(finite(quality.score)&&quality.score<0.7))&&String(spec.trustMode||source.metadata?.trustDefault||'').toUpperCase()==='STRICT'){
          emitState(source,'FAILED_PARTIAL',{reason:'STRICT_EXTRACTION_QUALITY_TOO_LOW',quality});
          sources.set(sourceId,source);
          throw new Error('STRICT_EXTRACTION_QUALITY_TOO_LOW');
        }
        emitState(source,'CONVERSATION_READY',{blocks:source.blocks.length});
        sources.set(sourceId,source);
        if(spec.trustMode||source.metadata?.trustDefault)trustBySource.set(sourceId,normalizeTrustMode(spec.trustMode||source.metadata.trustDefault));
        if(!activeSourceId){activeSourceId=sourceId;activePosition={sourceId,locator:source.blocks[0]?.locator||null,ordinal:source.blocks[0]?.ordinal||null,selection:null}}
        return snapshotSource(source);
      }catch(error){
        if(source.ingestState!=='FAILED_PARTIAL')emitState(source,'FAILED_PARTIAL',{reason:String(error?.message||error)});
        throw error;
      }
    }

    function snapshotSource(sourceOrId){
      const source=typeof sourceOrId==='string'?sources.get(sourceOrId):sourceOrId;
      if(!source)return null;
      const trustMode=trustBySource.get(source.sourceId)||(()=>{try{return recommendTrustMode(source)}catch(_){return 'EXPLORE'}})();
      return {sourceId:source.sourceId,sourceType:source.sourceType,title:source.title,ownerScope:source.ownerScope,rightsMode:source.rightsMode,revision:source.revision,fingerprint:source.fingerprint,language:source.language,ingestState:source.ingestState,stateHistory:[...source.stateHistory],structure:{...(source.structure||{})},blockCount:source.blocks.length,firstLocator:source.blocks[0]?.locator||null,lastLocator:source.blocks.at(-1)?.locator||null,trustMode,recommendedTrustMode:(()=>{try{return recommendTrustMode(source)}catch(_){return trustMode}})(),extractionQuality:extractionQuality(source),precisionState:source.precisionState||'BASE',packStateHistory:[...(source.packStateHistory||[])],metadata:{...source.metadata}};
    }

    function listSources(){return [...sources.values()].map(snapshotSource)}

    function setActiveSource(sourceId,{locator=null,selection=null}={}){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      activeSourceId=source.sourceId;
      const block=locator?source.locatorMap.get(String(locator)):source.blocks[0];
      activePosition={sourceId:source.sourceId,locator:block?.locator||null,ordinal:block?.ordinal||null,selection:selection?{...selection}:null};
      return {...activePosition};
    }

    function setPosition(sourceId,locator,{selection=null}={}){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const block=source.locatorMap.get(String(locator));if(!block)throw new Error(`LOCATOR_NOT_FOUND:${locator}`);
      activeSourceId=source.sourceId;
      activePosition={sourceId:source.sourceId,locator:block.locator,ordinal:block.ordinal,selection:selection?{...selection}:null};
      return {...activePosition};
    }

    function getPosition(){return activePosition?{...activePosition,selection:activePosition.selection?{...activePosition.selection}:null}:null}

    function addMemory(memory={}){
      const sourceId=String(memory.sourceId||activeSourceId||'');if(!sourceId)throw new Error('MEMORY_SOURCE_REQUIRED');
      const item={id:String(memory.id||`memory:${Date.now()}:${localMemories.length+1}`),sourceId,locator:memory.locator||null,title:clampText(memory.title||'',180),body:clampText(memory.body||memory.text||'',900),quote:clampText(memory.quote||'',500),tags:Array.isArray(memory.tags)?memory.tags.map(String):[],createdAt:memory.createdAt||new Date().toISOString(),metadata:{...(memory.metadata||{})}};
      localMemories.unshift(item);return {...item};
    }

    async function memoriesFor(source,query){
      let pool=localMemories.filter(x=>x.sourceId===source.sourceId);
      if(externalMemoryProvider){
        try{const extra=await externalMemoryProvider({source:snapshotSource(source),query});if(Array.isArray(extra))pool=pool.concat(extra)}catch(_){ }
      }
      const terms=tokenize(query);
      return pool.map(x=>({...x,__score:(x.locator===activePosition?.locator?12:0)+terms.reduce((n,t)=>n+(`${x.title} ${x.body} ${x.quote}`.toLowerCase().includes(t)?4:0),0)})).sort((a,b)=>b.__score-a.__score).slice(0,contract.maxMemories).map(x=>{const y={...x};delete y.__score;return y});
    }

    const normalizePackKind=value=>{
      const kind=String(value||'companion').trim().toLowerCase();
      if(!contract.packKinds.includes(kind))throw new Error(`INVALID_PACK_KIND:${value}`);
      return kind;
    };
    const normalizePackMatchMode=value=>{
      const mode=String(value||'exact-fingerprint').trim().toLowerCase().replace(/_/g,'-');
      if(!contract.packMatchModes.includes(mode))throw new Error(`INVALID_PACK_MATCH_MODE:${value}`);
      return mode;
    };
    const sourceLocatorScheme=source=>String(source?.metadata?.locatorScheme||source?.metadata?.locator_scheme||source?.structure?.kind||source?.sourceType||'').toLowerCase();
    const packArtifactFingerprint=pack=>`fnv1a:${hashString(JSON.stringify({schema:pack?.schema||contract.packSchema,id:pack?.id||pack?.packId||'',version:pack?.version||'0.0.0',kind:pack?.kind||'companion',compatibility:pack?.compatibility||{},payload:pack?.payload||{},metadata:pack?.metadata||{}}))}`;

    function checkPackCompatibility(sourceId,pack={}){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const schema=String(pack.schema||contract.packSchema);
      const legacy=typeof pack.search==='function'||typeof pack.augmentContext==='function';
      if(schema!==contract.packSchema&&!legacy)return {compatible:false,reason:'PACK_SCHEMA_UNSUPPORTED',schema,expectedSchema:contract.packSchema};
      const c=pack.compatibility&&typeof pack.compatibility==='object'?pack.compatibility:{};
      const mode=normalizePackMatchMode(c.mode||pack.sourceMatchMode||pack.source_match_mode||'exact-fingerprint');
      const expectedFingerprint=String(c.sourceFingerprint||c.source_fingerprint||pack.sourceFingerprint||pack.source_fingerprint||'');
      const expectedSourceId=String(c.sourceId||c.source_id||pack.sourceId||pack.source_id||'');
      const expectedRevision=String(c.sourceRevision||c.source_revision||pack.sourceRevision||pack.source_revision||'');
      const expectedWorkKey=String(c.workKey||c.work_key||pack.workKey||pack.work_key||'');
      const expectedLanguage=String(c.language||pack.language||'');
      const expectedLocator=String(c.locatorScheme||c.locator_scheme||pack.locatorScheme||pack.locator_scheme||'').toLowerCase();
      let ok=true,reason='COMPATIBLE';
      if(mode==='exact-fingerprint'){
        if(!expectedFingerprint&&!legacy){ok=false;reason='PACK_COMPATIBILITY_IDENTITY_REQUIRED';}
        else{const target=expectedFingerprint||source.fingerprint;ok=target===source.fingerprint;reason=ok?'COMPATIBLE':'PACK_SOURCE_FINGERPRINT_MISMATCH';}
      }else if(mode==='source-id'){
        ok=Boolean(expectedSourceId)&&expectedSourceId===source.sourceId;reason=ok?'COMPATIBLE':'PACK_SOURCE_ID_MISMATCH';
      }else if(mode==='work-revision'){
        const sourceWork=String(source.structure?.workKey||source.metadata?.workKey||source.metadata?.work_key||'');
        ok=Boolean(expectedWorkKey)&&expectedWorkKey===sourceWork&&Boolean(expectedRevision)&&expectedRevision===source.revision;
        reason=ok?'COMPATIBLE':'PACK_WORK_REVISION_MISMATCH';
      }
      if(ok&&expectedRevision&&expectedRevision!==source.revision){ok=false;reason='PACK_SOURCE_REVISION_MISMATCH';}
      if(ok&&expectedLanguage&&expectedLanguage!=='und'&&source.language!=='und'&&expectedLanguage!==source.language){ok=false;reason='PACK_LANGUAGE_MISMATCH';}
      if(ok&&expectedLocator&&expectedLocator!==sourceLocatorScheme(source)){ok=false;reason='PACK_LOCATOR_SCHEME_MISMATCH';}
      const declaredArtifact=String(pack.artifactFingerprint||pack.artifact_fingerprint||'');
      const computedArtifact=packArtifactFingerprint(pack);
      if(ok&&declaredArtifact&&declaredArtifact!==computedArtifact){ok=false;reason='PACK_ARTIFACT_FINGERPRINT_MISMATCH';}
      return {compatible:ok,reason,mode,sourceFingerprint:source.fingerprint,expectedFingerprint:expectedFingerprint||null,sourceId:source.sourceId,sourceRevision:source.revision,language:source.language,locatorScheme:sourceLocatorScheme(source),artifactFingerprint:computedArtifact};
    }

    function normalizeAliasRows(payload={}){
      const rows=Array.isArray(payload.aliases)?payload.aliases:[];
      return rows.map(row=>typeof row==='string'?{from:row,to:[]}:{from:String(row?.from||row?.alias||''),to:Array.isArray(row?.to)?row.to.map(String):Array.isArray(row?.targets)?row.targets.map(String):row?.to?[String(row.to)]:[],metadata:{...(row?.metadata||{})}}).filter(x=>x.from&&x.to.length);
    }
    function compilePackSearch(normalized){
      const payload=normalized.payload||{};
      const knowledge=Array.isArray(payload.knowledge)?payload.knowledge:[];
      const aliases=normalizeAliasRows(payload);
      if(!knowledge.length&&!aliases.length)return null;
      return async ({query,source,position})=>{
        const raw=String(query||'').toLowerCase();
        const terms=tokenize(query);
        const expanded=[];
        for(const row of aliases){
          const from=row.from.toLowerCase();
          if(raw.includes(from)||terms.includes(from))expanded.push(...row.to);
        }
        const effective=[String(query||''),...expanded].join(' ').toLowerCase();
        const scored=[];
        for(const row of knowledge){
          const hay=`${row.key||''} ${row.label||''} ${row.name||''} ${(row.aliases||[]).join(' ')} ${row.summary||row.text||''}`.toLowerCase();
          let score=0;for(const term of tokenize(effective)){if(hay.includes(term))score+=5;}
          if(!score)continue;
          const refs=[...(Array.isArray(row.sourceRefs)?row.sourceRefs:[]),...(Array.isArray(row.evidenceLocators)?row.evidenceLocators:[]),row.locator].filter(Boolean).map(String);
          scored.push({id:row.id||row.key||null,type:row.type||'knowledge',text:String(row.summary||row.text||row.label||''),sourceText:String(row.sourceText||''),locator:refs[0]||null,sourceRefs:[...new Set(refs)],score,metadata:{...(row.metadata||{}),packKnowledge:true}});
        }
        for(const hint of expanded)scored.push({id:`alias:${hint}`,type:'alias',text:`Search alias: ${hint}`,queryHint:hint,sourceRefs:[],score:3,metadata:{packAlias:true}});
        return scored.sort((a,b)=>b.score-a.score).slice(0,8);
      };
    }
    function packQueryHints(source,query){
      const raw=String(query||'').toLowerCase();const out=[];
      for(const pack of (attachedPacks.get(source.sourceId)||[])){
        for(const row of normalizeAliasRows(pack.payload||{})){
          const from=row.from.toLowerCase();if(raw.includes(from)||tokenize(query).includes(from))out.push(...row.to);
        }
        const hints=Array.isArray(pack.payload?.searchHints)?pack.payload.searchHints:[];
        for(const row of hints){
          if(typeof row==='string')continue;
          const when=String(row?.when||row?.query||'').toLowerCase();
          if(when&&raw.includes(when))out.push(...(Array.isArray(row.hints)?row.hints.map(String):[]));
        }
      }
      return [...new Set(out.filter(Boolean))].slice(0,8);
    }
    function listAttachedPacks(sourceId=activeSourceId){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      return (attachedPacks.get(source.sourceId)||[]).map(p=>({id:p.id,name:p.name,kind:p.kind,version:p.version,priority:p.priority,declaredTrustTier:p.declaredTrustTier||p.trustTier,trustTier:p.trustTier,trustAttested:Boolean(p.trustAttested),attestation:p.attestation?{...p.attestation}:null,verificationScope:p.verificationScope,verifiedTier:isVerifiedTier(p.trustTier)&&Boolean(p.trustAttested),sourceFingerprint:p.sourceFingerprint,artifactFingerprint:p.artifactFingerprint,compatibility:{...p.compatibility},rights:{...p.rights},metadata:{...p.metadata}}));
    }
    const PACK_SOFT_POLICY_KEYS=new Set(['answerStyle','explanationStyle','retrievalPreference','citationPreference','memoryPreference','domainInstructions','terminology','tone','hintStrategy']);
    const PACK_HARD_POLICY_KEYS=new Set(['trustMode','citationRequired','strictUnknown','exactVerification','allowAiNative','maxOrdinal','allowFuture','spoilerBoundary','revealAnswers','answerRevealAllowed','workbookMode']);
    function packPolicyBundle(source){
      const soft=[];const blocked=[];
      for(const pack of (attachedPacks.get(source.sourceId)||[])){
        const policies=pack.payload?.policies&&typeof pack.payload.policies==='object'?pack.payload.policies:{};
        const accepted={};
        for(const [key,value] of Object.entries(policies)){
          if(PACK_HARD_POLICY_KEYS.has(key)){blocked.push({packId:pack.id,key,reason:'HARD_RUNTIME_RULE_NOT_OVERRIDABLE'});continue;}
          if(PACK_SOFT_POLICY_KEYS.has(key))accepted[key]=value;
        }
        if(Object.keys(accepted).length)soft.push({packId:pack.id,priority:pack.priority,policies:accepted});
      }
      return {soft,blocked};
    }

    function attachPack(sourceId,pack={}){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const compatibilityReport=checkPackCompatibility(source.sourceId,pack);
      if(!compatibilityReport.compatible)throw new Error(compatibilityReport.reason);
      const packId=String(pack.id||pack.packId||`pack:${Date.now()}`);
      const kind=normalizePackKind(pack.kind||pack.packType||pack.pack_type||'companion');
      const payload=pack.payload&&typeof pack.payload==='object'?JSON.parse(JSON.stringify(pack.payload)):{};
      const declaredTrustTier=String(pack.trustTier||pack.trust_tier||'auto-generated');
      const legacyInternal=typeof pack.search==='function'||typeof pack.augmentContext==='function';
      let attestation=null;
      if(externalPackVerifier){try{attestation=externalPackVerifier({pack,source:snapshotSource(source),compatibilityReport})||null}catch(error){throw new Error(`PACK_ATTESTATION_FAILED:${String(error?.message||error)}`)}}
      const trustAttested=legacyInternal||attestation?.trusted===true;
      const effectiveTrustTier=trustAttested?String(attestation?.effectiveTrustTier||attestation?.trustTier||declaredTrustTier):'unverified';
      const normalized={
        schema:String(pack.schema||contract.packSchema),id:packId,name:String(pack.name||packId),kind,version:String(pack.version||pack.packVersion||pack.pack_version||'0.0.0'),priority:finite(pack.priority)?Number(pack.priority):0,
        creator:String(pack.creator||pack.creatorId||pack.creator_id||''),declaredTrustTier,trustTier:effectiveTrustTier,trustAttested,attestation:attestation&&typeof attestation==='object'?{trusted:Boolean(attestation.trusted),attestationId:attestation.attestationId||null,verifiedBy:attestation.verifiedBy||null,effectiveTrustTier:effectiveTrustTier}:null,verificationScope:String(pack.verificationScope||pack.verification_scope||attestation?.verificationScope||''),
        sourceFingerprint:source.fingerprint,artifactFingerprint:compatibilityReport.artifactFingerprint,compatibility:{...(pack.compatibility||{}),mode:compatibilityReport.mode},rights:{...(pack.rights||{}),declaration:pack.rightsDeclaration||pack.rights_declaration||pack.rights?.declaration||null},
        payload,search:typeof pack.search==='function'?pack.search:null,augmentContext:typeof pack.augmentContext==='function'?pack.augmentContext:null,metadata:{...(pack.metadata||{})}
      };
      if(!normalized.search)normalized.search=compilePackSearch(normalized);
      const list=attachedPacks.get(source.sourceId)||[];
      const next=[normalized,...list.filter(x=>x.id!==packId)].sort((a,b)=>b.priority-a.priority||a.id.localeCompare(b.id)).slice(0,contract.maxAttachedPacks);
      attachedPacks.set(source.sourceId,next);
      source.precisionState='PRECISION_READY';source.packStateHistory.push({action:'ATTACH',packId,version:normalized.version,artifactFingerprint:normalized.artifactFingerprint,at:new Date().toISOString()});
      return {...listAttachedPacks(source.sourceId).find(x=>x.id===packId),compatibilityReport};
    }

    function detachPack(sourceId,packId){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const list=attachedPacks.get(source.sourceId)||[];
      const next=list.filter(x=>x.id!==String(packId));attachedPacks.set(source.sourceId,next);
      const changed=list.length!==next.length;
      if(changed)source.packStateHistory.push({action:'DETACH',packId:String(packId),at:new Date().toISOString()});
      source.precisionState=next.length?'PRECISION_READY':'BASE';
      return changed;
    }

    function workbookRevealAllowed(source,options={}){
      if(!isWorkbook(source))return true;
      const mode=String(options.workbookMode||source.metadata?.workbookMode||'tutor').toLowerCase();
      return options.revealAnswers===true||source.metadata?.answerRevealAllowed===true||mode==='explain';
    }
    function blockIsRestrictedAnswer(block){
      const m=block?.metadata||{};
      return m.restricted===true||['answer','solution','official-answer','explanation'].includes(String(m.reveal||m.sectionRole||m.role||'').toLowerCase());
    }
    function blockAllowed(source,block,options={}){
      if(isWorkbook(source)&&!workbookRevealAllowed(source,options)&&blockIsRestrictedAnswer(block))return false;
      return true;
    }

    async function packEvidence(source,query,position,options={}){
      const packs=attachedPacks.get(source.sourceId)||[];
      const out=[];
      for(const pack of packs){
        if(!pack.search)continue;
        try{
          const rows=await pack.search({query,source:snapshotSource(source),position:{...position},trustMode:options.trustMode||getTrustMode(source.sourceId),workbookMode:options.workbookMode||source.metadata?.workbookMode||null});
          if(Array.isArray(rows)){
            for(const row of rows.slice(0,4)){
              if(isWorkbook(source)&&!workbookRevealAllowed(source,options)&&blockIsRestrictedAnswer({metadata:row.metadata||row}))continue;
              const refs=[...(Array.isArray(row.sourceRefs)?row.sourceRefs:[]),row.locator].filter(Boolean).map(String);
              for(const ref of refs){
                if(!source.locatorMap.has(ref)&&isBookLike(source)){
                  const m=ref.match(/:book:(\d+):/i);if(m)await loadBookUnitIntoSource(source,Number(m[1]));
                }
              }
              const validRefs=[...new Set(refs.filter(ref=>source.locatorMap.has(ref)))];
              const sourceValidated=validRefs.length>0;
              out.push({packId:pack.id,packName:pack.name,packVersion:pack.version,kind:pack.kind,trustTier:pack.trustTier,verificationScope:pack.verificationScope,artifactFingerprint:pack.artifactFingerprint,sourceValidated,verified:isVerifiedTier(pack.trustTier)&&Boolean(pack.trustAttested)&&sourceValidated,...row,sourceRefs:validRefs});
            }
          }
        }catch(error){out.push({packId:pack.id,error:String(error?.message||error)})}
      }
      return out.slice(0,8);
    }

    const BOOK_HISTORY_RE=/처음|첫\s*등장|전에|이전에|예전|어디서.*나왔|마지막.*봤|previously|first\s+appear|earlier|last\s+seen/i;
    const BOOK_FIRST_RE=/처음|첫\s*등장|first\s+appear/i;
    const cleanHistoryQuery=query=>String(query||'')
      .replace(/처음|첫\s*등장|전에|이전에|예전|어디서|나왔지|나왔어|나왔나요|등장|누구였지|누구야|기억나|previously|first\s+appear(?:ed)?|earlier|last\s+seen/gi,' ')
      .replace(/\s+/g,' ').trim()||String(query||'');

    async function loadBookUnitIntoSource(source,unitOrdinal){
      if(!staticAdapter||typeof staticAdapter.loadUnit!=='function'||!isBookLike(source))return 0;
      const workKey=source.structure?.workKey||source.metadata?.workKey;
      if(!workKey)return 0;
      const loaded=new Set((source.structure?.loadedUnits||[]).map(Number));
      const target=Math.max(1,Number(unitOrdinal)||1);
      if(loaded.has(target))return 0;
      const bundle=await staticAdapter.loadUnit({workKey,unitOrdinal:target,language:source.language||'ko'});
      const incoming=(bundle?.unit?.passages||[]).map((row,index)=>ensureBlock({
        locator:String(row.canonical_locator||`${workKey}:unit:${target}:block:${index+1}`),
        ordinal:finite(row.sequence)?Number(row.sequence):index+1,
        title:String(row.section_title||bundle?.unit?.unit_label||''),
        text:String(row.ko||row.en||''),sourceText:String(row.en||row.ko||''),
        metadata:{unitOrdinal:target,unitKey:bundle?.unit?.unit_key||null,sequence:finite(row.sequence)?Number(row.sequence):null,sourceTextHash:row.source_text_hash||null,translationTextHash:row.translation_text_hash||null,workKey}
      },index,source));
      const byLocator=new Map(source.blocks.map(x=>[x.locator,x]));
      let added=0;for(const block of incoming){if(!byLocator.has(block.locator)){byLocator.set(block.locator,block);added++}}
      source.blocks=[...byLocator.values()].sort((a,b)=>a.ordinal-b.ordinal||a.locator.localeCompare(b.locator));
      source.locatorMap=new Map(source.blocks.map(block=>[block.locator,block]));
      source.lexicalIndex=buildLexicalIndex(source.blocks);
      loaded.add(target);
      source.structure={...(source.structure||{}),loadedUnits:[...loaded].sort((a,b)=>a-b),lazyLookback:true};
      return added;
    }

    async function expandBookLookback(source,query,position,{forceHistory=false}={}){
      if(!isBookLike(source)||!staticAdapter||typeof staticAdapter.loadUnit!=='function')return {loadedUnits:[],historyIntent:false,firstAppearance:false};
      const currentBlock=source.locatorMap.get(String(position?.locator||''));
      const currentUnit=Number(currentBlock?.metadata?.unitOrdinal||source.metadata?.unitOrdinal||(source.structure?.loadedUnits||[]).at(-1)||1);
      const historyIntent=forceHistory||BOOK_HISTORY_RE.test(String(query||''));
      const firstAppearance=BOOK_FIRST_RE.test(String(query||''));
      const loaded=[];
      if(historyIntent){
        for(let unit=1;unit<=currentUnit;unit++){const n=await loadBookUnitIntoSource(source,unit);if(n)loaded.push(unit)}
        return {loadedUnits:loaded,historyIntent,firstAppearance};
      }
      // Generic recall: walk backward lazily until the query has a positive lexical hit.
      for(let unit=currentUnit-1;unit>=1;unit--){
        const n=await loadBookUnitIntoSource(source,unit);if(n)loaded.push(unit);
        const maxOrdinal=finite(position?.ordinal)?Number(position.ordinal):null;
        const probe=lexicalSearch(source,query,{limit:4,maxOrdinal,currentLocator:position?.locator});
        if(probe.some(x=>Number(x.__score)>0))break;
      }
      return {loadedUnits:loaded,historyIntent,firstAppearance};
    }

    function visibilityMaxOrdinal(source,position){
      const shouldBound=isBookLike(source)||source.metadata?.progressBounded===true;
      return shouldBound&&finite(position?.ordinal)?Number(position.ordinal):null;
    }

    async function retrieve({sourceId=activeSourceId,query='',locator=null,limit=contract.maxEvidenceBlocks,trustMode=null,workbookMode=null,revealAnswers=false,queryHints=null}={}){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const mode=trustMode?normalizeTrustMode(trustMode):getTrustMode(source.sourceId);
      const position=locator?{sourceId:source.sourceId,locator,ordinal:source.locatorMap.get(String(locator))?.ordinal??null}:((activePosition?.sourceId===source.sourceId)?activePosition:{sourceId:source.sourceId,locator:source.blocks[0]?.locator||null,ordinal:source.blocks[0]?.ordinal||null});
      const maxOrdinal=visibilityMaxOrdinal(source,position);
      const searchLimit=mode==='STRICT'?Math.min(12,Math.max(limit,contract.maxEvidenceBlocks)):limit;
      let plannerResult=null;
      const suppliedHints=Array.isArray(queryHints)?queryHints.map(String).filter(Boolean):[];
      if(externalRetrievalPlanner){
        try{plannerResult=await externalRetrievalPlanner({query:String(query||''),source:snapshotSource(source),position:{...position},trustMode:mode,maxOrdinal});}catch(error){plannerResult={error:String(error?.message||error)}}
      }
      const plannerHints=Array.isArray(plannerResult?.queryHints)?plannerResult.queryHints.map(String).filter(Boolean):[];
      const attachedPackHints=packQueryHints(source,query);
      const effectiveHints=[...new Set([...suppliedHints,...plannerHints,...attachedPackHints])].slice(0,8);
      let searchQuery=[String(query||''),...effectiveHints].filter(Boolean).join(' ');
      let history={loadedUnits:[],historyIntent:false,firstAppearance:false};
      let rows=lexicalSearch(source,searchQuery,{limit:searchLimit*2,maxOrdinal,currentLocator:position.locator}).filter(row=>blockAllowed(source,row,{workbookMode,revealAnswers}));
      const initialRelevant=rows.some(row=>Number(row.__score)>0);
      if(isBookLike(source)&&(BOOK_HISTORY_RE.test(String(query||''))||!initialRelevant)){
        history=await expandBookLookback(source,searchQuery,position,{forceHistory:BOOK_HISTORY_RE.test(String(query||''))});
        if(history.historyIntent)searchQuery=cleanHistoryQuery(searchQuery);
        rows=lexicalSearch(source,searchQuery,{limit:searchLimit*2,maxOrdinal,currentLocator:position.locator,preferEarliest:history.firstAppearance}).filter(row=>blockAllowed(source,row,{workbookMode,revealAnswers}));
      }
      let chars=0;const evidence=[];
      for(const row of rows){
        if(evidence.length>=searchLimit)break;
        const text=clampText(row.text||row.sourceText,1000);if(evidence.length&&chars+text.length>contract.maxEvidenceChars)continue;
        chars+=text.length;evidence.push({locator:row.locator,ordinal:row.ordinal,title:row.title,text,sourceText:clampText(row.sourceText,1000),metadata:{...row.metadata},score:row.__score,relevant:Number(row.__score)>0});
      }
      const relevantEvidence=evidence.filter(x=>x.relevant);
      return {source:snapshotSource(source),position:{...position},evidence,relevantEvidence,totalChars:chars,policy:{maxOrdinal,fullSourceSent:false,lexicalFirst:true,trustMode:mode,workbookAnswersHidden:isWorkbook(source)&&!workbookRevealAllowed(source,{workbookMode,revealAnswers}),bookHistoryIntent:history.historyIntent,bookFirstAppearanceIntent:history.firstAppearance,lazyLookbackUnits:history.loadedUnits,retrievalPlannerUsed:Boolean(externalRetrievalPlanner),packQueryHintsUsed:attachedPackHints.length>0,queryHints:effectiveHints,plannerError:plannerResult?.error||null}};
    }

    function classifyQuestion(source,question,{answerType=null}={}){
      if(answerType)return String(answerType).toUpperCase();
      const q=String(question||'').toLowerCase();
      if(/해석|의미|상징|왜 .*중요|문학적|신학적|interpret|meaning|symbol|theme|significance/.test(q))return 'INTERPRETATION';
      if(isScripture(source)&&/전통|교파|역사적|tradition|historical context|denomination/.test(q))return 'TRADITION_CONTEXT';
      if(/정답|해설|답은|solution|answer/.test(q))return 'ANSWER_REVEAL';
      return 'TEXTUAL_FACT';
    }

    function highRiskQuestion(source,question,questionType){
      const q=String(question||'');
      const triggers=[];
      if(isScripture(source)&&questionType==='TEXTUAL_FACT')triggers.push('SCRIPTURE_TEXTUAL_FACT');
      if(isStrictDocument(source))triggers.push('STRICT_DOCUMENT');
      if(isWorkbook(source)&&questionType==='ANSWER_REVEAL')triggers.push('WORKBOOK_ANSWER');
      if(/\b\d+(?:[.,]\d+)?\b|\d{4}[-/.]\d{1,2}|\b(year|month|day|days|years|percent|%)\b|년|월|일|기간|금액|원|달러|조항|제\s*\d+\s*조|자동갱신|해지|예외/i.test(q))triggers.push('EXACT_VALUE_OR_CLAUSE');
      if(/인용|quote|verbatim|exact text|정확한 문구/.test(q))triggers.push('QUOTE');
      return {required:triggers.length>0,triggers};
    }

    async function buildContext({sourceId=activeSourceId,question='',locator=null,selection=null,modelPriorHints=null,trustMode=null,answerType=null,workbookMode=null,revealAnswers=false}={}){
      const source=sources.get(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);
      const mode=trustMode?normalizeTrustMode(trustMode):getTrustMode(source.sourceId);
      const trustPolicy=TRUST_POLICIES[mode];
      const retrieval=await retrieve({sourceId:source.sourceId,query:question,locator,trustMode:mode,workbookMode,revealAnswers,queryHints:Array.isArray(modelPriorHints)?modelPriorHints:[]});
      const position=retrieval.position;
      const selected=selection||((activePosition?.sourceId===source.sourceId)?activePosition.selection:null);
      const memories=await memoriesFor(source,question);
      const packs=attachedPacks.get(source.sourceId)||[];
      const packRows=await packEvidence(source,question,position,{trustMode:mode,workbookMode,revealAnswers});
      const qType=classifyQuestion(source,question,{answerType});
      const highRisk=highRiskQuestion(source,question,qType);
      const quality=extractionQuality(source);
      const relevantCount=retrieval.relevantEvidence.length+(selected?.quote?1:0);
      const verifiedPackEvidence=packRows.filter(x=>x.verified&&!x.error);
      let context={
        schema:contract.schema,version:contract.version,
        source:retrieval.source,
        position,
        selection:selected?.quote?{quote:clampText(selected.quote,contract.maxSelectionChars),locator:selected.locator||position.locator||null}:null,
        question:clampText(question,1200),questionType:qType,
        evidence:retrieval.evidence,relevantEvidence:retrieval.relevantEvidence,
        memories,
        packs:{attached:listAttachedPacks(source.sourceId),evidence:packRows,verifiedEvidenceCount:verifiedPackEvidence.length,precisionState:source.precisionState||'BASE',policyBundle:packPolicyBundle(source)},
        modelPrior:{allowed:trustPolicy.modelPriorAllowed,purpose:mode==='EXPLORE'?'active-reasoning-and-retrieval-aid':'reasoning-aid-and-retrieval-hints-not-source-authority',hints:Array.isArray(modelPriorHints)?modelPriorHints.slice(0,12):[]},
        grounding:{sourceRequiredForSourceSpecificFacts:true,sourceFingerprint:source.fingerprint,fullSourceSent:false,evidenceChars:retrieval.totalChars,relevantEvidenceCount:relevantCount,verifiedPackEvidenceCount:verifiedPackEvidence.length,citationRequired:trustPolicy.citationRequired},
        trust:{mode,policy:{...trustPolicy},recommendedMode:recommendTrustMode(source),highRisk,extractionQuality:quality,strictReady:!(quality.status==='LOW'||(finite(quality.score)&&quality.score<0.7)),unknownIsValid:mode==='STRICT'},
        visibility:{maxOrdinal:retrieval.policy.maxOrdinal,workbookAnswersHidden:retrieval.policy.workbookAnswersHidden,spoilerBounded:isBookLike(source)||source.metadata?.progressBounded===true},
        policy:{conversationReady:source.ingestState==='CONVERSATION_READY'||source.ingestState==='PRECISION_READY',noMandatoryKnowledgePrecompute:true,lexicalFirst:true,maxEvidenceBlocks:contract.maxEvidenceBlocks,maxEvidenceChars:contract.maxEvidenceChars,visibilityMaxOrdinal:retrieval.policy.maxOrdinal}
      };
      for(const pack of packs){
        if(!pack.augmentContext)continue;
        try{const next=await pack.augmentContext({context,source:snapshotSource(source),trustMode:mode});if(next&&typeof next==='object')context=next}catch(_){ }
      }
      return context;
    }

    function sourceRefsFromContext(context){
      const refs=[];
      if(context?.selection?.locator)refs.push(context.selection.locator);
      for(const row of (context?.relevantEvidence||[]))if(row.locator&&!refs.includes(row.locator))refs.push(row.locator);
      return refs.slice(0,8);
    }
    function packRefsFromContext(context){
      const seen=new Set();const out=[];
      for(const row of (context?.packs?.evidence||[])){
        if(!row.packId||seen.has(row.packId)||row.error)continue;seen.add(row.packId);
        out.push({id:row.packId,name:row.packName||row.packId,version:row.packVersion||null,trustTier:row.trustTier||'unverified',verificationScope:row.verificationScope||'',artifactFingerprint:row.artifactFingerprint||null,sourceValidated:Boolean(row.sourceValidated),verified:Boolean(row.verified)});
      }
      return out;
    }
    function validSourceRefs(context,refs){
      const allowed=new Set([context?.position?.locator,context?.selection?.locator,...(context?.evidence||[]).map(x=>x.locator)].filter(Boolean));
      return [...new Set((Array.isArray(refs)?refs:[]).map(String))].filter(x=>allowed.has(x));
    }
    function exactClaimSupported(context,claim){
      const refs=validSourceRefs(context,claim?.sourceRefs||claim?.evidenceLocators||[]);
      if(!refs.length)return false;
      const exact=String(claim?.exactValue??claim?.quote??'').trim().toLowerCase();
      if(!exact)return true;
      return refs.some(ref=>{
        const row=(context.evidence||[]).find(x=>x.locator===ref);
        const text=`${row?.text||''} ${row?.sourceText||''}`.toLowerCase();
        return text.includes(exact);
      });
    }

    function provenanceFor(context,{providerUsed=false,providerResult=null}={}){
      const requestedRefs=providerUsed?(providerResult?.sourceRefs||providerResult?.sources||[]):sourceRefsFromContext(context);
      const sourceRefs=validSourceRefs(context,requestedRefs);
      const packRefs=packRefsFromContext(context);
      const verifiedPack=packRefs.find(x=>x.verified);
      let label='UNCERTAIN';
      let reason='insufficient-grounding';
      if(context.questionType==='INTERPRETATION'||String(providerResult?.provenance||providerResult?.label||'').toUpperCase()==='INTERPRETATION'){
        label='INTERPRETATION';reason='interpretive-answer-separated-from-textual-fact';
      }else if(verifiedPack&&packRefs.length){label='VERIFIED';reason='verified-pack-evidence-used';
      }else if(packRefs.length){label='PACK_ASSISTED';reason='attached-pack-evidence-used';
      }else if(sourceRefs.length){label='SOURCE_GROUNDED';reason='source-locator-evidence-used';
      }else if(providerUsed&&context.trust.mode==='EXPLORE'){label='AI_NATIVE';reason='explore-mode-model-answer-without-source-evidence';}
      return {label,reason,trustMode:context.trust.mode,sourceRefs,packRefs,verificationTier:verifiedPack?.trustTier||null,sourceFingerprint:context.source.fingerprint,questionType:context.questionType};
    }

    function deterministicAnswer(context){
      if(context?.trust?.mode==='STRICT'&&!context?.trust?.strictReady)return {route:'UNCERTAIN',title:'NEEDS REVIEW',body:'이 Source는 현재 추출 품질이 Strict 기준에 부족하여 확정 답변을 만들 수 없습니다.',source:null};
      if(context?.visibility?.workbookAnswersHidden&&context?.questionType==='ANSWER_REVEAL')return {route:'UNCERTAIN',title:'정답 숨김',body:'현재 문제 풀이 모드에서는 정답/해설 영역을 자동으로 노출하지 않습니다.',source:context.position?.locator||null};
      if(context?.selection?.quote)return {route:'SOURCE_GROUNDED',title:'선택한 Source',body:`선택한 구간을 기준으로 보면 “${clampText(context.selection.quote,500)}”입니다.`,source:context.selection.locator||context.position?.locator||null};
      const first=context?.relevantEvidence?.[0];
      if(first)return {route:context?.packs?.evidence?.some(x=>!x.error)?'PACK_ASSISTED':'SOURCE_GROUNDED',title:'Source 근거',body:clampText(first.text||first.sourceText,800),source:(context.relevantEvidence||[]).slice(0,3).map(x=>x.locator).join(' · ')};
      if(context?.trust?.mode==='EXPLORE')return {route:'AI_NATIVE',title:'AI 설명 가능',body:'현재 Source에서 직접 근거를 찾지 못했습니다. 모델의 일반 지식과 추론을 사용하되 Source-specific 사실은 확정하지 않습니다.',source:null};
      return {route:'UNCERTAIN',title:context?.trust?.mode==='STRICT'?'UNKNOWN / NEEDS REVIEW':'근거 부족',body:'현재 Source에서 이 답을 충분히 확인할 근거를 찾지 못했습니다.',source:context?.position?.locator||null};
    }

    function validateProviderAnswer(context,raw){
      const obj=raw&&typeof raw==='object'?raw:{body:String(raw??'')};
      const mode=context.trust.mode;
      const sourceRefs=validSourceRefs(context,obj.sourceRefs||obj.sources||[]);
      const claims=Array.isArray(obj.claims)?obj.claims:[];
      const packRefs=packRefsFromContext(context);
      const verifiedPack=packRefs.some(x=>x.verified);
      const relevantSource=context.grounding.relevantEvidenceCount>0||Boolean(context.selection?.quote);
      const interpretation=context.questionType==='INTERPRETATION'||String(obj.provenance||obj.label||'').toUpperCase()==='INTERPRETATION';
      const validation={status:'PASS',issues:[],sourceRefs,claimChecks:[],providerProvenance:String(obj.provenance||obj.label||'')||null};

      if(context.visibility.workbookAnswersHidden&&context.questionType==='ANSWER_REVEAL'){
        validation.status='BLOCKED';validation.issues.push('WORKBOOK_ANSWER_REVEAL_BLOCKED');return validation;
      }
      if(mode==='STRICT'&&!context.trust.strictReady){validation.status='BLOCKED';validation.issues.push('STRICT_EXTRACTION_QUALITY_TOO_LOW');return validation;}
      if((mode==='GROUNDED'||mode==='STRICT')&&!interpretation&&!sourceRefs.length&&!verifiedPack){
        validation.status='BLOCKED';validation.issues.push('CITATION_REQUIRED_FOR_FACTUAL_ANSWER');
      }
      if(mode==='STRICT'&&!interpretation&&!relevantSource&&!verifiedPack){validation.status='BLOCKED';validation.issues.push('STRICT_SOURCE_EVIDENCE_REQUIRED');}
      for(const claim of claims){
        const highRisk=claim?.highRisk===true||['number','date','amount','clause','name','quote','verse','answer','condition','exception'].includes(String(claim?.kind||'').toLowerCase());
        const supported=exactClaimSupported(context,claim);
        validation.claimChecks.push({kind:claim?.kind||'fact',text:clampText(claim?.text||'',240),highRisk,supported});
        if((mode==='STRICT'||(mode==='GROUNDED'&&highRisk))&&!supported){validation.status='BLOCKED';validation.issues.push(`UNSUPPORTED_${String(claim?.kind||'CLAIM').toUpperCase()}`);}
      }
      validation.issues=[...new Set(validation.issues)];
      return validation;
    }

    function setProvider(fn){modelProvider=typeof fn==='function'?fn:null;return Boolean(modelProvider)}
    function setMemoryProvider(fn){externalMemoryProvider=typeof fn==='function'?fn:null;return Boolean(externalMemoryProvider)}
    function setRetrievalPlanner(fn){externalRetrievalPlanner=typeof fn==='function'?fn:null;return Boolean(externalRetrievalPlanner)}
    function setPackVerifier(fn){externalPackVerifier=typeof fn==='function'?fn:null;return Boolean(externalPackVerifier)}

    async function answer(args={}){
      const context=await buildContext(args);
      const base=deterministicAnswer(context);
      if(!modelProvider){
        const provenance=provenanceFor(context,{providerUsed:false,providerResult:null});
        const finalLabel=base.route==='AI_NATIVE'?'AI_NATIVE':base.route==='UNCERTAIN'?'UNCERTAIN':provenance.label;
        return {...base,provenance:{...provenance,label:finalLabel},validation:{status:base.route==='UNCERTAIN'?'NEEDS_REVIEW':'PASS',issues:[]},context,providerMode:'deterministic'};
      }
      const raw=await modelProvider({question:String(args.question||''),context,modelPrior:context.modelPrior,grounding:context.grounding,trust:context.trust,visibility:context.visibility,requiredOutput:{sourceRefs:context.trust.policy.citationRequired,claimEvidence:context.trust.policy.exactVerification,provenanceLabels:contract.provenanceLabels}});
      const validation=validateProviderAnswer(context,raw);
      if(validation.status==='BLOCKED'){
        const fallback=deterministicAnswer(context);
        const uncertain={route:'UNCERTAIN',title:context.trust.mode==='STRICT'?'UNKNOWN / NEEDS REVIEW':'근거 부족',body:fallback.route==='UNCERTAIN'?fallback.body:'제공된 AI 답변은 현재 Trust Mode의 근거 조건을 충족하지 못해 확정 답변으로 표시하지 않습니다.',source:fallback.source||null};
        return {...uncertain,provenance:{...provenanceFor(context,{providerUsed:true,providerResult:raw}),label:'UNCERTAIN',reason:'post-validation-blocked'},validation,context,providerMode:'external-blocked'};
      }
      const rawObj=typeof raw==='string'?{body:raw}:raw&&typeof raw==='object'?raw:{};
      const provenance=provenanceFor(context,{providerUsed:true,providerResult:rawObj});
      const route=provenance.label;
      const result={...base,...rawObj,route,provenance,validation,context,providerMode:'external'};
      if(!result.source&&provenance.sourceRefs.length)result.source=provenance.sourceRefs.join(' · ');
      return result;
    }

    function onStateChange(fn){if(typeof fn!=='function')return ()=>{};stateListeners.add(fn);return ()=>stateListeners.delete(fn)}
    function status(){return {schema:contract.schema,version:contract.version,sourceCount:sources.size,activeSourceId,activePosition:getPosition(),sources:listSources(),localMemoryCount:localMemories.length,attachedPackCount:[...attachedPacks.values()].reduce((n,x)=>n+x.length,0),attachedPacks:Object.fromEntries([...sources.keys()].map(id=>[id,listAttachedPacks(id)])),providerInstalled:Boolean(modelProvider),retrievalPlannerInstalled:Boolean(externalRetrievalPlanner),packVerifierInstalled:Boolean(externalPackVerifier),trustModes:{...Object.fromEntries([...sources.keys()].map(id=>[id,getTrustMode(id)]))}}}

    const api={contract,registerSourceAdapter,ingest,listSources,getSource:snapshotSource,setActiveSource,setPosition,getPosition,retrieve,buildContext,answer,addMemory,attachPack,detachPack,listAttachedPacks,checkPackCompatibility,setProvider,setMemoryProvider,setRetrievalPlanner,setPackVerifier,onStateChange,status,recommendTrustMode,setTrustMode,getTrustMode,classifyQuestion};
    return Object.freeze(api);
  }


  const api={STORYMEMORY_UNIVERSAL_SOURCE_CONTRACT,createStoryMemoryUniversalSourceRuntime,createDocumentAdapter,createTranscriptAdapter,createBookAdapter};
  return api;
});
