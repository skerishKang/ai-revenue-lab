import assert from 'node:assert/strict';
import {test} from 'node:test';
import worker from '../public/_worker.js';

const base = 'https://reader.invalid';
const env = {BOOKAI_COM2_AI_SECRET: 'synthetic-fixture-not-a-real-credential'};
const packet = {
  version: '1', mode: 'storymemory_bounded_companion', source_scope: 'ceiling_filtered',
  diagnostics: {boundary_available: true, spoiler_policy: 'hard_no_future'},
  co_reader_decision: {decision: 'ALLOW', reason: 'WITHIN_CEILING'},
  reader_context: {authoritative_reader: true, current_work_key: 'bible-web'},
  reading_progress: {furthest_read_locator: 'bible:web:ACT:9:5', knowledge_ceiling_locator: 'bible:web:ACT:9:5'},
  source_passages: [{canonical_locator: 'bible:web:ACT:9:3', text: 'A light appeared.'}],
};
const contextPermission = {boundary_disposition: 'permitted', context_filtered_count: 0,
  context_allowed_count: 1, context_candidate_count: 1, filter_reason_codes: [], policy_version: 'v1'};
function request(extra = {}) {
  return new Request(base + '/api/storymemory-ai', {
    method: 'POST', headers: {'content-type': 'application/json', origin: base},
    body: JSON.stringify({question: 'What happened?', packet, ...extra}),
  });
}
function durations(response) {
  const header = response.headers.get('server-timing');
  assert.ok(header);
  const values = {};
  for (const part of header.split(', ')) {
    const match = /^(packet|worker|upstream);dur=(\d+)$/.exec(part);
    assert.ok(match, `invalid or unsafe timing entry: ${part}`);
    assert.equal(values[match[1]], undefined);
    values[match[1]] = Number(match[2]);
  }
  return values;
}

test('success reports packet, worker and upstream durations without forwarding diagnostics', async () => {
  const previous = globalThis.fetch;
  const forwarded = [];
  globalThis.fetch = async req => {
    forwarded.push(JSON.parse(await req.text()));
    await new Promise(resolve => setTimeout(resolve, 20));
    return Response.json({ok: true, answer: 'A light appeared.', context_permission: contextPermission});
  };
  try {
    const baselineResponse = await worker.fetch(request(), env);
    const baseline = await baselineResponse.json();
    const baselineTiming = durations(baselineResponse);
    assert.equal(baselineResponse.status, 200);
    assert.equal(baselineTiming.packet, undefined);
    const response = await worker.fetch(request({packet_ms: 123.6}), env);
    const body = await response.json();
    const timing = durations(response);
    assert.equal(response.status, 200);
    assert.deepEqual(body, baseline);
    assert.equal(timing.packet, 124);
    assert.ok(timing.upstream >= 10);
    assert.ok(timing.worker >= timing.upstream);
    assert.equal(forwarded.length, 2);
    assert.ok(forwarded.every(payload => !Object.hasOwn(payload, 'packet_ms')));
  } finally { globalThis.fetch = previous; }
});

test('invalid client timing is ignored and cannot inject a timing header', async () => {
  const previous = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ok: true, answer: 'answer', context_permission: contextPermission});
  try {
    for (const packet_ms of ['1, injected;dur=999', -1, 60001, null, {value: 1}]) {
      const response = await worker.fetch(request({packet_ms}), env);
      assert.equal(response.status, 200);
      const timing = durations(response);
      assert.equal(timing.packet, undefined);
      assert.ok(Number.isFinite(timing.worker));
      assert.ok(Number.isFinite(timing.upstream));
    }
  } finally { globalThis.fetch = previous; }
});

test('error responses keep bounded timing and existing status and body', async () => {
  const blocked = await worker.fetch(request({packet_ms: 7, packet: {...packet,
    co_reader_decision: {decision: 'BLOCK', reason: 'HARD_NO_FUTURE'}}}), env);
  assert.equal(blocked.status, 422);
  assert.equal((await blocked.json()).error, 'outside_knowledge_boundary');
  const blockedTiming = durations(blocked);
  assert.equal(blockedTiming.packet, 7);
  assert.equal(blockedTiming.upstream, undefined);
  const unknown = await worker.fetch(request({extra: 'value'}), env);
  assert.equal(unknown.status, 400);
  assert.equal((await unknown.json()).error, 'invalid_request');
  assert.equal(durations(unknown).packet, undefined);
  const previous = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ok: false, error: {code: 'temporary_error'}}, {status: 503});
  try {
    const failed = await worker.fetch(request({packet_ms: 2}), env);
    assert.equal(failed.status, 503);
    assert.equal((await failed.json()).error, 'temporary_error');
    const failureTiming = durations(failed);
    assert.equal(failureTiming.packet, 2);
    assert.ok(Number.isFinite(failureTiming.upstream));
  } finally { globalThis.fetch = previous; }
});