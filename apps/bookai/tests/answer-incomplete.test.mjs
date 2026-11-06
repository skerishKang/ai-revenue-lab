/* A half answer must not travel as a success. Drives the real Pages worker with
   the COM2 hop stubbed, so the contract checked here is the one the browser gets. */
import assert from 'node:assert/strict';
import test from 'node:test';
import worker from '../public/_worker.js';

const BASE = 'https://bookai-3to.pages.dev';
const env = {
  ASSETS: { fetch: async () => new Response('assets') },
  BOOKAI_COM2_AI_SECRET: 'test-worker-secret-' + 'x'.repeat(24),
};

function packet(overrides = {}) {
  const locator = 'bible:web:1CO:3:1';
  return {
    version: '1',
    mode: 'storymemory_bounded_companion',
    source_scope: 'ceiling_filtered',
    diagnostics: { boundary_available: true, spoiler_policy: 'hard_no_future' },
    co_reader_decision: { decision: 'ALLOW', reason: 'WITHIN_CEILING', question_class: 'work' },
    reader_context: { authoritative_reader: true, current_work_key: 'bible-web', current_work_title: '고린도전서 3장' },
    reading_progress: {
      furthest_read_locator: locator,
      knowledge_ceiling_locator: locator,
      reading_mode: 'browse',
      opened_units: ['bible:web:1CO:3'],
    },
    source_passages: [{ canonical_locator: locator, sequence: 1065, text: '형제들아 내가 신령한 자들을 대함과 같이', language: 'ko' }],
    ...overrides,
  };
}

// Runs one question and returns the worker response plus what it asked COM2 for.
async function ask(com2Body, com2Status = 200) {
  const sent = [];
  globalThis.fetch = async (request) => {
    sent.push(JSON.parse(await request.text()));
    const body = typeof com2Body === 'function' ? com2Body(sent[0]) : com2Body;
    return new Response(JSON.stringify(body), { status: com2Status, headers: { 'content-type': 'application/json' } });
  };
  const response = await worker.fetch(new Request(BASE + '/api/storymemory-ai', {
    method: 'POST',
    headers: { 'content-type': 'application/json', origin: BASE },
    body: JSON.stringify({ question: '이 장의 핵심을 정리해 주세요', packet: packet() }),
  }), env);
  return { response, payload: await response.json(), sent: sent[0] };
}

const engineEnvelope = (answer, extra = {}) => ({
  ok: true,
  answer,
  context_permission: { boundary_disposition: 'permitted', context_filtered_count: 0, context_allowed_count: 1 },
  metadata: { app_id: 'b61', trace_id: 'test-trace' },
  ...extra,
});

test('a thought block the model never closed is a retryable answer_incomplete, not a short 200', async () => {
  const { response, payload } = await ask(engineEnvelope(
    '바울은 신약에서 중요한 인물로, 예수 그리스도의 <thought>추론이 닫히지 않은 채 끝났다'
  ));
  assert.equal(response.status, 502, JSON.stringify(payload));
  assert.equal(payload.ok, false);
  assert.equal(payload.error, 'answer_incomplete');
  assert.equal(payload.retryable, true);
  assert.equal(payload.finish_reason, 'thought_unclosed');
  assert.ok(!('answer' in payload), 'the surviving fragment must not be served as an answer');
});

test('generation that used the whole output budget is answer_incomplete too', async () => {
  const { response, payload } = await ask((request) => engineEnvelope(
    '문장이 여기서',
    { metadata: { app_id: 'b61', trace_id: 'test-trace', usage: { output_tokens: request.agent.max_tokens } } }
  ));
  assert.equal(response.status, 502);
  assert.equal(payload.error, 'answer_incomplete');
  assert.equal(payload.finish_reason, 'length_cap');
});

test('the engine flag alone is enough when core already removed the block', async () => {
  const { response, payload } = await ask(engineEnvelope('잘린 앞부분', { answer_truncated: true }));
  assert.equal(response.status, 502);
  assert.equal(payload.error, 'answer_incomplete');
  assert.equal(payload.finish_reason, 'thought_unclosed');
});

test('a long multi-paragraph answer behind a closed block arrives whole', async () => {
  const paragraphs = [
    '바울은 다메섹 문에서 부르심을 받은 뒤 이방인의 사도로 보내졌습니다. 그는 안디옥 교회에서 바나바와 함께 오래 사역하며 믿는 이들을 가르쳤습니다.',
    '고린도 신자들에게 그는 스스로 놓은 기초 위에 다른 무엇도 놓지 말라고 경고했습니다. 금과 은과 보석과 나무와 풀과 볏짚으로 지은 건축은 각각 그 날에 드러난다고 말했습니다.',
    '그러나 하나님의 전은 거룩하며 그 전이 너희라고 그는 권면했습니다. 서로 분별하고 다툼이 이는 것은 육에 속한 어린 아이의 모양이라고 그는 지적했습니다.',
    '끝으로 그는 만물이 너희 것이라 그러나 너희는 그리스도의 것이요 그리스도는 하나님의 것이라고 고백하며, 장막을 떠나지 말고 거룩함을 이루라고 권했습니다.',
  ];
  const long = [...paragraphs, ...paragraphs, ...paragraphs].join('\n\n');
  assert.ok(long.length > 800, 'the fixture must exercise a genuinely long answer: ' + long.length);
  const { response, payload } = await ask(engineEnvelope('<thought>private</thought>' + long));
  assert.equal(response.status, 200, JSON.stringify(payload).slice(0, 200));
  assert.equal(payload.answer, long);
  assert.equal(payload.finish_reason, 'complete');
  assert.equal(payload.answer.split('\n\n').length, 12, 'every paragraph survives');
});
