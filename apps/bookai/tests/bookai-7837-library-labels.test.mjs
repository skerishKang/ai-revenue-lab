/* #7837 — 라이브러리 설정 창의 영어 대문자 라벨과 배수 표시를 쉬운 한국어로.
   보이는 글자만 바꾼다: 배수(range 값·저장 키·애니메이션 길이)와 정렬 키는 그대로다. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');
const firstscreen = readFileSync(
  new URL('../public/storymemory-b61-library-firstscreen-v1.js', import.meta.url), 'utf8');
const libraryUi = readFileSync(
  new URL('../public/storymemory-library-ui-v1.js', import.meta.url), 'utf8');
const memoryUi = readFileSync(
  new URL('../public/storymemory-memory-ui-v1.js', import.meta.url), 'utf8');

function labelOf(name) {
  // #8781: 네 줄 메뉴 통일 후 실제 단추 라벨을 검사한다.
  const match=name==='motionLabel'
    ? firstscreen.match(/motionText\.textContent='([^']+)'/)
    : html.match(/<span class="sm-menu-label">([^<]+)<\/span>/);
  assert.ok(match, name + ' 라벨을 찾지 못했다');
  return match[1];
}

test('라이브러리 설정 창 라벨은 쉬운 한국어다', () => {
  assert.equal(labelOf('motionLabel'), '책 넘김 속도');
  assert.equal(labelOf('orderLabel'), '책장 순서');
});

test('설정 창 라벨에 영어 대문자 낱말이 남지 않는다', () => {
  for (const label of [labelOf('motionLabel'), labelOf('orderLabel')]) {
    assert.doesNotMatch(label, /[A-Za-z]/, label);
  }
  assert.doesNotMatch(firstscreen, /'BOOK MOTION'|'SHELF ORDER'/);
});

test('책 넘김 속도 값은 배수가 아니라 쉬운 말로 보인다', () => {
  const source = html.match(/function __smMotionWord\(factor\)\{([\s\S]*?)\n\}/);
  assert.ok(source, '__smMotionWord 가 없다');
  const word = new Function('factor', source[1]);
  assert.equal(word(0.65), '빠르게');
  assert.equal(word(0.9), '보통');
  assert.equal(word(1), '보통');
  assert.equal(word(1.35), '느리게');
  assert.match(html, /const value=__smMotionWord\(__smMotionFactor\);/);
  assert.doesNotMatch(html, /const value=__smMotionFactor\.toFixed\(2\)/);
  assert.match(html, /<b id="motionValue">보통<\/b>/);
  assert.match(html, /<b id="motionValueDetail">보통<\/b>/);
});

test('배수와 정렬 키는 그대로다', () => {
  assert.match(html, /id="motionRange" type="range" min="0\.65" max="1\.35" step="0\.05" value="1"/);
  assert.match(html, /storymemory\.motionFactor/);
  assert.match(html, /function __smMotionDuration\(ms\)\{return Math\.round\(ms\*__smMotionFactor\)\}/);
  assert.match(html, /storymemory\.libraryOrder\.v1/);
  assert.match(html, /정렬 · <b>최근순<\/b>/);
  assert.match(html, /정렬 · <b>서가순<\/b>/);
});

test('#6476 사용자에게 보이는 SM·AI 약호는 한국어로 바뀐다', () => {
  assert.doesNotMatch(html, />SM</, '서가 표지·모티프에 SM 이 남았다');
  assert.doesNotMatch(html, /textContent='SM'/);
  assert.doesNotMatch(libraryUi, />SM</, '책 뒤표지·장 표식에 SM 이 남았다');
  assert.match(libraryUi, /class="back-monogram">기억</);
  assert.match(libraryUi, /class="paper-seal">기억</);
  assert.match(html, /<button data-mobile="ai">AI 질문<\/button>/, '하단 탭은 하는 일이 보여야 한다');
  assert.match(html, /<strong class="ai-t-desk">AI 질문<\/strong>/);
  assert.match(html, /<strong class="ai-t-mob">AI 질문<\/strong>/);
  assert.match(html, /<button class="pill" data-memory-filter="ai">AI 질문<\/button>/);
  assert.match(html, /kind:m\.kind==='ai'\?'AI 질문':'NOTE'/);
  assert.match(memoryUi, /<i title="AI 질문">/);
});

test('#6476 보이는 글자만 바꾸고 내부 이름은 그대로다', () => {
  assert.match(html, /data-mobile="ai"/);
  assert.match(html, /data-memory-filter="ai"/);
  assert.match(html, /class="ai-t-desk"/);
  assert.match(html, /class="ai-t-mob"/);
  assert.match(html, /motif motif-personal/);
  assert.match(html, /id="askInput"/);
  assert.match(libraryUi, /back-monogram/);
  assert.match(libraryUi, /paper-seal/);
});

test('첫 화면 숫자 옆에 무엇을 세는지 적혀 있다', () => {
  assert.match(html,
    /<button class="today-entry" id="todayEntry" type="button"><span>오늘 떠올릴 기억<\/span><b id="todayEntryCount">0<\/b><\/button>/);
  assert.match(libraryUi, /todayEntryCount'\)\.textContent=String\(due\.length\)/,
    '숫자는 복습 예정 기억 수(due)를 센다');
});
