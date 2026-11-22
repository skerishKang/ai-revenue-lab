// #7846: 2026-11-16 대표 결정 — 운영진 열람 문장을 최초 게시(v1)에 원래 있던 문장으로 넣는다.
// 버전·시행일은 그대로(v1 / 2026-11-16)이고 변경 이력 줄은 넣지 않는다.
import test from 'node:test';
import assert from 'node:assert/strict';
import { privacyPage, termsPage } from '../shared-docs.mjs';

const privacy = privacyPage();
const terms = termsPage();

const OPERATOR_SENTENCE = '운영진은 고객 지원과 서비스 운영(문제 확인·신고 처리·고객 관리)을 위해 계정 정보(이메일·가입일·활동 기록)와 기록(트리·순간·올린 사진, 공개하지 않은 것 포함)을 볼 수 있습니다. 운영진이 열람한 기록은 남기며 90일 뒤 자동으로 지웁니다.';

test('#7846: 새 문장이 러브트리 h2 바로 아래 1번 앞에 문장 그대로 있다', () => {
  const paragraph = `<p>${OPERATOR_SENTENCE}</p>`;
  assert.ok(privacy.includes(paragraph), 'verbatim sentence as its own paragraph');
  const h2 = privacy.indexOf('<h2 id="lovetree-title">다. 러브트리</h2>');
  const at = privacy.indexOf(paragraph);
  const h3 = privacy.indexOf('<h3>1. 내가 남기는 기록(트리·순간)</h3>');
  assert.ok(h2 >= 0 && at > h2 && h3 > at, 'placement: h2 < new sentence < section 1');
});

test('#7846: 두 곳을 교체했고 러브트리 1·2절에 나만 단독 표현이 없다', () => {
  const start = privacy.indexOf('<h3>1. 내가 남기는 기록(트리·순간)</h3>');
  const end = privacy.indexOf('<h3>3. 공유 링크</h3>');
  assert.ok(start > 0 && end > start, 'lovetree sections 1-2 located');
  const section12 = privacy.slice(start, end);
  assert.ok(section12.includes('③ 보이는 사람: 기본은 나와 운영진(위 목적에 한해).'), 'section 1 ③ replaced');
  assert.ok(section12.includes('③ 보이는 사람: 나와 운영진(위 목적에 한해). 공유 링크·둘러보기·미리보기 카드에는 쓰지 않음.'), 'section 2 ③ replaced');
  assert.ok(!section12.includes('나만'), 'no bare 나만 in sections 1-2');
});

test('#7846: #lovetree 앵커와 나머지 확정 문장은 유지된다', () => {
  assert.ok(privacy.includes('<section id="lovetree" aria-labelledby="lovetree-title">'), 'lovetree section');
  assert.ok(privacy.includes('id="lovetree"'), 'lovetree anchor');
  for (const sentence of [
    '공유를 취소하면 그 즉시 열리지 않음.',
    '공개 화면에는 내 이름·아이디·이메일을 보여 주지 않음.',
    '재생은 youtube-nocookie 주소로 함.',
  ]) assert.ok(privacy.includes(sentence), sentence);
});

test('#7846: 처리방침·약관 모두 v1 그대로, 시행일 2026-11-16, 변경 이력 없음', () => {
  const meta = '<p class="meta">시행일: 2026-11-16 · 버전: v1</p>';
  assert.ok(privacy.includes(meta), 'privacy stays v1 with the original effective date');
  assert.ok(terms.includes(meta), 'terms stays v1');
  assert.ok(!privacy.includes('버전: v2'), 'privacy has no v2 marker');
  assert.ok(!privacy.includes('변경 이력'), 'no change history line');
  assert.ok(!privacy.includes('러브트리 운영진 열람 추가'), 'no v2 change label');
});
