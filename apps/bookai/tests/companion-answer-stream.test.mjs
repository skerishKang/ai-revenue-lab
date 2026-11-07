/* The Pages worker's streamed answer path. Chat is stubbed at the COM2 hop so
   the frames the browser receives are the ones this worker wrote. */
import assert from 'node:assert/strict';
import test from 'node:test';
import worker from '../public/_worker.js';

const BASE = 'https://reader.invalid';
const env = {BOOKAI_COM2_AI_SECRET: 'test-worker-secret-' + 'x'.repeat(24)};
const streamEnv = {...env, BOOKAI_AI_STREAM: 'on'};
const packet = {
  version: '1', mode: 'storymemory_bounded_companion', source_scope: 'ceiling_filtered',
  diagnostics: {boundary_available: true, spoiler_policy: 'hard_no_future'},
  co_reader_decision: {decision: 'ALLOW', reason: 'WITHIN_CEILING'},
  reader_context: {authoritative_reader: true, current_work_key: 'bible-web'},
  reading_progress: {furthest_read_locator: 'bible:web:ACT:9:5', knowledge_ceiling_locator: 'bible:web:ACT:9:5'},
  source_passages: [{canonical_locator: 'bible:web:ACT:9:3', text: 'A light appeared.'}],
};
const contextPermission = {
  boundary_disposition: 'permitted', context_filtered_count: 0, context_allowed_count: 1,
  context_candidate_count: 1, filter_reason_codes: [], policy_version: 'v1',
};

function request(packetOverride = {}) {
  return new Request(BASE + '/api/storymemory-ai', {
    method: 'POST', headers: {'content-type': 'application/json', origin: BASE},
    body: JSON.stringify({question: 'What happened?', packet: {...packet, ...packetOverride}}),
  });
}

function streamResponse(frames) {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(JSON.stringify(frame) + '\n'));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200, headers: {'content-type': 'application/x-ndjson; charset=utf-8'},
  });
}

async function frames(response) {
  return (await response.text()).split('\n').filter(Boolean).map(line => JSON.parse(line));
}

function timingNames(response) {
  const header = response.headers.get('server-timing') || '';
  return header.split(', ').filter(Boolean).map(part => part.split(';')[0]);
}

test('deltas arrive in order and the validated terminal answer closes the stream', async () => {
  const calls = [];
  globalThis.fetch = async request => {
    calls.push(request);
    return streamResponse([
      {ok: true, type: 'delta', text: 'A light '},
      {ok: true, type: 'delta', text: 'appeared.'},
      {ok: true, type: 'done', answer: 'A light appeared.', context_permission: contextPermission,
        finish_reason: 'stop', metadata: {usage: {output_tokens: 4}}, timing: {chat: 10, p01: 9}},
    ]);
  };
  try {
    const response = await worker.fetch(request(), streamEnv);
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-type'), /^application\/x-ndjson/);
    const decoded = await frames(response);
    assert.deepEqual(decoded.map(frame => frame.type), ['delta', 'delta', 'done']);
    assert.equal(decoded[0].text, 'A light ');
    assert.equal(decoded[1].text, 'appeared.');
    assert.equal(decoded[2].answer, 'A light appeared.');
    assert.equal(decoded[2].context_permission.context_allowed_count, 1);
    assert.equal(decoded[2].transport, 'com2_p01');
    assert.equal(decoded[2].timing.chat, 10);
    assert.ok(Number.isFinite(decoded[2].timing.upstream));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].headers.get('accept'), 'application/x-ndjson');
    const timing = timingNames(response);
    assert.ok(timing.includes('first_chunk'));
    assert.ok(timing.includes('worker'));
  } finally { delete globalThis.fetch; }
});

test('a mid-stream error keeps retry guidance and never sends a success frame', async () => {
  globalThis.fetch = async () => streamResponse([
    {ok: true, type: 'delta', text: '잘린'},
    {ok: false, type: 'error', error: {code: 'answer_incomplete', retryable: true}},
  ]);
  try {
    const response = await worker.fetch(request(), streamEnv);
    assert.equal(response.status, 200);
    const decoded = await frames(response);
    assert.equal(decoded[0].type, 'delta');
    assert.equal(decoded[decoded.length - 1].type, 'error');
    assert.equal(decoded[decoded.length - 1].error.code, 'answer_incomplete');
    assert.equal(decoded[decoded.length - 1].error.retryable, true);
    assert.ok(!decoded.some(frame => frame.type === 'done'));
  } finally { delete globalThis.fetch; }
});

test('with the switch off the worker never asks for a stream', async () => {
  const calls = [];
  globalThis.fetch = async request => {
    calls.push(request);
    return Response.json({ok: true, answer: 'A light appeared.', context_permission: contextPermission});
  };
  try {
    const response = await worker.fetch(request(), env);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).answer, 'A light appeared.');
    assert.equal(calls.length, 1);
    assert.notEqual(calls[0].headers.get('accept'), 'application/x-ndjson');
  } finally { delete globalThis.fetch; }
});

test('a stream-capability refusal falls back to the one-shot path', async () => {
  const calls = [];
  globalThis.fetch = async request => {
    calls.push(request);
    if (calls.length === 1) {
      return Response.json({ok: false, error: {code: 'not_found'}}, {status: 404});
    }
    return Response.json({ok: true, answer: 'A light appeared.', context_permission: contextPermission});
  };
  try {
    const response = await worker.fetch(request(), streamEnv);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).answer, 'A light appeared.');
    assert.equal(calls.length, 2);
    assert.equal(calls[0].headers.get('accept'), 'application/x-ndjson');
    assert.notEqual(calls[1].headers.get('accept'), 'application/x-ndjson');
  } finally { delete globalThis.fetch; }
});

test('a folded first-read plot answer never uses the stream path', async () => {
  const calls = [];
  globalThis.fetch = async request => {
    calls.push(request);
    return Response.json({ok: true, answer: '현재 범위의 문단입니다.', context_permission: contextPermission});
  };
  try {
    const folded = {
      reading_progress: {...packet.reading_progress, reading_mode: 'first_read', opened_units: ['bible:web:ACT:9']},
      co_reader_decision: {decision: 'ALLOW', reason: 'WITHIN_CEILING', question_class: 'plot'},
    };
    const response = await worker.fetch(request(folded), streamEnv);
    assert.equal(response.status, 200);
    assert.equal(calls.length, 1);
    assert.notEqual(calls[0].headers.get('accept'), 'application/x-ndjson');
    assert.equal((await response.json()).reading_mode, 'first_read');
  } finally { delete globalThis.fetch; }
});
