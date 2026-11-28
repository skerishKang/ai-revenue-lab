// #8897: 처리방침·약관 문서 모양 다듬기 + ?theme=night|garden 테마 처리.
// 문서 조항·문구·링크 주소는 한 글자도 바뀌지 않는다(#7846 시험과 중복 확인).
import test from 'node:test';
import assert from 'node:assert/strict';
import { privacyPage, termsPage, resolveDocTheme } from '../shared-docs.mjs';
import { createSkinHarness, url } from './skin-harness.mjs';

test('#8897: 테마 값 정규화 — night·garden만 받고 나머지는 기본', () => {
  assert.equal(resolveDocTheme('night'), 'night');
  assert.equal(resolveDocTheme('garden'), 'garden');
  for (const value of [undefined, '', 'dark', 'NIGHT', 'night ', 'garden2', 'null']) {
    assert.equal(resolveDocTheme(value), '', `unknown value: ${String(value)}`);
  }
});

test('#8897: 기본 모양 — 테마 속성 없음, 링크 주소 그대로', () => {
  for (const page of [privacyPage(), termsPage(), privacyPage(''), privacyPage('mystery')]) {
    assert.ok(!page.includes('<html lang="ko" data-doc-theme'), 'no theme attribute');
    assert.ok(page.includes('href="#common"'), 'toc anchor unchanged');
    assert.ok(page.includes('href="/privacy">공용 개인정보처리방침</a>'), 'footer privacy link unchanged');
    assert.ok(page.includes('href="/terms">공용 이용약관</a>'), 'footer terms link unchanged');
  }
});

test('#8897: night 테마 — html 속성과 본문 16px CSS, 이동 링크에 테마 이어 붙임', () => {
  const privacy = privacyPage('night');
  const terms = termsPage('night');
  for (const [name, html] of [['privacy', privacy], ['terms', terms]]) {
    assert.ok(html.includes('<html lang="ko" data-doc-theme="night">'), `${name} night attribute`);
    assert.ok(html.includes(':root[data-doc-theme=night]{'), `${name} night palette`);
    assert.ok(html.includes('font-size:16px'), `${name} body 16px`);
    assert.ok(html.includes('max-width:720px'), `${name} 720px measure`);
    assert.ok(html.includes('href="?theme=night#common"'), `${name} toc carries theme`);
    assert.ok(html.includes('href="/privacy?theme=night"'), `${name} footer privacy carries theme`);
    assert.ok(html.includes('href="/terms?theme=night"'), `${name} footer terms carries theme`);
    assert.ok(!html.includes('href="/privacy"'), `${name} no bare footer privacy link`);
  }
  assert.ok(privacy.includes('href="?theme=night#lovetree"'), 'lovetree toc entry carries theme');
  // 외부 원문 링크는 테마와 무관하게 그대로다.
  assert.ok(privacy.includes('href="https://chat.padiem.net/privacy.html"'), 'external chat link unchanged');
});

test('#8897: garden 테마 — 정원 팔레트, 링크에 garden 이어 붙임', () => {
  const terms = termsPage('garden');
  assert.ok(terms.includes('<html lang="ko" data-doc-theme="garden">'), 'garden attribute');
  assert.ok(terms.includes(':root[data-doc-theme=garden]{'), 'garden palette');
  assert.ok(terms.includes('href="?theme=garden#chat"'), 'toc carries garden');
  assert.ok(terms.includes('href="/privacy?theme=garden"'), 'footer privacy carries garden');
});

test('#8897: 조항·문구는 테마와 무관하게 그대로(#7846 문장 재확인)', () => {
  const sentence = '운영진은 고객 지원과 서비스 운영(문제 확인·신고 처리·고객 관리)을 위해 계정 정보(이메일·가입일·활동 기록)와 기록(트리·순간·올린 사진, 공개하지 않은 것 포함)을 볼 수 있습니다.';
  const themed = privacyPage('night');
  assert.ok(themed.includes(sentence), 'verbatim operator sentence under night theme');
  assert.ok(themed.includes('<p class="meta">시행일: 2026-11-16 · 버전: v1</p>'), 'meta line unchanged');
});

test('#8897: /privacy·/terms가 ?theme을 받는다(모르는 값은 기본 모양)', async () => {
  const f = await createSkinHarness();
  const night = await (await f.app.fetch(new Request(`${url}/privacy?theme=night`))).text();
  assert.ok(night.includes('data-doc-theme="night"'), 'worker forwards night');
  assert.ok(night.includes('href="?theme=night#common"'), 'worker doc links carry night');
  const garden = await (await f.app.fetch(new Request(`${url}/terms?theme=garden`))).text();
  assert.ok(garden.includes('data-doc-theme="garden"'), 'worker forwards garden');
  const fallback = await (await f.app.fetch(new Request(`${url}/privacy?theme=bogus`))).text();
  assert.ok(!fallback.includes('<html lang="ko" data-doc-theme'), 'unknown theme falls back to default');
  const plain = await (await f.app.fetch(new Request(`${url}/terms`))).text();
  assert.ok(!plain.includes('<html lang="ko" data-doc-theme'), 'no query means default look');
});
