import type {
  AdClickFirstConsumerHomeViewModel,
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
  </article>`;
}

function renderEmptyState(): string {
  return `<div class="empty-state" role="status" data-empty-state="NO_LIVE_REWARD_SUPPLY">
    <div class="empty-state__mark" aria-hidden="true">✓</div>
    <h3>지금 참여 가능한 적립을 확인 중이에요</h3>
    <p>실제로 참여할 수 있고 보상 조건이 확인된 항목만 보여드릴게요.</p>
  </div>`;
}

/**
 * Deterministic, dependency-free consumer HTML renderer for the current B64 P0 lane.
 * It only accepts the already policy-filtered consumer Home view-model. A malformed
 * outbound URL is suppressed again at render time as defense in depth.
 */
export function renderAdClickFirstConsumerWeb(
  viewModel: AdClickFirstConsumerHomeViewModel,
): string {
  const renderedCards = viewModel.sections
    .flatMap((section) => section.cards)
    .map(renderCard)
    .filter((card): card is string => card !== null);

  const content = renderedCards.length > 0
    ? `<div class="reward-grid" data-visible-card-count="${renderedCards.length}">${renderedCards.join('\n')}</div>`
    : renderEmptyState();

  const navItems = viewModel.primaryNavigation
    .map((item) => `<a class="nav-item nav-item--active" href="#available-now" aria-current="page">${escapeHtml(item.label)}</a>`)
    .join('');

  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>바로 적립 | B64</title>
  <style>
    :root {
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #14251f;
      background: #f5f8f5;
      font-synthesis: none;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; background: #f5f8f5; color: #14251f; }
    a { color: inherit; }
    .shell { width: min(100%, 760px); margin: 0 auto; padding: 0 20px 56px; }
    .topbar { position: sticky; top: 0; z-index: 10; margin: 0 -20px; padding: 14px 20px 10px; background: rgba(245,248,245,.94); backdrop-filter: blur(14px); }
    .brand-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    .brand { display: inline-flex; align-items: center; gap: 9px; font-weight: 800; letter-spacing: -.02em; text-decoration: none; }
    .brand-mark { display: grid; place-items: center; width: 31px; height: 31px; border-radius: 10px; background: #173f31; color: white; font-size: 13px; }
    .trust-note { font-size: 12px; color: #63736c; }
    .primary-nav { display: flex; gap: 8px; padding-top: 12px; overflow-x: auto; scrollbar-width: none; }
    .primary-nav::-webkit-scrollbar { display: none; }
    .nav-item { flex: 0 0 auto; padding: 9px 14px; border-radius: 999px; text-decoration: none; font-size: 14px; font-weight: 700; }
    .nav-item--active { background: #173f31; color: #fff; }
    .hero { padding: 44px 2px 28px; }
    .eyebrow { margin: 0 0 10px; color: #3c705b; font-size: 13px; font-weight: 800; letter-spacing: .02em; }
    .hero h1 { margin: 0; max-width: 520px; font-size: clamp(32px, 8vw, 52px); line-height: 1.02; letter-spacing: -.055em; }
    .hero p { margin: 18px 0 0; max-width: 540px; color: #64716c; font-size: 16px; line-height: 1.65; }
    .section-head { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 18px 0 14px; }
    .section-head h2 { margin: 0; font-size: 20px; letter-spacing: -.025em; }
    .section-head span { color: #718078; font-size: 12px; }
    .reward-grid { display: grid; gap: 12px; }
    .reward-card { padding: 18px; border: 1px solid #dfe7e2; border-radius: 22px; background: #fff; box-shadow: 0 9px 28px rgba(29,61,48,.055); }
    .reward-card__topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .action-chip { display: inline-flex; align-items: center; min-height: 28px; padding: 0 10px; border-radius: 999px; background: #e9f3ed; color: #2d614c; font-size: 12px; font-weight: 800; }
    .freshness { color: #87938e; font-size: 11px; }
    .reward-card h3 { margin: 15px 0 13px; font-size: 19px; line-height: 1.35; letter-spacing: -.025em; }
    .reward-card__reward { display: flex; align-items: baseline; gap: 9px; }
    .reward-card__reward strong { color: #173f31; font-size: 24px; letter-spacing: -.03em; }
    .reward-card__reward span { color: #6f7d77; font-size: 12px; font-weight: 700; }
    .condition { margin: 12px 0 0; color: #4e5d57; font-size: 14px; line-height: 1.55; }
    .reward-card__meta { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 15px 0 16px; color: #73817b; font-size: 12px; }
    .reward-cta { display: flex; align-items: center; justify-content: center; min-height: 48px; border-radius: 15px; background: #173f31; color: #fff; text-decoration: none; font-size: 14px; font-weight: 800; transition: transform .16s ease, background .16s ease; }
    .reward-cta:hover { background: #235945; transform: translateY(-1px); }
    .reward-cta:focus-visible, .nav-item:focus-visible, .brand:focus-visible { outline: 3px solid #7cad96; outline-offset: 3px; }
    .empty-state { display: grid; justify-items: center; padding: 56px 24px; border: 1px dashed #cad8d0; border-radius: 24px; background: rgba(255,255,255,.66); text-align: center; }
    .empty-state__mark { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 50%; background: #e6f2eb; color: #2e654f; font-weight: 900; }
    .empty-state h3 { margin: 15px 0 8px; font-size: 18px; letter-spacing: -.02em; }
    .empty-state p { margin: 0; max-width: 360px; color: #718078; font-size: 14px; line-height: 1.6; }
    .footer-note { margin: 24px 0 0; color: #8a958f; font-size: 11px; line-height: 1.6; text-align: center; }
    @media (min-width: 680px) {
      .shell { padding-left: 28px; padding-right: 28px; }
      .topbar { margin-left: -28px; margin-right: -28px; padding-left: 28px; padding-right: 28px; }
      .reward-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">${escapeHtml(viewModel.hero.eyebrow)}</p>
        <h1 id="hero-title">${escapeHtml(viewModel.hero.title)}</h1>
        <p>${escapeHtml(viewModel.hero.description)}</p>
      </section>
      <section id="available-now" aria-labelledby="available-title">
        <div class="section-head">
          <h2 id="available-title">${escapeHtml(viewModel.sections[0]?.title ?? '바로 가능한 적립')}</h2>
          <span>${renderedCards.length > 0 ? `${renderedCards.length}개 확인됨` : '실시간 확인'}</span>
        </div>
        ${content}
      </section>
      <p class="footer-note">보상과 참여 조건은 제공처의 최신 기준을 따릅니다. 참여 전 외부 페이지의 조건을 다시 확인해 주세요.</p>
    </main>
  </div>
</body>
</html>`;
}
