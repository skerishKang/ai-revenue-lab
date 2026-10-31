/* StoryMemory R6 private refactor: legacy Hybrid AI router quarantine.
   Behavior-preserving extraction only. NOT AUTHORIZED for #1129 live provider execution. */
/* ===== StoryMemory v3.3.6 — Hybrid AI Context Retrieval =====
   Static corpus is authoritative text. Neon contributes bounded metadata/knowledge/user Memory only.
   No full-book body is sent to an AI provider. */
const STORYMEMORY_HYBRID_AI_CONTRACT=Object.freeze({
  version:'1.0.0',
  schema:'storymemory-hybrid-ai-context-1.0',
  maxEvidencePassages:6,
  maxStaticUnits:3,
  maxEvidenceChars:6000,
  maxAnswerCards:4,
  maxRelationships:8,
  maxMemories:6,
  maxEntities:8
});

function createStoryMemoryHybridAIAdapter({
  remoteAdapter=(typeof storyMemoryRemote!=='undefined'?storyMemoryRemote:null),
  staticAdapter=(typeof storyMemoryStatic!=='undefined'?storyMemoryStatic:null),
  contentResolver=(typeof storyMemoryResolveContent==='function'?storyMemoryResolveContent:(x=>x)),
  dbWorkKeyResolver=(typeof storyMemoryDbWorkKey==='function'?storyMemoryDbWorkKey:(x=>x?.workKey||x?.work_key||null)),
  staticWorkKeyResolver=(typeof storyMemoryStaticWorkKey==='function'?storyMemoryStaticWorkKey:(x=>x?.workKey||x?.work_key||null)),
  contract=STORYMEMORY_HYBRID_AI_CONTRACT
}={}){
  let provider=null;
  const eq=value=>`eq.${value}`;
  const inList=values=>`in.(${values.join(',')})`;
  const finite=v=>Number.isFinite(Number(v));
  const norm=v=>String(v??'').replace(/\\s+/g,' ').trim();
  const clip=(v,n=700)=>{const s=norm(v);return s.length>n?s.slice(0,Math.max(0,n-1))+'…':s};
  const terms=q=>[...new Set((String(q||'').toLowerCase().match(/[a-z0-9가-힣]{2,}/g)||[]).filter(x=>!['what','who','where','when','this','that','with','from','about','please','설명','무엇','누구','어디','현재','본문','부분','알려','주세요'].includes(x)))].slice(0,12);
  const scoreText=(text,ts)=>{const s=String(text||'').toLowerCase();return ts.reduce((n,x)=>n+(s.includes(x)?1:0),0)};
  const safeSeq=(row,currentSequence,fields=['source_sequence','evidence_sequence','first_visible_sequence','sequence'])=>{
    if(!finite(currentSequence))return true;
    const values=fields.map(k=>row?.[k]).filter(finite).map(Number);
    return values.every(v=>v<=Number(currentSequence));
  };
  function unitOrdinalFromLocator(locator,fallback=1){
    const s=String(locator||'');
    let m=s.match(/:book:(\\d{1,3}):/);if(m)return Math.max(1,Number(m[1]));
    m=s.match(/:canto:inferno-(\\d{1,3}):/);if(m)return Math.max(1,Number(m[1]));
    m=s.match(/:canto:purgatorio-(\\d{1,3}):/);if(m)return 34+Math.max(1,Number(m[1]));
    m=s.match(/:canto:paradiso-(\\d{1,3}):/);if(m)return 67+Math.max(1,Number(m[1]));
    return Math.max(1,Number(fallback)||1);
  }
  function selectedEntityIds(question,entities=[],aliases=[],mentions=[],canonicalLocator=null){
    const q=String(question||'').toLowerCase();
    const ids=new Set();
    entities.forEach(e=>{if(norm(e.canonical_name)&&q.includes(norm(e.canonical_name).toLowerCase()))ids.add(e.id)});
    aliases.forEach(a=>{if(norm(a.alias)&&q.includes(norm(a.alias).toLowerCase()))ids.add(a.entity_id)});
    if(!ids.size&&canonicalLocator){
      mentions.filter(m=>m.canonical_locator===canonicalLocator).forEach(m=>ids.add(m.entity_id));
    }
    return ids;
  }
  async function remoteSnapshot({workKey,question,currentSequence,canonicalLocator}={}){
    if(!remoteAdapter||!workKey||typeof remoteAdapter.getWorkByKey!=='function'||typeof remoteAdapter.request!=='function')return {mode:'unavailable',work:null,entities:[],aliases:[],mentions:[],relationships:[],answerCards:[],answerCardSources:[],memories:[]};
    try{
      const work=await remoteAdapter.getWorkByKey(workKey);
      if(!work)return {mode:'unavailable',work:null,entities:[],aliases:[],mentions:[],relationships:[],answerCards:[],answerCardSources:[],memories:[]};
      const req=(table,select,extra={})=>remoteAdapter.request(table,{query:{select,work_id:eq(work.id),...extra}});
      const [entities0,aliases0,mentions0,relationships0,cards0,memories0]=await Promise.all([
        req('entities','id,work_id,entity_type,canonical_name,normalized_key,metadata',{order:'canonical_name.asc',limit:500}),
        req('entity_aliases','id,work_id,entity_id,alias,normalized_alias,locale,metadata',{order:'normalized_alias.asc',limit:1000}),
        req('entity_mentions','id,work_id,entity_id,source_passage_id,canonical_locator,source_sequence,source_text_hash,surface_text,start_offset,end_offset,confidence,metadata',{limit:1500}),
        req('entity_relationships','id,work_id,from_entity_id,to_entity_id,relationship_type,source_passage_id,evidence_canonical_locator,evidence_sequence,evidence_text_hash,first_visible_locator,first_visible_sequence,metadata',{order:'first_visible_sequence.asc',limit:1000}),
        req('answer_cards','id,work_id,entity_id,card_key,question_key,route_class,answer_body,first_visible_locator,first_visible_sequence,metadata,enabled',{enabled:eq('true'),order:'first_visible_sequence.asc',limit:500}),
        req('memories','id,work_id,source_passage_id,canonical_locator,source_sequence,unit_key,semantic_page,content_version_key,source_preview,memory_type,title,body,quote,metadata,created_at,updated_at',{order:'created_at.desc',limit:100})
      ]);
      const entities=Array.isArray(entities0)?entities0:[],aliases=Array.isArray(aliases0)?aliases0:[];
      const mentions=(Array.isArray(mentions0)?mentions0:[]).filter(x=>safeSeq(x,currentSequence));
      const targetIds=selectedEntityIds(question,entities,aliases,mentions,canonicalLocator);
      const ts=terms(question);
      const relationships=(Array.isArray(relationships0)?relationships0:[]).filter(x=>safeSeq(x,currentSequence)).filter(x=>
        !targetIds.size||targetIds.has(x.from_entity_id)||targetIds.has(x.to_entity_id)||x.evidence_canonical_locator===canonicalLocator
      ).slice(0,contract.maxRelationships);
      let answerCards=(Array.isArray(cards0)?cards0:[]).filter(x=>safeSeq(x,currentSequence,['first_visible_sequence']));
      answerCards=answerCards.map(x=>({...x,__score:(targetIds.has(x.entity_id)?8:0)+scoreText(`${x.card_key} ${x.question_key} ${x.answer_body}`,ts)+(x.first_visible_locator===canonicalLocator?4:0)}))
        .filter(x=>x.__score>0||(!ts.length&&x.first_visible_locator===canonicalLocator)).sort((a,b)=>b.__score-a.__score).slice(0,contract.maxAnswerCards);
      let answerCardSources=[];
      const cardIds=answerCards.map(x=>x.id).filter(Boolean);
      if(cardIds.length){
        const rows=await remoteAdapter.request('answer_card_sources',{query:{select:'answer_card_id,source_passage_id,canonical_locator,source_sequence,source_text_hash,citation_order,citation_role',answer_card_id:inList(cardIds),order:'citation_order.asc',limit:100}});
        answerCardSources=(Array.isArray(rows)?rows:[]).filter(x=>safeSeq(x,currentSequence));
      }
      const entityNames=entities.filter(e=>targetIds.has(e.id)).map(e=>norm(e.canonical_name).toLowerCase()).filter(Boolean);
      let memories=(Array.isArray(memories0)?memories0:[]).filter(x=>safeSeq(x,currentSequence));
      memories=memories.map(x=>({...x,__score:(x.canonical_locator===canonicalLocator?8:0)+scoreText(`${x.title} ${x.body} ${x.quote} ${x.source_preview}`,ts)+entityNames.reduce((n,name)=>n+(String(`${x.title} ${x.body} ${x.quote}`).toLowerCase().includes(name)?2:0),0)}))
        .filter(x=>x.__score>0).sort((a,b)=>b.__score-a.__score).slice(0,contract.maxMemories);
      return {mode:'remote',work,entities:entities.filter(e=>targetIds.has(e.id)).slice(0,contract.maxEntities),aliases:aliases.filter(a=>targetIds.has(a.entity_id)).slice(0,20),mentions:mentions.filter(m=>targetIds.has(m.entity_id)||m.canonical_locator===canonicalLocator).slice(0,20),relationships,answerCards,answerCardSources,memories};
    }catch(error){
      return {mode:'unavailable',work:null,entities:[],aliases:[],mentions:[],relationships:[],answerCards:[],answerCardSources:[],memories:[],error:String(error?.message||error||'REMOTE_CONTEXT_ERROR')};
    }
  }
  async function staticEvidence({staticWorkKey,question,canonicalLocator,currentSequence,unitOrdinal,remote}={}){
    if(!staticAdapter||!staticWorkKey||typeof staticAdapter.loadUnit!=='function')return {mode:'unavailable',passages:[],loadedUnits:[],error:'STATIC_ADAPTER_UNAVAILABLE'};
    const desired=[];
    const add=(locator,role,sequence=null)=>{if(locator&&!desired.some(x=>x.locator===locator))desired.push({locator,role,sequence})};
    add(canonicalLocator,'current',currentSequence);
    (remote?.answerCardSources||[]).forEach(x=>add(x.canonical_locator,'answer-card',x.source_sequence));
    (remote?.relationships||[]).forEach(x=>add(x.evidence_canonical_locator,'relationship',x.evidence_sequence));
    (remote?.mentions||[]).forEach(x=>add(x.canonical_locator,'mention',x.source_sequence));
    const ordinals=[];
    const addOrdinal=o=>{o=Math.max(1,Number(o)||1);if(!ordinals.includes(o)&&ordinals.length<contract.maxStaticUnits)ordinals.push(o)};
    addOrdinal(unitOrdinalFromLocator(canonicalLocator,unitOrdinal));
    desired.forEach(x=>addOrdinal(unitOrdinalFromLocator(x.locator,unitOrdinal)));
    const bundles=[];
    try{
      for(const ordinal of ordinals)bundles.push(await staticAdapter.loadUnit({workKey:staticWorkKey,unitOrdinal:ordinal,language:'ko'}));
    }catch(error){return {mode:'unavailable',passages:[],loadedUnits:ordinals,error:String(error?.message||error||'STATIC_EVIDENCE_ERROR')}}
    const ts=terms(question);
    const desiredMap=new Map(desired.map((x,i)=>[x.locator,{...x,priority:100-i}]));
    const rows=[];
    bundles.forEach(bundle=>(bundle?.unit?.passages||[]).forEach(p=>{
      if(finite(currentSequence)&&finite(p.sequence)&&Number(p.sequence)>Number(currentSequence))return;
      const d=desiredMap.get(p.canonical_locator);
      const text=`${p.section_title||''} ${p.en||''} ${p.ko||''}`;
      const termScore=scoreText(text,ts);
      const distance=finite(currentSequence)&&finite(p.sequence)?Math.abs(Number(currentSequence)-Number(p.sequence)):999999;
      const score=(d?.priority||0)+(termScore*15)+(p.canonical_locator===canonicalLocator?200:0)-Math.min(30,distance/10000);
      if(d||termScore||p.canonical_locator===canonicalLocator)rows.push({p,bundle,score,role:d?.role||'relevant'});
    }));
    rows.sort((a,b)=>b.score-a.score||Number(a.p.sequence||0)-Number(b.p.sequence||0));
    const picked=[];let chars=0;
    for(const x of rows){
      if(picked.length>=contract.maxEvidencePassages)break;
      const en=clip(x.p.en,850),ko=clip(x.p.ko,850);
      const cost=en.length+ko.length;
      if(picked.length&&chars+cost>contract.maxEvidenceChars)continue;
      chars+=cost;
      picked.push({canonical_locator:x.p.canonical_locator,sequence:x.p.sequence,unit_key:x.bundle?.unit?.unit_key||null,section_title:x.p.section_title||null,en,ko,source_text_hash:x.p.source_text_hash||null,translation_text_hash:x.p.translation_text_hash||null,role:x.role});
    }
    return {mode:'static',passages:picked,loadedUnits:ordinals,totalChars:chars};
  }
  function boundKnowledge(remote,currentSequence){
    const clean=x=>{const y={...x};delete y.__score;return y};
    return {
      entities:(remote?.entities||[]).slice(0,contract.maxEntities).map(clean),
      relationships:(remote?.relationships||[]).slice(0,contract.maxRelationships).map(clean),
      answerCards:(remote?.answerCards||[]).slice(0,contract.maxAnswerCards).map(x=>({...clean(x),answer_body:clip(x.answer_body,900)})),
      answerCardSources:(remote?.answerCardSources||[]).slice(0,20).map(clean),
      memories:(remote?.memories||[]).slice(0,contract.maxMemories).map(x=>({...clean(x),body:clip(x.body,500),quote:clip(x.quote,350),source_preview:clip(x.source_preview,250)})),
      spoilerMaxSequence:finite(currentSequence)?Number(currentSequence):null
    };
  }
  async function buildContext({question,content,workKey,staticWorkKey,unitOrdinal=1,canonicalLocator=null,currentSequence=null,semanticPage=0,selection=null}={}){
    const resolved=contentResolver(content)||content||null;
    const dbKey=workKey||dbWorkKeyResolver(resolved);
    const staticKey=staticWorkKey||staticWorkKeyResolver(resolved)||dbKey;
    const remote=await remoteSnapshot({workKey:dbKey,question,currentSequence,canonicalLocator});
    const evidence=await staticEvidence({staticWorkKey:staticKey,question,canonicalLocator,currentSequence,unitOrdinal,remote});
    const packet={
      schema:contract.schema,version:contract.version,
      question:clip(question,1000),
      position:{work_key:dbKey||null,static_work_key:staticKey||null,unit_ordinal:Math.max(1,Number(unitOrdinal)||1),canonical_locator:canonicalLocator||null,current_sequence:finite(currentSequence)?Number(currentSequence):null,semantic_page:Math.max(0,Number(semanticPage)||0)},
      selection:selection?.quote?{quote:clip(selection.quote,1200),source:clip(selection.source,300)}:null,
      knowledge:boundKnowledge(remote,currentSequence),
      evidence:evidence.passages||[],
      retrieval:{remote_mode:remote.mode,static_mode:evidence.mode,loaded_units:evidence.loadedUnits||[],evidence_chars:evidence.totalChars||0,remote_error:remote.error||null,static_error:evidence.error||null},
      policy:{spoiler_safe:true,no_future_sequence:true,full_book_body_sent:false,max_evidence_passages:contract.maxEvidencePassages,max_evidence_chars:contract.maxEvidenceChars}
    };
    return packet;
  }
  function deterministicAnswer(context){
    const cards=context?.knowledge?.answerCards||[];
    const evidence=context?.evidence||[];
    if(context?.selection?.quote){
      return {route:'SUPPORTED_TEXT',title:'선택한 본문',body:`선택한 구간은 “${clip(context.selection.quote,420)}”입니다. 현재 읽은 위치와 정적 원문 범위를 넘어서 사실을 추가하지 않습니다.`,source:context.selection.source||context.position.canonical_locator||'현재 본문',spoilerBlocked:false};
    }
    if(cards.length){
      const body=cards.slice(0,2).map(x=>clip(x.answer_body,700)).filter(Boolean).join(' ');
      const locators=[...new Set((context.knowledge.answerCardSources||[]).map(x=>x.canonical_locator).filter(Boolean))].slice(0,4);
      return {route:'KNOWN_FACT',title:'검증된 Memory',body:body||'현재 읽은 범위의 검증된 answer card를 찾았습니다.',source:locators.join(' · ')||context.position.canonical_locator||'Neon answer card',spoilerBlocked:false};
    }
    if(evidence.length){
      const first=evidence[0];
      return {route:'SUPPORTED_TEXT',title:'현재 본문 근거',body:`현재 공개 범위의 정적 본문에서 확인되는 내용입니다. ${clip(first.ko||first.en,700)}`,source:evidence.slice(0,3).map(x=>x.canonical_locator).join(' · '),spoilerBlocked:false};
    }
    return {route:'UNKNOWN',title:'현재 범위에서 확인되지 않음',body:'현재 읽은 범위의 정적 본문과 검증된 관계/Memory에서 답변 근거를 찾지 못했습니다. 추측해서 답하지 않습니다.',source:context?.position?.canonical_locator||'현재 공개 범위',spoilerBlocked:false};
  }
  function setProvider(fn){provider=typeof fn==='function'?fn:null;return Boolean(provider)}
  async function answer(args={}){
    const context=await buildContext(args);
    if(provider){
      const raw=await provider({question:String(args.question||''),context});
      if(typeof raw==='string')return {...deterministicAnswer(context),body:raw,context,providerMode:'external'};
      if(raw&&typeof raw==='object')return {...deterministicAnswer(context),...raw,context,providerMode:'external'};
    }
    return {...deterministicAnswer(context),context,providerMode:'deterministic'};
  }
  return Object.freeze({contract,buildContext,answer,setProvider,unitOrdinalFromLocator});
}

