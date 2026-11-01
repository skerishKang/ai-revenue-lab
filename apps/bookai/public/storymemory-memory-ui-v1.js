/* StoryMemory B61 #1337 R7 — behavior-preserving private UI extraction.
   PRIVATE SOURCE. Not for public GitHub publication. */
function renderGlobalRelationship(host,q=''){
  const entities=globalEntityNames()
    .filter(x=>!q || x.toLowerCase().includes(q) || globalEntityContextEvidence(x).some(c=>c.context.toLowerCase().includes(q)))
    .sort((a,b)=>globalEntityStrength(b)-globalEntityStrength(a));

  if(!entities.length){
    host.innerHTML+='<div class="annotation-empty">관계로 묶을 Memory가 아직 없습니다. 본문 표시·메모·AI Memory가 쌓이면 여기에 연결됩니다.</div>';
    return;
  }

  if(!__smGlobalFocusEntity || !entities.includes(__smGlobalFocusEntity)){
    __smGlobalFocusEntity=entities[0];
  }

  const shell=document.createElement('div');
  shell.className='global-relationship-shell';

  const head=document.createElement('div');
  head.className='global-relationship-head';
  const contextEvidence=globalEntityContextEvidence(__smGlobalFocusEntity);
  head.innerHTML=`
    <div><b>GLOBAL RELATIONSHIP</b><h4>${escapeHtml(__smGlobalFocusEntity)}</h4></div>
    <small>${contextEvidence.length}개의 Reading에서 형성된 개인 Memory 관계</small>`;
  shell.append(head);

  const chips=document.createElement('div');
  chips.className='global-entity-chips';
  entities.forEach(entity=>{
    const b=document.createElement('button');
    b.type='button';
    b.className='global-entity-chip'+(entity===__smGlobalFocusEntity?' on':'');
    b.textContent=entity;
    b.onclick=()=>{__smGlobalFocusEntity=entity;renderGlobalMemoryOverview()};
    chips.append(b);
  });
  shell.append(chips);

  const relations=globalRelationsFor(__smGlobalFocusEntity).slice(0,6);
  const graph=document.createElement('div');
  graph.className='global-rel-graph';

  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 100 100');
  svg.setAttribute('preserveAspectRatio','none');

  const center=document.createElement('button');
  center.type='button';
  center.className='global-rel-node center';
  center.style.left='50%';center.style.top='50%';
  center.innerHTML=`<b>${escapeHtml(__smGlobalFocusEntity)}</b><small>${escapeHtml(memoryTypeLabel(inferSystemMemoryType(__smGlobalFocusEntity)))} · ${globalEntityStrength(__smGlobalFocusEntity)}</small>`;
  graph.append(center);

  relations.forEach((rel,i)=>{
    const [x,y]=globalRelationNodePos(i,relations.length);

    const line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1','50');line.setAttribute('y1','50');
    line.setAttribute('x2',String(x));line.setAttribute('y2',String(y));
    line.setAttribute('class','global-rel-edge'+(rel.score>=4?' strong':''));
    svg.append(line);

    const node=document.createElement('button');
    node.type='button';
    node.className='global-rel-node';
    node.style.left=x+'%';node.style.top=y+'%';
    node.innerHTML=`<b>${escapeHtml(rel.entity)}</b><small>${escapeHtml(memoryTypeLabel(rel.type))} · ${rel.score}</small>`;
    node.onclick=()=>{__smGlobalFocusEntity=rel.entity;renderGlobalMemoryOverview()};
    graph.append(node);
  });

  graph.prepend(svg);
  shell.append(graph);

  const evidence=document.createElement('div');
  evidence.className='global-rel-evidence';
  if(relations.length){
    const top=relations[0];
    evidence.innerHTML=`<b>가장 강한 연결</b><p>${escapeHtml(__smGlobalFocusEntity)} ↔ ${escapeHtml(top.entity)} · ${escapeHtml((top.evidence||[]).slice(0,3).join(' · '))}</p>`;
  }else{
    evidence.innerHTML='<b>관계 형성 중</b><p>현재는 단독 Memory입니다. 다른 인물·장소·개념과 함께 기록되면 관계가 생깁니다.</p>';
  }
  shell.append(evidence);

  const history=document.createElement('div');
  history.className='global-entity-history';
  history.innerHTML='<strong>MEMORY EVOLUTION · READING별 형성 과정</strong>';

  contextEvidence.forEach(c=>{
    const total=c.text+c.note+c.ai+c.annotation;
    const b=document.createElement('button');
    b.type='button';b.className='global-history-card';
    const pieces=[];
    if(c.text)pieces.push(`본문 ${c.text}`);
    if(c.note)pieces.push(`메모 ${c.note}`);
    if(c.ai)pieces.push(`AI ${c.ai}`);
    if(c.annotation)pieces.push(`표시 ${c.annotation}`);
    b.innerHTML=`<div><b>${escapeHtml(c.context)}</b><span>${escapeHtml(pieces.join(' · '))}</span></div><i>${total}</i>`;
    b.onclick=()=>openStoredMemoryContext(c.context,()=>{
      const item=document.querySelector(`.system-memory[data-memory-key="${CSS.escape(__smGlobalFocusEntity)}"]`);
      if(item){renderMemoryFocus(__smGlobalFocusEntity)}
    });
    history.append(b);
  });
  shell.append(history);

  host.append(shell);
}

