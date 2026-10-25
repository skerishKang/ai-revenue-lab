import type { UserIncomeRecord, UserIncomeSummary, IncomePipelineStatus } from './domain.js';
import { INCOME_PIPELINE_STATUS_LABELS, INCOME_PIPELINE_STATUSES, formatCurrencyAmount, formatIncomeDate, filterUserIncomeRecords, sortUserIncomeRecords, buildUserIncomeSummary } from './domain.js';
import type { PublicOpportunity } from '../public-supply/domain.js';
import { toPublicOpportunityCard, isPublicOpportunityDisplayable } from '../public-supply/domain.js';

export interface IncomePipelineFilterState {
  readonly status: import('./domain.js').IncomePipelineStatus | null;
  readonly vendor: string | null;
}

export interface IncomePipelineViewModel {
  readonly mode: 'INCOME_PIPELINE';
  readonly userId: string | null;
  readonly summary: UserIncomeSummary | null;
  readonly records: readonly UserIncomeRecord[];
  readonly filteredRecords: readonly UserIncomeRecord[];
  readonly filters: IncomePipelineFilterState;
  readonly availableOpportunities: readonly PublicOpportunity[];
  readonly emptyState: 'NO_USER' | 'NO_RECORDS' | null;
  readonly accountOnboardingVisibleToConsumer: false;
  readonly laterTierNavigationVisible: false;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function safeOutboundHref(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? escapeHtml(url.toString()) : null;
  } catch {
    return null;
  }
}

function renderBrandMark(className: string): string {
  return `<svg class="${className}" viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M6 25V7h8.5c5.2 0 8.5 2.8 8.5 7.1 0 4.4-3.3 7.2-8.5 7.2H10" stroke="currentColor" stroke-linecap="round" stroke-width="1.6" />
    <path d="M10 11h4.5c2.5 0 4 1.1 4 3.1s-1.5 3.2-4 3.2H10" stroke="url(#padiem-mark)" stroke-linecap="round" stroke-width="1.6" />
    <defs><linearGradient id="padiem-mark" x1="10" y1="11" x2="19" y2="19" gradientUnits="userSpaceOnUse"><stop stop-color="#8BCBFF" /><stop offset="1" stop-color="#F0C77C" /></linearGradient></defs>
  </svg>`;
}

function renderEmptyState(message: string): string {
  return `<div class="empty-state" role="status">
    <div class="empty-state__mark" aria-hidden="true">${renderBrandMark('empty-state__mark-svg')}</div>
    <h3>${escapeHtml(message)}</h3>
  </div>`;
}

function renderPrimaryNav(activeId: 'HOME' | 'TODAY' | 'BROWSE' | 'PIPELINE' | null): string {
  const items = [
    { id: 'HOME' as const, href: '/', label: '홈' },
    { id: 'TODAY' as const, href: '/today', label: '오늘의 기회' },
    { id: 'BROWSE' as const, href: '/browse', label: '수익 기회' },
    { id: 'PIPELINE' as const, href: '/pipeline', label: '내 수익 관리' },
  ];
  return items
    .map((item) => `<a class="nav-item${item.id === activeId ? ' nav-item--active' : ''}" href="${item.href}"${item.id === activeId ? ' aria-current="page"' : ''}>${item.label}</a>`)
    .join('');
}

function renderSummary(summary: UserIncomeSummary): string {
  const expectedEntries = Array.from(summary.expectedTotal.entries());
  const actualEntries = Array.from(summary.actualTotal.entries());
  const expectedStr = expectedEntries.length > 0
    ? expectedEntries.map(([cur, amt]) => `${amt.toLocaleString()} ${cur}`).join(', ')
    : '미확인';
  const actualStr = actualEntries.length > 0
    ? actualEntries.map(([cur, amt]) => `${amt.toLocaleString()} ${cur}`).join(', ')
    : '0';
  return `<section class="pipeline-summary" aria-labelledby="summary-title">
    <div class="section-head">
      <h2 id="summary-title">수익 요약</h2>
      <span>${summary.totalRecords}건</span>
    </div>
    <div class="summary-grid">
      <div class="summary-card">
        <span class="summary-label">진행 중</span>
        <strong class="summary-value">${summary.activeCount}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">완료</span>
        <strong class="summary-value">${summary.completedCount}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">지급 완료</span>
        <strong class="summary-value">${summary.paidCount}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">예상 수익</span>
        <strong class="summary-value summary-value--expected">${escapeHtml(expectedStr)}</strong>
      </div>
      <div class="summary-card">
        <span class="summary-label">실제 지급</span>
        <strong class="summary-value summary-value--actual">${escapeHtml(actualStr)}</strong>
      </div>
    </div>
  </section>`;
}

