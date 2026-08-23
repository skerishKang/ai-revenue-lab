(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const mappings = window.B60_EXECUTION_HANDOFF?.mappings || {};
  const explore = document.getElementById('explore');
  const grid = document.getElementById('signal-grid-v6');
  if (!signals.length || !explore || !grid) return;

  const byId = new Map(signals.map(signal => [signal.id, signal]));
  const WATCH_KEY = 'b60.ai-api.watchlist.v1';
  const matchingAction = (selector, id) => [...document.querySelectorAll(selector)].find(button => button.dataset.saveId === id || button.dataset.compareId === id);
  const isSaved = id => {
    const peer = matchingAction('[data-save-id]', id);
    if (peer?.getAttribute('aria-pressed') === 'true') return true;
    try {
      const value = JSON.parse(localStorage.getItem(WATCH_KEY) || '[]');
      return Array.isArray(value) && value.includes(id);
    } catch {
      return false;
    }
  };
  const isCompared = id => matchingAction('[data-compare-id]', id)?.getAttribute('aria-pressed') === 'true';
  const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const legacyDrawer = document.querySelector('.signal-drawer-v6');
  if (legacyDrawer) {
    legacyDrawer.hidden = true;
    legacyDrawer.setAttribute('aria-hidden', 'true');
  }

  const detail = document.createElement('section');
  detail.className = 'ux3-route-detail';
  detail.setAttribute('aria-hidden', 'true');
  detail.innerHTML = '<div class="ux3-route-panel" role="dialog" aria-modal="true" aria-label="Access route detail"><button type="button" class="ux3-close" data-close-route aria-label="Close route detail">×</button><div data-route-body></div></div>';
  document.body.appendChild(detail);

  let currentId = null;

  const mappingFor = signal => mappings[signal.id] || null;
  const executionLabel = signal => mappingFor(signal) ? 'ROUTER MAPPED' : 'INFO ONLY';
  const sourceLinks = signal => (signal.sources || []).map(source => `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.label)} ↗</a>`).join('');
  const expiryBlock = signal => {
    if (signal.expiresAt && signal.expiryVerification === 'VERIFIED_OFFICIAL_WEB') {
      return `<div class="ux3-offer-fact"><span>VERIFIED END DATE</span><strong>${esc(signal.expiresAt)}</strong><p>Primary-source expiry evidence is present.</p></div>`;
    }
    if (signal.pending) {
      return `<div class="ux3-pending"><span>${esc(signal.pending.state)}</span><strong>${esc(signal.pending.label)}</strong><p>${esc(signal.pending.note)}</p></div>`;
    }
    return '<div class="ux3-offer-fact"><span>END DATE</span><strong>NO VERIFIED END DATE</strong><p>종료일을 추측해서 카운트다운하지 않습니다.</p></div>';
  };

  function publicRouteUrl(id) {
    const url = new URL(location.href);
    url.searchParams.set('route', id);
    url.hash = 'explore';
    return url;
  }

  function syncUrl(id) {
    const url = new URL(location.href);
    if (id) {
      url.searchParams.set('route', id);
      url.hash = 'explore';
    } else {
      url.searchParams.delete('route');
      url.hash = 'explore';
    }
    history.replaceState(id ? { b60Route: id } : null, '', url);
  }

  function renderActions(signal) {
    const mapped = mappingFor(signal);
    return `<div class="ux3-actions">
      <button type="button" data-save-id="${esc(signal.id)}" aria-pressed="${isSaved(signal.id) ? 'true' : 'false'}">${isSaved(signal.id) ? 'SAVED' : 'SAVE'}</button>
      <button type="button" data-compare-id="${esc(signal.id)}" aria-pressed="${isCompared(signal.id) ? 'true' : 'false'}">${isCompared(signal.id) ? 'SELECTED' : 'COMPARE'}</button>
      <button type="button" data-provider-open="${esc(signal.provider)}">PROVIDER</button>
      ${signal.model ? `<button type="button" data-model-open="${esc(signal.model)}">MODEL</button>` : ''}
      ${mapped ? `<button type="button" class="ux3-mapped-action" data-handoff-id="${esc(signal.id)}">HANDOFF DETAILS</button>` : ''}
      <button type="button" data-copy-route="${esc(signal.id)}">COPY LINK</button>
    </div>`;
  }

  function openRoute(id, { sync = true } = {}) {
    const signal = byId.get(id);
    if (!signal) return false;
    currentId = id;
    const mapped = mappingFor(signal);
    detail.querySelector('[data-route-body]').innerHTML = `
      <header class="ux3-route-head">
        <div><span>ACCESS ROUTE</span><h2>${esc(signal.model || signal.title)}</h2><p>${esc(signal.provider)} · ${esc(signal.title)}</p></div>
        <b class="ux3-exec ${mapped ? 'is-mapped' : ''}">${executionLabel(signal)}</b>
      </header>
      <div class="ux3-route-layout">
        <section class="ux3-route-main">
          <div class="ux3-section-label">CURRENT ACCESS</div>
          <div class="ux3-offer-hero"><small>${esc(signal.dealType || 'ACCESS')}</small><strong>${esc(signal.freeLabel || 'Current access')}</strong><p>${esc(signal.summary || '')}</p></div>
          ${expiryBlock(signal)}
          <div class="ux3-section-label">ROUTE</div>
          <dl class="ux3-facts">
            <div><dt>PROVIDER</dt><dd>${esc(signal.provider)}</dd></div>
            <div><dt>MODEL</dt><dd>${esc(signal.model || 'Catalog / varies')}</dd></div>
            <div><dt>ACCESS</dt><dd>${esc((signal.access || []).join(' · ') || '—')}</dd></div>
            <div><dt>PRICE</dt><dd>${esc(signal.price || 'Unknown')}</dd></div>
            <div><dt>CONTEXT</dt><dd>${esc(signal.context || 'Unknown')}</dd></div>
            <div><dt>EXECUTION</dt><dd>${executionLabel(signal)}</dd></div>
          </dl>
        </section>
        <aside class="ux3-evidence">
          <div class="ux3-section-label">SOURCE CONFIDENCE</div>
          <strong>${esc(signal.verification || 'UNKNOWN')}</strong>
          <p>VERIFIED ${esc(signal.verifiedAt || 'Unknown')}</p>
          <ul>${(signal.facts || []).map(fact => `<li>${esc(fact)}</li>`).join('')}</ul>
          <div class="ux3-sources">${sourceLinks(signal)}</div>
          ${mapped ? `<div class="ux3-mapping-note"><b>EXECUTION ROUTE VERIFIED</b><p>정확한 실행 모델/route 계약이 확인됐지만 승인된 live target은 아직 연결되지 않았습니다.</p></div>` : '<div class="ux3-mapping-note is-info"><b>DISCOVERY ONLY</b><p>공식 접근 정보는 확인됐지만 현재 실행 계층의 정확한 route와 매핑하지 않습니다.</p></div>'}
        </aside>
      </div>
      ${renderActions(signal)}`;
    detail.classList.add('is-open');
    detail.setAttribute('aria-hidden', 'false');
    document.body.classList.add('ux3-route-open');
    syncDetailSave();
    if (sync) syncUrl(id);
    return true;
  }

  function syncDetailSave() {
    const button = detail.querySelector('.ux3-actions [data-save-id]');
    if (!button) return;
    const active = isSaved(button.dataset.saveId);
    button.textContent = active ? 'SAVED' : 'SAVE';
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  }

  function closeRoute({ sync = true } = {}) {
    detail.classList.remove('is-open');
    detail.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('ux3-route-open');
    currentId = null;
    if (sync) syncUrl(null);
  }

  function signalTarget(target) {
    const item = target.closest('[data-id]');
    if (!item || !grid.contains(item)) return null;
    const id = item.dataset.id;
    return byId.has(id) ? { item, id } : null;
  }

  document.addEventListener('click', async event => {
    if (event.target.closest('[data-close-route]') || event.target === detail) {
      event.preventDefault();
      closeRoute();
      return;
    }

    const detailSave = event.target.closest('.ux3-actions [data-save-id]');
    if (detailSave) {
      setTimeout(syncDetailSave, 0);
      return;
    }

    const copy = event.target.closest('[data-copy-route]');
    if (copy) {
      event.preventDefault();
      const id = copy.dataset.copyRoute;
      const url = publicRouteUrl(id).toString();
      try {
        await navigator.clipboard.writeText(url);
        copy.textContent = 'COPIED';
      } catch {
        copy.textContent = 'LINK READY';
      }
      copy.title = url;
      return;
    }

    if (detail.classList.contains('is-open') && event.target.closest('[data-provider-open],[data-model-open]')) {
      closeRoute({ sync: false });
      syncUrl(null);
      return;
    }

    if (event.target.closest('[data-save-id],[data-compare-id],[data-handoff-id],[data-provider-open],[data-model-open]')) return;

    const target = signalTarget(event.target);
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
    openRoute(target.id);
  }, true);

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && detail.classList.contains('is-open')) {
      event.preventDefault();
      closeRoute();
      return;
    }
    if (!['Enter', ' '].includes(event.key) || event.target.closest('button,a,input')) return;
    const target = signalTarget(event.target);
    if (!target) return;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === 'function') event.stopImmediatePropagation();
    openRoute(target.id);
  }, true);

  addEventListener('popstate', () => {
    const id = new URL(location.href).searchParams.get('route');
    if (id && byId.has(id)) openRoute(id, { sync: false });
    else closeRoute({ sync: false });
  });

  const initialRoute = new URL(location.href).searchParams.get('route');
  if (initialRoute && byId.has(initialRoute)) {
    const landOnRoute = () => {
      explore.scrollIntoView({ block: 'start' });
      requestAnimationFrame(() => {
        explore.scrollIntoView({ block: 'start' });
        openRoute(initialRoute, { sync: false });
      });
    };
    if (document.readyState === 'complete') landOnRoute();
    else addEventListener('load', landOnRoute, { once: true });
  }
})();
