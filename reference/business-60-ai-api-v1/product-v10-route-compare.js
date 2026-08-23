(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const contract = window.B60_EXECUTION_HANDOFF || { mappings: {} };
  const grid = document.getElementById('signal-grid-v6');
  const stats = document.getElementById('explore-stats');
  if (!signals.length || !grid) return;

  const byId = new Map(signals.map(signal => [signal.id, signal]));
  const selected = new Set();
  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const routeLabel = signal => `${signal.provider}${signal.model ? ` → ${signal.model}` : ''}`;
  const mappingFor = signal => contract.mappings?.[signal.id] || null;
  const userState = signal => mappingFor(signal)?.userState === 'ROUTER_MAPPED' ? 'ROUTER MAPPED' : 'INFO ONLY';

  const tray = document.createElement('div');
  tray.className = 'ux2-compare-tray';
  tray.setAttribute('aria-live', 'polite');
  tray.innerHTML = '<div><span>ROUTE COMPARE</span><b data-compare-count>0 / 3</b><em data-compare-status>경로를 선택해 비교하세요.</em></div><button type="button" data-open-compare disabled>COMPARE</button>';
  document.body.appendChild(tray);

  const sheet = document.createElement('section');
  sheet.className = 'ux2-sheet';
  sheet.setAttribute('aria-hidden', 'true');
  sheet.innerHTML = '<div class="ux2-sheet-panel" role="dialog" aria-modal="true" aria-label="Access route comparison"><button type="button" class="ux2-sheet-close" data-close-sheet aria-label="Close comparison">×</button><div data-sheet-body></div></div>';
  document.body.appendChild(sheet);

  const handoff = document.createElement('section');
  handoff.className = 'ux2-handoff';
  handoff.setAttribute('aria-hidden', 'true');
  handoff.innerHTML = '<div class="ux2-handoff-panel" role="dialog" aria-modal="true" aria-label="Execution handoff details"><button type="button" class="ux2-sheet-close" data-close-handoff aria-label="Close handoff details">×</button><div data-handoff-body></div></div>';
  document.body.appendChild(handoff);

  function updateTray(message = '') {
    const count = selected.size;
    tray.classList.toggle('is-visible', count > 0);
    tray.querySelector('[data-compare-count]').textContent = `${count} / 3`;
    tray.querySelector('[data-open-compare]').disabled = count < 2;
    tray.querySelector('[data-compare-status]').textContent = message || (count < 2 ? '한 경로를 더 선택하면 비교할 수 있습니다.' : `${count}개 접근 경로를 비교할 수 있습니다.`);
    document.querySelectorAll('[data-compare-id]').forEach(button => {
      const on = selected.has(button.dataset.compareId);
      button.classList.toggle('is-selected', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.textContent = on ? 'SELECTED' : 'COMPARE';
    });
  }

  function toggleCompare(id) {
    if (!byId.has(id)) return;
    if (selected.has(id)) selected.delete(id);
    else if (selected.size >= 3) return updateTray('최대 3개 경로까지 비교할 수 있습니다.');
    else selected.add(id);
    updateTray();
  }

  function compareCard(signal) {
    const mapping = mappingFor(signal);
    const source = signal.sources?.[0];
    return `<article class="ux2-compare-card">
      <div class="ux2-compare-card-head"><small>${esc(signal.provider)}</small><h3>${esc(signal.model || signal.title)}</h3><button type="button" data-remove-compare="${esc(signal.id)}">REMOVE</button></div>
      <dl>
        <div><dt>ACCESS</dt><dd>${esc((signal.access || []).join(' · ') || '—')}</dd></div>
        <div><dt>FREE / CREDIT</dt><dd>${esc(signal.freeLabel || '—')}</dd></div>
        <div><dt>PRICE</dt><dd>${esc(signal.price || 'Unknown')}</dd></div>
        <div><dt>CONTEXT</dt><dd>${esc(signal.context || 'Unknown')}</dd></div>
        <div><dt>VERIFIED</dt><dd>${esc(signal.verifiedAt || 'Unknown')} · ${esc(signal.verification || 'UNKNOWN')}</dd></div>
        <div><dt>EXECUTION</dt><dd><b class="ux2-exec-state ${mapping ? 'is-mapped' : ''}">${userState(signal)}</b></dd></div>
      </dl>
      ${source ? `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">OFFICIAL SOURCE ↗</a>` : ''}
      ${mapping ? `<button type="button" class="ux2-handoff-action" data-handoff-id="${esc(signal.id)}">HANDOFF DETAILS</button>` : '<p class="ux2-info-note">현재는 탐색 정보만 제공합니다. 실행 경로를 추정해서 만들지 않습니다.</p>'}
    </article>`;
  }

  function openCompare() {
    const list = [...selected].map(id => byId.get(id)).filter(Boolean);
    if (list.length < 2) return;
    sheet.querySelector('[data-sheet-body]').innerHTML = `<header class="ux2-sheet-head"><span>COMPARE ACCESS ROUTES</span><h2>같은 ‘무료’라도,<br>실제로는 다른 경로입니다.</h2><p>Provider, 모델, 무료 조건, 가격, context, 검증 상태와 실행 준비 상태를 같은 기준으로 비교합니다.</p></header><div class="ux2-compare-grid">${list.map(compareCard).join('')}</div>`;
    sheet.classList.add('is-open');
    sheet.setAttribute('aria-hidden', 'false');
  }

  function closeSheet() {
    sheet.classList.remove('is-open');
    sheet.setAttribute('aria-hidden', 'true');
  }

  function openHandoff(id) {
    const signal = byId.get(id);
    const mapping = signal && mappingFor(signal);
    if (!signal || !mapping) return;
    handoff.querySelector('[data-handoff-body]').innerHTML = `<header class="ux2-sheet-head"><span>EXECUTION HANDOFF</span><h2>${esc(signal.model || signal.title)}</h2><p>이 경로는 현재 Business 14 Router Core의 정확한 모델 ID와 매핑됩니다. 실행과 자격증명 처리는 B60이 아니라 실행 계층에서 담당합니다.</p></header>
      <div class="ux2-handoff-route"><b>ROUTER MAPPED</b><dl>
        <div><dt>DISCOVERY ROUTE</dt><dd>${esc(signal.provider)} → ${esc(signal.model || signal.title)}</dd></div>
        <div><dt>B14 MODEL</dt><dd><code>${esc(mapping.b14ModelId)}</code></dd></div>
        <div><dt>B14 ROUTE</dt><dd><code>${esc(mapping.b14RouteId)}</code></dd></div>
        <div><dt>CREDENTIAL</dt><dd>${esc(mapping.credentialMode)}</dd></div>
        <div><dt>WORKSPACE</dt><dd><code>${esc(mapping.workspacePath)}</code></dd></div>
        <div><dt>LIVE TARGET</dt><dd>${mapping.targetUrl ? 'BOUND' : 'NOT BOUND'}</dd></div>
      </dl></div>
      <div class="ux2-handoff-boundary"><strong>지금은 연결 계약까지만 열려 있습니다.</strong><p>승인된 B14 배포 대상 URL이 설정되기 전에는 외부 실행 버튼을 만들지 않습니다. API Key도 이 사이트에서 받거나 저장하지 않습니다.</p></div>`;
    handoff.classList.add('is-open');
    handoff.setAttribute('aria-hidden', 'false');
  }

  function closeHandoff() {
    handoff.classList.remove('is-open');
    handoff.setAttribute('aria-hidden', 'true');
  }

  function signalFromRouteArticle(article) {
    const text = article.querySelector('.ia-route-top h4')?.textContent?.trim();
    return signals.find(signal => routeLabel(signal) === text) || null;
  }

  function signalFromConnectArticle(article) {
    const provider = article.querySelector('small')?.textContent?.trim();
    const model = article.querySelector('h4')?.textContent?.trim();
    return signals.find(signal => signal.provider === provider && (signal.model || signal.title) === model) || null;
  }

  function actionMarkup(signal) {
    const mapping = mappingFor(signal);
    return `<div class="ux2-route-actions"><button type="button" data-compare-id="${esc(signal.id)}" aria-pressed="${selected.has(signal.id) ? 'true' : 'false'}">${selected.has(signal.id) ? 'SELECTED' : 'COMPARE'}</button>${mapping ? `<button type="button" class="ux2-handoff-action" data-handoff-id="${esc(signal.id)}">HANDOFF DETAILS</button>` : '<span class="ux2-info-only">INFO ONLY</span>'}</div>`;
  }

  function decorateRoute(article) {
    if (article.dataset.ux2Ready === 'true') return;
    const signal = signalFromRouteArticle(article);
    if (!signal) return;
    article.dataset.ux2Ready = 'true';
    article.dataset.routeId = signal.id;
    const runtime = article.querySelector('[data-runtime-state]');
    const mapping = mappingFor(signal);
    if (runtime) {
      runtime.dataset.runtimeState = mapping ? 'CONNECTABLE' : 'DISCOVERABLE_ONLY';
      runtime.textContent = mapping ? 'ROUTER MAPPED' : 'INFO ONLY';
      runtime.classList.toggle('is-mapped', Boolean(mapping));
    }
    article.insertAdjacentHTML('beforeend', actionMarkup(signal));
  }

  function decorateAccessCard(card) {
    if (card.dataset.ux2Compare === 'true') return;
    const signal = byId.get(card.dataset.id);
    if (!signal) return;
    card.dataset.ux2Compare = 'true';
    card.insertAdjacentHTML('beforeend', `<button type="button" class="ux2-card-compare" data-compare-id="${esc(signal.id)}" aria-pressed="${selected.has(signal.id) ? 'true' : 'false'}">${selected.has(signal.id) ? 'SELECTED' : 'COMPARE'}</button>`);
  }

  function decorateConnect() {
    const boundary = grid.querySelector('.ia-connect-boundary');
    if (!boundary) return;
    const mappedCount = signals.filter(signal => mappingFor(signal)).length;
    const infoCount = signals.length - mappedCount;
    if (stats) stats.innerHTML = `<span><b>${signals.length}</b> known routes</span><span><b>${mappedCount}</b> router mapped</span><span><b>${infoCount}</b> info only</span>`;
    boundary.querySelectorAll('.ia-connect-routes article').forEach(article => {
      if (article.dataset.ux2Ready === 'true') return;
      const signal = signalFromConnectArticle(article);
      if (!signal) return;
      article.dataset.ux2Ready = 'true';
      article.dataset.routeId = signal.id;
      const mapping = mappingFor(signal);
      const state = article.querySelector('.ia-state');
      if (state) {
        state.classList.toggle('discoverable', !mapping);
        state.classList.toggle('connectable', Boolean(mapping));
        state.textContent = mapping ? 'ROUTER MAPPED' : 'INFO ONLY';
        state.dataset.runtimeState = mapping ? 'CONNECTABLE' : 'DISCOVERABLE_ONLY';
      }
      const side = article.lastElementChild;
      if (mapping && side && !side.querySelector('[data-handoff-id]')) side.insertAdjacentHTML('beforeend', `<button type="button" class="ux2-handoff-action" data-handoff-id="${esc(signal.id)}">HANDOFF DETAILS</button>`);
    });
    const key = boundary.querySelector('.ia-state-key .connectable');
    if (key) key.textContent = 'ROUTER MAPPED';
  }

  function decorate() {
    grid.querySelectorAll('.ia-route-detail').forEach(decorateRoute);
    grid.querySelectorAll('.access-card[data-id]').forEach(decorateAccessCard);
    decorateConnect();
    updateTray();
  }

  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; decorate(); });
  });
  observer.observe(grid, { childList: true });

  document.addEventListener('click', event => {
    const compare = event.target.closest('[data-compare-id]');
    if (compare) {
      event.preventDefault(); event.stopPropagation(); toggleCompare(compare.dataset.compareId); return;
    }
    const remove = event.target.closest('[data-remove-compare]');
    if (remove) { event.preventDefault(); selected.delete(remove.dataset.removeCompare); updateTray(); openCompare(); return; }
    const handoffButton = event.target.closest('[data-handoff-id]');
    if (handoffButton) { event.preventDefault(); event.stopPropagation(); openHandoff(handoffButton.dataset.handoffId); return; }
    if (event.target.closest('[data-open-compare]')) { event.preventDefault(); openCompare(); return; }
    if (event.target.closest('[data-close-sheet]') || event.target === sheet) closeSheet();
    if (event.target.closest('[data-close-handoff]') || event.target === handoff) closeHandoff();
  }, true);

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') { closeSheet(); closeHandoff(); }
  });

  decorate();
})();