function renderStatusFilter(filters: IncomePipelineFilterState): string {
  const options = INCOME_PIPELINE_STATUSES.map((s) => {
    const selected = filters.status === s ? 'selected' : '';
    return `<option value="${s}" ${selected}>${INCOME_PIPELINE_STATUS_LABELS[s]}</option>`;
  }).join('');
  return `<form class="filter-bar" method="GET" action="/pipeline" role="search" aria-label="파이프라인 필터">
    <label>상태 <select name="status">
      <option value="" ${filters.status === null ? 'selected' : ''}>전체</option>
      ${options}
    </select></label>
    <label>업체 <input type="search" name="vendor" value="${escapeHtml(filters.vendor ?? '')}" placeholder="업체명" /></label>
    <button type="submit">필터</button>
  </form>`;
}

function renderRecordCard(record: UserIncomeRecord): string {
  const statusLabel = INCOME_PIPELINE_STATUS_LABELS[record.status];
  const expectedStr = formatCurrencyAmount(record.expectedAmount, record.expectedCurrency);
  const actualStr = formatCurrencyAmount(record.actualAmount, record.actualCurrency);
  const detailHref = record.opportunityId ? `/detail?id=${escapeHtml(record.opportunityId)}` : null;
  return `<article class="pipeline-card" data-record-id="${escapeHtml(record.id)}">
    <div class="pipeline-card__topline">
      <span class="status-chip status-chip--${record.status.toLowerCase()}">${escapeHtml(statusLabel)}</span>
      <span class="freshness">${formatIncomeDate(record.updatedAt)}</span>
    </div>
    <h3 title="${escapeHtml(record.title)}">${escapeHtml(record.title)}</h3>
    <p class="pipeline-vendor">${escapeHtml(record.vendor)}</p>
    <div class="pipeline-amounts">
      <div class="pipeline-amount">
        <span class="amount-label">예상</span>
        <strong>${escapeHtml(expectedStr)}</strong>
      </div>
      <div class="pipeline-amount">
        <span class="amount-label">실제</span>
        <strong>${escapeHtml(actualStr)}</strong>
      </div>
    </div>
    <div class="pipeline-dates">
      ${record.appliedAt ? `<span>신청 ${formatIncomeDate(record.appliedAt)}</span>` : ''}
      ${record.acceptedAt ? `<span>선발 ${formatIncomeDate(record.acceptedAt)}</span>` : ''}
      ${record.completedAt ? `<span>완료 ${formatIncomeDate(record.completedAt)}</span>` : ''}
      ${record.paidAt ? `<span>지급 ${formatIncomeDate(record.paidAt)}</span>` : ''}
    </div>
    ${record.note ? `<p class="pipeline-note">${escapeHtml(record.note)}</p>` : ''}
    <div class="pipeline-actions">
      ${detailHref ? `<a class="detail-link" href="${detailHref}">기회 상세 보기 →</a>` : ''}
      ${record.sourceUrl ? `<a class="detail-link" href="${escapeHtml(record.sourceUrl)}" target="_blank" rel="noopener noreferrer nofollow">공식 페이지 ↗</a>` : ''}
      <form method="POST" action="/pipeline" style="display:inline">
        <input type="hidden" name="action" value="delete" />
        <input type="hidden" name="recordId" value="${escapeHtml(record.id)}" />
        <button type="submit" class="detail-link" style="background:none;border:none;cursor:pointer;padding:0">삭제</button>
      </form>
    </div>
  </article>`;
}

function renderAvailableOpportunities(opportunities: readonly PublicOpportunity[]): string {
  const displayable = opportunities.filter((opp) => isPublicOpportunityDisplayable(opp)).map(toPublicOpportunityCard);
  if (displayable.length === 0) return '';
  return `<section class="pipeline-available" aria-labelledby="available-title">
    <div class="section-head">
      <h2 id="available-title">추적 가능한 공개 기회</h2>
      <span>${displayable.length}개</span>
    </div>
    <p class="public-note">아래 기회를 파이프라인에 추가하여 진행 상황을 추적할 수 있습니다.</p>
    <div class="pipeline-available-list">
      ${displayable.map((card) => `<div class="pipeline-available-item">
        <span class="available-title">${escapeHtml(card.titleKo)}</span>
        <span class="available-vendor">${escapeHtml(card.vendor)}</span>
        <span class="available-tier">${escapeHtml(card.tierLabel)}</span>
      </div>`).join('\n')}
    </div>
  </section>`;
}

