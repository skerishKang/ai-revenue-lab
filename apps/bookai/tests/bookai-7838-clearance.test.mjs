// #7838: 넓은 화면 AI 판이 본문을 가리지 않게 한 배치 규칙과, 390 첫 화면의
// 떠 있는 단추 영역 여백 변수가 실제로 배포 파일에 있는지 정적으로 확인한다.
// 숫자 실측(겹침 0·scrollWidth≤clientWidth)은 브라우저 실측 기록으로 보고한다.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(appRoot, 'public');
const read = (...parts) => fs.readFileSync(path.join(publicRoot, ...parts), 'utf8');

test('#7838·#8781 첫 화면 여백: 떠 있는 의견 단추 제거 뒤 통계 양옆 16px', () => {
  const css = read('styles', 'bookai-7838-clearance-v1.css');
  assert.doesNotMatch(css,/--sm-corner-fab-zone/,'제거된 떠 있는 단추의 예약폭을 남기지 않는다');
  assert.match(
    css,
    /@media\(max-width:768px\)\s*\{[\s\S]*?#library \.library-order-control\{right:16px\}/,
    '768 이하 통계 줄은 오른쪽 16px를 지킨다',
  );
  // 이 파일은 기존 규칙을 뒤집지 않는다 — 새 !important 없음
  assert.ok(!css.includes('!important'), '새 파일에 !important를 추가하지 않는다');
  // 배포 파일로 실제로 읽힌다 — 유리 테마(마지막 시트) 다음 줄
  const html = read('index.html');
  const glassAt = html.indexOf('bookai-glass-theme-v1.css');
  const clearanceAt = html.indexOf('bookai-7838-clearance-v1.css');
  assert.ok(glassAt >= 0 && clearanceAt > glassAt, '여백 시트는 유리 테마 다음(마지막)에 읽혀야 한다');
});

test('#7838 1280 이상: AI 판이 열리면 본문 무리가 유리판 폭만큼 줄어든다', () => {
  const css = read('styles', 'storymemory-b61-floating-glass-v1.css');
  // 세로 칸은 공유 변수 --sm-ai-col을 따르고, 열린 상태에서 유리판 실제 폭
  // (clamp 식) + 오른쪽 12px + 틈 12px를 변수로 채운다 — 새 !important 없음
  assert.match(
    css,
    /\.reader-layout\{grid-template-columns:44px minmax\(0,1fr\) var\(--sm-ai-col,44px\)!important\}/,
    '1280 이상 격자 세로 칸이 --sm-ai-col 변수를 따라야 한다',
  );
  assert.match(
    css,
    /body\.ai-open \.reader-layout\{--sm-ai-col:calc\(clamp\(320px,calc\(50vw - 482px\),400px\) \+ 24px\)\}/,
    '열린 상태 변수값이 유리판 폭+24px이어야 하고 !important가 없어야 한다',
  );
  assert.match(css, /body\.focus-reading \.reader-layout\{grid-template-columns:0 minmax\(0,1fr\) 0!important\}/,
    '집중 읽기는 그대로 전 폭이어야 한다');
  // 이 파일에서 #7838이 새로 !important를 붙이지 않았다 — 변수 규칙은 맨 값만 있다
  assert.ok(!/--sm-ai-col:[^}]*!important/.test(css), '--sm-ai-col 규칙에 !important를 붙이지 않는다');
});

test('#7838 769-1024: 원인 규칙이 !important를 내려놓아 시트 계약이 다시 이긴다', () => {
  const typo = read('styles', 'storymemory-b61-typography-authority-v1.css');
  // 원인: body.ai-open .reader-layout>.ai-panel{position:relative!important;width:auto!important}
  // 가 (0,3,1)로 1024 시트 계약(0,2,0)을 이겼다 — 이제 !important가 없어야 한다.
  const inFlowRule = typo.match(/body\.ai-open \.reader-layout>\.ai-panel\{[^}]*\}/);
  assert.ok(inFlowRule, '769 이상 안쪽 흐름 판 규칙이 있어야 한다');
  assert.ok(!inFlowRule[0].includes('!important'), '원인 규칙에 !important가 남으면 안 된다');
  assert.match(inFlowRule[0], /position:relative/, '1025-1279 안쪽 흐름 계약은 유지된다');

  const sheet = read('styles', 'bookai-7573-layout-v1.css');
  // 시트 계약은 기존 !important를 그대로 쓰고, 세로 칸은 공유 변수로 예약한다
  assert.match(
    sheet,
    /\.reader-layout\{grid-template-columns:44px minmax\(0,1fr\) var\(--sm-ai-col,44px\)!important\}/,
    '769-1024 격자 세로 칸이 --sm-ai-col 변수를 따라야 한다',
  );
  assert.match(
    sheet,
    /body\.ai-open \.reader-layout\{--sm-ai-col:min\(360px,88vw\)\}/,
    '열린 상태 변수값이 시트 폭 min(360px,88vw)이어야 하고 !important가 없어야 한다',
  );
  assert.ok(!/--sm-ai-col:[^}]*!important/.test(sheet), '--sm-ai-col 규칙에 !important를 붙이지 않는다');
  // 시트 폭과 예약 폭이 같아야 겹침이 0이다
  const sheetWidth = sheet.match(/\.reader-layout>\.ai-panel\{[\s\S]*?width:min\(360px,88vw\)!important/);
  assert.ok(sheetWidth, '시트 폭 규칙(기존 계약)이 있어야 한다');
});

test('#7838 판 안 위쪽 빈 공간: 안내 블록이 가운데가 아니라 위에서부터 이어진다', () => {
  const css = read('styles', 'storymemory-b61-typography-authority-v1.css');
  // 769 이상 규칙: margin:auto 0 수직 중앙정렬이 빈 공간의 원인이었다
  const desktopBlock = css.slice(css.indexOf('B61 #1684 CENTRAL v2'), css.indexOf('@media (max-width:768px)'));
  assert.ok(desktopBlock.includes('.companion-empty-state{'), '769 이상 안내 블록 규칙이 있어야 한다');
  assert.ok(!/margin:auto 0/.test(desktopBlock), '판 안내 블록을 세로 가운데로 밀지 않는다');
  assert.match(desktopBlock, /min-height:min\(330px,46vh\);padding:18px 2px 20px;margin:0;/,
    '안내 블록은 위에서부터 이어진다');
});
