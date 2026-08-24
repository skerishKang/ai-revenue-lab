(() => {
  const signals = window.B60_ACCESS_SIGNALS || [];
  const opportunities = window.B60_EDITORIAL_OPPORTUNITIES || [];
  const media = window.B60_EDITORIAL_MEDIA || {};
  const top = document.getElementById('top');
  const cinematic = document.getElementById('cinematic');
  const explore = document.getElementById('explore');
  if ((!signals.length && !opportunities.length) || !top || !cinematic || !explore) return;

  document.documentElement.dataset.b60V13 = 'editorial';

  const esc = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const authoritativeVerification = value => ['VERIFIED_OFFICIAL_WEB', 'VERIFIED_OFFICIAL_SOCIAL'].includes(value);
  const isEditorial = item => Boolean(item.editorialRole || item.opportunityType);
  const today = new Date();
  const todayKey = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'
  }).format(today);
  const dayMs = 24 * 60 * 60 * 1000;
  const todayEpoch = Date.parse(`${todayKey}T00:00:00Z`);

  function daysUntil(dateString) {
    if (!dateString) return null;
    const endEpoch = Date.parse(`${dateString}T00:00:00Z`);
    if (Number.isNaN(endEpoch)) return null;
    return Math.ceil((endEpoch - todayEpoch) / dayMs);
  }

  const isExpired = item => {
    const days = daysUntil(item.expiresAt);
    return days !== null && days < 0;
  };

  const verifiedExpiring = item => {
    const days = daysUntil(item.expiresAt);
    return days !== null && days >= 0 && days <= 7 && authoritativeVerification(item.expiryVerification);
  };

  const activeOpportunities = opportunities.filter(item => !isExpired(item));
  const hottest = activeOpportunities.find(item => item.editorialRole === 'HOTTEST') || activeOpportunities[0] || signals[0];
  const justDropped = activeOpportunities.filter(item => item.editorialRole === 'JUST_DROPPED' && item.id !== hottest?.id);
  const signupCredits = activeOpportunities.filter(item => item.opportunityType === 'SIGNUP_CREDIT');
  const durable = signals.filter(signal => ['PERMANENT_FREE', 'FREE_MODEL', 'RECURRING_CREDIT'].includes(signal.dealType));
  const expiring = [...activeOpportunities, ...signals].filter(verifiedExpiring);
  const checkedItems = [...activeOpportunities, ...signals].sort((a, b) => String(b.verifiedAt || '').localeCompare(String(a.verifiedAt || '')));
  const pending = [...activeOpportunities, ...signals].filter(item => item.pending);

  const visualFor = item => media[item.id] || {
    image: 'assets/woman-field.webp',
    alt: 'AI 접근 정보를 탐색하는 장면',
    source: 'B60 로컬 자산',
    credit: '기존 디자인 자산',
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

  function openEditorial(url) {
    if (!url) return;
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  function mechanicLabel(item) {
    if (item.opportunityType === 'TEMP_FREE_ACCESS') return '한시 무료 개방';
    if (item.opportunityType === 'SIGNUP_CREDIT') return '가입 크레딧';
    if (item.opportunityType === 'RECURRING_FREE' || item.dealType === 'RECURRING_CREDIT') return '반복 무료';
    if (item.opportunityType === 'ALWAYS_FREE' || ['PERMANENT_FREE', 'FREE_MODEL'].includes(item.dealType)) return '상시 무료';
    return verifiedExpiring(item) ? '기간 한정 무료' : '무료 기회';
  }

  function verificationLabel(item) {
    if (item.verification === 'VERIFIED_OFFICIAL_WEB') return '공식 웹 확인';
    if (item.verification === 'VERIFIED_OFFICIAL_SOCIAL') return '공식 발표 확인';
    return '검토 필요';
  }

  const benefit = item => item.benefitLabel || item.freeLabel || '무료';
  const headline = item => item.headline || item.title || item.provider;
  const sourceLink = item => item.sources?.[0]?.url || '#';
  const sourceName = item => item.sources?.[0]?.label || '공식 출처';

  function itemAction(item, label) {
    if (isEditorial(item)) {
      return `<button type="button" data-radar-url="${esc(item.ctaUrl || sourceLink(item))}">${esc(label)}</button>`;
    }
    return `<button type="button" data-radar-open="${esc(item.id)}">${esc(label)}</button>`;
  }

  function imageFigure(item, className = '') {
    const visual = visualFor(item);
    return `<figure class="radar-photo ${className}">
      <img src="${esc(visual.image)}" alt="${esc(visual.alt)}" loading="eager" decoding="async">
      <figcaption><span>${esc(visual.source)}</span><span>${esc(visual.credit)}</span></figcaption>
    </figure>`;
  }

  function featureCard(item) {
    return `<article class="radar-feature" data-radar-id="${esc(item.id)}">
      ${imageFigure(item, 'is-feature')}
      <div class="radar-feature-copy">
        <div class="radar-feature-kicker">지금 가장 핫함</div>
        <div class="radar-meta"><b>${esc(mechanicLabel(item))}</b><span>${esc(item.provider)}</span></div>
        <h2>${esc(benefit(item))}</h2>
        <h3>${esc(headline(item))}</h3>
        <p>${esc(item.summary)}</p>
        <div class="radar-condition-line">${(item.conditions || []).slice(0, 2).map(condition => `<span>${esc(condition)}</span>`).join('')}</div>
        <div class="radar-actions">
          ${itemAction(item, '지금 사용 경로 보기')}
          <a href="${esc(sourceLink(item))}" target="_blank" rel="noopener noreferrer">${esc(sourceName(item))} ↗</a>
        </div>
        <div class="radar-trust"><span>${verificationLabel(item)}</span><time>${esc(item.verifiedAt || '날짜 미확인')}</time></div>
      </div>
    </article>`;
  }

  function boardItem(item, index) {
    const visual = visualFor(item);
    const action = isEditorial(item) ? `data-radar-url="${esc(item.ctaUrl || sourceLink(item))}"` : `data-radar-open="${esc(item.id)}"`;
    return `<button class="radar-board-item" type="button" ${action}>
      <img src="${esc(visual.image)}" alt="" loading="eager" decoding="async">
      <span class="radar-board-no">0${index + 1}</span>
      <span class="radar-board-copy"><small>${esc(mechanicLabel(item))} · ${esc(item.provider)}</small><strong>${esc(benefit(item))}</strong><em>${esc(item.title || headline(item))}</em></span>
    </button>`;
  }

  function droppedCard(item) {
    const dates = item.startAt && item.expiresAt ? `${item.startAt.slice(5).replace('-', '.')} → ${item.expiresAt.slice(5).replace('-', '.')}` : '기간 확인 중';
    return `<article class="radar-dropped-card">
      ${imageFigure(item, 'is-dropped')}
      <div class="radar-dropped-copy">
        <div class="radar-dropped-top"><span>방금 뜬 무료</span><time>${esc(dates)}</time></div>
        <div class="radar-meta"><b>${esc(mechanicLabel(item))}</b><span>${esc(item.provider)}</span></div>
        <h2>${esc(benefit(item))}</h2>
        <h3>${esc(headline(item))}</h3>
        <p>${esc(item.summary)}</p>
        <div class="radar-tags">${(item.categories || []).map(tag => `<span>${esc(tag)}</span>`).join('')}</div>
        <div class="radar-actions">
          ${itemAction(item, '무료 경로 열기')}
          <a href="${esc(sourceLink(item))}" target="_blank" rel="noopener noreferrer">공식 발표 ↗</a>
        </div>
        <div class="radar-trust"><span>${verificationLabel(item)}</span><time>${esc(item.verifiedAt || '날짜 미확인')}</time></div>
      </div>
    </article>`;
  }

  function durableCard(item, index) {
    return `<article class="radar-free-card ${index === 0 ? 'is-wide' : ''}">
      ${imageFigure(item)}
      <div class="radar-free-copy">
        <div class="radar-meta"><b>${esc(mechanicLabel(item))}</b><span>${esc(item.provider)}</span></div>
        <h3>${esc(benefit(item))}</h3>
        <p>${esc(item.summary)}</p>
        ${itemAction(item, '조건 · 출처 보기')}
      </div>
    </article>`;
  }

  function signupCard(item) {
    return `<article class="radar-signup-card">
      <span>신규 가입 혜택</span>
      <strong>${esc(benefit(item))}</strong>
      <h3>${esc(item.provider)}</h3>
      <p>${esc(item.summary)}</p>
      ${itemAction(item, '가입 조건 보기')}
    </article>`;
  }

  function expiringBlock() {
    if (!expiring.length) {
      return `<div class="radar-expiry-empty"><span>종료 임박</span><strong>7일 안에 끝나는 것으로 공식 확인된 혜택은 현재 없습니다.</strong><p>끝나는 날짜가 있더라도 아직 7일 이상 남았다면 이 칸에 올리지 않습니다. 날짜가 가까워지면 자동으로 이 영역에 들어옵니다.</p></div>`;
    }
    return expiring.map(item => `<article class="radar-expiry-card">
      <span>종료 임박 · ${daysUntil(item.expiresAt)}일</span><strong>${esc(benefit(item))}</strong><time>${esc(item.expiresAt)}</time>${itemAction(item, '보기')}
    </article>`).join('');
  }

  const radar = document.createElement('section');
  radar.className = 'editorial-radar-v13';
  radar.id = 'radar';
  radar.setAttribute('aria-label', '지금 무료로 쓸 수 있는 AI 기회');
  radar.innerHTML = `
    <div class="radar-masthead">
      <a class="radar-wordmark" href="#radar">AI 무료 레이더</a>
      <p>오늘 쓸 수 있는 무료 AI를 먼저 보고, 가입 혜택과 상시 무료는 따로 비교합니다.</p>
      <span>${activeOpportunities.length}개 라이브 기회 · ${durable.length}개 지속 경로 · 수동 큐레이션</span>
    </div>

    <div class="radar-rule"><span>지금 무료</span><time>${todayKey}</time></div>

    <div class="radar-lead" id="radar-live">
      ${featureCard(hottest)}
      <aside class="radar-board" aria-label="오늘의 무료 보드">
        <header><span>오늘의 보드</span><strong>계속 쓸 수 있는 것</strong></header>
        ${durable.slice(0, 3).map(boardItem).join('')}
        <button class="radar-directory-link" type="button" data-radar-scroll="explore">전체 조건 비교 →</button>
      </aside>
    </div>

    ${justDropped.length ? `<section class="radar-dropped" id="just-dropped">${justDropped.map(droppedCard).join('')}</section>` : ''}

    <section class="radar-expiring" aria-label="종료 임박 혜택">${expiringBlock()}</section>

    ${signupCredits.length ? `<section class="radar-signups" id="signup-benefits"><header class="radar-section-head"><div><span>가입 혜택</span><h2>가입하면 받는 것,<br>한시 무료와는 따로.</h2></div><p>신규 계정 크레딧은 유용하지만 ‘지금 열린 무료 모델’과 같은 종류로 취급하지 않습니다.</p></header><div class="radar-signup-grid">${signupCredits.map(signupCard).join('')}</div></section>` : ''}

    <section class="radar-always" id="always-free">
      <header class="radar-section-head"><div><span>계속 무료</span><h2>오늘만이 아니라,<br>다시 쓸 수 있는 것들.</h2></div><p>상시 무료 티어·무료 모델·반복 크레딧처럼 지속적으로 이용할 수 있는 경로를 모았습니다.</p></header>
      <div class="radar-free-grid">${durable.map(durableCard).join('')}</div>
    </section>

    <section class="radar-checked" id="just-checked">
      <header class="radar-section-head"><div><span>최근 확인</span><h2>광고 문구보다<br>확인 날짜를 봅니다.</h2></div><p>웹 문서와 공식 브랜드 발표를 구분해 기록하고, 종료일·제한을 추측하지 않습니다.</p></header>
      <div class="radar-check-list">
        ${checkedItems.map(item => {
          const action = isEditorial(item) ? `data-radar-url="${esc(item.ctaUrl || sourceLink(item))}"` : `data-radar-open="${esc(item.id)}"`;
          return `<button type="button" ${action}><time>${esc(item.verifiedAt || '—')}</time><span>${esc(item.provider)}</span><strong>${esc(benefit(item))}</strong><em>${esc(verificationLabel(item))}</em></button>`;
        }).join('')}
      </div>
      ${pending.length ? `<div class="radar-pending"><span>확인 중</span>${pending.map(item => `<p><b>${esc(item.provider)}</b> · ${esc(item.pending.label)} <em>${esc(item.pending.state)}</em></p>`).join('')}<small>확인되지 않은 종료일이나 프로모션 문구는 종료 임박으로 승격하지 않습니다.</small></div>` : ''}
    </section>
  `;

  cinematic.before(radar);

  document.addEventListener('click', event => {
    const external = event.target.closest('[data-radar-url]');
    if (external) {
      event.preventDefault();
      openEditorial(external.dataset.radarUrl);
      return;
    }
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
    nav.innerHTML = `<a href="#radar-live">가장 핫함</a>${justDropped.length ? '<a href="#just-dropped">방금 뜸</a>' : ''}<a href="#always-free">계속 무료</a><a href="#just-checked">확인 기록</a>`;
  }

  window.B60_EDITORIAL_RADAR = Object.freeze({
    openRoute,
    hottestId: hottest?.id || null,
    justDroppedIds: justDropped.map(item => item.id),
    signupCreditIds: signupCredits.map(item => item.id),
    durableIds: durable.map(item => item.id),
    verifiedExpiringIds: expiring.map(item => item.id)
  });
})();
