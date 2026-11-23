/* #7837 — 출처 줄은 기본이 짧은 한국어 표기이고 상세(구절 코드·영역본 이름·영어)는
   펼칠 때만 보인다. 읽기 설정 이름·설명, 첫 화면 작은 글씨 하한을 고정한다.
   글자 크기는 브라우저 실측이 아니라 CSS에 적힌 선언만 확인한다. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const read = (name) => readFileSync(new URL('../public/' + name, import.meta.url), 'utf8');
const html = read('index.html');
const settingsJs = read('storymemory-reader-settings-v1.js');
const settingsCss = read('styles/storymemory-reader-settings-v1.css');
const firstscreenCss = read('styles/storymemory-b61-library-firstscreen-v1.css');
const interactionCss = read('styles/storymemory-interaction-v28-v282.css');
const memoryCss = read('styles/storymemory-memory-v29-v298.css');
const overridesCss = read('styles/storymemory-b61-overrides-v1.css');

const definition = html.match(/function storyMemorySourceNoteMarkup\(\{[\s\S]*?\n\}\n/);
assert.ok(definition, '출처 줄 렌더러 storyMemorySourceNoteMarkup 이 없다');
const noteMarkup = new Function('escapeHtml', definition[0] + '\nreturn storyMemorySourceNoteMarkup;')(
  (value) => String(value).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));

const bibleNote = noteMarkup({
  range: 'GEN 1:1 → GEN 1:5',
  lang: '한국어 KRV-1961 · 영어 WEB (World English Bible) · 출처 표기 KRV-1961 / eBible ENGWEBP',
  isStaticBible: true,
  hasKo: true,
});
const summaryOf = (markup) => markup.slice(0, markup.indexOf('</summary>')).replace(/<[^>]+>/g, '').trim();
const detailOf = (markup) => markup.slice(markup.indexOf('</summary>')).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

test('출처 줄은 기본으로 짧은 한국어 표기만 보인다', () => {
  assert.match(bibleNote, /<details class="sm-source-detail">/);
  assert.match(bibleNote, /<div class="sm-source-full">/);
  assert.equal(summaryOf(bibleNote), '개역한글(1961)출처 자세히');
  assert.doesNotMatch(summaryOf(bibleNote), /[A-Za-z]/, '기본 상태에 로마자가 남았다');
});

test('펼친 안에는 구절 코드와 영역본 이름이 원래 표기로 있다', () => {
  const detail = detailOf(bibleNote);
  assert.match(detail, /GEN 1:1 → GEN 1:5/);
  assert.match(detail, /한국어 KRV-1961/);
  assert.match(detail, /영어 WEB \(World English Bible\)/);
  assert.match(detail, /출처 표기 KRV-1961 \/ eBible ENGWEBP/);
});

test('출처 줄 두 렌더러가 같은 렌더러를 쓴다', () => {
  const uses = html.match(/storyMemorySourceNoteMarkup\(\{/g) || [];
  assert.ok(uses.length >= 3, '정의 1 + 사용 2곳(동적 페이지·접힘 페이지)이어야 한다: ' + uses.length);
  assert.doesNotMatch(html, /<b>번역본 · 출처<\/b>\$\{escapeHtml/);
});

test('영어 본문만 있는 자료와 한국어 자료도 한국어 표기를 쓴다', () => {
  const englishOnly = noteMarkup({ range: 'WEB 1:1', lang: '영어 원문', isStaticBible: false, hasKo: false });
  assert.match(summaryOf(englishOnly), /^영어 원문/);
  assert.doesNotMatch(summaryOf(englishOnly), /[A-Za-z]/);
  const korean = noteMarkup({ range: 'p.1', lang: '한국어 본문 · 원문 연결', isStaticBible: false, hasKo: true });
  assert.match(summaryOf(korean), /^한국어 본문/);
});

test('읽기 설정 이름이 쉬운 한국어이고 어려운 항목에 설명이 붙는다', () => {
  assert.match(settingsJs, /segRow\('영어 함께 보기','englishMode'\)/);
  assert.doesNotMatch(settingsJs, /'번역본 표시'/);
  assert.match(settingsJs, /segRow\('줄 간격','lineHeight'\)/);
  assert.match(settingsJs, /본문 줄 사이를 넓게 또는 좁게 조절합니다\./);
  assert.match(settingsJs, /본문 아래에 영어 원문을 함께 보여 줍니다\. 기본은 한글만이라 영어를 숨깁니다\./);
  assert.match(settingsCss, /\.srsg-desc\{/);
  assert.match(settingsJs, /englishMode:\[\['show','한영 함께'\],\['compact','영어 작게'\],\['hide','한글만'\]\]/,
    '기본값 동작(한글만)과 선택지는 그대로여야 한다');
});

test('읽기 방식 두 항목에 실제 차이를 적은 설명이 붙는다', () => {
  assert.match(settingsJs, /'찾아보며 읽기','어느 장이든 먼저 펼쳐 볼 수 있고, AI도 전체 내용을 참고합니다\.'/);
  assert.match(settingsJs, /'처음 읽어요','읽은 곳까지만 넘기고, AI는 아직 안 읽은 내용을 접어 둡니다\.'/);
  assert.match(settingsJs, /b\.append\(lb,nt\)/, '항목 이름과 설명이 버튼 안에 함께 있어야 한다');
  assert.match(settingsCss, /\.srsg-opt-note\{/);
});

function fontSize(css, selector) {
  let index = -1;
  while ((index = css.indexOf(selector + '{', index + 1)) >= 0) {
    const body = css.slice(index + selector.length + 1, css.indexOf('}', index));
    const declared = body.match(/font(?:-size)?:([^;}]*)/);
    const px = declared && declared[1].match(/(\d+(?:\.\d+)?)px/);
    if (px) return Number(px[1]);
  }
  assert.fail(selector + ' 규칙에서 글자 크기를 찾지 못했다');
}

test('첫 화면 칩·부제는 390에서 12px 이상, 1440에서 13px 이상이다', () => {
  assert.ok(fontSize(overridesCss, '.today-entry') >= 13, '데스크톱 칩');
  assert.ok(fontSize(overridesCss, '.today-entry b') >= 12, '칩 숫자');
  assert.ok(fontSize(memoryCss, '.today-entry span') >= 12, '390 칩');
  assert.ok(fontSize(firstscreenCss, '#library .lib-head .kicker') >= 13, '데스크톱 부제');
  assert.ok(fontSize(interactionCss, '.lib-head .kicker') >= 12, '390 부제');
});

/* #6476 — 어두운 테마에서 출처 줄 글자 대비가 4.5:1 이상인지 선언값으로 확인한다.
   배경은 어두운 테마의 읽기 종이(.reader-page-note)색이다. */
