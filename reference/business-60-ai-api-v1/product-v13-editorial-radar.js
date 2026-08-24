(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const media = window.B60_EDITORIAL_MEDIA || {};
  const top = document.getElementById('top');
  const cinematic = document.getElementById('cinematic');
  const explore = document.getElementById('explore');
  if (!signals.length || !top || !cinematic || !explore) return;

  document.documentElement.dataset.b60V13 = 'editorial';

  const esc = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const official = signal => signal.verification === 'VERIFIED_OFFICIAL_WEB';
  const verifiedExpiring = signal => Boolean(signal.expiresAt && signal.expiryVerification === 'VERIFIED_OFFICIAL_WEB');
  const alwaysFree = signal => ['PERMANENT_FREE', 'FREE_MODEL'].includes(signal.dealType) && !verifiedExpiring(signal);
  const live = signals.filter(signal => !alwaysFree(signal));
  const evergreen = signals.filter(alwaysFree);
  const expiring = signals.filter(verifiedExpiring);
  const sortedChecked = [...signals].sort((a, b) => String(b.verifiedAt || '').localeCompare(String(a.verifiedAt || '')));
  const featured = live[0] || signals[0];

  const visualFor = signal => media[signal.id] || {
    image: 'assets/woman-field.webp',
    alt: 'AI 접근 정보를 탐색하는 장면',
    source: 'B60 local asset',
    credit: 'Owner design asset',
    sourcePage: '#'
  };

  function routeUrl(id) {
    const url = new URL(location.href);
    url.searchParams.set('route', id);
    url.hash = 'explore';
    return url;
  }

  function openRoute(id) {
    const url = routeUrl(id);
    history.pushState({ b60Route: id }, '', url);
    dispatchEvent(new PopStateEvent('popstate', { state: { b60Route: id } }));
    explore.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const benefitLabel = signal => {
    if (verifiedExpiring(signal)) return 'LIMITED FREE';
    if (signal.dealType === 'RECURRING_CREDIT') return 'FREE CREDIT';
    if (signal.dealType === 'FREE_MODEL') return 'FREE MODEL';
    return 'ALWAYS FREE';
  };

  const sourceLink = signal => signal.sources?.[0]?.url || '#';
  const sourceName = signal => signal.sources?.[0]?.label || '공식 출처';

  function imageFigure(signal, className = '') {
    const visual = visualFor(signal);
    return `<figure class="radar-photo ${className}">
      <img src="${esc(visual.image)}" alt="${esc(visual.alt)}" loading="${signal.id === featured.id ? 'eager' : 'lazy'}" decoding="async">
      <figcaption><span>${esc(visual.source)}</span><span>${esc(visual.credit)}</span></figcaption>
    </figure>`;
  }

  function featureCard(signal) {
    return `<article class="radar-feature" data-radar-id="${esc(signal.id)}">
      ${imageFigure(signal, 'is-feature')}
      <div class="radar-feature-copy">
        <div class="radar-meta"><b>${benefitLabel(signal)}</b><span>${esc(signal.provider)}</span></div>
        <h2>${esc(signal.freeLabel)}</h2>
        <h3>${esc(signal.title)}</h3>
        <p>${esc(signal.summary)}</p>
        <div class="radar-actions">
          <button type="button" data-radar-open="${esc(signal.id)}">혜택 자세히 보기</button>
          <a href="${esc(sourceLink(signal))}" target="_blank" rel="noopener noreferrer">${esc(sourceName(signal))} ↗</a>
        </div>
        <div class="radar-trust"><span>${official(signal) ? '공식 확인' : '검토 필요'}</span><time>${esc(signal.verifiedAt || '날짜 미확인')}</time></div>
      </div>
    </article>`;
  }

  function boardItem(signal, index) {
    const visual = visualFor(signal);
    return `<button class="radar-board-item" type="button" data-radar-open="${esc(signal.id)}">
      <img src="${esc(visual.image)}" alt="" loading="lazy" decoding="async">
      <span class="radar-board-no">0${index + 1}</span>
      <span class="radar-board-copy"><small>${benefitLabel(signal)} · ${esc(signal.provider)}</small><strong>${esc(signal.freeLabel)}</strong><em>${esc(signal.title)}</em></span>
    </button>`;
  }

  function freeCard(signal, index) {
    return `<article class="radar-free-card ${index === 0 ? 'is-wide' : ''}">
      ${imageFigure(signal)}
      <div class="radar-free-copy">
        <div class="radar-meta"><b>ALWAYS FREE</b><span>${esc(signal.provider)}</span></div>
        <h3>${esc(signal.freeLabel)}</h3>
        <p>${esc(signal.summary)}</p>
        <button type="button" data-radar-open="${esc(signal.id)}">조건 · 출처 보기</button>
      </div>
    </article>`;
  }

  function expiringBlock() {
    if (!expiring.length) {
      return `<div class="radar-expiry-empty"><span>ENDING SOON</span><strong>지금은 공식 종료일이 확인된 혜택이 없습니다.</strong><p>날짜를 추측해서 긴급함을 만들지 않습니다. 공식 출처에서 종료일이 확인된 혜택만 여기에 올라옵니다.</p></div>`;
    }
    return expiring.map(signal => `<article class="radar-expiry-card">
      <span>ENDING SOON</span><strong>${esc(signal.freeLabel)}</strong><time>${esc(signal.expiresAt)}</time><button type="button" data-radar-open="${esc(signal.id)}">보기</button>
    </article>`).join('');
  }

  const pending = signals.filter(signal => signal.pending);
  const radar = document.createElement('section');
  radar.className = 'editorial-radar-v13';
  radar.id = 'radar';
  radar.setAttribute('aria-label', '지금 무료로 쓸 수 있는 AI 기회');
  radar.innerHTML = `
    <div class="radar-masthead">
      <a class="radar-wordmark" href="#radar">AI FREE RADAR</a>
      <p>오늘 쓸 수 있는 무료 AI와 크레딧을 빠르게 고르고, 공식 출처까지 확인합니다.</p>
      <span>${signals.length} VERIFIED ROUTES · MANUALLY CURATED</span>
    </div>

    <div class="radar-rule"><span>FREE NOW</span><time>${new Date().toISOString().slice(0, 10)}</time></div>

    <div class="radar-lead" id="radar-live">
      ${featureCard(featured)}
      <aside class="radar-board" aria-label="오늘의 무료 보드">
        <header><span>TODAY'S BOARD</span><strong>지금 바로 볼 것</strong></header>
        ${(evergreen.length ? evergreen : signals.filter(signal => signal.id !== featured.id)).slice(0, 3).map(boardItem).join('')}
        <button class="radar-directory-link" type="button" data-radar-scroll="explore">전체 조건 비교 →</button>
      </aside>
    </div>

    <section class="radar-expiring" aria-label="종료 임박 혜택">${expiringBlock()}</section>

    <section class="radar-always" id="always-free">
      <header class="radar-section-head"><div><span>ALWAYS FREE</span><h2>오늘만이 아니라,<br>계속 무료인 것들.</h2></div><p>무료 티어·무료 모델·반복 크레딧 중 상시 이용 조건이 확인된 경로를 모았습니다.</p></header>
      <div class="radar-free-grid">${evergreen.map(freeCard).join('')}</div>
    </section>

    <section class="radar-checked" id="just-checked">
      <header class="radar-section-head"><div><span>JUST CHECKED</span><h2>광고 문구보다<br>확인 날짜를 봅니다.</h2></div><p>사용 조건이 바뀌기 쉬운 정보라서, 무엇을 언제 공식 페이지에서 확인했는지 같이 보여줍니다.</p></header>
      <div class="radar-check-list">
        ${sortedChecked.map(signal => `<button type="button" data-radar-open="${esc(signal.id)}"><time>${esc(signal.verifiedAt || '—')}</time><span>${esc(signal.provider)}</span><strong>${esc(signal.freeLabel)}</strong><em>${official(signal) ? 'OFFICIAL' : 'REVIEW'}</em></button>`).join('')}
      </div>
      ${pending.length ? `<div class="radar-pending"><span>CHECKING NOW</span>${pending.map(signal => `<p><b>${esc(signal.provider)}</b> · ${esc(signal.pending.label)} <em>${esc(signal.pending.state)}</em></p>`).join('')}<small>확인되지 않은 종료일이나 프로모션 문구는 LIVE/ENDING SOON으로 승격하지 않습니다.</small></div>` : ''}
    </section>
  `;

  cinematic.before(radar);

  document.addEventListener('click', event => {
    const open = event.target.closest('[data-radar-open]');
    if (open) {
      event.preventDefault();
      openRoute(open.dataset.radarOpen);
      return;
    }
    const jump = event.target.closest('[data-radar-scroll]');
    if (jump?.dataset.radarScroll === 'explore') {
      event.preventDefault();
      explore.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });

  const nav = document.querySelector('.shell nav');
  if (nav) {
    nav.innerHTML = '<a href="#radar-live">지금 무료</a><a href="#always-free">상시 무료</a><a href="#just-checked">확인 기록</a><a href="#explore">전체 보기</a>';
  }

  window.B60_EDITORIAL_RADAR = Object.freeze({
    openRoute,
    featuredId: featured.id,
    alwaysFreeIds: evergreen.map(signal => signal.id),
    verifiedExpiringIds: expiring.map(signal => signal.id)
  });
})();
