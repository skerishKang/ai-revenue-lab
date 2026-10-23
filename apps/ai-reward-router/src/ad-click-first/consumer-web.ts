import type {
  AdClickFirstConsumerHomeViewModel,
  AdClickFirstTodayRouteViewModel,
  AdClickFirstBrowseViewModel,
  AdClickFirstOpportunityDetailViewModel,
} from './consumer-home.js';
import type { AdClickConsumerCard } from './consumer-card.js';

const ACTION_LABELS: Readonly<Record<AdClickConsumerCard['actionKind'], string>> = Object.freeze({
  AD_VIEW: '광고 보기',
  CLICK: '클릭 적립',
  VISIT: '방문',
  ATTENDANCE: '출석',
  VERY_SHORT_FREE_ACTION: '간단 참여',
});

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function safeOutboundHref(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? escapeHtml(url.toString()) : null;
  } catch {
    return null;
  }
}

function formatActiveTime(seconds: number): string {
  if (seconds < 60) return `약 ${Math.ceil(seconds)}초`;
  return `약 ${Math.ceil(seconds / 60)}분`;
}

function formatFreshness(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '최근 확인';
  const yyyy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(date.getUTCDate()).padStart(2, '0');
  return `${yyyy}.${mm}.${dd} 확인`;
}

function renderCard(card: AdClickConsumerCard): string | null {
  const href = safeOutboundHref(card.canonicalDestinationUrl);
  if (!href) return null;

  const certaintyLabel = card.certainty === 'GUARANTEED' ? '확정 보상' : '조건 충족 시';
  return `<article class="reward-card" data-card-id="${escapeHtml(card.id)}">
    <div class="reward-card__topline">
      <span class="action-chip">${ACTION_LABELS[card.actionKind]}</span>
      <span class="freshness">${formatFreshness(card.lastVerifiedAt)}</span>
    </div>
    <h3>${escapeHtml(card.title)}</h3>
    <div class="reward-card__reward">
      <strong>${escapeHtml(card.rewardLabel)}</strong>
      <span>${certaintyLabel}</span>
    </div>
    <p class="condition">${escapeHtml(card.conditionSummary)}</p>
    <div class="reward-card__meta" aria-label="참여 정보">
      <span>⏱ ${formatActiveTime(card.estimatedActiveSeconds)}</span>
      <span>외부 페이지에서 참여</span>
    </div>
    <a class="reward-cta" href="${href}" target="_blank" rel="noopener noreferrer nofollow">적립하러 가기<span aria-hidden="true"> ↗</span></a>
    <a class="detail-link" href="/detail?id=${escapeHtml(card.id)}">자세히 보기</a>
  </article>`;
}

function renderEmptyState(): string {
  return `<div class="empty-state" role="status" data-empty-state="NO_LIVE_REWARD_SUPPLY">
    <div class="empty-state__mark" aria-hidden="true">P</div>
    <h3>지금 참여 가능한 적립을 확인 중이에요</h3>
    <p>실제로 참여할 수 있고 보상 조건이 확인된 항목만 보여드릴게요.</p>
    <ul class="empty-steps">
      <li>광고·클릭·방문처럼 짧게 끝나는 적립부터 준비됩니다.</li>
      <li>검증된 공급자가 연결되면 여기에 바로 표시됩니다.</li>
      <li>조건과 보상은 참여 전 외부 페이지에서 다시 확인하세요.</li>
    </ul>
  </div>`;
}

