import assert from 'node:assert/strict';
import test from 'node:test';
import {createFront} from '../worker.mjs';

// The host→Chat-Worker voice RPC (#7228) reaches the Python Worker through the
// CHAT_WORKER binding on exactly one path. These cases pin the narrowness: one
// method, one path, and only when the host's service proof is already attached.
const env = {
  FRONT_ORIGIN: 'https://host.invalid',
  FALLBACK_MODE: 'static',
  COM2_CANONICAL: 'writes',
  HEALTH_TTL_MS: '10000',
};
const sign = async request => new Headers(request.headers);
const proofHeaders = {
  'content-type': 'application/json',
  'x-padiem-service-at': '1793534400',
  'x-padiem-service-id': 'id_fixture',
  'x-padiem-service-proof': 'v2=' + 'a'.repeat(64),
};

function bindingEnv(calls) {
  return {
    ...env,
    CHAT_WORKER: {
      fetch: async request => {
        calls.push(request);
        return Response.json({status: 200, body: '{"mode":"live"}'}, {headers: {'cache-control': 'no-store'}});
      },
    },
  };
}

test('the signed voice-RPC POST goes to the Worker binding, not COM2', async () => {
  const forwarded = [];
  const binding = [];
  const handle = createFront({sign, fetchImpl: async request => {
    forwarded.push(request);
    return Response.json({unexpected: true});
  }});
  const body = JSON.stringify({op: 'live_token', productId: 'p', sessionId: 's'});
  const response = await handle(
    new Request('https://chat.padiem.net/internal/rpc/voice_stt', {method: 'POST', headers: proofHeaders, body}),
    bindingEnv(binding),
  );
  assert.equal(response.status, 200);
  assert.equal(forwarded.length, 0);
  assert.equal(binding.length, 1);
  assert.equal(binding[0].url, 'https://chat.padiem.net/internal/rpc/voice_stt');
  assert.equal(binding[0].headers.get('x-padiem-service-proof'), proofHeaders['x-padiem-service-proof']);
  assert.equal(await binding[0].text(), body);
});

test('an unproven POST on that path never reaches the Worker binding', async () => {
  const binding = [];
  const handle = createFront({sign, fetchImpl: async () => new Response('404', {status: 404})});
  const response = await handle(
    new Request('https://chat.padiem.net/internal/rpc/voice_stt', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: '{}',
    }),
    bindingEnv(binding),
  );
  assert.equal(response.status, 404);
  assert.equal(binding.length, 0);
});

test('other paths and methods on the Worker stay off the voice route', async () => {
  const binding = [];
  const handle = createFront({sign, fetchImpl: async () => new Response('404', {status: 404})});
  for (const [method, path] of [
    ['GET', '/internal/rpc/voice_stt'],
    ['POST', '/internal/rpc/voice_stt/extra'],
    ['POST', '/internal/rpc/password'],
    ['POST', '/internal/store'],
  ]) {
    await handle(new Request('https://chat.padiem.net' + path, {method, headers: proofHeaders}), bindingEnv(binding));
  }
  assert.equal(binding.length, 0);
});

test('a missing binding answers a bounded 503 instead of a crash', async () => {
  const handle = createFront({sign, fetchImpl: async () => new Response('404', {status: 404})});
  const response = await handle(
    new Request('https://chat.padiem.net/internal/rpc/voice_stt', {method: 'POST', headers: proofHeaders, body: '{}'}),
    {...env},
  );
  assert.equal(response.status, 503);
});
