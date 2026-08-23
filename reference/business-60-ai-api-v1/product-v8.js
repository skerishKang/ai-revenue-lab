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
  const esc = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#039;'}[c]));
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
    stats.innerHTML = `<span><b>${list.length}</b> new today</span><span><b>${latest.records.length}</b> current records</span><span><b>${latest.date}</b> baseline date</span>`;
    grid.innerHTML = list.length
      ? `<div class="v8-context"><span>NEW TODAY</span><h3>오늘 처음 검증된 AI 접근 경로</h3><p>첫 snapshot 날짜와 FIRST_SEEN이 같은 항목만 표시합니다. 기존 항목을 새것처럼 재포장하지 않습니다.</p></div>${list.map(signal=>row(signal,'FIRST SEEN TODAY')).join('')}`
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

  newTab.addEventListener('click',()=>{setActive(newTab);renderNew()});
  endingTab.addEventListener('click',()=>{setActive(endingTab);renderEnding()});

  document.querySelectorAll('.explore-tab:not([data-v8-view])').forEach(tab=>tab.addEventListener('click',()=>{mode=null}));
  search.addEventListener('input',()=>{if(mode==='new')renderNew();else if(mode==='ending')renderEnding()});
})();