function buildRecallQueue(){
  const items=[];

  __smUserMemories.forEach(m=>{
    items.push({
      id:'memory:'+m.id,
      kind:m.kind==='ai'?'ai':'note',
      context:m.context,
      title:m.kind==='ai'?'AI Memory':'내 메모',
      prompt:m.quote
        ?'이 문장과 연결해 무엇을 기억했나요?'
        :'이 Reading에서 남긴 생각을 떠올려보세요.',
      cue:m.quote||m.title||'저장한 Memory',
      answer:m.body,
      source:m.source||m.context,
      page:Number(m.page||0),
      jump:()=>jumpToUserMemory(m)
    });
  });

  __smAnnotations.forEach(a=>{
    items.push({
      id:'annotation:'+a.id,
      kind:'annotation',
      context:a.context,
      title:annotationTypeLabel(a.type),
      prompt:'왜 이 문장을 표시했는지 떠올려보세요.',
      cue:a.text.slice(0,72),
      answer:a.text,
      source:a.source||a.context,
      page:Number(a.page||0),
      jump:()=>jumpToAnnotation(a)
    });
  });

  Object.values(__smContextEntityLedger).forEach(entry=>{
    Object.entries(entry?.entities||{}).forEach(([entity,count])=>{
      items.push({
        id:`entity:${entry.context}:${entity}`,
        kind:'entity',
        context:entry.context,
        title:memoryTypeLabel(inferSystemMemoryType(entity)),
        prompt:`${entity}에 대해 이 Reading에서 무엇을 기억하나요?`,
        cue:entity,
        answer:`${entity}는 이 Reading 범위에서 ${count}회 연결되어 있습니다.`,
        source:entry.context,
        page:0,
        jump:()=>openStoredMemoryContext(entry.context,()=>{
          renderMemoryFocus(entity);
          if(__smReaderCompactMode())document.body.classList.add('memory-open');
        })
      });
    });
  });

  const q=__smMemorySearch.trim().toLowerCase();
  const filtered=q
    ?items.filter(x=>[x.context,x.title,x.prompt,x.cue,x.answer,x.source].join(' ').toLowerCase().includes(q))
    :items;

  return filtered.sort((a,b)=>{
    const sa=recallItemState(a.id), sb=recallItemState(b.id);
    const aDue=Number(sa.nextDue||0)<=Date.now()?0:1;
    const bDue=Number(sb.nextDue||0)<=Date.now()?0:1;
    if(aDue!==bDue)return aDue-bDue;
    if(Number(sa.reviews||0)!==Number(sb.reviews||0))return Number(sa.reviews||0)-Number(sb.reviews||0);
    return String(a.context).localeCompare(String(b.context));
  });
}

