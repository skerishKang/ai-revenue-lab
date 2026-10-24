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

function formatVerifiedAtKst(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '최근 확인';
  const kst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const yyyy = kst.getUTCFullYear();
  const mm = String(kst.getUTCMonth() + 1).padStart(2, '0');
  const dd = String(kst.getUTCDate()).padStart(2, '0');
  const hh = String(kst.getUTCHours()).padStart(2, '0');
  const mi = String(kst.getUTCMinutes()).padStart(2, '0');
  return `${yyyy}.${mm}.${dd} ${hh}:${mi} KST 확인`;
}

function renderPrimaryNav(activeId: 'HOME' | 'TODAY' | 'BROWSE' | null): string {
  const items: ReadonlyArray<{ id: 'HOME' | 'TODAY' | 'BROWSE'; href: string; label: string }> = Object.freeze([
    Object.freeze({ id: 'HOME', href: '/', label: '홈' }),
    Object.freeze({ id: 'TODAY', href: '/today', label: '오늘 바로 적립' }),
    Object.freeze({ id: 'BROWSE', href: '/browse', label: '수익 기회' }),
  ]);
  return items
    .map((item) => `<a class="nav-item${item.id === activeId ? ' nav-item--active' : ''}" href="${item.href}"${item.id === activeId ? ' aria-current="page"' : ''}>${item.label}</a>`)
    .join('');
}