function renderShell(title: string, navItems: string, content: string): string {
  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark" />
  <title>내 수익 관리 | PADIEM AI Reward Router</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #06080d; --bg-soft: #0b0f16;
      --surface: rgba(255,255,255,.055); --surface-strong: rgba(255,255,255,.105);
      --line: rgba(255,255,255,.14); --line-soft: rgba(255,255,255,.09);
      --text: #f4f6fb; --muted: rgba(255,255,255,.68); --faint: rgba(255,255,255,.45);
      --accent: #88c9ff; --accent-strong: #5fb3ff; --accent-dim: rgba(136,201,255,.14);
      --gold: #efc984; --radius-card: 16px; --radius-btn: 10px;
      --pad: clamp(16px, 4vw, 64px);
      font-family: "SUIT Variable", "SUIT", "Pretendard", "Apple SD Gothic Neo", system-ui, sans-serif;
      font-synthesis: none; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; background: radial-gradient(1100px 480px at 50% -120px, rgba(136,201,255,.075), transparent 62%) var(--bg); color: var(--text); }
    a { color: inherit; text-decoration: none; }
    .shell { width: min(100%, 1200px); margin: 0 auto; padding: 0 var(--pad) 72px; }
    .topbar { position: sticky; top: 0; z-index: 10; margin: 0 calc(var(--pad) * -1); padding: 10px var(--pad) 8px; background: rgba(6,8,13,.78); backdrop-filter: blur(16px); border-bottom: 1px solid var(--line-soft); }
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
    .hero h1 { margin: 0; max-width: 720px; font-size: clamp(27px, 5.6vw, 56px); line-height: 1.06; letter-spacing: -.045em; font-weight: 640; text-wrap: balance; }
    .hero p { margin: 14px 0 0; max-width: 560px; color: var(--muted); font-size: 15px; line-height: 1.6; }
    .section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 20px 0 14px; flex-wrap: wrap; }
    .section-head h2 { margin: 0; font-size: 19px; letter-spacing: -.025em; font-weight: 650; }
    .section-head > span { display: inline-flex; align-items: center; min-height: 24px; padding: 0 10px; border-radius: 999px; background: var(--surface); border: 1px solid var(--line-soft); color: var(--muted); font-size: 12px; }
    .empty-state { display: grid; justify-items: center; padding: 44px 24px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03)); text-align: center; }
    .empty-state__mark { display: grid; place-items: center; width: 56px; height: 56px; border-radius: 50%; background: var(--accent-dim); border: 1px solid rgba(136,201,255,.22); color: var(--accent); }
    .empty-state__mark-svg { width: 28px; height: 28px; }
    .empty-state h3 { margin: 16px 0 8px; font-size: 17px; letter-spacing: -.02em; font-weight: 650; }
    .empty-state p { margin: 0; max-width: 380px; color: var(--muted); font-size: 14px; line-height: 1.6; }
    .filter-bar { display: grid; grid-template-columns: 1fr; gap: 10px; align-items: end; padding: 12px 0 2px; }
    .filter-bar label { display: flex; flex-direction: column; gap: 5px; font-size: 11px; color: var(--muted); font-weight: 600; letter-spacing: .04em; min-width: 0; }
    .filter-bar input, .filter-bar select { width: 100%; min-height: 44px; padding: 9px 12px; border-radius: var(--radius-btn); border: 1px solid var(--line-soft); background: var(--surface); color: var(--text); font-size: 14px; min-width: 0; }
    .filter-bar button { grid-column: 1 / -1; min-height: 46px; padding: 0 22px; border-radius: var(--radius-btn); border: 1px solid var(--accent); background: var(--accent); color: #06080d; font-size: 14px; font-weight: 700; cursor: pointer; }
    .summary-grid { display: grid; gap: 10px; grid-template-columns: repeat(2, 1fr); }
    .summary-card { padding: 16px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: var(--surface); }
    .summary-label { display: block; font-size: 11px; color: var(--faint); font-weight: 600; letter-spacing: .04em; margin-bottom: 6px; }
    .summary-value { font-size: 20px; font-weight: 700; letter-spacing: -.02em; color: var(--gold); }
    .summary-value--expected { font-size: 14px; }
    .summary-value--actual { font-size: 14px; color: var(--accent); }
    .pipeline-card { padding: 18px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: linear-gradient(180deg, rgba(255,255,255,.075), rgba(255,255,255,.045)); margin-bottom: 12px; }
    .pipeline-card__topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .pipeline-card h3 { margin: 10px 0 4px; font-size: 16px; line-height: 1.4; font-weight: 650; overflow-wrap: anywhere; }
    .pipeline-vendor { margin: 0 0 10px; color: var(--muted); font-size: 13px; }
    .status-chip { display: inline-flex; align-items: center; min-height: 24px; padding: 0 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }
    .status-chip--saved { background: var(--surface); color: var(--muted); border: 1px solid var(--line-soft); }
    .status-chip--applied { background: var(--accent-dim); color: var(--accent); border: 1px solid rgba(136,201,255,.25); }
    .status-chip--in_review, .status-chip--accepted, .status-chip--in_progress { background: rgba(239,201,132,.14); color: var(--gold); border: 1px solid rgba(239,201,132,.32); }
    .status-chip--completed { background: rgba(136,201,255,.14); color: var(--accent); border: 1px solid rgba(136,201,255,.25); }
    .status-chip--paid { background: rgba(100,220,130,.14); color: #64dc82; border: 1px solid rgba(100,220,130,.32); }
    .status-chip--rejected, .status-chip--expired, .status-chip--cancelled { background: rgba(255,100,100,.14); color: #ff6464; border: 1px solid rgba(255,100,100,.32); }
    .freshness { color: var(--faint); font-size: 11px; white-space: nowrap; }
    .pipeline-amounts { display: flex; gap: 16px; margin: 10px 0; }
    .pipeline-amount { display: flex; flex-direction: column; gap: 2px; }
    .amount-label { font-size: 11px; color: var(--faint); font-weight: 600; }
    .pipeline-amount strong { font-size: 14px; color: var(--gold); font-weight: 700; }
    .pipeline-dates { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 8px 0; color: var(--faint); font-size: 11.5px; }
    .pipeline-note { margin: 8px 0 0; color: var(--muted); font-size: 13px; line-height: 1.5; }
    .pipeline-actions { display: flex; gap: 12px; margin-top: 10px; flex-wrap: wrap; }
    .save-form { display: grid; gap: 10px; padding: 16px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: var(--surface); }
    .save-form label { display: flex; flex-direction: column; gap: 5px; font-size: 11px; color: var(--muted); font-weight: 600; letter-spacing: .04em; }
    .save-form input, .save-form select, .save-form textarea { width: 100%; min-height: 40px; padding: 8px 12px; border-radius: var(--radius-btn); border: 1px solid var(--line-soft); background: var(--bg-soft); color: var(--text); font-size: 14px; font-family: inherit; }
    .save-form button { min-height: 44px; padding: 0 22px; border-radius: var(--radius-btn); border: 1px solid var(--accent); background: var(--accent); color: #06080d; font-size: 14px; font-weight: 700; cursor: pointer; }
    .save-form button:hover { background: var(--accent-strong); }
    .detail-link { font-size: 13px; color: var(--accent); font-weight: 600; }
    .detail-link:hover { text-decoration: underline; }
    .pipeline-available { margin-top: 24px; }
    .pipeline-available-list { display: grid; gap: 8px; }
    .pipeline-available-item { display: flex; align-items: center; gap: 8px; padding: 10px 14px; border: 1px solid var(--line-soft); border-radius: 10px; background: var(--surface); font-size: 13px; }
    .available-title { flex: 1; font-weight: 600; overflow-wrap: anywhere; }
    .available-vendor { color: var(--muted); font-size: 12px; }
    .available-tier { font-size: 11px; color: var(--faint); }
    .public-note { margin: 0 0 12px; color: var(--faint); font-size: 12px; line-height: 1.55; }
    .footer-note { margin: 40px auto 0; max-width: 560px; color: var(--faint); font-size: 11.5px; line-height: 1.65; text-align: center; }
    @media (min-width: 680px) {
      .summary-grid { grid-template-columns: repeat(3, 1fr); }
    }
    @media (min-width: 1024px) {
      .summary-grid { grid-template-columns: repeat(5, 1fr); }
    }
    @media (max-width: 480px) {
      .summary-value { font-size: 16px; }
      .pipeline-amounts { flex-direction: column; gap: 8px; }
    }
  </style>
</head>
<body>
  <div class="shell" data-consumer-mode="INCOME_PIPELINE">
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="#top" aria-label="PADIEM AI Reward Router">
          ${renderBrandMark('brand-mark')}
          <span class="brand-wordmark">PADIEM</span>
          <span class="brand-divider" aria-hidden="true"></span>
          <span class="brand-product">AI Reward Router</span>
        </a>
        <span class="trust-note">내 수익 관리</span>
        <nav class="primary-nav" aria-label="주요 메뉴">${navItems}</nav>
      </div>
    </header>
    <main id="top">
      <section class="hero" aria-labelledby="hero-title">
        <p class="eyebrow">내 수익 관리</p>
        <h1 id="hero-title">${escapeHtml(title)}</h1>
        <p>저장한 기회와 진행 상황, 예상·실제 수익을 한곳에서 관리합니다.</p>
      </section>
      ${content}
      <p class="footer-note">수익·지급 정보는 사용자 직접 기록이며, 외부 업체의 신청·지급 상태를 대신하지 않습니다.</p>
    </main>
  </div>
</body>
</html>`;
}

export function buildIncomePipelineViewModel(input: {
  userId: string | null;
  records: readonly UserIncomeRecord[];
  filters?: { status?: IncomePipelineStatus | null; vendor?: string | null };
  availableOpportunities?: readonly PublicOpportunity[];
}): IncomePipelineViewModel {
  const filters: IncomePipelineFilterState = Object.freeze({
    status: input.filters?.status ?? null,
    vendor: input.filters?.vendor ?? null,
  });

  const filtered = filterUserIncomeRecords(input.records, { status: filters.status, vendor: filters.vendor });
  const sorted = sortUserIncomeRecords(filtered);
  const summary = input.userId ? buildUserIncomeSummary(input.records) : null;

  let emptyState: 'NO_USER' | 'NO_RECORDS' | null = null;
  if (!input.userId) emptyState = 'NO_USER';
  else if (input.records.length === 0) emptyState = 'NO_RECORDS';

  return Object.freeze({
    mode: 'INCOME_PIPELINE' as const,
    userId: input.userId,
    summary,
    records: Object.freeze([...input.records]),
    filteredRecords: sorted,
    filters,
    availableOpportunities: Object.freeze([...(input.availableOpportunities ?? [])]),
    emptyState,
    accountOnboardingVisibleToConsumer: false as const,
    laterTierNavigationVisible: false as const,
  });
}

export function renderIncomePipelineWeb(viewModel: IncomePipelineViewModel): string {
  const navItems = renderPrimaryNav('PIPELINE');

  if (viewModel.emptyState === 'NO_USER') {
    const content = renderEmptyState('로그인이 필요합니다. PADIEM 계정으로 로그인 후 이용해 주세요.');
    return renderShell('내 수익 관리', navItems, content);
  }

  const summaryHtml = viewModel.summary ? renderSummary(viewModel.summary) : '';
  const filterHtml = renderStatusFilter(viewModel.filters);

  const recordsHtml = viewModel.filteredRecords.length > 0
    ? viewModel.filteredRecords.map(renderRecordCard).join('\n')
    : renderEmptyState('아직 추적 중인 기회가 없습니다. 수익 기회에서 기회를 저장해 보세요.');

  const availableHtml = renderAvailableOpportunities(viewModel.availableOpportunities);

  const saveFormHtml = viewModel.userId ? `
    <section class="pipeline-save" aria-labelledby="save-title">
      <div class="section-head">
        <h2 id="save-title">기회 저장</h2>
      </div>
      <form method="POST" action="/pipeline" class="save-form">
        <input type="hidden" name="action" value="save" />
        <label>제목 <input type="text" name="title" required placeholder="기회 제목" /></label>
        <label>업체 <input type="text" name="vendor" required placeholder="업체명" /></label>
        <label>상태 <select name="status">
          ${INCOME_PIPELINE_STATUSES.map((s) => `<option value="${s}">${INCOME_PIPELINE_STATUS_LABELS[s]}</option>`).join('')}
        </select></label>
        <label>예상 금액 <input type="number" name="expectedAmount" min="0" step="any" placeholder="예상 수익" /></label>
        <label>통화 <select name="expectedCurrency">
          <option value="">미확인</option>
          <option value="KRW">KRW</option>
          <option value="USD">USD</option>
          <option value="EUR">EUR</option>
          <option value="GBP">GBP</option>
        </select></label>
        <label>메모 <textarea name="note" rows="2" placeholder="메모"></textarea></label>
        <button type="submit">저장</button>
      </form>
    </section>` : '';

  const content = `
    ${summaryHtml}
    ${filterHtml}
    <section class="pipeline-records" aria-labelledby="records-title">
      <div class="section-head">
        <h2 id="records-title">진행 중인 기회</h2>
        <span>${viewModel.filteredRecords.length}건</span>
      </div>
      ${recordsHtml}
    </section>
    ${saveFormHtml}
    ${availableHtml}`;

  return renderShell('내 수익 관리', navItems, content);
}
