(() => {
  'use strict';

  const core = window.B60_OPPORTUNITY_DETAIL_CORE;
  const opportunities = window.B60_EDITORIAL_OPPORTUNITIES || [];
  const media = window.B60_EDITORIAL_MEDIA || {};
  if (!core || !opportunities.length) return;

  const esc = (value = '') => String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  }[char]));

  const mediaFor = item => media[item.id] || {
    image: 'assets/woman-field.webp',
    alt: 'AI 무료 기회를 살펴보는 장면',
    source: 'B60 로컬 자산',
    credit: '기존 디자인 자산'
  };

  const shell = document.createElement('section');
  shell.className = 'b60-opportunity-detail';
  shell.dataset.b60OpportunityDetail = 'v14';
  shell.hidden = true;
  shell.innerHTML = `
    <div class="b60-detail-backdrop" data-detail-close aria-hidden="true"></div>
    <aside class="b60-detail-panel" role="dialog" aria-modal="true" aria-labelledby="b60-detail-title" tabindex="-1">
      <button class="b60-detail-close" type="button" data-detail-close aria-label="상세 닫기">닫기 ×</button>
      <div class="b60-detail-content"></div>
    </aside>
  `;
  document.body.append(shell);

  const panel = shell.querySelector('.b60-detail-panel');
  const content = shell.querySelector('.b60-detail-content');
  let activeId = null;
  let lastFocus = null;

  function render(item) {
    const vm = core.viewModel(item, new Date());
    const visual = mediaFor(item);
    const primarySource = vm.sources[0];
    content.innerHTML = `
      <figure class="b60-detail-visual">
        <img src="${esc(visual.image)}" alt="${esc(visual.alt || '')}" decoding="async">
        <figcaption><span>${esc(visual.source || '')}</span><span>${esc(visual.credit || '')}</span></figcaption>
      </figure>

      <div class="b60-detail-intro">
        <div class="b60-detail-kicker"><span>기회 상세</span><time>${esc(vm.verifiedAt)}</time></div>
        <div class="b60-detail-meta"><b>${esc(vm.mechanic)}</b><span>${esc(vm.provider)}</span></div>
        <strong class="b60-detail-benefit">${esc(vm.benefit)}</strong>
        <h2 id="b60-detail-title">${esc(vm.headline)}</h2>
        <p>${esc(vm.summary)}</p>
      </div>

      <div class="b60-detail-truth" aria-label="검증 상태">
        <div><span>누가 받을 수 있나</span><strong>${esc(vm.eligibility)}</strong></div>
        <div><span>언제까지인가</span><strong>${esc(vm.expiry)}</strong></div>
        <div><span>검증 상태</span><strong>${esc(vm.verification)}</strong></div>
      </div>

      <section class="b60-detail-section">
        <header><span>01</span><h3>실제로 받는 것</h3></header>
        <dl class="b60-detail-facts">
          <div><dt>제품 / 모델</dt><dd>${esc(vm.productOrModel)}</dd></div>
          <div><dt>비용 / 크레딧</dt><dd>${esc(vm.priceOrCredit)}</dd></div>
          <div><dt>시작</dt><dd>${esc(vm.start)}</dd></div>
          <div><dt>제한</dt><dd>${esc(vm.limit)}</dd></div>
        </dl>
        ${vm.access.length ? `<div class="b60-detail-tags" aria-label="접근 경로">${vm.access.map(value => `<span>${esc(value)}</span>`).join('')}</div>` : ''}
      </section>

      <section class="b60-detail-section">
        <header><span>02</span><h3>조건</h3></header>
        ${vm.conditions.length
          ? `<ul class="b60-detail-conditions">${vm.conditions.map(value => `<li>${esc(value)}</li>`).join('')}</ul>`
          : '<p class="b60-detail-empty">별도 조건이 기록되지 않았습니다. 실제 사용 전 공식 페이지를 다시 확인하세요.</p>'}
      </section>

      <section class="b60-detail-section b60-detail-sources">
        <header><span>03</span><h3>공식 근거</h3></header>
        <div class="b60-detail-source-list">
          ${vm.sources.map((source, index) => `<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">
            <span class="b60-detail-source-no">0${index + 1}</span>
            <span class="b60-detail-source-copy"><b>${esc(source.authorityLabel)}</b><strong>${esc(source.label)}</strong></span>
            <em>열기 ↗</em>
          </a>`).join('')}
        </div>
      </section>

      <footer class="b60-detail-actions">
        ${primarySource ? `<a class="is-source" href="${esc(primarySource.url)}" target="_blank" rel="noopener noreferrer">공식 출처 먼저 보기 ↗</a>` : ''}
        <a class="is-primary" href="${esc(vm.ctaUrl)}" target="_blank" rel="noopener noreferrer">실제 사용하기 ↗</a>
        <small>외부 사이트로 이동합니다. 조건과 가격은 이동 후에도 다시 확인하세요.</small>
      </footer>
    `;
  }

  function setUrl(id, mode = 'push') {
    const next = id ? core.buildDealLink(location.href, id) : core.clearDealLink(location.href);
    const state = id ? { ...(history.state || {}), b60Deal: id } : { ...(history.state || {}) };
    if (!id) delete state.b60Deal;
    history[mode === 'replace' ? 'replaceState' : 'pushState'](state, '', next);
  }

  function open(item, options = {}) {
    if (!item) return;
    if (!shell.hidden && activeId === item.id) return;
    lastFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    activeId = item.id;
    render(item);
    shell.hidden = false;
    document.body.classList.add('b60-detail-open');
    if (options.history !== false) setUrl(item.id, options.replace ? 'replace' : 'push');
    requestAnimationFrame(() => panel.focus({ preventScroll: true }));
  }

  function close(options = {}) {
    if (shell.hidden) return;
    shell.hidden = true;
    document.body.classList.remove('b60-detail-open');
    activeId = null;
    if (options.history !== false) setUrl(null, 'replace');
    if (options.restoreFocus !== false && lastFocus && document.contains(lastFocus)) lastFocus.focus({ preventScroll: true });
  }

  function syncFromLocation() {
    const id = new URL(location.href).searchParams.get('deal');
    if (!id) {
      close({ history: false, restoreFocus: false });
      return;
    }
    const item = core.getOpportunityById(opportunities, id);
    if (item) open(item, { history: false });
    else close({ history: false, restoreFocus: false });
  }

  document.addEventListener('click', event => {
    const closeTarget = event.target.closest('[data-detail-close]');
    if (closeTarget) {
      event.preventDefault();
      close();
    }
  });

  document.addEventListener('click', event => {
    if (event.target.closest('.b60-opportunity-detail')) return;
    const primary = event.target.closest('[data-radar-url]');
    if (!primary) return;
    const item = core.resolveOpportunityByUrl(opportunities, primary.dataset.radarUrl);
    if (!item) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    open(item);
  }, true);

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !shell.hidden) {
      event.preventDefault();
      close();
    }
  });

  window.addEventListener('popstate', syncFromLocation);
  syncFromLocation();

  window.B60_OPPORTUNITY_DETAIL = Object.freeze({
    openById(id) {
      const item = core.getOpportunityById(opportunities, id);
      if (item) open(item);
    },
    close,
    get activeId() { return activeId; }
  });
})();
