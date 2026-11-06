/* 261106 · 동행 답변 정규화·배지 시험 (오프라인 node --test).
   (1) 모델이 JSON 으로 답하면 클라이언트 정규화가 문단 텍스트로 바꾼다 — 원시 JSON 이
       화면에 찍히지 않는다. 순수 JSON·코드펜스 JSON 모두.
   (2) 깨진(잘린) JSON 은 정규화에 실패해 null 이 돌고, 화면에는
       '답을 정리하지 못했어요 · 다시 시도' 안내가 대신 표시된다.
   (3) 근거 칩이 없는 GROUNDED 답의 배지 키는 CHAT 이다('근거 답변' 대신 '대화'). */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const publicDir = path.join(__dirname, '../public');
const window = {};
vm.runInNewContext(
  fs.readFileSync(path.join(publicDir, 'storymemory-answer-normalize-v1.js'), 'utf8'),
  {window}
);
const normalize = window.storyMemoryNormalizeCompanionAnswerV1;
const badgeKey = window.storyMemoryCompanionBadgeV1;

const pureJson = JSON.stringify({paragraphs: [
  {text: '지금 읽은 창세기 37장에서는 요셉이 형들에게 팔립니다.', citations: ['창세기 37:28']},
  {text: '이후 이집트에서 자신을 드러냅니다.', citations: ['창세기 45:4']}
]});
const fencedJson = '```json\n' + pureJson + '\n```';
const brokenJson = '{"paragraphs":[{"text":"네, 요셉은 형들을 다시 만납니다';

test('순수 JSON 답은 문단 텍스트로 정규화되고 인용 라벨을 붙인다', () => {
  const out = normalize(pureJson);
  assert.ok(out);
  assert.ok(!out.includes('"paragraphs"'), 'JSON 키가 화면 문자열에 남지 않는다');
  assert.ok(out.includes('팔립니다'));
  assert.ok(out.includes('(창세기 37:28)'), '인용 라벨이 문단 뒤에 붙어 근거 칩 산출을 유지한다');
  assert.ok(out.includes('\n\n'), '문단 사이가 유지된다');
});

test('코드펜스 JSON 답도 같은 정규화를 거친다', () => {
  const out = normalize(fencedJson);
  assert.ok(out);
  assert.ok(!out.includes('```'), '펜스가 남지 않는다');
  assert.ok(!out.includes('"paragraphs"'));
  assert.ok(out.includes('이집트에서 자신을 드러냅니다'));
});

test('깨진 JSON 은 null 이고 비 JSON 문자열도 정규화 대상이 아니다', () => {
  assert.equal(normalize(brokenJson), null, '깨진 JSON 은 null — 호출부가 안내 문구로 바꾼다');
  assert.equal(normalize('{"paragraphs": []}'), null, '빈 문단은 정규화 실패로 본다');
  assert.equal(normalize('보통 문단 답변입니다.'), null, "'{' 로 시작하지 않으면 대상이 아니다");
  assert.equal(normalize(''), null);
  assert.equal(normalize(null), null);
});

test('근거 칩이 없는 GROUNDED 답의 배지는 대화(CHAT)로 바뀐다', () => {
  assert.equal(badgeKey('GROUNDED', false), 'CHAT', '칩 0개 근거 답변 → 대화 배지');
  assert.equal(badgeKey('GROUNDED', true), 'GROUNDED', '칩이 있으면 기존 근거 답변 배지');
  assert.equal(badgeKey('GENERAL_CHAT', false), 'GENERAL_CHAT', '일반 대화 상태는 유지');
  assert.equal(badgeKey('NO_RELEVANT_WITHIN_CEILING_EVIDENCE', false), 'NO_RELEVANT_WITHIN_CEILING_EVIDENCE');
  assert.equal(badgeKey('HARD_NO_FUTURE', false), 'HARD_NO_FUTURE');
});

console.log('PASS: companion answer normalize (pure/fenced JSON → paragraphs, broken → null) + chat badge key asserted');
