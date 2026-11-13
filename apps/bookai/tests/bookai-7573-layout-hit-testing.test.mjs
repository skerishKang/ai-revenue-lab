/* #7573 · 페이지 버튼이 종이 애니메이션에 가려지지 않고, 장식 층이 클릭을 받지 않는다.
   #7574 · 새 사용자의 '다시 떠올릴 기억' 숫자가 예시 개체 기억을 세지 않는다.

   이 파일은 브라우저 없이 도는 계약 시험이다. 실제 좌표 클릭과 히트 테스트는
   같은 이름의 .browser.cjs 가 맡는다(브라우저 QA 레인 전용). */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../public/styles/bookai-7573-layout-v1.css', import.meta.url), 'utf8');
const html = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8');

const rules = css.replace(/\s+/g, ' ');

test('장식 층(종이 더미·밑장)은 클릭을 받지 않는다', () => {
  assert.match(rules, /#paperStack\{pointer-events:none\}/,
    '종이 묶음 상자는 클릭을 통과시켜야 한다');
  assert.match(rules, /#paperStack \.under-sheet\{pointer-events:none\}/,
    '밑장 장식은 클릭을 받지 않아야 한다');
  assert.match(rules, /#paperStack>:is\(#paper,\.turn-zone,\.page-turn-btn,\.reading-progress-edge\)\{pointer-events:auto\}/,
    '본문·넘김 영역·페이지 버튼·진행 표시는 스스로 클릭을 받아야 한다');
});

test('페이지 버튼은 장식 층 앞에 있다', () => {
  assert.match(rules, /#reader \.page-turn-btn\{translate:0 0 1px\}/,
    '버튼이 종이와 같은 깊이에 있으면 클릭이 종이로 간다');
  assert.match(rules, /#reader \.page-turn-btn\{z-index:33\}/,
    '버튼은 보이지 않는 넘김 영역(z-index 25)보다 위에 있어야 한다');
});

test('종이의 상시 움직임은 그대로 두고 버튼만 앞에 세운다', () => {
  assert.doesNotMatch(rules, /\.paper-stack\{animation:none/,
    '종이 묶음의 상시 움직임 자체를 없애면 안 된다');
  assert.match(rules, /#reader \.page-turn-btn\{translate:0 0 1px\}/,
    '버튼이 종이와 같은 깊이에 있으면 클릭이 종이로 간다');
});

test('움직임 줄이기에서는 상시 애니메이션이 멈춘다', () => {
  const product = readFileSync(new URL('../public/styles/storymemory-product-v30-v319.css', import.meta.url), 'utf8')
    .replace(/\s+/g, ' ');
  assert.match(product, /@media\(prefers-reduced-motion:reduce\)\{ #reader\.active:not\(\.paper-enter\) \.paper-stack, #reader\.active:not\(\.paper-enter\) \.under1, #reader\.active:not\(\.paper-enter\) \.under2,/,
    '움직임 줄이기에서 상시 애니메이션이 멈추지 않는다');
});

test('오늘 화면 집계는 예시 개체 기억을 세지 않는다', () => {
  const body = html.match(/function todayRecallItems\(\)\{[\s\S]*?\n\}/);
  assert.ok(body, 'todayRecallItems 를 찾지 못했다');
  const fn = new Function('buildRecallQueue', 'recallItemState', body[0] + '\nreturn todayRecallItems;');
  const due = {
    'memory:1': { nextDue: 0 },
    'annotation:2': { nextDue: 0 },
    'entity:ctx:바울': { nextDue: 0 },
    'memory:3': { nextDue: Date.now() + 86400000 },
  };
  const queue = [
    { id: 'memory:1', kind: 'note' },
    { id: 'annotation:2', kind: 'annotation' },
    { id: 'entity:ctx:바울', kind: 'entity' },
    { id: 'memory:3', kind: 'note' },
  ];
  const items = fn(() => queue, (id) => due[id] || {})();
  assert.deepEqual(items.map((i) => i.id), ['memory:1', 'annotation:2'],
    '사용자가 남긴 기억만, 복습 시점이 된 것만 세야 한다');
});
