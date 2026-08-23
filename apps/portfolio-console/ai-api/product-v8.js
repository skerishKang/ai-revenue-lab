(() => {
  const engine = window.B60_DIFF_ENGINE;
  const snapshots = window.B60_SNAPSHOTS || [];
  const signals = window.B60_ACCESS_SIGNALS || [];
  const history = window.B60_SIGNAL_HISTORY || [];
  const explore = document.getElementById('explore');
  if (!engine || !snapshots.length || !signals.length || !explore) return;

  const tabs = document.querySelector('.explore-tabs');
  const grid = document.getElementById('signal-grid-v6');
  const stats = document.getElementById('explore-stats');
  const search = document.getElementById('signal-search');
  if (!tabs || !grid || !stats || !search) return;

  const latest = snapshots[snapshots.length - 1];
  const diff = window.B60_SNAPSHOT_DIFF || { events:[], summary:{} };
  const byId = id => signals.find(signal => signal.id === id);
  const esc = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let mode = null;

  const newTab = document.createElement('button');
  newTab.className = 'explore-tab';
  newTab.type = 'button';
  newTab.dataset.v8View = 'new';
  newTab.textContent = 'NEW TODAY';

  const endingTab = document.createElement('button');
  endingTab.className = 'explore-tab';
  endingTab.type = 'button';
  endingTab.dataset.v8View = 'ending';
  endingTab.textContent = 'ENDING SOON';
  tabs.append(newTab, endingTab);

  const snapshotBadge = document.createElement('div');
  snapshotBadge.className = 'snapshot-badge-v8';
  snapshotBadge.innerHTML = `<span>SNAPSHOT</span><b>${esc(latest.date)}</b><em>${snapshots.length} captured · ${latest.records.length} records · ${diff.summary?.verified || 0} verified diffs</em>`;
  document.querySelector('.explore-head')?.appendChild(snapshotBadge);

  const setActive = button => {
    document.querySelectorAll('.explore-tab').forEach(tab => tab.classList.remove('is-active'));
    button.classList.add('is-active');
  };

  const query = () => search.value.trim().toLowerCase();
  const matches = signal => !query() || [signal.provider,signal.title,signal.model,signal.summary,...(signal.access||[])].join(' ').toLowerCase().includes(query());

  function row(signal, label){
    return `<article class="v8-signal-row" data-id="${esc(signal.id)}">
      <div><small>${esc(label)} · ${esc(signal.provider)}</small><h3>${esc(signal.title)}</h3><p>${esc(signal.summary)}</p></div>
      <div><strong>${esc(signal.freeLabel)}</strong><span>${esc(signal.model)}</span><em>VERIFIED ${esc(signal.verifiedAt)}</em></div>
    </article>`;
  }

  function renderNew(){
    mode = 'new';
    const ids = engine.newToday(history, latest.date);
    const list = ids.map(byId).filter(Boolean).filter(matches);
    stats.innerHTML = `<span><b>${list.length}</b> new today</span><span><b>${latest.records.length}</b> current records</span><span><b>${latest.date}</b> snapshot date</span>`;
    grid.innerHTML = list.length
      ? `<div class="v8-context"><span>NEW TODAY</span><h3>오늘 처음 검증된 AI 접근 경로</h3><p>FIRST_SEEN이 현재 snapshot 날짜와 같은 항목만 표시합니다. 기존 항목을 새것처럼 재포장하지 않습니다.</p></div>${list.map(signal=>row(signal,'FIRST SEEN TODAY')).join('')}`
      : '<div class="v7-empty"><span>NEW TODAY</span><h3>오늘 새로 검증된 경로가 없습니다.</h3><p>새 공식-source snapshot에서 처음 등장한 항목만 이곳에 표시됩니다.</p></div>';
  }

  function renderEnding(){
    mode = 'ending';
    const ending = engine.endingSoon(latest, new Date(), 7).map(record=>byId(record.id)).filter(Boolean).filter(matches);
    stats.innerHTML = `<span><b>${ending.length}</b> ending ≤ 7 days</span><span><b>${latest.records.length}</b> checked records</span><span><b>OFFICIAL</b> expiry required</span>`;
    grid.innerHTML = ending.length
      ? ending.map(signal=>row(signal,`ENDS ${signal.expiresAt}`)).join('')
      : '<div class="v8-context truth"><span>ENDING SOON · TRUTH FIRST</span><h3>공식 종료일이 확인된 7일 이내 signal이 없습니다.</h3><p>pending 홍보 문구나 커뮤니티 게시글만으로는 countdown을 만들지 않습니다. snapshot의 <code>expiresAt</code>과 <code>expiryVerification=VERIFIED_OFFICIAL_WEB</code>이 함께 있어야 여기에 나타납니다.</p></div>';
  }

  function diffDescription(event){
    if (event.type === 'NEW') return 'Current official snapshot에서 새로 등장했습니다.';
    if (event.type === 'REMOVED') return 'Current official snapshot에서 더 이상 확인되지 않습니다.';
    return (event.changes || []).map(change => `${change.field}: ${String(change.before ?? '∅')} → ${String(change.after ?? '∅')}`).join(' · ');
  }

  function renderChanges(){
    mode = 'changes';
    const q = query();
    const events = (diff.events || []).filter(event => {
      const signal = byId(event.id) || event.after || event.before || {};
      return !q || [signal.provider,signal.title,event.type,diffDescription(event)].join(' ').toLowerCase().includes(q);
    });
    const verified = events.filter(event => event.verified);
    stats.innerHTML = `<span><b>${events.length}</b> snapshot diffs</span><span><b>${verified.length}</b> verified</span><span><b>${snapshots.length}</b> snapshots</span>`;

    if (snapshots.length < 2) {
      const firstSeen = history.filter(item => item.firstSeen === latest.date).length;
      grid.innerHTML = `<div class="v8-context"><span>CHANGE ENGINE · BASELINE ONLY</span><h3>아직 비교할 이전 snapshot이 없습니다.</h3><p>${esc(latest.date)}가 첫 공식 snapshot입니다. ${firstSeen}개 signal의 FIRST_SEEN만 보존되어 있으며, 두 번째 snapshot부터 실제 before → after diff가 자동 생성됩니다.</p></div>`;
      return;
    }

    grid.innerHTML = events.length ? events.map(event => {
      const signal = byId(event.id) || event.after || event.before || { id:event.id, provider:'Unknown', title:event.id };
      return `<article class="v8-change-row ${event.verified?'is-verified':'is-unverified'}">
        <div><span>${esc(event.type)}</span><time>${esc(diff.previous)} → ${esc(diff.current)}</time></div>
        <div><small>${esc(signal.provider || '')}</small><h3>${esc(signal.title || event.id)}</h3><p>${esc(diffDescription(event))}</p></div>
        <strong>${event.verified?'VERIFIED DIFF':'REVIEW REQUIRED'}</strong>
      </article>`;
    }).join('') : '<div class="v8-context"><span>NO CHANGE</span><h3>두 snapshot 사이에 추적 필드 변화가 없습니다.</h3><p>가격·무료량·접근방식·모델·공식 종료일·검증 상태가 동일합니다.</p></div>';
  }

  newTab.addEventListener('click',()=>{setActive(newTab);renderNew()});
  endingTab.addEventListener('click',()=>{setActive(endingTab);renderEnding()});

  const changesTab = document.querySelector('[data-v7-view="changes"]');
  if (changesTab) changesTab.addEventListener('click',()=>{setActive(changesTab);renderChanges()});

  document.querySelectorAll('.explore-tab:not([data-v8-view]):not([data-v7-view="changes"])').forEach(tab=>tab.addEventListener('click',()=>{mode=null}));
  search.addEventListener('input',()=>{
    if(mode==='new') renderNew();
    else if(mode==='ending') renderEnding();
    else if(mode==='changes') renderChanges();
  });
})();
