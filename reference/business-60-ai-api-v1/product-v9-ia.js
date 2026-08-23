(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const explore = document.getElementById('explore');
  if (!signals.length || !explore) return;

  const shell = explore.querySelector('.explore-shell');
  const toolbar = explore.querySelector('.explore-toolbar');
  const legacyTabs = explore.querySelector('.explore-tabs');
  const grid = document.getElementById('signal-grid-v6');
  const stats = document.getElementById('explore-stats');
  const search = document.getElementById('signal-search');
  const searchLabel = search?.closest('.explore-search');
  const headerNav = document.querySelector('.shell nav');
  const head = explore.querySelector('.explore-head');
  const headTitle = head?.querySelector('h2');
  const headCopy = head?.querySelector('p');
  if (!shell || !toolbar || !legacyTabs || !grid || !stats || !search || !headTitle || !headCopy) return;

  legacyTabs.classList.add('ia-legacy-tabs');
  legacyTabs.setAttribute('aria-hidden', 'true');

  const primary = document.createElement('nav');
  primary.className = 'ia-primary';
  primary.setAttribute('aria-label', 'AI API primary product navigation');
  primary.innerHTML = [
    ['discover', 'Discover'],
    ['providers', 'Providers'],
    ['models', 'Models'],
    ['connect', 'Connect'],
    ['watch', 'Watch']
  ].map(([id, label]) => `<button type="button" data-ia-view="${id}">${label}</button>`).join('');
  toolbar.before(primary);

  const secondary = document.createElement('div');
  secondary.className = 'ia-secondary';
  secondary.setAttribute('role', 'tablist');
  secondary.setAttribute('aria-label', 'Current section views');
  toolbar.prepend(secondary);

  if (headerNav) {
    headerNav.innerHTML = [
      ['discover', 'DISCOVER'],
      ['providers', 'PROVIDERS'],
      ['models', 'MODELS'],
      ['connect', 'CONNECT'],
      ['watch', 'WATCH']
    ].map(([id, label]) => `<a href="#explore" data-ia-view="${id}">${label}</a>`).join('');
  }

  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[c]));

  const freeLike = signal => /FREE|CREDIT|TRIAL/.test(signal.dealType || '') || /free|credit|no-charge/i.test(signal.freeLabel || '');
  const searchable = signal => [signal.provider, signal.title, signal.model, signal.summary, ...(signal.access || [])].join(' ').toLowerCase();
  const query = () => search.value.trim().toLowerCase();
  const matches = signal => !query() || searchable(signal).includes(query());
  const latestDate = list => list.map(item => item.verifiedAt || '').filter(Boolean).sort().at(-1) || '—';

  let activeView = 'discover';
  let discoverSubview = 'free';
  let entityDetail = null;

  const legacyButton = selector => legacyTabs.querySelector(selector);
  const triggerLegacy = selector => {
    const button = legacyButton(selector);
    if (button) button.click();
  };

  function setHead(title, copy) {
    headTitle.innerHTML = title;
    headCopy.textContent = copy;
  }

  function setSearchVisible(visible, placeholder = 'provider / model / access') {
    if (searchLabel) searchLabel.hidden = !visible;
    search.placeholder = placeholder;
  }

  function setPrimaryActive(view) {
    activeView = view;
    document.querySelectorAll('[data-ia-view]').forEach(control => {
      const on = control.dataset.iaView === view;
      control.classList.toggle('is-active', on);
      if (control.tagName === 'BUTTON') control.setAttribute('aria-current', on ? 'page' : 'false');
    });
  }

  function setSecondary(items, selected) {
    secondary.hidden = !items.length;
    secondary.innerHTML = items.map(item => `<button type="button" role="tab" data-ia-subview="${item.id}" class="${item.id === selected ? 'is-active' : ''}" aria-selected="${item.id === selected ? 'true' : 'false'}">${item.label}</button>`).join('');
  }

  function signalCard(signal, index = 0) {
    return `<article class="access-card ${index === 0 ? 'is-featured' : ''}" tabindex="0" role="button" data-id="${esc(signal.id)}" aria-label="Open ${esc(signal.title)} details">
      <div class="card-top"><span class="card-provider">${esc(signal.provider)}</span><span class="verify-pill">OFFICIAL</span></div>
      <h3>${esc(signal.title)}</h3>
      <p>${esc(signal.summary)}</p>
      <strong class="card-free">${esc(signal.freeLabel)}</strong>
      <div class="card-meta">${(signal.access || []).map(x => `<span>${esc(x)}</span>`).join('')}<span>${esc(signal.dealType)}</span></div>
      <span class="card-arrow">↗</span>
    </article>`;
  }

  function renderFree() {
    discoverSubview = 'free';
    const list = signals.filter(freeLike).filter(matches);
    const providers = new Set(list.map(item => item.provider)).size;
    stats.innerHTML = `<span><b>${list.length}</b> free/credit paths</span><span><b>${providers}</b> providers</span><span><b>${list.filter(item => item.verification === 'VERIFIED_OFFICIAL_WEB').length}</b> official</span>`;
    grid.innerHTML = list.map(signalCard).join('') || '<div class="v7-empty"><span>FREE NOW</span><h3>현재 조건에 맞는 무료 접근 경로가 없습니다.</h3><p>검색어를 지우거나 다른 Provider/Model을 확인해보세요.</p></div>';
  }

  const discoverItems = [
    { id: 'free', label: 'FREE NOW' },
    { id: 'new', label: 'NEW TODAY' },
    { id: 'ending', label: 'ENDING SOON' },
    { id: 'changes', label: 'CHANGES' },
    { id: 'all', label: 'ALL ACCESS' }
  ];

  function showDiscover(subview = discoverSubview || 'free') {
    entityDetail = null;
    setPrimaryActive('discover');
    setHead('지금 쓸 수 있는 AI,<br>검증된 경로부터.', '무료·크레딧·새 접근 경로와 실제 변경사항을 공식 출처 기준으로 탐색합니다.');
    setSearchVisible(true, 'provider / model / access');
    discoverSubview = subview;
    setSecondary(discoverItems, subview);
    if (subview === 'new') triggerLegacy('[data-v8-view="new"]');
    else if (subview === 'ending') triggerLegacy('[data-v8-view="ending"]');
    else if (subview === 'changes') triggerLegacy('[data-v7-view="changes"]');
    else if (subview === 'all') triggerLegacy('[data-view="now"]');
    else renderFree();
  }

  function providerGroups() {
    const groups = new Map();
    signals.forEach(signal => {
      if (!groups.has(signal.provider)) groups.set(signal.provider, []);
      groups.get(signal.provider).push(signal);
    });
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  function renderProviders() {
    entityDetail = null;
    const q = query();
    const groups = providerGroups().filter(([provider, items]) => !q || provider.toLowerCase().includes(q) || items.some(matches));
    stats.innerHTML = `<span><b>${groups.length}</b> providers</span><span><b>${groups.reduce((n, [, items]) => n + items.length, 0)}</b> known routes</span><span><b>${groups.reduce((n, [, items]) => n + items.filter(freeLike).length, 0)}</b> free/credit paths</span>`;
    grid.innerHTML = groups.map(([provider, items]) => {
      const models = new Set(items.map(item => item.model).filter(Boolean));
      const access = [...new Set(items.flatMap(item => item.access || []))];
      return `<button class="ia-provider-card" type="button" data-provider-open="${esc(provider)}">
        <div class="ia-card-label">PROVIDER</div>
        <div class="ia-card-head"><h3>${esc(provider)}</h3><span>${items.length} routes</span></div>
        <p>${models.size} model entries · ${items.filter(freeLike).length} free/credit paths · verified ${esc(latestDate(items))}</p>
        <div class="ia-chip-row">${access.slice(0, 4).map(item => `<span>${esc(item)}</span>`).join('')}</div>
        <em>VIEW PROVIDER ↗</em>
      </button>`;
    }).join('') || '<div class="v7-empty"><span>PROVIDERS</span><h3>검색 결과가 없습니다.</h3><p>다른 Provider/Model 키워드로 검색해보세요.</p></div>';
  }

  function showProviders() {
    setPrimaryActive('providers');
    setHead('어디를 통해<br>AI에 접근할 수 있나.', 'Provider·Gateway·Router를 하나의 탐색축으로 보되, 현재 데이터가 확인해 주는 사실만 표시합니다.');
    setSearchVisible(true, 'search providers / models');
    setSecondary([], '');
    renderProviders();
  }

  function renderProviderDetail(provider) {
    const items = signals.filter(signal => signal.provider === provider);
    if (!items.length) return renderProviders();
    entityDetail = { type: 'provider', id: provider };
    stats.innerHTML = `<span><b>${items.length}</b> routes</span><span><b>${new Set(items.map(item => item.model).filter(Boolean)).size}</b> model entries</span><span><b>${items.filter(freeLike).length}</b> free/credit</span><span><b>${esc(latestDate(items))}</b> latest verify</span>`;
    grid.innerHTML = `<section class="ia-entity-detail">
      <button type="button" class="ia-back" data-ia-back="providers">← ALL PROVIDERS</button>
      <div class="ia-entity-hero"><div><span>PROVIDER</span><h3>${esc(provider)}</h3><p>현재 B60 catalog에 검증된 접근 signal만 모았습니다. Provider 유형·지역·런타임 연결 가능성은 근거 데이터가 있을 때 별도 상태로 표시합니다.</p></div><strong>VERIFIED ACCESS</strong></div>
      <div class="ia-route-list">${items.map(item => routeDetail(item)).join('')}</div>
    </section>`;
  }

  function modelGroups() {
    const groups = new Map();
    signals.filter(signal => signal.model).forEach(signal => {
      if (!groups.has(signal.model)) groups.set(signal.model, []);
      groups.get(signal.model).push(signal);
    });
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  function renderModels() {
    entityDetail = null;
    const q = query();
    const groups = modelGroups().filter(([model, items]) => !q || model.toLowerCase().includes(q) || items.some(matches));
    stats.innerHTML = `<span><b>${groups.length}</b> models/catalog entries</span><span><b>${groups.reduce((n, [, items]) => n + items.length, 0)}</b> access routes</span><span><b>${groups.reduce((n, [, items]) => n + items.filter(freeLike).length, 0)}</b> free/credit routes</span>`;
    grid.innerHTML = groups.map(([model, items]) => {
      const providers = [...new Set(items.map(item => item.provider))];
      const contexts = [...new Set(items.map(item => item.context).filter(Boolean))];
      return `<button class="ia-model-card" type="button" data-model-open="${esc(model)}">
        <div><span>MODEL</span><h3>${esc(model)}</h3><p>${providers.length} provider route${providers.length === 1 ? '' : 's'} · ${esc(contexts[0] || 'context not specified')}</p></div>
        <div class="ia-model-side"><strong>${items.some(freeLike) ? 'FREE ROUTE FOUND' : 'ACCESS FOUND'}</strong><small>${providers.map(esc).join(' · ')}</small><em>VIEW ROUTES ↗</em></div>
      </button>`;
    }).join('') || '<div class="v7-empty"><span>MODELS</span><h3>검색 결과가 없습니다.</h3><p>다른 모델 이름이나 Provider를 검색해보세요.</p></div>';
  }

  function showModels() {
    setPrimaryActive('models');
    setHead('모델을 고르고,<br>접근 경로를 비교합니다.', '모델과 Provider를 분리해 봅니다. 같은 모델이 여러 경로에 존재하면 각각의 접근 조건을 독립적으로 비교할 수 있습니다.');
    setSearchVisible(true, 'search models / providers');
    setSecondary([], '');
    renderModels();
  }

  function renderModelDetail(model) {
    const items = signals.filter(signal => signal.model === model);
    if (!items.length) return renderModels();
    entityDetail = { type: 'model', id: model };
    const providers = [...new Set(items.map(item => item.provider))];
    stats.innerHTML = `<span><b>${items.length}</b> access routes</span><span><b>${providers.length}</b> providers</span><span><b>${items.filter(freeLike).length}</b> free/credit</span><span><b>${esc(latestDate(items))}</b> latest verify</span>`;
    grid.innerHTML = `<section class="ia-entity-detail">
      <button type="button" class="ia-back" data-ia-back="models">← ALL MODELS</button>
      <div class="ia-entity-hero"><div><span>MODEL</span><h3>${esc(model)}</h3><p>이 모델/카탈로그 항목에 대해 현재 확인된 Provider 경로를 분리해 보여줍니다. 가격·context·무료 조건은 각 route의 근거 데이터 범위 안에서만 표시합니다.</p></div><strong>${providers.length} PROVIDER${providers.length === 1 ? '' : 'S'}</strong></div>
      <div class="ia-route-list">${items.map(item => routeDetail(item, true)).join('')}</div>
    </section>`;
  }

  function sourceLinks(signal) {
    return (signal.sources || []).map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.label)} ↗</a>`).join('');
  }

  function routeDetail(signal, showProviderJump = false) {
    return `<article class="ia-route-detail">
      <div class="ia-route-top"><div><span>ACCESS ROUTE</span><h4>${esc(signal.provider)}${signal.model ? ` → ${esc(signal.model)}` : ''}</h4></div><b class="ia-state verified">VERIFIED</b></div>
      <p>${esc(signal.summary)}</p>
      <strong>${esc(signal.freeLabel)}</strong>
      <div class="ia-chip-row">${(signal.access || []).map(item => `<span>${esc(item)}</span>`).join('')}<span>${esc(signal.dealType)}</span></div>
      <dl class="ia-route-facts"><div><dt>PRICE</dt><dd>${esc(signal.price || 'Unknown')}</dd></div><div><dt>CONTEXT</dt><dd>${esc(signal.context || 'Unknown')}</dd></div><div><dt>VERIFIED</dt><dd>${esc(signal.verifiedAt || 'Unknown')}</dd></div><div><dt>RUNTIME</dt><dd>DISCOVERABLE_ONLY</dd></div></dl>
      ${signal.pending ? `<div class="ia-pending"><b>${esc(signal.pending.state)}</b><span>${esc(signal.pending.label)}</span><p>${esc(signal.pending.note)}</p></div>` : ''}
      <div class="ia-source-row">${sourceLinks(signal)}</div>
      ${showProviderJump ? `<button type="button" class="ia-inline-action" data-provider-open="${esc(signal.provider)}">VIEW PROVIDER</button>` : ''}
    </article>`;
  }

  function showConnect() {
    entityDetail = null;
    setPrimaryActive('connect');
    setHead('찾은 경로를,<br>실제로 쓰는 곳으로.', 'B60은 어떤 접근 경로가 존재하는지 설명하고, 실행·BYOK·Router·사용량은 B14로 넘깁니다. 지금은 그 경계를 먼저 정확히 보여줍니다.');
    setSearchVisible(false);
    setSecondary([], '');
    const list = signals.filter(matches);
    stats.innerHTML = `<span><b>${list.length}</b> discoverable routes</span><span><b>0</b> declared B14 mappings</span><span><b>B14</b> execution authority</span>`;
    grid.innerHTML = `<section class="ia-connect-boundary">
      <div class="ia-connect-summary"><span>DISCOVERY → EXECUTION</span><h3>Connect는 B60이 키를 받는 화면이 아닙니다.</h3><p>Provider adapter, API key/BYOK, 실제 호출, routing, fallback, usage는 Business 14가 소유합니다. B14 mapping이 명시되기 전에는 아래 경로를 실행 가능하다고 표시하지 않습니다.</p><div class="ia-state-key"><b class="ia-state discoverable">DISCOVERABLE_ONLY</b><b class="ia-state connectable">CONNECTABLE · future explicit mapping</b><b class="ia-state connected">CONNECTED · B14-owned</b></div></div>
      <div class="ia-connect-routes">${list.map(signal => `<article><div><small>${esc(signal.provider)}</small><h4>${esc(signal.model || signal.title)}</h4><p>${esc(signal.freeLabel)}</p></div><div><b class="ia-state discoverable">DISCOVERABLE_ONLY</b><button type="button" data-provider-open="${esc(signal.provider)}">VIEW PROVIDER</button></div></article>`).join('')}</div>
    </section>`;
  }

  const watchItems = [
    { id: 'saved', label: 'SAVED' },
    { id: 'changes', label: 'CHANGES' }
  ];

  function showWatch(subview = 'saved') {
    entityDetail = null;
    setPrimaryActive('watch');
    setHead('저장하고,<br>바뀐 것만 다시 봅니다.', '지금은 계정 없이 이 브라우저에 저장합니다. 이후 Provider·Model·Offer 단위 Watch로 확장하되 현재 local fallback은 유지합니다.');
    setSearchVisible(true, 'search saved / changes');
    setSecondary(watchItems, subview);
    if (subview === 'changes') triggerLegacy('[data-v7-view="changes"]');
    else triggerLegacy('[data-v7-view="watchlist"]');
  }

  function activate(view) {
    if (view === 'providers') showProviders();
    else if (view === 'models') showModels();
    else if (view === 'connect') showConnect();
    else if (view === 'watch') showWatch();
    else showDiscover('free');
  }

  document.addEventListener('click', event => {
    const top = event.target.closest('[data-ia-view]');
    if (top) {
      event.preventDefault();
      activate(top.dataset.iaView);
      explore.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    const sub = event.target.closest('[data-ia-subview]');
    if (sub) {
      event.preventDefault();
      if (activeView === 'discover') showDiscover(sub.dataset.iaSubview);
      else if (activeView === 'watch') showWatch(sub.dataset.iaSubview);
      return;
    }

    const provider = event.target.closest('[data-provider-open]');
    if (provider) {
      event.preventDefault();
      setPrimaryActive('providers');
      setHead('Provider를 열어,<br>현재 경로를 확인합니다.', '현재 catalog에 있는 검증된 signal과 공식 source를 Provider 기준으로 모아 봅니다.');
      setSearchVisible(true, 'search providers / models');
      setSecondary([], '');
      renderProviderDetail(provider.dataset.providerOpen);
      explore.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    const model = event.target.closest('[data-model-open]');
    if (model) {
      event.preventDefault();
      setPrimaryActive('models');
      setHead('모델 하나에,<br>여러 접근 경로를.', 'Provider와 Model을 분리해 실제 선택 가능한 route를 비교할 수 있도록 준비합니다.');
      setSearchVisible(true, 'search models / providers');
      setSecondary([], '');
      renderModelDetail(model.dataset.modelOpen);
      explore.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    const back = event.target.closest('[data-ia-back]');
    if (back) {
      event.preventDefault();
      activate(back.dataset.iaBack);
    }
  });

  search.addEventListener('input', () => {
    if (activeView === 'discover' && discoverSubview === 'free') renderFree();
    else if (activeView === 'providers' && !entityDetail) renderProviders();
    else if (activeView === 'models' && !entityDetail) renderModels();
  });

  showDiscover('free');
})();
