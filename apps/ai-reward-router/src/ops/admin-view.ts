import type { B64OperationsSnapshot } from './operations-snapshot.js';
import type { B64Theme } from '../ui/theme.js';
import { THEME_CSS_VARIABLES } from '../ui/theme.js';

/**
 * The operator's read-only view of what B64 is actually doing (issue #6001).
 *
 * It reports state; it changes none. The existing `src/admin-console/` module is
 * an opportunity review workflow with its own fixture state and mutation
 * commands, and pointing it at production would mean building that whole write
 * surface for no part of this task — so this view reuses what is genuinely
 * shared instead: the same provider assessment the `supply:check` CLI prints,
 * the same theme tokens the consumer screens use, and counts read straight from
 * B64's own tables.
 *
 * No address, token, secret or value appears here. Environment variables are
 * named, never shown.
 */

function escapeHtml(value: string | number): string {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function row(label: string, value: string | number): string {
  return `<tr><th scope="row">${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`;
}

const PROVIDER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  AYET: 'ayeT (Rewarded Video)',
  ADSCEND: 'Adscend',
  TREMENDOUS: 'Tremendous',
});

export function renderB64AdminConsole(snapshot: B64OperationsSnapshot, theme: B64Theme): string {
  const providerRows = Object.values(snapshot.providerAssessment.providers)
    .map((provider) => `<tr>
        <th scope="row">${escapeHtml(PROVIDER_LABELS[provider.provider] ?? provider.provider)}</th>
        <td>${escapeHtml(provider.mode)}</td>
        <td>${provider.readyForServerInitialization ? '준비' : '미준비'}</td>
        <td>${provider.missingEnvironmentNames.length === 0
    ? '없음'
    : escapeHtml(provider.missingEnvironmentNames.join(', '))}</td>
      </tr>`)
    .join('\n      ');

  return `<!doctype html>
<html lang="ko" data-theme="${theme}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="${theme}" />
  <title>B64 운영 상태 · 관리자</title>
  <style>
${THEME_CSS_VARIABLES}
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg-glow) var(--bg); color: var(--text); }
    main { width: min(100%, 880px); margin: 0 auto; padding: 32px 20px 72px; }
    h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -.02em; }
    .note { margin: 0 0 24px; color: var(--muted); font-size: 13px; }
    section { margin-top: 28px; }
    h2 { margin: 0 0 10px; font-size: 15px; letter-spacing: .02em; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--line-soft); text-align: left; }
    table th[scope="row"] { font-weight: 600; color: var(--muted); width: 46%; }
    td { font-variant-numeric: tabular-nums; }
    .card { padding: 16px 18px; border: 1px solid var(--line-soft); border-radius: var(--radius-card); background: var(--surface); }
    code { font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; font-size: 12.5px; }
  </style>
</head>
<body>
  <main>
    <h1>B64 운영 상태</h1>
    <p class="note">읽기 전용 관리자 화면입니다. 이 화면은 상태를 표시하며 어떤 것도 변경하지 않습니다. 생성 시각 ${escapeHtml(snapshot.generatedAt)}.</p>

    <section class="card">
      <h2>저장소</h2>
      <table>
        ${row('D1 연결', snapshot.storageConnected ? '연결됨' : '미연결 (운영 데이터 없음)')}
        ${row('B64 회원', snapshot.members)}
        ${row('Google 연결 회원', snapshot.googleLinkedMembers)}
        ${row('유효 세션', snapshot.liveSessions)}
        ${row('수익 기록', snapshot.incomeRecords)}
      </table>
    </section>

    <section class="card">
      <h2>ayeT 리워드 이벤트</h2>
      <table>
        ${row('전체', snapshot.rewardEvents.total)}
        ${row('공급사 확정 대기', snapshot.rewardEvents.pending)}
        ${row('확정', snapshot.rewardEvents.confirmed)}
        ${row('취소', snapshot.rewardEvents.reversed)}
      </table>
      <p class="note">확정 상태는 공급사 보고이며 지급 확정이 아닙니다. 지급 가능 잔액은 이 테이블에서 계산되지 않습니다.</p>
    </section>

    <section class="card">
      <h2>광고 공급사 설정</h2>
      <table>
        <thead><tr><th scope="col">공급사</th><th scope="col">모드</th><th scope="col">서버 초기화</th><th scope="col">누락 설정</th></tr></thead>
        <tbody>
      ${providerRows}
        </tbody>
      </table>
      <p class="note">${snapshot.providerAssessment.allDisabled
    ? '모든 공급사가 비활성입니다. 소비자 화면에는 실제 재고 없는 리워드가 표시되지 않습니다.'
    : '활성화된 공급사가 있습니다. 공급사 승인 근거와 함께 확인해야 합니다.'} 설정값은 이름만 표시하며 값은 표시하지 않습니다.</p>
    </section>
  </main>
</body>
</html>
`;
}
