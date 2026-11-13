import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

// #7573 읽기 화면 이동 레인 — 창/브라우저 없이 확인할 수 있는 순수 규칙:
// - 장 순서와 장 수는 index.html 의 기존 자료(VOLUMES·VOLUME_CHAPTERS)에서 읽는다.
//   여기서는 그 자료를 고의로 바꿔 주입해 모듈이 손으로 만든 목록을 쓰지 않음을 확인한다.
// - 다음 장: 같은 책 다음 장 → 책의 마지막 장이면 다음 책 1장 → 요한계시록 끝이면 없음(멈춤).
// - 이전 장: 같은 책 이전 장 → 1장이면 이전 책의 마지막 장 → 창세기 1장이면 없음(멈춤).

const source = fs.readFileSync(
  path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'bookai-7573-navigation-v1.js'),
  'utf8',
);

function loadModule(globals) {
  const context = {
    console,
    setTimeout,
    clearTimeout,
    document: { addEventListener() {}, getElementById: () => null, querySelector: () => null },
    window: {},
    ...globals,
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: 'bookai-7573-navigation-v1.js' });
  return context;
}

const BASE_DATA = {
  VOLUMES: ['창세기', '시편', '말라기', '마태복음', '요한계시록'],
  VOLUME_CHAPTERS: { 창세기: 50, 시편: 150, 말라기: 4, 마태복음: 28, 요한계시록: 22 },
};

function loadWith(data = BASE_DATA) {
  return loadModule({ ...data, __smCurrentReaderKind: 'bible', __smCurrentReaderLabel: '고린도전서 3장' });
}

test('the module exposes its pure chapter-order helpers', () => {
  const ctx = loadWith();
  const api = ctx.window.BookAI7573NavigationV1;
  assert.ok(api, 'BookAI7573NavigationV1 must be exported');
  assert.equal(typeof api.nextChapterAfter, 'function');
  assert.equal(typeof api.prevChapterBefore, 'function');
  assert.equal(typeof api.currentBibleContext, 'function');
});

test('next chapter continues inside the book', () => {
  const api = loadWith().window.BookAI7573NavigationV1;
  assert.deepEqual({...api.nextChapterAfter('말라기', 2)}, { volume: '말라기', chapter: 3 });
  assert.deepEqual({...api.nextChapterAfter('시편', 149)}, { volume: '시편', chapter: 150 });
});

test('next chapter crosses into the next book at chapter 1', () => {
  const api = loadWith().window.BookAI7573NavigationV1;
  assert.deepEqual({...api.nextChapterAfter('말라기', 4)}, { volume: '마태복음', chapter: 1 });
  assert.deepEqual({...api.nextChapterAfter('시편', 150)}, { volume: '말라기', chapter: 1 });
});

test('next chapter stops at the end of 요한계시록 22장', () => {
  const api = loadWith().window.BookAI7573NavigationV1;
  assert.equal(api.nextChapterAfter('요한계시록', 22), null);
});

test('previous chapter continues inside the book and lands on its last chapter', () => {
  const api = loadWith().window.BookAI7573NavigationV1;
  assert.deepEqual({...api.prevChapterBefore('마태복음', 1)}, { volume: '말라기', chapter: 4 });
  assert.deepEqual({...api.prevChapterBefore('시편', 1)}, { volume: '창세기', chapter: 50 });
  assert.deepEqual({...api.prevChapterBefore('시편', 5)}, { volume: '시편', chapter: 4 });
});

test('previous chapter stops at 창세기 1장', () => {
  const api = loadWith().window.BookAI7573NavigationV1;
  assert.equal(api.prevChapterBefore('창세기', 1), null);
});

test('the helpers read the existing order data instead of a hand-made list', () => {
  // 요한계시록을 자료에서 빼 버리면 그 뒤는 끝이 된다 — 목록을 모듈이 갖고 있지 않다는 증거.
  const api = loadWith({
    VOLUMES: ['창세기', '말라기'],
    VOLUME_CHAPTERS: { 창세기: 50, 말라기: 4 },
  }).window.BookAI7573NavigationV1;
  assert.equal(api.nextChapterAfter('말라기', 4), null);
  assert.deepEqual({...api.nextChapterAfter('말라기', 3)}, { volume: '말라기', chapter: 4 });
});

test('the current context is parsed from the existing reader label', () => {
  const ctx = loadModule({
    ...BASE_DATA,
    __smCurrentReaderKind: 'bible',
    __smCurrentReaderLabel: '시편 150장',
  });
  const api = ctx.window.BookAI7573NavigationV1;
  assert.deepEqual({...api.currentBibleContext()}, { volume: '시편', chapter: 150, count: 150, index: 1 });

  const nonBible = loadModule({
    ...BASE_DATA,
    __smCurrentReaderKind: 'book',
    __smCurrentReaderLabel: '일리아스',
  });
  assert.equal(nonBible.window.BookAI7573NavigationV1.currentBibleContext(), null);
});

test('a chapter outside the known counts is not treated as a bible context', () => {
  const ctx = loadModule({
    ...BASE_DATA,
    __smCurrentReaderKind: 'bible',
    __smCurrentReaderLabel: '시편 151장',
  });
  assert.equal(ctx.window.BookAI7573NavigationV1.currentBibleContext(), null);
});
