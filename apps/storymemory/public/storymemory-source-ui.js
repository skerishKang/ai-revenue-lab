(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){root.StoryMemorySourceUI=api;if(root.document)api.install(root)}
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const CONTRACT=Object.freeze({schema:'storymemory-source-ui-1.0',version:'1.0.0',supportedKinds:['book','document','workbook','transcript']});
  const FIXTURES=Object.freeze([
    {
      id:'source-contract-demo',kind:'contract',label:'PDF / CONTRACT',title:'서비스 이용 계약서',note:'조항·날짜·금액을 Source 근거로 확인',progress:46,trust:'STRICT',icon:'PDF',
      spec:{sourceId:'source-contract-demo',sourceType:'contract',title:'서비스 이용 계약서',ownerScope:'user-private',rightsMode:'user-supplied',revision:'2026-08-27-r1',fingerprint:'demo-contract-20260827-r1',language:'ko',metadata:{profile:'contract',strictRecommended:true,purpose:'exact work',locatorScheme:'page-block',extractionQuality:{score:.98,status:'HIGH'}},pages:[
        {page:1,title:'계약 개요',blocks:[{locator:'doc:source-contract-demo:page:1:block:1',title:'제1조 목적',text:'본 계약은 서비스 제공자와 이용자 사이의 서비스 이용 조건과 권리·의무를 정하는 것을 목적으로 한다.'}]},
        {page:2,title:'계약기간',blocks:[{locator:'doc:source-contract-demo:page:2:block:1',title:'제4조 계약기간 및 갱신',text:'계약기간은 서명일로부터 12개월로 한다. 어느 한쪽이 만료 30일 전까지 서면으로 갱신 거절을 통지하지 않으면 동일 조건으로 12개월 연장한다.'}]},
        {page:3,title:'이용요금',blocks:[{locator:'doc:source-contract-demo:page:3:block:1',title:'제8조 이용요금',text:'월 이용요금은 49,000원이며 매월 5일까지 지정된 결제수단으로 납부한다.'}]}
      ]}
    },
    {
      id:'source-workbook-demo',kind:'workbook',label:'WORKBOOK',title:'미적분 연습문제',note:'문제 단위 위치 + Tutor 정답 공개 제어',progress:28,trust:'GROUNDED',icon:'Q',
      spec:{sourceId:'source-workbook-demo',sourceType:'workbook',title:'미적분 연습문제',ownerScope:'user-private',rightsMode:'user-supplied',revision:'1',fingerprint:'demo-workbook-v1',language:'ko',metadata:{profile:'workbook',purpose:'study',workbookMode:'tutor',locatorScheme:'problem-block'},pages:[
        {page:1,title:'Unit 01',blocks:[{locator:'workbook:source-workbook-demo:problem:1',title:'문제 1',text:'함수 f(x)=x²+3x의 도함수를 구하고 x=2에서의 순간변화율을 계산하시오.',metadata:{role:'problem'}},{locator:'workbook:source-workbook-demo:answer:1',title:'문제 1 해설',text:'f′(x)=2x+3이므로 f′(2)=7이다.',metadata:{role:'answer',restricted:true}}]},
        {page:2,title:'Unit 01',blocks:[{locator:'workbook:source-workbook-demo:problem:2',title:'문제 2',text:'함수 g(x)=x³의 x=1에서 접선의 방정식을 구하시오.',metadata:{role:'problem'}},{locator:'workbook:source-workbook-demo:answer:2',title:'문제 2 해설',text:'g′(1)=3이고 점 (1,1)을 지나므로 접선은 y=3x-2이다.',metadata:{role:'answer',restricted:true}}]}
      ]}
    },
    {
      id:'source-transcript-demo',kind:'transcript',label:'URL / TRANSCRIPT',title:'Context Engineering 강연',note:'timestamp·transcript segment를 기억하며 대화',progress:63,trust:'EXPLORE',icon:'▶',
      spec:{sourceId:'source-transcript-demo',sourceType:'youtube',title:'Context Engineering 강연',ownerScope:'user-private',rightsMode:'user-authorized-transcript',revision:'capture-20260827',fingerprint:'demo-transcript-20260827',language:'ko',url:'https://example.invalid/context-engineering',metadata:{profile:'media',purpose:'explore',locatorScheme:'timestamp-segment'},segments:[
        {locator:'url:source-transcript-demo:t:0-30000',startMs:0,endMs:30000,title:'00:00 · Introduction',text:'컨텍스트 엔지니어링의 핵심은 모델에게 모든 정보를 보내는 것이 아니라 지금 필요한 근거와 상태를 고르는 것이다.'},
        {locator:'url:source-transcript-demo:t:30000-60000',startMs:30000,endMs:60000,title:'00:30 · Retrieval',text:'검색은 정확한 키워드와 현재 위치를 먼저 사용하고 의미 검색은 실제 필요가 확인될 때 확장하는 편이 효율적이다.'},
        {locator:'url:source-transcript-demo:t:60000-90000',startMs:60000,endMs:90000,title:'01:00 · Memory',text:'사용자 메모리와 현재 자료의 근거를 구분하면 세션이 바뀌어도 대화의 맥락을 안전하게 이어갈 수 있다.'}
      ]}
    }
  ]);

  const clone=value=>JSON.parse(JSON.stringify(value));
  const sourceCardModel=(fixture,status='NOT INGESTED')=>({id:fixture.id,kind:fixture.kind,title:fixture.title,label:fixture.label,note:fixture.note,progress:fixture.progress,trust:fixture.trust,status,icon:fixture.icon});
  const flattenBlocks=fixture=>{
    const spec=fixture.spec||fixture;
    if(Array.isArray(spec.pages))return spec.pages.flatMap(page=>(page.blocks||[]).map((b,i)=>({locator:b.locator||`doc:${spec.sourceId}:page:${page.page||1}:block:${i+1}`,title:b.title||page.title||`Page ${page.page||1}`,text:String(b.text||''),metadata:{page:page.page||null,...(b.metadata||{})}})));
    if(Array.isArray(spec.segments))return spec.segments.map((s,i)=>({locator:s.locator||`url:${spec.sourceId}:t:${s.startMs||i*30000}-${s.endMs||(i+1)*30000}`,title:s.title||`Segment ${i+1}`,text:String(s.text||''),metadata:{startMs:s.startMs||0,endMs:s.endMs||0,...(s.metadata||{})}}));
    return [];
  };
  const formatMs=ms=>{const total=Math.max(0,Math.floor(Number(ms||0)/1000));return `${String(Math.floor(total/60)).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`};
  const htmlEscape=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const normalizeKind=sourceType=>{const t=String(sourceType||'').toLowerCase();if(['workbook','worksheet','problem-set'].includes(t))return'workbook';if(['url','youtube','video','audio','transcript','web','webpage'].includes(t))return'transcript';if(['book','bible','scripture'].includes(t))return'book';return'document'};
  function buildImportedFixture({title,type,text}){
    const cleanTitle=String(title||'제목 없는 자료').trim()||'제목 없는 자료';const clean=String(text||'').trim();if(!clean)throw new Error('SOURCE_TEXT_REQUIRED');
    const id=`source-user-${Date.now()}`;const kind=normalizeKind(type);const chunks=clean.split(/\n\s*\n|\n(?=\[[0-9]{1,2}:[0-9]{2}\])/).map(x=>x.trim()).filter(Boolean);
    if(kind==='transcript'){
      const segments=chunks.map((chunk,i)=>({locator:`url:${id}:t:${i*30000}-${(i+1)*30000}`,startMs:i*30000,endMs:(i+1)*30000,title:`구간 ${i+1}`,text:chunk.replace(/^\[[0-9]{1,2}:[0-9]{2}\]\s*/, '')}));
      return {id,kind,label:'PRIVATE TRANSCRIPT',title:cleanTitle,note:'현재 세션의 사용자 제공 transcript',progress:0,trust:'EXPLORE',icon:'▶',spec:{sourceId:id,sourceType:'transcript',title:cleanTitle,ownerScope:'user-private',rightsMode:'user-supplied',revision:'session-1',language:'ko',metadata:{profile:'media',locatorScheme:'timestamp-segment'},segments}};
    }
    const sourceType=kind==='workbook'?'workbook':'document';
    const blocks=chunks.map((chunk,i)=>({locator:`doc:${id}:page:1:block:${i+1}`,title:kind==='workbook'?`문제/항목 ${i+1}`:`문단 ${i+1}`,text:chunk,metadata:{role:kind==='workbook'?'problem':'body'}}));
    return {id,kind,label:kind==='workbook'?'PRIVATE WORKBOOK':'PRIVATE DOCUMENT',title:cleanTitle,note:'현재 세션의 사용자 제공 Source',progress:0,trust:kind==='workbook'?'GROUNDED':'GROUNDED',icon:kind==='workbook'?'Q':'DOC',spec:{sourceId:id,sourceType, title:cleanTitle,ownerScope:'user-private',rightsMode:'user-supplied',revision:'session-1',language:'ko',metadata:{profile:kind,locatorScheme:kind==='workbook'?'problem-block':'page-block'},pages:[{page:1,title:cleanTitle,blocks}]}};
  }

  function install(root){
    const d=root.document, runtime=root.storyMemoryUniversalSource;if(!d||!runtime)return false;
    if(d.documentElement.dataset.sm087Installed==='true')return true;d.documentElement.dataset.sm087Installed='true';d.documentElement.dataset.storymemoryBuild='v3.4.4-source-agnostic-ui';
    const state={libraryMode:'books',selectedSource:0,activeSourceId:null,fixtures:FIXTURES.map(clone),statuses:new Map(),legacySend:root.sendChat,legacyAskPreset:root.askPreset};
    root.__storyMemorySourceUIState=state;

    const library=d.getElementById('library'),today=d.getElementById('todayEntry');
    const switcher=d.createElement('div');switcher.className='source-mode-switch';switcher.innerHTML='<button type="button" data-library-mode="books" class="on">책</button><button type="button" data-library-mode="sources">자료</button><button type="button" class="source-add" data-source-add aria-label="자료 추가">＋</button>';library.insertBefore(switcher,today?.nextSibling||library.firstChild);
    const caption=d.createElement('div');caption.className='source-library-caption';caption.innerHTML='<small>자료 서재</small><strong>자료를 읽고 중요한 내용을 기억할 수 있습니다.</strong>';library.append(caption);
    const deck=d.createElement('div');deck.className='source-deck';deck.id='sourceDeck';library.append(deck);

    const importer=d.createElement('div');importer.className='source-import-dialog';importer.id='sourceImportDialog';importer.innerHTML='<div class="source-import-sheet" role="dialog" aria-modal="true" aria-labelledby="sourceImportTitle"><button class="source-import-close" type="button" data-source-import-close>×</button><small class="native-source-kicker">임시 자료</small><h2 id="sourceImportTitle">자료 추가</h2><p>자료에서 미리 추출한 글이나 영상 자막을 붙여넣어 주세요. PDF 파일이나 영상은 여기서 직접 변환하지 않습니다. 이 보조 화면에 추가한 자료는 새로고침하면 사라집니다.</p><label for="sourceImportType">자료 종류</label><select id="sourceImportType"><option value="document">문서에서 추출한 글</option><option value="workbook">학습지·문제</option><option value="transcript">영상·음성 자막</option></select><label for="sourceImportName">자료 이름</label><input id="sourceImportName" placeholder="자료 이름"><label for="sourceImportText">내용 붙여넣기</label><textarea id="sourceImportText" placeholder="문단 사이를 한 줄 비워 붙여넣으세요."></textarea><div class="source-import-actions"><button type="button" data-source-import-close>취소</button><button type="button" class="primary" id="sourceImportSubmit">대화 준비</button></div></div>';d.body.append(importer);

    const stage=d.querySelector('#reader .reader-stage');const native=d.createElement('section');native.id='nativeSourceShell';native.className='native-source-shell';native.innerHTML='<header class="native-source-head"><div><small class="native-source-kicker" id="nativeSourceKicker">자료 읽기</small><h1 id="nativeSourceTitle">Source</h1><p id="nativeSourceMeta"></p></div><div class="native-source-badges"><span class="native-source-badge" id="nativeSourceTrust">EXPLORE</span><span class="native-source-badge" id="nativeSourcePack">PACK · 0</span><span class="native-source-badge ready" id="nativeSourceReady">READY</span></div></header><div class="native-source-body" id="nativeSourceBody"></div>';stage.insertBefore(native,d.getElementById('paperStack'));

    const memory=d.querySelector('#reader .memory-rail');const rail=d.createElement('section');rail.id='sourceContextRail';rail.className='source-context-rail';rail.hidden=true;rail.innerHTML='<div class="source-rail-kicker">현재 읽는 부분</div><div class="source-context-current" id="sourceContextTitle">—</div><div class="source-context-locator" id="sourceContextLocator">—</div><div class="source-context-list" id="sourceContextList"></div><div class="source-context-actions"><button type="button" id="sourceRememberPosition">기억하기</button><button type="button" id="sourceCopyLocator">위치 코드 복사</button></div>';memory.insertBefore(rail,memory.firstChild?.nextSibling||memory.firstChild);

    const aiPanel=d.querySelector('#reader .ai-panel');const trust=d.createElement('section');trust.className='source-trust-control';trust.id='sourceTrustControl';trust.hidden=true;trust.innerHTML='<div class="trust-row"><label for="sourceTrustSelect">답변 방식</label><select id="sourceTrustSelect"><option value="EXPLORE">넓게 살펴보기</option><option value="GROUNDED">자료 근거 중심</option><option value="STRICT">자료에 엄격히 맞추기</option></select></div><div class="source-pack-state" id="sourcePackState">추가 지식 팩 없음</div>';
    /* B61 #1855: conversation-first Companion nests runtime context inside
       #chatThread, so a descendant .context-card is not a valid reference node
       for aiPanel.insertBefore(). Mount against stable direct-child structure
       instead, with a hidden fallback when the Companion surface is unavailable. */
    if(aiPanel){
      const composer=aiPanel.querySelector('.ask');
      const thread=aiPanel.querySelector('#chatThread,.chat-thread');
      if(composer&&composer.parentNode===aiPanel)aiPanel.insertBefore(trust,composer);
      else if(thread&&thread.parentNode===aiPanel)aiPanel.insertBefore(trust,thread.nextSibling);
      else aiPanel.append(trust);
    }else{
      trust.dataset.sourceUiUnmounted='true';
      (d.body||d.documentElement)?.append(trust);
    }

    function fixtureById(id){return state.fixtures.find(x=>x.id===id)||null}
    function currentFixture(){return state.fixtures[state.selectedSource]||null}
    function statusLabel(value){return ({'NOT INGESTED':'읽기 전','RECEIVED':'준비 중','CONVERSATION_READY':'자료 준비됨','FAILED_PARTIAL':'일부 확인 필요'})[value]||String(value).replace(/_/g,' ')}
    function sourceKindName(f){return ({contract:'계약 문서',workbook:'학습 자료',transcript:'강연 자막',document:'문서'})[f.kind]||'자료'}
    function sourceModeName(value){return ({EXPLORE:'넓게 살펴보기',GROUNDED:'자료 근거 중심',STRICT:'자료에 엄격히 맞추기'})[value]||String(value)}
    function sourceNote(f){return ({'source-contract-demo':'조항과 이용 조건을 살펴보는 예시','source-workbook-demo':'문제를 읽고 풀이를 생각해 보는 예시','source-transcript-demo':'강연 자막을 살펴보는 예시'})[f.id]||(f.id.startsWith('source-user-')?'현재 화면에서 추가한 자료':f.note)}
    function sourcePlace(f,block){if(!block)return '읽기 위치';if(f.kind==='transcript')return f.id.startsWith('source-user-')?(block.title||'자막 구간'):formatMs(block.metadata?.startMs);if(block.metadata?.page)return block.metadata.page+'쪽';return block.title||'읽기 위치'}
    function statusFor(id){return state.statuses.get(id)||runtime.getSource(id)?.ingestState||'NOT INGESTED'}
    function renderDeck(){
      deck.innerHTML='';state.fixtures.forEach((f,i)=>{const model=sourceCardModel(f,statusFor(f.id));const b=d.createElement('button');b.type='button';b.className='source-object'+(i===state.selectedSource?' selected':'');b.dataset.sourceId=f.id;b.dataset.sourceKind=f.kind;b.setAttribute('aria-label',`${f.title} 열기`);const cls=model.status==='CONVERSATION_READY'?' ready':model.status==='FAILED_PARTIAL'?' failed':'';b.innerHTML=`<span class="source-object-shell"><span class="source-object-icon">${htmlEscape(f.icon)}</span><span class="source-object-state${cls}">${htmlEscape(statusLabel(model.status))}</span><span class="source-object-copy"><small>${htmlEscape(sourceKindName(f))} · ${htmlEscape(sourceModeName(f.trust))}</small><strong>${htmlEscape(f.title)}</strong><span>${htmlEscape(sourceNote(f))}</span></span><span class="source-object-progress" style="--source-progress:${Number(f.progress||0)}%"><i></i></span></span>`;b.onclick=()=>{if(i===state.selectedSource)openSelectedSource();else{state.selectedSource=i;renderDeck();syncSelectedSourceMeta()}};deck.append(b)});
    }
    function syncSelectedSourceMeta(){const f=currentFixture();if(!f)return;d.getElementById('libCounter').textContent=String(state.selectedSource+1).padStart(2,'0')+' / '+String(state.fixtures.length).padStart(2,'0');d.getElementById('libTitle').textContent=f.title;d.getElementById('libNote').textContent=sourceNote(f);d.getElementById('libProgressText').textContent=`${statusLabel(statusFor(f.id))} · ${sourceModeName(f.trust)}`;d.getElementById('libProgressBar').style.width=(Number(f.progress||0))+'%';d.getElementById('selectedEditionNo').textContent=String(state.selectedSource+1).padStart(2,'0');d.getElementById('materialNote').textContent=sourceKindName(f);d.getElementById('objectWeight').textContent='디지털 자료';d.getElementById('finishNote').textContent=`답변 방식 · ${sourceModeName(f.trust)}`;d.getElementById('collectionNo').textContent=String(state.selectedSource+1).padStart(2,'0')+' / '+String(state.fixtures.length).padStart(2,'0');d.getElementById('openBook').textContent='자료 열기';}
    function setLibraryMode(mode){state.libraryMode=mode==='sources'?'sources':'books';library.dataset.libraryMode=state.libraryMode;switcher.querySelectorAll('[data-library-mode]').forEach(b=>b.classList.toggle('on',b.dataset.libraryMode===state.libraryMode));if(state.libraryMode==='sources'){renderDeck();syncSelectedSourceMeta()}else{d.getElementById('openBook').textContent='책 열기';try{root.renderLibrary?.()}catch(_){}}return state.libraryMode}

    runtime.onStateChange((event)=>{state.statuses.set(event.sourceId,event.state);renderDeck();if(state.libraryMode==='sources')syncSelectedSourceMeta()});
    async function ensureIngested(f){let source=runtime.getSource(f.id);if(!source){state.statuses.set(f.id,'RECEIVED');renderDeck();source=await runtime.ingest(clone(f.spec))}return runtime.getSource(f.id)||source}
    function activeBlocks(f){return flattenBlocks(f)}
    function setPosition(locator){if(!state.activeSourceId||!locator)return;runtime.setPosition(state.activeSourceId,locator);renderActivePosition()}
    function renderActivePosition(){const f=fixtureById(state.activeSourceId);if(!f)return;const pos=runtime.getPosition();const blocks=activeBlocks(f);const idx=Math.max(0,blocks.findIndex(x=>x.locator===pos?.locator));const block=blocks[idx]||blocks[0];d.getElementById('sourceContextTitle').textContent=block?.title||f.title;d.getElementById('sourceContextLocator').textContent=sourcePlace(f,block);d.getElementById('aiReadingContext').textContent=`${f.title} · ${block?.title||'현재 위치'}`;d.querySelectorAll('.native-source-block').forEach(el=>el.classList.toggle('active',el.dataset.locator===block?.locator));d.querySelectorAll('#sourceContextList button').forEach(el=>el.classList.toggle('on',el.dataset.locator===block?.locator));const pct=blocks.length?Math.round(((idx+1)/blocks.length)*100):0;d.getElementById('nativeSourceMeta').textContent=`${sourceKindName(f)} · ${idx+1} / ${blocks.length} · ${pct}%`;const transcript=d.querySelector('.native-transcript-player .track');if(transcript)transcript.style.setProperty('--media-progress',pct+'%')}
    function renderRail(f){const list=d.getElementById('sourceContextList');list.innerHTML='';activeBlocks(f).slice(0,10).forEach(block=>{const b=d.createElement('button');b.type='button';b.dataset.locator=block.locator;b.textContent=block.title;b.onclick=()=>{setPosition(block.locator);d.querySelector(`.native-source-block[data-locator="${CSS.escape(block.locator)}"]`)?.scrollIntoView({behavior:'smooth',block:'center'})};list.append(b)})}
    function renderNativeSource(f,source){
      d.getElementById('nativeSourceKicker').textContent=sourceKindName(f)+(f.id.startsWith('source-')&&f.id.endsWith('-demo')?' · 예시':'');d.getElementById('nativeSourceTitle').textContent=f.title;d.getElementById('nativeSourceReady').textContent=statusLabel(source.ingestState);d.getElementById('nativeSourceTrust').textContent=sourceModeName(runtime.getTrustMode(f.id));const packs=runtime.listAttachedPacks(f.id);d.getElementById('nativeSourcePack').textContent=`지식 팩 ${packs.length}개`;d.getElementById('sourcePackState').textContent=packs.length?packs.map(p=>`${p.name} ${p.version}`).join(' · '):'추가 지식 팩 없음';d.getElementById('sourceTrustSelect').value=runtime.getTrustMode(f.id);
      const body=d.getElementById('nativeSourceBody');body.innerHTML='';if(f.kind==='transcript'){const player=d.createElement('div');player.className='native-transcript-player';player.innerHTML='<button type="button" aria-label="음성 없는 자막 자료" disabled>▶</button><span class="track"><i></i></span><small>자막 위치 · 음성 없음</small>';body.append(player)}
      activeBlocks(f).forEach(block=>{const art=d.createElement('article');const role=String(block.metadata?.role||'');art.className='native-source-block'+(role==='answer'?' answer-hidden':'');art.dataset.locator=block.locator;if(role)art.dataset.role=role;const locLabel=f.kind==='transcript'?(f.id.startsWith('source-user-')?'자막':formatMs(block.metadata?.startMs)):block.metadata?.page?`${block.metadata.page}쪽`:'본문';art.innerHTML=`<small>${htmlEscape(locLabel)}</small><h2>${htmlEscape(block.title)}</h2><p>${htmlEscape(block.text)}</p>`;art.addEventListener('click',()=>setPosition(block.locator));body.append(art)});renderRail(f);renderActivePosition();
    }
    function syncAIForSource(f){const sideSmall=d.querySelector('#reader .ai-panel .side-head small');if(sideSmall)sideSmall.textContent=sourceModeName(runtime.getTrustMode(f.id));const meta=d.querySelector('#reader .ai-panel .context-meta');if(meta)meta.innerHTML=`<span>${sourceKindName(f)}</span><span>${sourceModeName(runtime.getTrustMode(f.id))}</span><span>지식 팩 ${runtime.listAttachedPacks(f.id).length}개</span>`;const rule=d.querySelector('#reader .ai-panel .context-rule span');if(rule)rule.textContent='현재 읽는 부분과 관련된 자료를 바탕으로 답합니다';const quick=[...d.querySelectorAll('#reader .quick button')];const qs=f.kind==='contract'?['자동 갱신 조건은?','월 이용요금은?','30일은 어떤 조건이야?','이 조항을 근거와 함께 설명해줘']:f.kind==='workbook'?['이 문제를 어떻게 시작해?','힌트만 줘','사용한 개념은?','정답 말고 풀이 방향은?']:['방금 핵심은 뭐야?','자료 검색을 설명해줘','앞에서 기억에 대해 뭐라고 했지?','현재 구간을 요약해줘'];quick.forEach((b,i)=>{b.textContent=qs[i]||qs[0];b.dataset.sourceQuestion=qs[i]||qs[0]})}
    async function openSelectedSource(){const f=currentFixture();if(!f)return;const source=await ensureIngested(f);state.activeSourceId=f.id;runtime.setActiveSource(f.id);runtime.setPosition(f.id,source.firstLocator);d.body.classList.add('source-native-active');d.getElementById('reader').dataset.sourceType=f.kind;d.getElementById('nativeSourceShell').hidden=false;rail.hidden=false;trust.hidden=false;d.getElementById('backToChapters').textContent='← 자료 서재';d.getElementById('focusToggle').textContent='자료에 집중';renderNativeSource(f,source);syncAIForSource(f);root.showScreen?.('reader');return source}
    function exitNativeSource({toLibrary=false}={}){if(!state.activeSourceId)return;state.activeSourceId=null;d.body.classList.remove('source-native-active');d.getElementById('reader').removeAttribute('data-source-type');native.hidden=true;rail.hidden=true;trust.hidden=true;d.getElementById('backToChapters').textContent='← 장 선택';try{root.renderReaderPage?.(root.readerPageIndex||0)}catch(_){}if(toLibrary){root.showScreen?.('library');setLibraryMode('sources')}}

    async function submitNativeQuestion(question){const q=String(question||'').trim();if(!q||!state.activeSourceId)return null;const input=d.getElementById('askInput');if(input)input.value='';try{root.appendUserMessage?.(q,null)}catch(_){const thread=d.getElementById('chatThread');thread?.insertAdjacentHTML('beforeend',`<div class="msg user"><p>${htmlEscape(q)}</p></div>`)}const pos=runtime.getPosition();const f=fixtureById(state.activeSourceId);const result=await runtime.answer({sourceId:state.activeSourceId,question:q,locator:pos?.locator||null,trustMode:runtime.getTrustMode(state.activeSourceId),workbookMode:f?.kind==='workbook'?'tutor':null,revealAnswers:false});const title=result.title||result.provenance?.label||'Companion';const body=result.body||'현재 자료에서 답을 찾지 못했습니다.';const source=Array.isArray(result.provenance?.sourceRefs)&&result.provenance.sourceRefs.length?result.provenance.sourceRefs.join(' · '):(result.source||pos?.locator||'현재 자료');try{root.appendAIMessage?.(title,body,source,{...result,route:result.provenance?.label||result.route,sourceType:f?.kind})}catch(_){d.getElementById('chatThread')?.insertAdjacentHTML('beforeend',`<div class="msg ai"><div class="verified">${htmlEscape(result.provenance?.label||result.route||'SOURCE')}</div><h3>${htmlEscape(title)}</h3><p>${htmlEscape(body)}</p><div class="source">${htmlEscape(source)}</div></div>`)}return result}

    switcher.addEventListener('click',e=>{const mode=e.target.closest('[data-library-mode]')?.dataset.libraryMode;if(mode)setLibraryMode(mode);if(e.target.closest('[data-source-add]'))importer.classList.add('open')});
    importer.addEventListener('click',e=>{if(e.target===importer||e.target.closest('[data-source-import-close]'))importer.classList.remove('open')});
    d.getElementById('sourceImportSubmit').onclick=async()=>{try{const f=buildImportedFixture({title:d.getElementById('sourceImportName').value,type:d.getElementById('sourceImportType').value,text:d.getElementById('sourceImportText').value});state.fixtures.push(f);state.selectedSource=state.fixtures.length-1;importer.classList.remove('open');setLibraryMode('sources');await ensureIngested(f);syncSelectedSourceMeta()}catch(error){d.getElementById('sourceImportText').setCustomValidity(error?.message==='SOURCE_TEXT_REQUIRED'?'내용을 입력해 주세요.':String(error?.message||error));d.getElementById('sourceImportText').reportValidity();setTimeout(()=>d.getElementById('sourceImportText').setCustomValidity(''),800)}};

    ['prevBook','nextBook','openBook'].forEach(id=>d.getElementById(id)?.addEventListener('click',e=>{if(state.libraryMode!=='sources')return;e.preventDefault();e.stopImmediatePropagation();if(id==='openBook')openSelectedSource();else{const dir=id==='nextBook'?1:-1;state.selectedSource=(state.selectedSource+dir+state.fixtures.length)%state.fixtures.length;renderDeck();syncSelectedSourceMeta()}},true));
    d.getElementById('backToChapters')?.addEventListener('click',e=>{if(!state.activeSourceId)return;e.preventDefault();e.stopImmediatePropagation();exitNativeSource({toLibrary:true})},true);
    d.getElementById('sourceTrustSelect').onchange=e=>{if(!state.activeSourceId)return;runtime.setTrustMode(state.activeSourceId,e.target.value);const f=fixtureById(state.activeSourceId);renderNativeSource(f,runtime.getSource(state.activeSourceId));syncAIForSource(f)};
    d.getElementById('sourceRememberPosition').onclick=()=>{if(!state.activeSourceId)return;const p=runtime.getPosition();const f=fixtureById(state.activeSourceId);runtime.addMemory({sourceId:state.activeSourceId,locator:p?.locator,title:`${f?.title||'Source'} 위치`,body:'사용자가 현재 위치를 기억하기로 저장했습니다.',tags:['bookmark']});d.getElementById('sourceRememberPosition').textContent='기억됨 ✓'};
    d.getElementById('sourceCopyLocator').onclick=async()=>{const loc=runtime.getPosition()?.locator||'';try{await root.navigator?.clipboard?.writeText(loc);d.getElementById('sourceCopyLocator').textContent='복사됨 ✓'}catch(_){d.getElementById('sourceCopyLocator').textContent=loc.slice(0,24)}};
    d.querySelector('#reader .quick')?.addEventListener('click',e=>{if(!state.activeSourceId)return;const b=e.target.closest('button');if(!b)return;e.preventDefault();e.stopImmediatePropagation();submitNativeQuestion(b.dataset.sourceQuestion||b.textContent)},true);
    const legacySend=state.legacySend;root.sendChat=async function(){if(state.activeSourceId)return submitNativeQuestion(d.getElementById('askInput')?.value||'');return typeof legacySend==='function'?legacySend():null};
    root.askPreset=function(key){if(state.activeSourceId){const b=[...d.querySelectorAll('#reader .quick button')].find(x=>x.dataset.q===key)||d.querySelector('#reader .quick button');return submitNativeQuestion(b?.dataset.sourceQuestion||b?.textContent||key)}return typeof state.legacyAskPreset==='function'?state.legacyAskPreset(key):null};

    renderDeck();setLibraryMode('books');
    root.storyMemorySourceUI={contract:CONTRACT,fixtures:state.fixtures,getState:()=>({libraryMode:state.libraryMode,selectedSource:state.selectedSource,activeSourceId:state.activeSourceId}),setLibraryMode,openSelectedSource,exitNativeSource,submitNativeQuestion,addSource:fixture=>{state.fixtures.push(clone(fixture));renderDeck();return fixture.id}};
    return true;
  }

  return Object.freeze({CONTRACT,FIXTURES,sourceCardModel,flattenBlocks,buildImportedFixture,normalizeKind,formatMs,install});
});