function renderRecallView(host){
  recordCurrentContextEntityLedger();
  __smRecallQueue=buildRecallQueue();

  const shell=document.createElement('div');
  shell.className='memory-recall-shell';

  const reviewed=Object.values(__smRecallState).filter(x=>Number(x.reviews||0)>0).length;
  const due=__smRecallQueue.filter(x=>Number(recallItemState(x.id).nextDue||0)<=Date.now()).length;
  const remembered=Object.values(__smRecallState).filter(x=>x.lastRating==='good').length;

  const head=document.createElement('div');
  head.className='memory-recall-head';
  head.innerHTML=`
    <div><b>MEMORY RECALL</b><h4>기억을 다시 꺼내기</h4></div>
    <small>정답 맞히기가 아니라, 읽은 기억을 스스로 먼저 떠올린 뒤 원문과 비교합니다.</small>`;
  shell.append(head);

  const stats=document.createElement('div');
  stats.className='memory-recall-stats';
  stats.innerHTML=`
    <div class="memory-recall-stat"><b>${__smRecallQueue.length}</b><span>QUEUE</span></div>
    <div class="memory-recall-stat"><b>${due}</b><span>DUE</span></div>
    <div class="memory-recall-stat"><b>${remembered}</b><span>REMEMBERED</span></div>`;
  shell.append(stats);

  if(!__smRecallQueue.length){
    const empty=document.createElement('div');
    empty.className='memory-recall-empty';
    empty.innerHTML='<b>아직 복습할 Memory가 없습니다.</b><span>본문에 표시를 남기거나 메모·AI Memory를 저장하면 Recall Queue가 만들어집니다.</span>';
    shell.append(empty);
    host.append(shell);
    return;
  }

  if(__smRecallIndex>=__smRecallQueue.length)__smRecallIndex=0;
  const item=__smRecallQueue[__smRecallIndex];
  const st=recallItemState(item.id);

  const card=document.createElement('section');
  card.className='memory-recall-card';
  card.innerHTML=`
    <div class="memory-recall-kind"><span>${escapeHtml(item.title)} · ${escapeHtml(item.context)}</span><span>${escapeHtml(recallDueLabel(item))}</span></div>
    <div class="memory-recall-question">
      <h5>${escapeHtml(item.prompt)}</h5>
      <p>${escapeHtml(item.cue)}</p>
      <span class="recall-context">${escapeHtml(item.context)}</span>
    </div>
    <div class="memory-recall-reveal">
      <b>REVEAL · 실제 저장 Memory</b>
      <blockquote>${escapeHtml(item.answer)}</blockquote>
      <small>${escapeHtml(item.source)}</small>
    </div>
    <div class="memory-recall-actions">
      <button type="button" class="reveal">기억 확인</button>
      <button type="button" class="rate good" data-recall-rate="good">기억남</button>
      <button type="button" class="rate unsure" data-recall-rate="unsure">애매</button>
      <button type="button" class="rate again" data-recall-rate="again">다시보기</button>
    </div>
    <div class="memory-recall-source-actions"><button type="button">↗ 원문 / Memory로 이동</button></div>
    <div class="memory-recall-progress"><i></i></div>`;

  const jumpRecallSource=()=>{
    applyMemoryScope('current');
    item.jump?.();
  };
  card.querySelector('.reveal').onclick=()=>card.classList.add('revealed');
  card.querySelector('.memory-recall-source-actions button').onclick=jumpRecallSource;

  card.querySelectorAll('[data-recall-rate]').forEach(b=>{
    b.onclick=()=>{
      const rating=b.dataset.recallRate;
      applyRecallRating(item,rating);
      if(rating==='again'){
        jumpRecallSource();
        return;
      }
      __smRecallIndex=(__smRecallIndex+1)%Math.max(1,__smRecallQueue.length);
      renderGlobalMemoryOverview();
    };
  });

  const progress=((__smRecallIndex+1)/Math.max(1,__smRecallQueue.length))*100;
  card.querySelector('.memory-recall-progress i').style.width=progress+'%';

  if(Number(st.reviews||0)>0){
    card.dataset.previousRating=st.lastRating||'';
  }

  shell.append(card);
  host.append(shell);
}