function renderBrandMark(className: string): string {
  return `<svg class="${className}" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M6 25V7h8.5c5.2 0 8.5 2.8 8.5 7.1 0 4.4-3.3 7.2-8.5 7.2H10" stroke="currentColor" stroke-linecap="round" stroke-width="1.6" />
    <path d="M10 11h4.5c2.5 0 4 1.1 4 3.1s-1.5 3.2-4 3.2H10" stroke="url(#padiem-mark)" stroke-linecap="round" stroke-width="1.6" />
    <defs><linearGradient id="padiem-mark" x1="10" y1="11" x2="19" y2="19" gradientUnits="userSpaceOnUse"><stop stop-color="#8BCBFF" /><stop offset="1" stop-color="#F0C77C" /></linearGradient></defs>
  </svg>`;
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
    <h3 title="${escapeHtml(card.title)}">${escapeHtml(card.title)}</h3>
    <div class="reward-card__reward">
      <strong>${escapeHtml(card.rewardLabel)}</strong>
      <span>${certaintyLabel}</span>
    </div>
    <p class="condition" title="${escapeHtml(card.conditionSummary)}">${escapeHtml(card.conditionSummary)}</p>
    <div class="reward-card__meta" aria-label="참여 정보">
      <span>⏱ ${formatActiveTime(card.estimatedActiveSeconds)}</span>
      <span aria-hidden="true" class="meta-dot">·</span>
      <span>외부 페이지에서 참여</span>
    </div>
    <a class="reward-cta" href="${href}" target="_blank" rel="noopener noreferrer nofollow">적립하러 가기<span aria-hidden="true"> ↗</span></a>
    <a class="detail-link" href="/detail?id=${escapeHtml(card.id)}">자세히 보기<span aria-hidden="true"> →</span></a>
  </article>`;
}

function renderEmptyState(): string {
  return `<div class="empty-state" role="status" data-empty-state="NO_LIVE_REWARD_SUPPLY">
    <div class="empty-state__mark" aria-hidden="true">${renderBrandMark('empty-state__mark-svg')}</div>
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
      <li class="how-step">
        <span class="how-step__num" aria-hidden="true">1</span>
        <div class="how-step__body">
          <h3>짧은 적립 선택</h3>
          <p>광고 보기, 클릭, 방문처럼 짧게 끝나는 항목만 먼저 준비돼요.</p>
        </div>
      </li>
      <li class="how-step">
        <span class="how-step__num" aria-hidden="true">2</span>
        <div class="how-step__body">
          <h3>조건과 보상 확인</h3>
          <p>보상 단가, 소요 시간, 참여 조건을 참여 전에 확인해요.</p>
        </div>
      </li>
      <li class="how-step">
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
  <meta name="color-scheme" content="dark" />
  <title>AI Reward Router | PADIEM</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #06080d;
      --bg-soft: #0b0f16;
      --surface: rgba(255,255,255,.055);
      --surface-strong: rgba(255,255,255,.105);
      --line: rgba(255,255,255,.14);
      --line-soft: rgba(255,255,255,.09);
      --text: #f4f6fb;
      --muted: rgba(255,255,255,.68);
      --faint: rgba(255,255,255,.45);
      --accent: #88c9ff;
      --accent-strong: #5fb3ff;
      --accent-dim: rgba(136,201,255,.14);
      --gold: #efc984;
      --radius-card: 16px;
      --radius-btn: 10px;
      --pad: clamp(16px, 4vw, 64px);
      font-family: "SUIT Variable", "SUIT", "Pretendard", "Apple SD Gothic Neo", system-ui, sans-serif;
      font-synthesis: none;
      text-rendering: optimizeLegibility;
      -webkit-font-smoothing: antialiased;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background: radial-gradient(1100px 480px at 50% -120px, rgba(136,201,255,.075), transparent 62%) var(--bg);
      color: var(--text);
    }
    a { color: inherit; text-decoration: none; }

    .shell { width: min(100%, 1200px); margin: 0 auto; padding: 0 var(--pad) 72px; }

    .topbar {
      position: sticky; top: 0; z-index: 10;
      margin: 0 calc(var(--pad) * -1); padding: 10px var(--pad) 8px;
      background: rgba(6,8,13,.78); backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--line-soft);
    }
    .topbar-inner { display: flex; align-items: center; justify-content: space-between; gap: 8px 16px; flex-wrap: wrap; }
    .brand { display: inline-flex; align-items: center; gap: 10px; font-size: 17px; font-weight: 600; letter-spacing: .16em; }
    .brand-mark { width: 26px; height: 26px; flex: 0 0 auto; filter: drop-shadow(0 0 12px rgba(136,201,255,.25)); }
    .brand-wordmark { line-height: 1; }
    .brand-divider { width: 1px; height: 14px; background: var(--line); flex: 0 0 auto; }
    .brand-product { font-size: 12px; font-weight: 500; letter-spacing: .02em; color: var(--muted); white-space: nowrap; }
    .trust-note { margin-left: auto; font-size: 11px; color: var(--faint); white-space: nowrap; }

    .primary-nav { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; width: 100%; order: 3; padding: 8px 0 2px; }
    .primary-nav::-webkit-scrollbar { display: none; }
    .nav-item { flex: 0 0 auto; padding: 7px 13px; border-radius: 999px; font-size: 13px; font-weight: 600; color: var(--muted); border: 1px solid transparent; transition: color .16s ease, background .16s ease, border-color .16s ease; }
    .nav-item:hover { color: var(--text); }
    .nav-item--active { background: var(--surface-strong); color: var(--text); border-color: var(--line); }

    .hero { padding: 30px 0 20px; }
    .eyebrow { margin: 0 0 12px; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
    .hero h1 {
      margin: 0; max-width: 720px;
      font-size: clamp(27px, 5.6vw, 56px);
      line-height: 1.06; letter-spacing: -.045em; font-weight: 640;
      text-wrap: balance;
    }
    .hero p { margin: 14px 0 0; max-width: 560px; color: var(--muted); font-size: 15px; line-height: 1.6; }

    .section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 20px 0 14px; flex-wrap: wrap; }
    .section-head h2 { margin: 0; font-size: 19px; letter-spacing: -.025em; font-weight: 650; }
    .section-head > span { display: inline-flex; align-items: center; min-height: 24px; padding: 0 10px; border-radius: 999px; background: var(--surface); border: 1px solid var(--line-soft); color: var(--muted); font-size: 12px; }

    .home-intro { margin: 18px 0 8px; }
    .intro-desc { margin: 8px 0 0; color: var(--muted); font-size: 14px; line-height: 1.55; }
    .cta-link { color: var(--accent); font-size: 13px; font-weight: 700; white-space: nowrap; }
    .cta-link:hover { text-decoration: underline; }
    .home-actions { display: flex; flex-direction: column; gap: 10px; margin: 24px 0 10px; }
    .home-cta { display: flex; align-items: center; justify-content: center; min-height: 48px; border-radius: var(--radius-btn); font-size: 15px; font-weight: 700; letter-spacing: -.01em; transition: background .16s ease, transform .16s ease; }
    .home-cta--primary { background: var(--accent); color: #06080d; }
    .home-cta--secondary { background: var(--surface); border: 1px solid var(--line); color: var(--text); }
    .home-cta--primary:hover { background: var(--accent-strong); }
    .home-cta--secondary:hover { background: var(--surface-strong); }
    .visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

    .reward-grid { display: grid; gap: 12px; grid-template-columns: 1fr; }
    .reward-card {
      display: flex; flex-direction: column;
      padding: 18px; border: 1px solid var(--line-soft); border-radius: var(--radius-card);
      background: linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.045));
      transition: border-color .16s ease, transform .16s ease;
    }
    .reward-card:hover { border-color: rgba(136,201,255,.38); transform: translateY(-2px); }
    .reward-card__topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .action-chip { display: inline-flex; align-items: center; min-height: 24px; padding: 0 10px; border-radius: 999px; background: var(--accent-dim); color: var(--accent); font-size: 12px; font-weight: 700; border: 1px solid rgba(136,201,255,.25); }
    .freshness { color: var(--faint); font-size: 11px; white-space: nowrap; }
    .reward-card h3 { margin: 13px 0 10px; font-size: 16px; line-height: 1.4; letter-spacing: -.015em; font-weight: 650; overflow-wrap: anywhere; }
    .reward-card__reward { display: flex; align-items: baseline; gap: 8px; }
    .reward-card__reward strong { color: var(--gold); font-size: 23px; letter-spacing: -.03em; font-weight: 700; }
    .reward-card__reward span { color: var(--faint); font-size: 12px; font-weight: 600; }
    .condition {
      margin: 10px 0 0; color: var(--muted); font-size: 13.5px; line-height: 1.55;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .reward-card__meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; margin: 12px 0 16px; color: var(--muted); font-size: 12px; }
    .meta-dot { color: var(--faint); }
    .reward-cta {
      display: flex; align-items: center; justify-content: center; min-height: 46px; padding: 0 22px;
      border-radius: var(--radius-btn); background: var(--accent); color: #06080d;
      font-size: 14px; font-weight: 700; letter-spacing: -.01em;
      transition: background .16s ease, transform .16s ease;
      margin-top: auto;
    }
    .reward-cta:hover { background: var(--accent-strong); transform: translateY(-1px); }
    .detail-link { display: inline-flex; align-items: center; gap: 4px; align-self: flex-start; margin-top: 11px; font-size: 13px; color: var(--accent); font-weight: 600; }
    .detail-link:hover { text-decoration: underline; }
    .reward-cta:focus-visible, .nav-item:focus-visible, .brand:focus-visible, .detail-link:focus-visible, .filter-bar input:focus-visible, .filter-bar select:focus-visible, .filter-bar button:focus-visible, .back-link:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

    .empty-state {
      display: grid; justify-items: center;
      padding: 44px 24px; border: 1px solid var(--line-soft); border-radius: var(--radius-card);
      background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));
      text-align: center;
    }
    .empty-state__mark { display: grid; place-items: center; width: 56px; height: 56px; border-radius: 50%; background: var(--accent-dim); border: 1px solid rgba(136,201,255,.22); color: var(--accent); }
    .empty-state__mark-svg { width: 28px; height: 28px; }
    .empty-state h3 { margin: 16px 0 8px; font-size: 17px; letter-spacing: -.02em; font-weight: 650; }
    .empty-state p { margin: 0; max-width: 380px; color: var(--muted); font-size: 14px; line-height: 1.6; }
    .empty-steps { list-style: none; padding: 0; margin: 20px 0 0; max-width: 420px; display: grid; gap: 9px; text-align: left; }
    .empty-steps li { position: relative; padding-left: 18px; font-size: 13px; color: var(--muted); line-height: 1.55; }
    .empty-steps li::before { content: ""; position: absolute; left: 0; top: 7px; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); opacity: .8; }
    .empty-state .ghost-btn { margin-top: 20px; min-width: 220px; }

    .how-it-works { padding: 28px 0 0; }
    .how-steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; grid-template-columns: 1fr; }
    .how-step { display: flex; align-items: flex-start; gap: 13px; padding: 16px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: var(--surface); }
    .how-step__num { flex: 0 0 auto; display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; background: var(--accent-dim); color: var(--accent); font-weight: 700; font-size: 13px; }
    .how-step__body h3 { margin: 2px 0 4px; font-size: 14.5px; font-weight: 650; letter-spacing: -.01em; }
    .how-step__body p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.55; }

    .later-tier-notice { margin: 14px 0 0; color: var(--muted); font-size: 12px; text-align: center; }
    .footer-note { margin: 40px auto 0; max-width: 560px; color: var(--faint); font-size: 11.5px; line-height: 1.65; text-align: center; }

    .filter-bar { display: grid; grid-template-columns: 1fr; gap: 10px; align-items: end; padding: 12px 0 2px; }
    .filter-bar label { display: flex; flex-direction: column; gap: 5px; font-size: 11px; color: var(--muted); font-weight: 600; letter-spacing: .04em; min-width: 0; }
    .filter-bar input, .filter-bar select {
      width: 100%; min-height: 44px; padding: 9px 12px; border-radius: var(--radius-btn);
      border: 1px solid var(--line-soft); background: var(--surface); color: var(--text);
      font-size: 14px; min-width: 0;
    }
    .filter-bar input::placeholder { color: var(--faint); }
    .filter-bar select { height: 44px; }
    .filter-bar button {
      grid-column: 1 / -1; min-height: 46px; padding: 0 22px; border-radius: var(--radius-btn);
      border: 1px solid var(--accent); background: var(--accent); color: #06080d;
      font-size: 14px; font-weight: 700; cursor: pointer; letter-spacing: -.01em;
      transition: background .16s ease;
    }
    .filter-bar button:hover { background: var(--accent-strong); }

    .category-tabs { display: flex; gap: 6px; padding: 14px 0 2px; overflow-x: auto; scrollbar-width: none; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; }
    .category-tabs::-webkit-scrollbar { display: none; }
    .category-tabs .nav-item { font-size: 12px; }
    .nav-item[aria-disabled="true"] { color: var(--faint); cursor: default; }

    .back-link { display: inline-flex; align-items: center; gap: 6px; margin: 18px 0 0; font-size: 13px; color: var(--muted); font-weight: 600; }
    .back-link:hover { color: var(--text); }

    .detail-card { padding: 22px 18px 20px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: linear-gradient(180deg, rgba(255,255,255,.07), rgba(255,255,255,.04)); }
    .detail-card h2 { margin: 12px 0 16px; font-size: 24px; line-height: 1.25; letter-spacing: -.03em; font-weight: 660; overflow-wrap: anywhere; }
    .detail-reward { display: flex; align-items: baseline; gap: 10px; padding-bottom: 18px; border-bottom: 1px solid var(--line-soft); }
    .detail-reward strong { color: var(--gold); font-size: 32px; line-height: 1; letter-spacing: -.03em; font-weight: 700; }
    .detail-reward span { color: var(--faint); font-size: 12px; font-weight: 600; }
    .detail-facts { display: grid; gap: 0; padding: 6px 0 14px; }
    .detail-fact { display: grid; grid-template-columns: 116px 1fr; gap: 12px; padding: 13px 0; border-bottom: 1px dashed var(--line-soft); }
    .detail-fact:last-child { border-bottom: 0; }
    .detail-fact__label { color: var(--faint); font-size: 11px; font-weight: 650; letter-spacing: .07em; text-transform: uppercase; padding-top: 2px; }
    .detail-fact__value { font-size: 14.5px; line-height: 1.55; overflow-wrap: anywhere; }
    .detail-meta { display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 4px 0 18px; color: var(--faint); font-size: 11.5px; }
    .detail-cta { margin-top: 0; }
    .detail-actions { display: grid; gap: 10px; margin-top: 18px; }
    .ghost-btn { display: flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 20px; border-radius: var(--radius-btn); border: 1px solid var(--line); background: transparent; color: var(--text); font-size: 13.5px; font-weight: 600; transition: border-color .16s ease, background .16s ease; }
    .ghost-btn:hover { border-color: rgba(136,201,255,.4); background: rgba(255,255,255,.04); }

    @media (min-width: 680px) {
      .reward-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
      .how-steps { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .filter-bar { grid-template-columns: 1fr 1fr auto; }
      .filter-bar button { grid-column: auto; }
      .detail-actions { grid-template-columns: 1fr 1fr; align-items: stretch; }
      .detail-card { padding: 28px 28px 24px; }
      .detail-card h2 { font-size: 27px; }
    }
    @media (min-width: 880px) {
      .primary-nav { width: auto; order: 0; padding: 0; }
      .trust-note { margin-left: 0; }
    }
    @media (min-width: 1024px) {
      .reward-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
      .hero { padding: 64px 0 32px; }
      .hero p { font-size: 16px; }
      .reward-card { padding: 20px; }
      .how-it-works { padding-top: 40px; }
    }
    @media (min-width: 1280px) {
      .hero { padding: 76px 0 36px; }
      .hero h1 { font-size: 60px; }
      .reward-card { padding: 22px; }
      .section-head { margin: 26px 0 16px; }
      .detail-card { padding: 32px 32px 28px; }
    }
    @media (max-width: 480px) {
      .brand { font-size: 15px; }
      .brand-mark { width: 22px; height: 22px; }
      .brand-divider { height: 12px; }
      .brand-product { font-size: 11px; }
      .trust-note { display: none; }
      .nav-item { padding: 6px 11px; font-size: 12px; }
      .hero { padding: 24px 0 16px; }
      .hero h1 { font-size: 27px; }
      .hero p { font-size: 14px; margin-top: 10px; }
      .eyebrow { margin-bottom: 9px; }
      .section-head { margin: 14px 0 11px; }
      .section-head h2 { font-size: 17px; }
      .reward-card { padding: 16px; }
      .reward-card h3 { font-size: 15.5px; margin: 11px 0 8px; }
      .reward-card__reward strong { font-size: 21px; }
      .empty-state { padding: 36px 18px; }
      .how-step { padding: 14px; }
      .detail-card { padding: 18px 16px; }
      .detail-card h2 { font-size: 21px; margin: 10px 0 14px; }
      .detail-fact { grid-template-columns: 96px 1fr; gap: 10px; }
      .footer-note { margin-top: 32px; }
      .home-actions { margin: 18px 0 8px; }
      .home-cta { min-height: 44px; font-size: 14px; }
      .cta-link { font-size: 12px; }
      .intro-desc { font-size: 13px; }
      .hero { padding: 20px 0 14px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
    }
  </style>
</head>
<body>
  <div class="shell" data-consumer-mode="${viewModel.mode}" data-issue="${viewModel.issueNumber}">
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="#top" aria-label="PADIEM AI Reward Router">
          ${renderBrandMark('brand-mark')}
          <span class="brand-wordmark">PADIEM</span>
          <span class="brand-divider" aria-hidden="true"></span>
          <span class="brand-product">AI Reward Router</span>
        </a>
        <span class="trust-note">확인된 적립만 표시</span>
        <nav class="primary-nav" aria-label="주요 메뉴">${navItems}</nav>
      </div>
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

  const intro = `
    <section class="home-intro" aria-labelledby="intro-title">
      <div class="section-head">
        <h2 id="intro-title">오늘의 추천</h2>
        <a class="cta-link" href="/today">추천 보러 가기<span aria-hidden="true"> →</span></a>
      </div>
      <p class="intro-desc">오늘 가장 먼저 참여하기 좋은 적립을 모았습니다.</p>
    </section>`;

  const actions = `
    <section class="home-actions" aria-labelledby="actions-title">
      <h2 id="actions-title" class="visually-hidden">수익 기회 탐색</h2>
      <a class="home-cta home-cta--primary" href="/browse">수익 기회 찾기<span aria-hidden="true"> →</span></a>
      <a class="home-cta home-cta--secondary" href="/today">오늘의 추천 보기<span aria-hidden="true"> →</span></a>
    </section>`;

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

  const navItems = renderPrimaryNav('HOME');

  const hero = `
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">${escapeHtml(viewModel.hero.eyebrow)}</p>
        <h1 id="hero-title">${escapeHtml(viewModel.hero.title)}</h1>
        <p>${escapeHtml(viewModel.hero.description)}</p>
      </section>`;

  return renderShell({ mode: viewModel.mode, issueNumber: viewModel.issueNumber }, navItems, hero, `${intro}${actions}${content}`, { howItWorks: true });
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

  const navItems = renderPrimaryNav('TODAY');

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

  const navItems = renderPrimaryNav('BROWSE');

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
    ? `<a class="back-link" href="/browse">← 수익 기회 목록</a>
    <section id="opportunity-detail" aria-labelledby="detail-title">
      <div class="detail-card">
        <p class="eyebrow">수익 기회 상세</p>
        <h2 id="detail-title">${escapeHtml(card.title)}</h2>
        <div class="detail-reward">
          <strong>${escapeHtml(card.rewardLabel)}</strong>
          <span>${escapeHtml(card.certainty === 'GUARANTEED' ? '확정 보상' : '조건 충족 시')}</span>
        </div>
        <div class="detail-facts">
          <div class="detail-fact">
            <span class="detail-fact__label">예상 소요 시간</span>
            <span class="detail-fact__value">약 ${card.estimatedActiveSeconds}초</span>
          </div>
          <div class="detail-fact">
            <span class="detail-fact__label">참여 자격·조건</span>
            <span class="detail-fact__value">${escapeHtml(card.conditionSummary)}</span>
          </div>
          <div class="detail-fact">
            <span class="detail-fact__label">보상 제공 업체</span>
            <span class="detail-fact__value">${escapeHtml(card.sourceId)}</span>
          </div>
        </div>
        <div class="detail-meta">
          <span>출처 · ${escapeHtml(card.sourceId)}</span>
          <span>최종 검증 · ${formatVerifiedAtKst(card.lastVerifiedAt)}</span>
        </div>
        <div class="detail-actions">
          ${safeOutboundHref(card.canonicalDestinationUrl) ? `<a class="reward-cta detail-cta" href="${safeOutboundHref(card.canonicalDestinationUrl)}" target="_blank" rel="noopener noreferrer nofollow">공식 제공처에서 참여하기<span aria-hidden="true"> ↗</span></a>` : ''}
          <a class="ghost-btn" href="/browse">다른 기회 둘러보기</a>
        </div>
      </div>
    </section>`
    : `<a class="back-link" href="/browse">← 수익 기회 목록</a>
    <section id="opportunity-detail" aria-labelledby="detail-title">
      <div class="empty-state" role="status" data-empty-state="NO_LIVE_REWARD_SUPPLY">
        <div class="empty-state__mark" aria-hidden="true">${renderBrandMark('empty-state__mark-svg')}</div>
        <h3>수익 기회를 찾을 수 없습니다</h3>
        <p>요청한 기회가 없거나 현재 공개되지 않은 상태입니다.</p>
        <a class="ghost-btn" href="/browse">수익 기회 탐색으로 이동</a>
      </div>
    </section>`;

  const navItems = renderPrimaryNav(null);

  const hero = `
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">수익 기회 상세</p>
        <h1 id="hero-title">${card ? escapeHtml(card.title) : '수익 기회 상세'}</h1>
        <p>${card ? '조건을 확인한 뒤 외부 제공처에서 참여하세요.' : '요청한 기회를 확인할 수 없습니다.'}</p>
      </section>`;

  return renderShell({ mode: viewModel.mode, issueNumber: null }, navItems, hero, content);
}
