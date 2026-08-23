(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const history = window.B60_SIGNAL_HISTORY || [];
  const explore = document.getElementById('explore');
  if (!signals.length || !explore) return;

  const grid = document.getElementById('signal-grid-v6');
  const tabs = document.querySelector('.explore-tabs');
  const search = document.getElementById('signal-search');
  const stats = document.getElementById('explore-stats');
  if (!grid || !tabs || !search || !stats) return;

  const KEY = 'b60.ai-api.watchlist.v1';
  const VISIT_KEY = 'b60.ai-api.last-visit.v1';
  const esc = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

  let storageAvailable = true;
  const safeGet = (key, fallback=null) => {
    try { return localStorage.getItem(key) ?? fallback; }
    catch { storageAvailable = false; return fallback; }
  };
  const safeSet = (key, value) => {
    try { localStorage.setItem(key, value); return true; }
    catch { storageAvailable = false; return false; }
  };
  const safeArray = raw => {
    try { const value = JSON.parse(raw || '[]'); return Array.isArray(value) ? value : []; }
    catch { return []; }
  };

  const saved = new Set(safeArray(safeGet(KEY, '[]')));
  const previousVisit = safeGet(VISIT_KEY, null);
  safeSet(VISIT_KEY, new Date().toISOString());

  let mode = 'v6';

  const watchTab = document.createElement('button');
  watchTab.className = 'explore-tab';
  watchTab.type = 'button';
  watchTab.dataset.v7View = 'watchlist';
  watchTab.textContent = 'WATCHLIST';

  const changesTab = document.createElement('button');
  changesTab.className = 'explore-tab';
  changesTab.type = 'button';
  changesTab.dataset.v7View = 'changes';
  changesTab.textContent = 'CHANGES';

  tabs.append(watchTab, changesTab);

  const toolbar = document.querySelector('.explore-toolbar');
  const watchBadge = document.createElement('button');
  watchBadge.type = 'button';
  watchBadge.className = 'watch-badge-v7';
  watchBadge.innerHTML = '<span>WATCHING</span><b>0</b>';
  toolbar?.appendChild(watchBadge);

  const signalById = id => signals.find(s => s.id === id);
  const persist = () => safeSet(KEY, JSON.stringify([...saved]));
  const setActive = btn => {
    document.querySelectorAll('.explore-tab').forEach(b => b.classList.remove('is-active'));
    btn?.classList.add('is-active');
  };

  function updateBadge(){
    watchBadge.querySelector('b').textContent = String(saved.size);
    watchBadge.classList.toggle('has-items', saved.size > 0);
    watchBadge.title = storageAvailable ? 'Saved in this browser' : 'Browser storage unavailable; session only';
  }

  function toggleSave(id){
    if (!signalById(id)) return;
    saved.has(id) ? saved.delete(id) : saved.add(id);
    persist();
    updateBadge();
    if (mode === 'watchlist') renderWatchlist();
    else decorateCards();
  }

  function saveButton(id){
    const active = saved.has(id);
    return `<button type="button" class="save-v7 ${active?'is-saved':''}" data-save-id="${esc(id)}" aria-pressed="${active?'true':'false'}"><span>${active?'SAVED':'SAVE'}</span><i>${active?'★':'☆'}</i></button>`;
  }

  function decorateCards(){
    if (mode !== 'v6') return;
    grid.querySelectorAll('.access-card[data-id]').forEach(card => {
      const id = card.dataset.id;
      let btn = card.querySelector('.save-v7');
      if (!btn) {
        card.insertAdjacentHTML('beforeend', saveButton(id));
      } else {
        const active = saved.has(id);
        btn.classList.toggle('is-saved', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        btn.querySelector('span').textContent = active ? 'SAVED' : 'SAVE';
        btn.querySelector('i').textContent = active ? '★' : '☆';
      }
    });
  }

  const observer = new MutationObserver(() => decorateCards());
  observer.observe(grid, { childList:true });

  function renderWatchlist(){
    mode = 'watchlist';
    const q = search.value.trim().toLowerCase();
    const list = [...saved].map(signalById).filter(Boolean).filter(s => !q || [s.provider,s.title,s.model,s.summary,...(s.access||[])].join(' ').toLowerCase().includes(q));
    stats.innerHTML = `<span><b>${list.length}</b> watched</span><span><b>${saved.size}</b> saved total</span><span><b>${storageAvailable?'LOCAL':'SESSION'}</b> ${storageAvailable?'browser storage':'storage unavailable'}</span>`;
    if (!list.length) {
      grid.innerHTML = `<div class="v7-empty"><span>WATCHLIST</span><h3>${saved.size ? '검색 결과가 없습니다.' : '아직 저장한 경로가 없습니다.'}</h3><p>${saved.size ? '검색어를 지워보세요.' : `NOW에서 관심 있는 경로의 SAVE를 누르면 이곳에 모입니다. ${storageAvailable?'현재 단계에서는 계정 없이 이 브라우저에만 저장됩니다.':'현재 브라우저 저장소가 차단되어 이 세션에서만 유지됩니다.'}`}</p></div>`;
      return;
    }
    grid.innerHTML = list.map(s => `<article class="watch-card-v7" data-id="${esc(s.id)}">
      <div><small>${esc(s.provider)} · ${esc(s.verification)}</small><h3>${esc(s.title)}</h3><p>${esc(s.summary)}</p></div>
      <div class="watch-card-side"><strong>${esc(s.freeLabel)}</strong><span>VERIFIED ${esc(s.verifiedAt)}</span>${saveButton(s.id)}</div>
    </article>`).join('');
  }

  function eventKind(type){
    if (type === 'FIRST_SEEN') return 'BASELINE';
    if (type === 'PENDING_CLAIM_RECORDED') return 'PENDING';
    return 'CHANGED';
  }

  function renderChanges(){
    mode = 'changes';
    const q = search.value.trim().toLowerCase();
    const events = history.flatMap(h => (h.events || []).map(e => ({...e, id:h.id, firstSeen:h.firstSeen, lastVerified:h.lastVerified})))
      .map(e => ({...e, signal:signalById(e.id)}))
      .filter(e => e.signal)
      .filter(e => !q || [e.signal.provider,e.signal.title,e.type,e.summary].join(' ').toLowerCase().includes(q))
      .sort((a,b) => b.date.localeCompare(a.date));

    const realChanges = events.filter(e => !['FIRST_SEEN','PENDING_CLAIM_RECORDED'].includes(e.type));
    stats.innerHTML = `<span><b>${events.length}</b> history events</span><span><b>${realChanges.length}</b> verified changes</span><span><b>${history.length}</b> tracked signals</span>`;
    const intro = `<div class="changes-intro-v7"><span>CHANGE LEDGER</span><h3>${realChanges.length ? '검증된 변경사항이 있습니다.' : '아직 before → after 변경 기록은 없습니다.'}</h3><p>2026-08-23이 첫 catalog snapshot입니다. 따라서 오늘은 FIRST_SEEN과 pending-claim 기록만 존재합니다. 다음 검증 snapshot부터 가격·무료량·종료일·접근방식 변화가 생기면 여기에 이전값과 새값을 남깁니다.${previousVisit ? ' 이 브라우저의 이전 방문 시각도 저장되어 있습니다.' : ''}</p></div>`;
    grid.innerHTML = intro + events.map(e => `<article class="change-row-v7">
      <div><span class="change-kind ${eventKind(e.type).toLowerCase()}">${eventKind(e.type)}</span><time>${esc(e.date)}</time></div>
      <div><small>${esc(e.signal.provider)}</small><h4>${esc(e.signal.title)}</h4><p>${esc(e.summary)}</p></div>
      <code>${esc(e.type)}</code>
    </article>`).join('');
  }

  watchTab.addEventListener('click', () => { setActive(watchTab); renderWatchlist(); });
  changesTab.addEventListener('click', () => { setActive(changesTab); renderChanges(); });
  watchBadge.addEventListener('click', () => { setActive(watchTab); renderWatchlist(); document.getElementById('explore')?.scrollIntoView({behavior:'smooth'}); });

  document.querySelectorAll('.explore-tab:not([data-v7-view])').forEach(btn => btn.addEventListener('click', () => { mode='v6'; setTimeout(decorateCards, 0); }));
  search.addEventListener('input', () => { if (mode==='watchlist') renderWatchlist(); else if (mode==='changes') renderChanges(); });

  document.addEventListener('click', e => {
    const save = e.target.closest('[data-save-id]');
    if (!save) return;
    e.preventDefault();
    e.stopPropagation();
    toggleSave(save.dataset.saveId);
  }, true);

  grid.addEventListener('keydown', e => {
    const save = e.target.closest('[data-save-id]');
    if (save && (e.key==='Enter' || e.key===' ')) {
      e.preventDefault(); e.stopPropagation(); toggleSave(save.dataset.saveId);
    }
  });

  window.B60_WATCH_STATE = Object.freeze({
    ids: () => [...saved],
    has: id => saved.has(id),
    toggle: id => toggleSave(id),
    storageAvailable: () => storageAvailable
  });

  updateBadge();
  decorateCards();
})();