function renderGlobalMemoryOverview(){
  const host=document.getElementById('globalMemoryOverview');
  if(!host)return;
  const global=__smMemoryScope==='global';
  host.classList.toggle('show',global);
  if(!global){host.innerHTML='';return}

  recordCurrentContextEntityLedger();

  const {contexts,memories,ai}=globalMemoryStats();
  const q=__smMemorySearch.trim().toLowerCase();

  host.innerHTML='';

  const stats=document.createElement('div');
  stats.className='global-memory-summary';
  stats.innerHTML=`
    <div class="global-memory-stat"><b>${contexts.length}</b><span>READINGS</span></div>
    <div class="global-memory-stat"><b>${memories}</b><span>MEMORIES</span></div>
    <div class="global-memory-stat"><b>${ai}</b><span>AI MEMORY</span></div>`;
  host.append(stats);

  const toggle=document.createElement('div');
  toggle.className='global-view-toggle';
  toggle.innerHTML=`
    <button type="button" data-global-view="readings">Reading</button>
    <button type="button" data-global-view="relationship">관계</button>
    <button type="button" data-global-view="recall">Recall</button>`;
  toggle.querySelectorAll('[data-global-view]').forEach(b=>{
    b.classList.toggle('on',b.dataset.globalView===__smGlobalView);
    b.onclick=()=>{
      __smGlobalView=b.dataset.globalView;
      renderGlobalMemoryOverview();
    };
  });
  host.append(toggle);

  if(__smGlobalView==='relationship'){
    renderGlobalRelationship(host,q);
    return;
  }
  if(__smGlobalView==='recall'){
    renderRecallView(host);
    return;
  }

  const list=document.createElement('div');
  list.className='global-context-list';

  const filtered=contexts.filter(c=>{
    if(!q)return true;
    if(c.context.toLowerCase().includes(q))return true;
    return c.notes.some(m=>memorySearchTextForUser(m).includes(q))
      || c.annotations.some(a=>memorySearchTextForAnnotation(a).includes(q));
  });

  if(!filtered.length){
    list.innerHTML='<div class="annotation-empty">검색과 일치하는 전체 Memory가 없습니다.</div>';
  }else{
    filtered.forEach(c=>{
      const card=document.createElement('div');
      card.className='global-context-card'+(__smExpandedGlobalContext===c.context?' active':'');
      const aiCount=c.notes.filter(m=>m.kind==='ai').length;
      const myCount=c.notes.filter(m=>m.kind!=='ai').length;

      const main=document.createElement('button');
      main.type='button';main.className='global-context-main';
      const progressLabel=c.progress
        ?(c.progress.mode==='flow'?`FLOW · ${Math.round((c.progress.scrollRatio||0)*100)}%`:`PAGE ${(Number(c.progress.page||0)+1)}`)
        :'읽기 기록 없음';
      main.innerHTML=`
        <div><strong>${escapeHtml(c.context)}</strong><small>${escapeHtml(progressLabel)}</small></div>
        <div class="global-context-counts"><i title="내 메모">${myCount}</i><i title="AI">${aiCount}</i><i title="표시">${c.annotations.length}</i></div>`;
      main.onclick=()=>{
        __smExpandedGlobalContext=__smExpandedGlobalContext===c.context?null:c.context;
        renderGlobalMemoryOverview();
      };

      const preview=document.createElement('div');
      preview.className='global-context-preview';
      const entries=contextPreviewEntries(c.context).slice(-5).reverse();
      if(!entries.length){
        preview.innerHTML='<div class="annotation-empty">이 Reading에는 아직 저장된 Memory가 없습니다.</div>';
      }else{
        entries.forEach(e=>{
          const b=document.createElement('button');
          b.type='button';
          b.innerHTML=`<b>${escapeHtml(e.kind)}</b> · ${escapeHtml(e.text.slice(0,80))}${e.text.length>80?'…':''}<small>${escapeHtml(e.source)}</small>`;
          b.onclick=ev=>{ev.stopPropagation();e.jump()};
          preview.append(b);
        });
      }

      card.append(main,preview);
      list.append(card);
    });
  }
  host.append(list);
}

function renderRelationshipView(key,host){
  const relations=relationshipSetForKey(key);
  const centerType=inferSystemMemoryType(key);

  const wrap=document.createElement('div');
  wrap.className='memory-relation-wrap';

  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 100 100');
  svg.setAttribute('preserveAspectRatio','none');
  svg.classList.add('memory-relation-svg');

  const center=document.createElement('button');
  center.type='button';
  center.className='memory-relation-node center';
  center.style.left='50%';center.style.top='50%';
  center.style.setProperty('--node-accent',memoryNodeAccent(centerType));
  center.innerHTML=`<b><i></i>${escapeHtml(key)}</b><small>${escapeHtml(memoryTypeLabel(centerType))}</small>`;
  center.onclick=()=>{__smMemoryFocusMode='timeline';renderMemoryFocus(key)};
  wrap.append(center);

  relations.slice(0,6).forEach((rel,i)=>{
    const [x,y]=relationNodePosition(i,Math.min(6,relations.length));

    const line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1','50');line.setAttribute('y1','50');
    line.setAttribute('x2',String(x));line.setAttribute('y2',String(y));
    line.setAttribute('class','memory-relation-edge'+(rel.score>=3?' strong':''));
    svg.append(line);

    const node=document.createElement('button');
    node.type='button';
    node.className='memory-relation-node';
    node.style.left=x+'%';node.style.top=y+'%';
    node.style.setProperty('--node-accent',memoryNodeAccent(rel.type));
    node.innerHTML=`<b><i></i>${escapeHtml(rel.key)}</b><small>${escapeHtml(memoryTypeLabel(rel.type))} · ${rel.score}</small>`;
    node.onclick=()=>{__smFocusedMemoryKey=rel.key;renderMemoryFocus(rel.key)};
    wrap.append(node);
  });

  wrap.prepend(svg);
  host.append(wrap);

  const legend=document.createElement('div');
  legend.className='memory-relation-legend';
  legend.innerHTML='<span>굵은 선 = 강한 연결</span><span>숫자 = 연결 근거 수</span><span>노드 클릭 = Timeline 이동</span>';
  host.append(legend);

  const evidence=document.createElement('div');
  evidence.className='memory-relation-evidence';
  if(relations.length){
    const top=relations[0];
    evidence.innerHTML=`<b>가장 강한 연결</b><p>${escapeHtml(key)} ↔ ${escapeHtml(top.key)} · ${top.evidence.length?escapeHtml(top.evidence.join(' · ')):'현재 읽은 범위의 공동 등장'}</p>`;
  }else{
    evidence.innerHTML='<b>관계 근거 없음</b><p>현재 읽은 범위에서는 다른 Memory와의 직접 연결을 찾지 못했습니다.</p>';
  }
  host.append(evidence);
}