function renderHowItWorks(): string {
  return `<section class="how-it-works" aria-labelledby="how-title">
    <div class="section-head">
      <h2 id="how-title">참여 방식</h2>
      <span>짧은 행동부터</span>
    </div>
    <ol class="how-steps">
      <li>
        <span class="how-step__num" aria-hidden="true">1</span>
        <div class="how-step__body">
          <h3>짧은 적립 선택</h3>
          <p>광고 보기, 클릭, 방문처럼 짧게 끝나는 항목만 먼저 준비돼요.</p>
        </div>
      </li>
      <li>
        <span class="how-step__num" aria-hidden="true">2</span>
        <div class="how-step__body">
          <h3>조건과 보상 확인</h3>
          <p>보상 단가, 소요 시간, 참여 조건을 참여 전에 확인해요.</p>
        </div>
      </li>
      <li>
        <span class="how-step__num" aria-hidden="true">3</span>
        <div class="how-step__body">
          <h3>외부 페이지에서 적립</h3>
          <p>공급자 공식 페이지에서 완료하면 보상이 적립돼요.</p>
        </div>
      </li>
    </ol>
  </section>`;
}

function renderShell(
  viewModel: { mode: string; issueNumber: number | null },
  navItems: string,
  hero: string,
  content: string,
  options: { howItWorks?: boolean } = {},
): string {
  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>바로 적립 | B64</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07090d;
      --bg-soft: #0d1117;
      --surface: rgba(255,255,255,.06);
      --surface-strong: rgba(255,255,255,.10);
      --line: rgba(255,255,255,.14);
      --text: #f4f6fb;
      --muted: rgba(255,255,255,.68);
      --accent: #88c9ff;
      --accent-strong: #5fb3ff;
      --gold: #efc984;
      --radius: 14px;
      --radius-lg: 20px;
      font-family: "SUIT Variable", "SUIT", "Pretendard", "Apple SD Gothic Neo", system-ui, sans-serif;
      font-synthesis: none;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; background: var(--bg); color: var(--text); }
    a { color: inherit; text-decoration: none; }
    .shell { width: min(100%, 1080px); margin: 0 auto; padding: 0 20px 64px; }
    .topbar { position: sticky; top: 0; z-index: 10; margin: 0 -20px; padding: 16px 20px 12px; background: rgba(7,9,13,.72); backdrop-filter: blur(16px); border-bottom: 1px solid var(--line); }
    .brand-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
    .brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700; letter-spacing: -.03em; font-size: 18px; }
    .brand-mark { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: linear-gradient(135deg, var(--accent), var(--accent-strong)); color: #07090d; font-size: 12px; font-weight: 800; }
    .trust-note { font-size: 12px; color: var(--muted); }
    .primary-nav { display: flex; gap: 6px; padding-top: 12px; overflow-x: auto; scrollbar-width: none; flex-wrap: wrap; }
    .primary-nav::-webkit-scrollbar { display: none; }
    .nav-item { flex: 0 0 auto; padding: 8px 14px; border-radius: 999px; text-decoration: none; font-size: 13px; font-weight: 600; color: var(--muted); border: 1px solid transparent; transition: color .16s ease, background .16s ease, border-color .16s ease; }
    .nav-item:hover { color: var(--text); }
    .nav-item--active { background: var(--surface-strong); color: var(--text); border-color: var(--line); }
    .category-tabs { display: flex; gap: 6px; padding: 4px 0 0; overflow-x: auto; scrollbar-width: none; flex-wrap: wrap; }
    .category-tabs::-webkit-scrollbar { display: none; }
    .hero { padding: 56px 0 24px; }
    .eyebrow { margin: 0 0 12px; color: var(--accent); font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    .hero h1 { margin: 0; max-width: 640px; font-size: clamp(30px, 6vw, 56px); line-height: 1.0; letter-spacing: -.055em; font-weight: 700; }
    .hero p { margin: 18px 0 0; max-width: 560px; color: var(--muted); font-size: 16px; line-height: 1.6; }
    .section-head { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 24px 0 14px; flex-wrap: wrap; }
    .section-head h2 { margin: 0; font-size: 20px; letter-spacing: -.02em; font-weight: 700; }
    .section-head span { color: var(--muted); font-size: 12px; }
    .reward-grid { display: grid; gap: 14px; grid-template-columns: 1fr; }
    .reward-card { padding: 20px; border: 1px solid var(--line); border-radius: var(--radius-lg); background: var(--surface); backdrop-filter: blur(8px); transition: border-color .16s ease, transform .16s ease; }
    .reward-card:hover { border-color: rgba(136,201,255,.35); transform: translateY(-2px); }
    .reward-card__topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .action-chip { display: inline-flex; align-items: center; min-height: 26px; padding: 0 10px; border-radius: 999px; background: rgba(136,201,255,.14); color: var(--accent); font-size: 12px; font-weight: 700; border: 1px solid rgba(136,201,255,.25); }
    .freshness { color: var(--muted); font-size: 11px; }
    .reward-card h3 { margin: 14px 0 12px; font-size: 18px; line-height: 1.3; letter-spacing: -.02em; font-weight: 600; }
    .reward-card__reward { display: flex; align-items: baseline; gap: 9px; }
    .reward-card__reward strong { color: var(--gold); font-size: 24px; letter-spacing: -.03em; font-weight: 700; }
    .reward-card__reward span { color: var(--muted); font-size: 12px; font-weight: 600; }
    .condition { margin: 12px 0 0; color: var(--muted); font-size: 14px; line-height: 1.55; }
    .reward-card__meta { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 14px 0 16px; color: var(--muted); font-size: 12px; }
    .reward-cta { display: flex; align-items: center; justify-content: center; min-height: 46px; padding: 0 22px; border-radius: 999px; background: var(--accent); color: #07090d; text-decoration: none; font-size: 14px; font-weight: 700; transition: background .16s ease, transform .16s ease; }
    .reward-cta:hover { background: var(--accent-strong); transform: translateY(-1px); }
    .detail-link { display: inline-block; margin-top: 10px; font-size: 13px; color: var(--accent); font-weight: 600; }
    .detail-link:hover { text-decoration: underline; }
    .reward-cta:focus-visible, .nav-item:focus-visible, .brand:focus-visible, .detail-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
    .empty-state { display: grid; justify-items: center; padding: 48px 24px; border: 1px dashed var(--line); border-radius: var(--radius-lg); background: var(--surface); text-align: center; }
    .empty-state__mark { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 50%; background: rgba(136,201,255,.14); color: var(--accent); font-weight: 800; font-size: 18px; }
    .empty-state h3 { margin: 16px 0 8px; font-size: 18px; letter-spacing: -.02em; font-weight: 700; }
    .empty-state p { margin: 0; max-width: 360px; color: var(--muted); font-size: 14px; line-height: 1.6; }
    .empty-steps { list-style: none; padding: 0; margin: 18px 0 0; max-width: 420px; display: grid; gap: 8px; }
    .empty-steps li { position: relative; padding-left: 18px; font-size: 13px; color: var(--muted); line-height: 1.5; }
    .empty-steps li::before { content: ""; position: absolute; left: 0; top: 7px; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }
    .how-it-works { padding: 8px 0 0; }
    .how-steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; grid-template-columns: 1fr; }
    .how-step { display: flex; align-items: flex-start; gap: 14px; padding: 18px; border: 1px solid var(--line); border-radius: var(--radius-lg); background: var(--surface); }
    .how-step__num { flex: 0 0 auto; display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; background: rgba(136,201,255,.14); color: var(--accent); font-weight: 700; font-size: 14px; }
    .how-step__body h3 { margin: 0 0 4px; font-size: 15px; font-weight: 700; letter-spacing: -.01em; }
    .how-step__body p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
    .later-tier-notice { margin: 14px 0 0; color: var(--muted); font-size: 12px; text-align: center; }
    .footer-note { margin: 32px 0 0; color: var(--muted); font-size: 11px; line-height: 1.6; text-align: center; }
    .filter-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; padding: 12px 0 8px; }
    .filter-bar label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); font-weight: 600; }
    .filter-bar input, .filter-bar select { padding: 9px 12px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--surface); color: var(--text); font-size: 14px; min-width: 140px; }
    .filter-bar button { padding: 9px 20px; border-radius: 999px; border: 1px solid var(--accent); background: var(--accent); color: #07090d; font-size: 14px; font-weight: 700; cursor: pointer; }
    .filter-bar button:hover { background: var(--accent-strong); }
    .detail-card { padding: 24px; border: 1px solid var(--line); border-radius: var(--radius-lg); background: var(--surface); }
    .detail-card h2 { margin: 0 0 16px; font-size: 22px; letter-spacing: -.03em; font-weight: 700; }
    .detail-list { display: grid; grid-template-columns: 120px 1fr; gap: 8px 16px; margin: 0 0 20px; }
    .detail-list dt { color: var(--muted); font-size: 13px; font-weight: 600; }
    .detail-list dd { margin: 0; font-size: 14px; line-height: 1.5; }
    .category-tabs .nav-item { font-size: 12px; }
    @media (min-width: 680px) {
      .shell { padding-left: 28px; padding-right: 28px; }
      .topbar { margin-left: -28px; margin-right: -28px; padding-left: 28px; padding-right: 28px; }
      .reward-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .how-steps { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (min-width: 1024px) {
      .reward-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .detail-list { grid-template-columns: 140px 1fr; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
    }
  </style>
</head>
<body>
  <div class="shell" data-consumer-mode="${viewModel.mode}" data-issue="${viewModel.issueNumber}">
    <header class="topbar">
      <div class="brand-row">
        <a class="brand" href="#top" aria-label="B64 바로 적립 홈"><span class="brand-mark" aria-hidden="true">B64</span><span>바로 적립</span></a>
        <span class="trust-note">확인된 적립만 표시</span>
      </div>
      <nav class="primary-nav" aria-label="주요 메뉴">${navItems}</nav>
    </header>
    <main id="top">
      ${hero}
      ${content}
      ${options.howItWorks ? renderHowItWorks() : ''}
      <p class="footer-note">보상과 참여 조건은 제공처의 최신 기준을 따릅니다. 참여 전 외부 페이지의 조건을 다시 확인해 주세요.</p>
    </main>
  </div>
</body>
</html>`;
}

export function renderAdClickFirstConsumerWeb(viewModel: AdClickFirstConsumerHomeViewModel): string {
  const renderedCards = viewModel.sections
    .flatMap((section) => section.cards)
    .map(renderCard)
    .filter((card): card is string => card !== null);

  const content = renderedCards.length > 0
    ? `<section id="available-now" aria-labelledby="available-title">
      <div class="section-head">
        <h2 id="available-title">${escapeHtml(viewModel.sections[0]?.title ?? '바로 가능한 적립')}</h2>
        <span>${renderedCards.length}개 확인됨</span>
      </div>
      <div class="reward-grid" data-visible-card-count="${renderedCards.length}">${renderedCards.join('\n')}</div>
    </section>`
    : `<section id="available-now" aria-labelledby="available-title">
      <div class="section-head">
        <h2 id="available-title">${escapeHtml(viewModel.sections[0]?.title ?? '바로 가능한 적립')}</h2>
        <span>실시간 확인</span>
      </div>
      ${renderEmptyState()}
    </section>`;

  const navItems = viewModel.primaryNavigation
    .map((item) => `<a class="nav-item nav-item--active" href="#available-now" aria-current="page">${escapeHtml(item.label)}</a>`)
    .join('') + '<a class="nav-item" href="/browse">수익 기회</a>';

  const hero = `
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">${escapeHtml(viewModel.hero.eyebrow)}</p>
        <h1 id="hero-title">${escapeHtml(viewModel.hero.title)}</h1>
        <p>${escapeHtml(viewModel.hero.description)}</p>
      </section>`;

  return renderShell({ mode: viewModel.mode, issueNumber: viewModel.issueNumber }, navItems, hero, content, { howItWorks: true });
}

// Backwards/alias exports for compatibility with alternate naming used by tests/CTO contracts.
export { renderAdClickFirstBrowseWeb as renderAdClickFirstOpportunityBrowseWeb };
export { renderAdClickFirstBrowseWeb as renderOpportunityBrowseWeb };
export { renderAdClickFirstOpportunityDetailWeb as renderAdClickFirstOpportunityDetailPageWeb };
export { renderAdClickFirstOpportunityDetailWeb as renderOpportunityDetailWeb };

export function renderAdClickFirstTodayRouteWeb(viewModel: AdClickFirstTodayRouteViewModel): string {
  const renderedCards = viewModel.cards
    .map(renderCard)
    .filter((card): card is string => card !== null);

  const content = renderedCards.length > 0
    ? `<section id="available-now" aria-labelledby="available-title">
      <div class="section-head">
        <h2 id="available-title">오늘 바로 가능한 적립</h2>
        <span>${renderedCards.length}개 확인됨</span>
      </div>
      <div class="reward-grid" data-visible-card-count="${renderedCards.length}">${renderedCards.join('\n')}</div>
    </section>`
    : `<section id="available-now" aria-labelledby="available-title">
      <div class="section-head">
        <h2 id="available-title">오늘 바로 가능한 적립</h2>
        <span>실시간 확인</span>
      </div>
      ${renderEmptyState()}
    </section>`;

  const navItems = `<a class="nav-item nav-item--active" href="#available-now" aria-current="page">오늘 바로 적립</a><a class="nav-item" href="/browse">수익 기회</a>`;

  const hero = `
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">오늘 추천 우선순위로</p>
        <h1 id="hero-title">지금 바로 할 수 있는 적립</h1>
        <p>짧고 안전하게 끝나는 적립만 먼저 보여드릴게요.</p>
      </section>`;

  return renderShell({ mode: viewModel.mode, issueNumber: null }, navItems, hero, content);
}

export function renderAdClickFirstBrowseWeb(viewModel: AdClickFirstBrowseViewModel): string {
  const renderedCards = viewModel.cards.map(renderCard).filter((card): card is string => card !== null);

  const categoryTabs = viewModel.categories
    .map((cat) => {
      const active = cat.id === viewModel.selectedCategory;
      const href = cat.active ? `/browse?category=${cat.id}` : '#';
      const label = cat.active ? `${cat.label} (${cat.count})` : `${cat.label} (준비 중)`;
      return `<a class="nav-item${active ? ' nav-item--active' : ''}" href="${escapeHtml(href)}" ${active ? 'aria-current="page"' : ''} ${cat.active ? '' : 'aria-disabled="true"'}>${escapeHtml(label)}</a>`;
    })
    .join('');

  const filterForm = `<form class="filter-bar" method="GET" action="/browse" role="search" aria-label="수익 기회 필터">
    <input type="hidden" name="category" value="${escapeHtml(viewModel.selectedCategory)}" />
    <label>검색 <input type="search" name="q" value="${escapeHtml(viewModel.filters.query)}" placeholder="기회 제목" /></label>
    <label>최대 소요 시간(초) <select name="maxSeconds">
      <option value="" ${viewModel.filters.maxSeconds === null ? 'selected' : ''}>전체</option>
      <option value="60" ${viewModel.filters.maxSeconds === 60 ? 'selected' : ''}>60초 이하</option>
      <option value="120" ${viewModel.filters.maxSeconds === 120 ? 'selected' : ''}>2분 이하</option>
      <option value="300" ${viewModel.filters.maxSeconds === 300 ? 'selected' : ''}>5분 이하</option>
    </select></label>
    <button type="submit">필터 적용</button>
  </form>`;

  const content = renderedCards.length > 0
    ? `<section id="available-now" aria-labelledby="available-title">
      <div class="section-head">
        <h2 id="available-title">수익 기회 탐색</h2>
        <span>${renderedCards.length}개 확인됨</span>
      </div>
      <div class="reward-grid" data-visible-card-count="${renderedCards.length}">${renderedCards.join('\n')}</div>
    </section>`
    : `<section id="available-now" aria-labelledby="available-title">
      <div class="section-head">
        <h2 id="available-title">수익 기회 탐색</h2>
        <span>실시간 확인</span>
      </div>
      ${renderEmptyState()}
      <p class="later-tier-notice">${escapeHtml(viewModel.laterTierNotice)}</p>
    </section>`;

  const navItems = `<a class="nav-item" href="/">홈</a><a class="nav-item" href="/today">오늘 추천</a><a class="nav-item nav-item--active" href="/browse" aria-current="page">수익 기회</a>`;

  const hero = `
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">수익 기회 탐색</p>
        <h1 id="hero-title">참여 가능한 수익 기회</h1>
        <p>확인된 조건과 보상만 표시합니다. 미확인 정보는 추정하지 않습니다.</p>
      </section>
      <nav class="category-tabs" aria-label="카테고리">${categoryTabs}</nav>
      ${filterForm}`;

  return renderShell({ mode: viewModel.mode, issueNumber: null }, navItems, hero, content, { howItWorks: true });
}

export function renderAdClickFirstOpportunityDetailWeb(viewModel: AdClickFirstOpportunityDetailViewModel): string {
  const card = viewModel.card;
  const content = card
    ? `<section id="opportunity-detail" aria-labelledby="detail-title">
      <div class="detail-card">
        <h2 id="detail-title">${escapeHtml(card.title)}</h2>
        <dl class="detail-list">
          <dt>제공 업체</dt><dd>${escapeHtml(card.sourceId)}</dd>
          <dt>보상</dt><dd>${escapeHtml(card.rewardLabel)} (${escapeHtml(card.certainty === 'GUARANTEED' ? '확정 보상' : '조건 충족 시')})</dd>
          <dt>예상 소요 시간</dt><dd>약 ${card.estimatedActiveSeconds}초</dd>
          <dt>참여 자격·조건</dt><dd>${escapeHtml(card.conditionSummary)}</dd>
          <dt>출처</dt><dd>${escapeHtml(card.sourceId)}</dd>
          <dt>최종 검증 시각</dt><dd>${escapeHtml(card.lastVerifiedAt)}</dd>
        </dl>
        ${safeOutboundHref(card.canonicalDestinationUrl) ? `<a class="reward-cta" href="${safeOutboundHref(card.canonicalDestinationUrl)}" target="_blank" rel="noopener noreferrer nofollow">공식 사이트에서 참여하기<span aria-hidden="true"> ↗</span></a>` : ''}
      </div>
    </section>`
    : `<section id="opportunity-detail" aria-labelledby="detail-title">
      <div class="empty-state" role="status" data-empty-state="NO_LIVE_REWARD_SUPPLY">
        <div class="empty-state__mark" aria-hidden="true">✓</div>
        <h3>수익 기회를 찾을 수 없습니다</h3>
        <p>요청한 기회가 없거나 현재 공개되지 않은 상태입니다.</p>
      </div>
    </section>`;

  const navItems = `<a class="nav-item" href="/">홈</a><a class="nav-item" href="/today">오늘 추천</a><a class="nav-item" href="/browse">수익 기회</a>`;

  const hero = `
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">수익 기회 상세</p>
        <h1 id="hero-title">${card ? escapeHtml(card.title) : '수익 기회 상세'}</h1>
        <p>${card ? '조건을 확인한 뒤 외부 제공처에서 참여하세요.' : '요청한 기회를 확인할 수 없습니다.'}</p>
      </section>`;

  return renderShell({ mode: viewModel.mode, issueNumber: null }, navItems, hero, content);
}