const storyMemoryHybridAI=createStoryMemoryHybridAIAdapter();
window.storyMemoryHybridAI=storyMemoryHybridAI;
window.createStoryMemoryHybridAIAdapter=createStoryMemoryHybridAIAdapter;
window.installStoryMemoryAIProvider=fn=>storyMemoryHybridAI.setProvider(fn);

function storyMemoryHybridCurrentArgs(question,selection=null){
  let content=null,exact=null;
  try{content=storyMemoryResumeContent?.()||storyMemoryReaderContentForContext?.({kind:__smCurrentReaderKind,book:__smCurrentReaderLabel})||null}catch(_){}
  try{exact=storyMemoryExactResumeSnapshot?.()||null}catch(_){}
  return {
    question,content,workKey:storyMemoryDbWorkKey?.(content)||null,staticWorkKey:storyMemoryStaticWorkKey?.(content)||null,
    unitOrdinal:Math.max(1,Number(exact?.unitOrdinal||__smDynamicReaderState?.unitOrdinal)||1),
    canonicalLocator:exact?.canonicalLocator||null,currentSequence:exact?.sourceSequence??null,semanticPage:Number(exact?.page??readerPageIndex)||0,selection
  };
}
async function storyMemorySubmitHybridQuestion(question,{selection=null,delay=80}={}){
  const q=String(question||'').trim();if(!q)return null;
  appendUserMessage(q,selection);
  try{
    const args=storyMemoryHybridCurrentArgs(q,selection);
    if(!args.staticWorkKey)throw new Error('NO_STATIC_WORK_FOR_CURRENT_CONTEXT');
    const result=await storyMemoryHybridAI.answer(args);
    setTimeout(()=>appendAIMessage(result.title,result.body,result.source,{...result,question:q,packet:selection,hybridContext:result.context}),delay);
    return result;
  }catch(error){
    const fallback=routeCompanionQuestion(q,{selection});
    setTimeout(()=>appendAIMessage(fallback.title,fallback.body,fallback.source,{...fallback,question:q,packet:selection,hybridFallback:String(error?.message||error)}),delay);
    return fallback;
  }
}
window.storyMemorySubmitHybridQuestion=storyMemorySubmitHybridQuestion;

