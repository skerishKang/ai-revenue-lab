/* #7837 — AI 동행 지시: 원어를 로마자로 섞지 않고, 한국어 답변에 영어 낱말을 섞지 않는다.
   지시는 워커가 실제로 모델 요청에 싣는 agent.system_instruction 을 가로채서 확인한다.
   (답변을 고쳐 쓰는 후처리는 없다: 서버는 받은 답변을 그대로 쓴다.) */
import assert from 'node:assert/strict';
import test from 'node:test';
import bookai from '../public/_worker.js';

const env = { BOOKAI_COM2_AI_SECRET: 'synthetic-bookai-ai-test-credential' };
const packet = {
  version: '1', mode: 'storymemory_bounded_companion', source_scope: 'ceiling_filtered',
  diagnostics: { boundary_available: true, spoiler_policy: 'hard_no_future' },
  co_reader_decision: { decision: 'ALLOW', reason: 'WITHIN_CEILING' },
  reader_context: { authoritative_reader: true, current_work_key: 'bible-web' },
  reading_progress: { furthest_read_locator: 'bible:web:GEN:1:2', knowledge_ceiling_locator: 'bible:web:GEN:1:2' },
  source_passages: [{ canonical_locator: 'bible:web:GEN:1:2', text: '땅이 혼돈하고 공허하며' }],
};
const cp = {
  boundary_disposition: 'permitted', context_filtered_count: 0, context_allowed_count: 2,
  context_candidate_count: 2, filter_reason_codes: [], policy_version: 'storymemory-b61-ceiling:v1',
};

async function sentPayload(packetOverride = packet) {
  let payload = null;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (request) => {
    payload = JSON.parse(await request.text());
    return Response.json({ ok: true, answer: '땅은 아직 질서가 없고 비어 있었습니다.', context_permission: cp });
  };
  try {
    const response = await bookai.fetch(new Request('https://reader.invalid/api/storymemory-ai', {
      method: 'POST',
      headers: { 'content-type': 'application/json', origin: 'https://reader.invalid' },
      body: JSON.stringify({ question: '혼돈과 공허는 무슨 뜻인가요?', packet: packetOverride }),
    }), env);
    assert.equal(response.status, 200);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.ok(payload, '모델 요청이 만들어지지 않았다');
  return payload;
}

test('한국어 지시에 원어 음역·뜻 규칙이 들어간다', async () => {
  const instruction = (await sentPayload()).agent.system_instruction;
  assert.match(instruction, /원어\(히브리어·헬라어 등\)를 말할 때는 한글 음역과 뜻을 먼저/);
  assert.match(instruction, /토후\(형체 없음\)/);
  assert.match(instruction, /원어를 로마자로 표기하지 마세요/);
  assert.match(instruction, /꼭 필요하면 괄호 안에 한 번만/);
});

test('한국어 지시에 영어 낱말 금지 규칙이 들어간다', async () => {
  const instruction = (await sentPayload()).agent.system_instruction;
  assert.match(instruction, /한국어 답변에 영어 낱말을 섞지 마세요/);
  assert.match(instruction, /성경 책 이름과 용어는 한국어로/);
});

test('기존 규칙은 그대로 남는다', async () => {
  const instruction = (await sentPayload()).agent.system_instruction;
  for (const rule of [/태그명/, /UNTRUSTED_REFERENCE/, /책이름 장:절/, /성경 배경 지식/]) {
    assert.match(instruction, rule);
  }
  const firstRead = await sentPayload({
    ...packet,
    reading_progress: {
      furthest_read_locator: 'bible:web:GEN:1:2', knowledge_ceiling_locator: 'bible:web:GEN:1:2',
      reading_mode: 'first_read', opened_units: ['bible:web:GEN:1'],
    },
    co_reader_decision: { decision: 'ALLOW', reason: 'WITHIN_CEILING', question_class: 'plot' },
    reader_context: { authoritative_reader: true, current_work_key: 'bible-web', current_unit_key: 'bible:web:GEN:1' },
  });
  assert.match(firstRead.agent.system_instruction, /사전 학습 지식/);
  assert.match(firstRead.agent.system_instruction, /paragraphs/);
  assert.match(firstRead.agent.system_instruction, /한국어 답변에 영어 낱말을 섞지 마세요/);
});

test('요청은 한국어 과제이고 지시에 모델·제공사 이름이 없다', async () => {
  const payload = await sentPayload();
  assert.equal(payload.agent.task_type, 'korean');
  assert.equal(payload.agent.optimize_for, 'korean');
  const instruction = payload.agent.system_instruction;
  assert.doesNotMatch(instruction, /gemini|openai|anthropic|claude|gpt/i);
  assert.doesNotMatch(instruction, /tohu|bohu/i);
});