function renderMemoryFocus(key){
  const host=document.getElementById('memoryFocus');
  if(!host)return;

  if(!key){
    __smFocusedMemoryKey=null;
    host.innerHTML='<div class="memory-focus-empty"><b>MEMORY TIMELINE</b><span>인물·장소·개념을 누르면 읽은 범위 안에서 언제 등장했고, 어떤 메모와 AI 대화가 연결됐는지 한곳에 모읍니다.</span></div>';
    document.querySelectorAll('.system-memory').forEach(x=>x.classList.remove('focused'));
    return;
  }

  __smFocusedMemoryKey=key;
  const def=KNOWN_MEMORY_ENTITIES[key]||{type:inferSystemMemoryType(key),summary:'현재 읽기에서 연결된 Memory입니다.'};
  const events=timelineEventsForKey(key);
  const notes=events.filter(e=>e.kind==='note'||e.kind==='ai').length;
  const textHits=events.filter(e=>e.kind==='text').length;
  const relations=relationshipSetForKey(key);

  host.innerHTML='';
  const card=document.createElement('div');
  card.className='memory-focus-card';
  card.innerHTML=`
    <div class="memory-focus-top">
      <div><span class="memory-focus-type">${escapeHtml(memoryTypeLabel(def.type))} · MEMORY</span><h4>${escapeHtml(key)}</h4></div>
      <button type="button" class="memory-focus-close" aria-label="Memory 닫기">×</button>
    </div>
    <p class="memory-focus-summary">${escapeHtml(def.summary)}</p>
    <div class="memory-focus-meta">
      <span>본문 ${textHits}</span>
      <span>연결 Memory ${notes}</span>
      <span>관계 ${relations.length}</span>
    </div>
    <div class="memory-focus-view-toggle">
      <button type="button" data-focus-mode="timeline">Timeline</button>
      <button type="button" data-focus-mode="relationship">관계</button>
    </div>
    <div class="memory-focus-body"></div>`;

  card.querySelector('.memory-focus-close').onclick=()=>renderMemoryFocus(null);
  card.querySelectorAll('[data-focus-mode]').forEach(b=>{
    b.classList.toggle('on',b.dataset.focusMode===__smMemoryFocusMode);
    b.onclick=()=>{
      __smMemoryFocusMode=b.dataset.focusMode;
      renderMemoryFocus(key);
    };
  });

  const body=card.querySelector('.memory-focus-body');

  if(__smMemoryFocusMode==='relationship'){
    renderRelationshipView(key,body);
  }else{
    const timeline=document.createElement('div');
    timeline.className='memory-timeline';

    if(!events.length){
      timeline.innerHTML='<div class="annotation-empty">현재 읽은 범위에서는 연결된 위치를 찾지 못했습니다.</div>';
    }else{
      events.forEach(e=>{
        const btn=document.createElement('button');
        btn.type='button';
        btn.className='memory-timeline-event';
        btn.style.setProperty('--event-accent',e.accent||'#ba7c59');
        btn.innerHTML=`<b>${escapeHtml(e.label)}</b><span>${escapeHtml(e.text)}</span><small>${escapeHtml(e.source)}</small>`;
        btn.onclick=()=>jumpToTimelineEvent(e,key);
        timeline.append(btn);
      });
    }
    body.append(timeline);
  }

  host.append(card);
  document.querySelectorAll('.system-memory').forEach(x=>x.classList.toggle('focused',x.dataset.memoryKey===key));
}
