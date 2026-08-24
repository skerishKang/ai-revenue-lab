(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const signalHistory = window.B60_SIGNAL_HISTORY || [];
  const mappings = window.B60_EXECUTION_HANDOFF?.mappings || {};
  const watchState = window.B60_WATCH_STATE;
  const explore = document.getElementById('explore');
  const grid = document.getElementById('signal-grid-v6');
  const stats = document.getElementById('explore-stats');
  const search = document.getElementById('signal-search');
  const searchLabel = search?.closest('.explore-search');
  const secondary = explore?.querySelector('.ia-secondary');
  const head = explore?.querySelector('.explore-head');
  const headTitle = head?.querySelector('h2');
  const headCopy = head?.querySelector('p');
  if (!signals.length || !watchState || !explore || !grid || !stats || !search || !secondary || !headTitle || !headCopy) return;

  const byId = new Map(signals.map(signal => [signal.id, signal]));
  const historyById = new Map(signalHistory.map(item => [item.id, item]));
  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const searchable = signal => [signal.provider, signal.title, signal.model, signal.summary, signal.freeLabel, ...(signal.access || [])].join(' ').toLowerCase();
  const eventKind = type => type === 'FIRST_SEEN' ? 'BASELINE' : type === 'PENDING_CLAIM_RECORDED' ? 'PENDING' : 'CHANGED';
  const routeState = signal => mappings[signal.id] ? 'ROUTER MAPPED' : 'INFO ONLY';
  const savedSignals = () => watchState.ids().map(id => byId.get(id)).filter(Boolean);
  const eventsFor = id => (historyById.get(id)?.events || []).map((event, eventIndex) => ({...event, eventIndex, id, signal: byId.get(id)})).filter(event => event.signal);
  const eventSort = (a, b) => b.date.localeCompare(a.date) || b.eventIndex - a.eventIndex;
  const allEvents = () => signalHistory.flatMap(item => eventsFor(item.id)).sort(eventSort);
  const latestEvent = id => [...eventsFor(id)].sort(eventSort)[0] || null;
  const query = () => search.value.trim().toLowerCase();

  let watchActive = false;
  let subview = 'saved';

  function setPrimaryActive() {
    document.querySelectorAll('[data-ia-view]').forEach(control => {
      const on = control.dataset.iaView === 'watch';
      control.classList.toggle('is-active', on);
      if (control.tagName === 'BUTTON') control.setAttribute('aria-current', on ? 'page' : 'false');
    });
  }

  function setWatchHead() {
    headTitle.innerHTML = '저장한 경로와,<br>기록된 변화를 함께 봅니다.';
    headCopy.textContent = watchState.storageAvailable()
      ? '저장 상태는 이 브라우저에만 유지됩니다. Provider·Model 관계와 검증 이력을 같은 route 기준으로 다시 확인합니다.'
      : '브라우저 저장소가 차단되어 현재 세션에서만 유지됩니다. 계정이나 서버 저장으로 가장하지 않습니다.';
    if (searchLabel) searchLabel.hidden = false;
    search.placeholder = subview === 'saved' ? 'search saved routes / providers / models' : 'search recorded activity';
    secondary.hidden = false;
    secondary.innerHTML = `<button type="button" role="tab" data-ux4-watch="saved" class="${subview === 'saved' ? 'is-active' : ''}" aria-selected="${subview === 'saved' ? 'true' : 'false'}">SAVED</button><button type="button" role="tab" data-ux4-watch="changes" class="${subview === 'changes' ? 'is-active' : ''}" aria-selected="${subview === 'changes' ? 'true' : 'false'}">CHANGES</button>`;
  }

  function renderEvent(event, scope = 'catalog') {
    const kind = eventKind(event.type);
    const signal = event.signal;
    return `<article class="ux4-event" data-event-scope="${scope}">
      <div class="ux4-event-meta"><span class="ux4-kind is-${kind.toLowerCase()}">${kind}</span><time>${esc(event.date)}</time></div>
      <div class="ux4-event-body"><small>${esc(signal.provider)}${signal.model ? ` · ${esc(signal.model)}` : ''}</small><h4>${esc(signal.title)}</h4><p>${esc(event.summary)}</p></div>
      <div class="ux4-event-side"><code>${esc(event.type)}</code><button type="button" data-watch-open-route="${esc(signal.id)}">OPEN ROUTE</button></div>
    </article>`;
  }

  function renderSaved() {
    subview = 'saved';
    setWatchHead();
    const q = query();
    const all = savedSignals();
    const list = all.filter(signal => !q || searchable(signal).includes(q));
    const providers = new Set(all.map(signal => signal.provider));
    const models = new Set(all.map(signal => signal.model).filter(Boolean));
    const mapped = all.filter(signal => mappings[signal.id]).length;
    stats.innerHTML = `<span><b>${all.length}</b> saved routes</span><span><b>${providers.size}</b> providers</span><span><b>${models.size}</b> models</span><span><b>${mapped}</b> router mapped</span><span><b>${watchState.storageAvailable() ? 'LOCAL' : 'SESSION'}</b> storage</span>`;

    if (!list.length) {
      grid.innerHTML = `<section class="ux4-empty"><span>SAVED ROUTES</span><h3>${all.length ? '검색 결과가 없습니다.' : '아직 저장한 접근 경로가 없습니다.'}</h3><p>${all.length ? '검색어를 지우거나 Provider/Model 이름을 바꿔보세요.' : 'Discover 또는 Route Detail에서 SAVE를 누르면 Provider·Model 관계와 함께 이곳에서 다시 열 수 있습니다.'}</p><small>${watchState.storageAvailable() ? 'ACCOUNT SYNC 없음 · 이 브라우저에만 저장' : 'LOCAL STORAGE 사용 불가 · 현재 세션에서만 유지'}</small></section>`;
      return;
    }

    grid.innerHTML = `<section class="ux4-saved-list">${list.map(signal => {
      const event = latestEvent(signal.id);
      const mappedRoute = Boolean(mappings[signal.id]);
      return `<article class="ux4-saved-route" data-watch-route-id="${esc(signal.id)}">
        <header><div><span>ACCESS ROUTE</span><h3>${esc(signal.model || signal.title)}</h3><p>${esc(signal.provider)} · ${esc(signal.title)}</p></div><b class="ux4-runtime ${mappedRoute ? 'is-mapped' : ''}">${routeState(signal)}</b></header>
        <div class="ux4-saved-grid">
          <div class="ux4-current"><small>CURRENT ACCESS</small><strong>${esc(signal.freeLabel || 'Current access')}</strong><p>${esc(signal.summary || '')}</p><dl><div><dt>VERIFIED</dt><dd>${esc(signal.verifiedAt || 'Unknown')}</dd></div><div><dt>SOURCE STATE</dt><dd>${esc(signal.verification || 'UNKNOWN')}</dd></div></dl></div>
          <div class="ux4-entity-context"><small>ENTITY CONTEXT</small><dl><div><dt>PROVIDER</dt><dd>${esc(signal.provider)}</dd></div><div><dt>MODEL</dt><dd>${esc(signal.model || 'Catalog / varies')}</dd></div><div><dt>ACCESS</dt><dd>${esc((signal.access || []).join(' · ') || '—')}</dd></div></dl></div>
          <div class="ux4-activity"><small>LATEST RECORDED ACTIVITY</small>${event ? `<span class="ux4-kind is-${eventKind(event.type).toLowerCase()}">${eventKind(event.type)}</span><strong>${esc(event.date)}</strong><p>${esc(event.summary)}</p>` : '<strong>NO HISTORY EVENT</strong><p>현재 route에 연결된 history event가 없습니다.</p>'}</div>
        </div>
        <div class="ux4-actions">
          <button type="button" class="is-primary" data-watch-open-route="${esc(signal.id)}">OPEN ROUTE</button>
          <button type="button" data-provider-open="${esc(signal.provider)}">PROVIDER</button>
          ${signal.model ? `<button type="button" data-model-open="${esc(signal.model)}">MODEL</button>` : ''}
          <button type="button" data-compare-id="${esc(signal.id)}" aria-pressed="false">COMPARE</button>
          <button type="button" class="is-remove" data-watch-remove="${esc(signal.id)}">REMOVE</button>
        </div>
      </article>`;
    }).join('')}</section>`;
  }

  function renderChanges() {
    subview = 'changes';
    setWatchHead();
    const q = query();
    const savedIds = new Set(watchState.ids());
    const savedEvents = allEvents().filter(event => savedIds.has(event.id)).filter(event => !q || [event.signal.provider, event.signal.title, event.signal.model, event.type, event.summary].join(' ').toLowerCase().includes(q));
    const catalogEvents = allEvents().filter(event => !q || [event.signal.provider, event.signal.title, event.signal.model, event.type, event.summary].join(' ').toLowerCase().includes(q));
    const verifiedChanges = catalogEvents.filter(event => eventKind(event.type) === 'CHANGED');
    const pending = catalogEvents.filter(event => eventKind(event.type) === 'PENDING');
    stats.innerHTML = `<span><b>${savedEvents.length}</b> saved-route events</span><span><b>${verifiedChanges.length}</b> verified changes</span><span><b>${pending.length}</b> pending evidence</span><span><b>${catalogEvents.length}</b> catalog events</span>`;

    const savedBlock = savedEvents.length
      ? savedEvents.map(event => renderEvent(event, 'saved')).join('')
      : `<div class="ux4-activity-empty"><strong>${savedIds.size ? '저장한 경로에 표시할 기록이 없습니다.' : '먼저 관심 경로를 저장해보세요.'}</strong><p>Watch는 저장한 Access Route의 기록을 우선 보여줍니다.</p></div>`;
    const catalogBlock = catalogEvents.length
      ? catalogEvents.map(event => renderEvent(event, 'catalog')).join('')
      : '<div class="ux4-activity-empty"><strong>검색 조건에 맞는 기록이 없습니다.</strong></div>';

    grid.innerHTML = `<section class="ux4-changes">
      <div class="ux4-change-intro"><span>WATCH ACTIVITY</span><h3>${verifiedChanges.length ? '검증된 before → after 변경 기록이 있습니다.' : '아직 검증된 before → after 변경은 없습니다.'}</h3><p>FIRST_SEEN은 catalog 기준선으로, PENDING_CLAIM_RECORDED는 확인 대기 증거로 표시합니다. 둘 다 CHANGED 또는 새 알림으로 과장하지 않습니다.</p></div>
      <section class="ux4-change-section"><header><span>SAVED-ROUTE ACTIVITY</span><strong>${savedEvents.length}</strong></header>${savedBlock}</section>
      <section class="ux4-change-section is-secondary"><header><span>CATALOG ACTIVITY</span><strong>${catalogEvents.length}</strong></header>${catalogBlock}</section>
    </section>`;
  }

  function showWatch(next = 'saved') {
    watchActive = true;
    subview = next === 'changes' ? 'changes' : 'saved';
    setPrimaryActive();
    if (subview === 'changes') renderChanges(); else renderSaved();
  }

  function openRoute(id) {
    if (!byId.has(id)) return;
    const url = new URL(location.href);
    url.searchParams.set('route', id);
    url.hash = 'explore';
    window.history.pushState({ b60Route: id }, '', url);
    dispatchEvent(new PopStateEvent('popstate', { state: { b60Route: id } }));
  }

  document.addEventListener('click', event => {
    const watchNav = event.target.closest('[data-ia-view="watch"], .watch-badge-v7');
    if (watchNav) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showWatch('saved');
      explore.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    const primary = event.target.closest('[data-ia-view]');
    if (primary && primary.dataset.iaView !== 'watch') {
      watchActive = false;
      return;
    }

    const watchTab = event.target.closest('[data-ux4-watch]');
    if (watchTab) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showWatch(watchTab.dataset.ux4Watch);
      return;
    }

    const open = event.target.closest('[data-watch-open-route]');
    if (open) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openRoute(open.dataset.watchOpenRoute);
      return;
    }

    const remove = event.target.closest('[data-watch-remove]');
    if (remove) {
      event.preventDefault();
      event.stopImmediatePropagation();
      watchState.toggle(remove.dataset.watchRemove);
      if (watchActive) renderSaved();
      return;
    }

    if (watchActive && event.target.closest('[data-provider-open],[data-model-open]')) {
      watchActive = false;
      return;
    }

    if (watchActive && event.target.closest('[data-save-id]')) {
      setTimeout(() => {
        if (!watchActive) return;
        if (subview === 'changes') renderChanges(); else renderSaved();
        const routeButton = document.querySelector('.ux3-route-detail.is-open [data-save-id]');
        if (routeButton) {
          const active = watchState.has(routeButton.dataset.saveId);
          routeButton.textContent = active ? 'SAVED' : 'SAVE';
          routeButton.setAttribute('aria-pressed', active ? 'true' : 'false');
        }
      }, 0);
    }
  }, true);

  search.addEventListener('input', event => {
    if (!watchActive) return;
    event.stopImmediatePropagation();
    if (subview === 'changes') renderChanges(); else renderSaved();
  }, true);

  window.B60_WATCH_UX = Object.freeze({
    show: showWatch,
    active: () => watchActive,
    subview: () => subview
  });
})();