const contrastOn = (color, background) => {
  const luminance = (hex) => {
    const [r, g, b] = hex.replace('#', '').match(/../g).map((h) => parseInt(h, 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [hi, lo] = [luminance(color), luminance(background)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
};
const darkSourceColor = (suffix) => {
  const rule = html.match(new RegExp(
    'body\\.smr-theme-dark \\.sm-verified-source-note ' + suffix + '\\{([^}]*)\\}'));
  assert.ok(rule, '어두운 테마 출처 줄 규칙이 없다: ' + suffix);
  const color = rule[1].match(/color:\s*(#[0-9a-fA-F]{6})/);
  assert.ok(color, '규칙에 색이 없다: ' + suffix);
  return color[1].toLowerCase();
};

test('어두운 테마 출처 줄은 종이 위에서 4.5:1 이상이다', () => {
  const paper = '#2e2820';
  const parts = {
    요약: darkSourceColor('\\.sm-source-detail summary'),
    마커: darkSourceColor('\\.sm-source-detail summary::after'),
    자세히: darkSourceColor('\\.sm-source-more'),
    상세: darkSourceColor('\\.sm-source-full'),
    상세제목: darkSourceColor('\\.sm-source-full b'),
  };
  for (const [name, color] of Object.entries(parts)) {
    const ratio = contrastOn(color, paper);
    assert.ok(ratio >= 4.5, `${name} 대비 ${ratio.toFixed(2)}:1 — ${color} on ${paper}`);
  }
  assert.ok(contrastOn('#8a7c6d', paper) < 4.5, '고치기 전 색은 기준 미만이어야 의미가 있다');
});

test('밝은 테마 출처 줄 색은 바꾸지 않았다', () => {
  assert.match(html, /\.sm-source-detail summary\{[^}]*color:#8a7c6d\}/);
  assert.match(html, /\.sm-source-more\{[^}]*color:#a06b4d\}/);
  assert.match(html, /\.sm-source-full\{[^}]*color:#8a7c6d[;}]/);
  assert.doesNotMatch(html, /smr-theme-light[^}]*\.sm-verified-source-note/,
    '밝은 테마에는 출처 줄 전용 색을 더하지 않는다');
});

test('출처 줄 기본 글자도 390에서 12px 이상, 1440에서 13px 이상이다', () => {
  assert.ok(fontSize(html, '.sm-verified-source-note') >= 12);
  assert.ok(fontSize(html, '.sm-source-detail summary') >= 12);
  assert.match(html, /@media\(min-width:721px\)\{\s*\.sm-verified-source-note,\.sm-source-detail summary\{font-size:13px\}/);
});