// #1129 live integration quarantine: keep legacy callable APIs, but never own live UI unless explicitly enabled for isolated diagnostics.
if(window.__smLegacyHybridUIEnabled===true){
sendChat=async function(){
  const input=document.getElementById('askInput');const q=input.value.trim();if(!q)return;
  const selection=selectedContextText?{quote:selectedContextText,source:selectedContextMeta?.source||__smCurrentReaderLabel}:null;
  input.value='';
  await storyMemorySubmitHybridQuestion(q,{selection,delay:120});
  selectedContextText='';selectedContextMeta=null;selectionChip.classList.remove('show');selectionChipMeta.textContent='';
};
const __smV334Send=document.getElementById('sendBtn');if(__smV334Send)__smV334Send.onclick=sendChat;
if(typeof __smQuickHost!=='undefined'&&__smQuickHost){
  __smQuickHost.addEventListener('click',e=>{
    const b=e.target.closest?.('button');if(!b||!__smQuickHost.contains(b))return;
    e.preventDefault();e.stopImmediatePropagation();
    const q=b.dataset.query||b.textContent||'';storyMemorySubmitHybridQuestion(q,{delay:100});
  },true);
}
askPreset=function(key){
  const button=[...document.querySelectorAll('.quick button')].find(b=>b.dataset.q===key)||document.querySelector(`[data-q="${CSS.escape(key)}"]`);
  const q=button?.dataset.query||button?.textContent||key;return storyMemorySubmitHybridQuestion(q,{delay:100});
};
}
window.__smLegacyHybridAIQuarantinedV1=true;

document.documentElement.dataset.storymemoryBuild='v3.3.4-hybrid-ai-context';
