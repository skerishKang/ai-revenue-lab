import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler, createEmptySupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import { clearStore } from '../src/income-pipeline/store.js';
import { createTestAuthResolver } from '../src/income-pipeline/auth.js';

test('pipeline requires server-side auth (no client identity)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const noAuth = await handler(new Request('https://b64.example/pipeline'));
  assert.equal(noAuth.status, 200);
  const html = await noAuth.text();
  assert.ok(html.includes('INCOME_PIPELINE'));
});

test('pipeline rejects POST without auth', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Hack&vendor=Evil&status=SAVED',
  }));
  assert.equal(res.status, 401);
});

test('pipeline CRUD: save and retrieve record', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [], resolveAuth: createTestAuthResolver('test-crud-user-12345678') });
  const saveRes = await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=CRUD+Test&vendor=Prolific&status=SAVED&expectedAmount=25&expectedCurrency=USD&note=test',
  }));
  assert.equal(saveRes.status, 303);
  const getRes = await handler(new Request('https://b64.example/pipeline'));
  assert.equal(getRes.status, 200);
  const html = await getRes.text();
  assert.ok(html.includes('CRUD Test'));
  assert.ok(html.includes('Prolific'));
});

test('pipeline cross-user isolation: user B cannot see user A records', async () => {
  clearStore();
  const handlerA = createConsumerHttpHandler({ loadCandidates: () => [], resolveAuth: createTestAuthResolver('user-aaaaaaaaaaaaaaaa') });
  const handlerB = createConsumerHttpHandler({ loadCandidates: () => [], resolveAuth: createTestAuthResolver('user-bbbbbbbbbbbbbbbb') });
  await handlerA(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Secret+Record&vendor=Outlier&status=SAVED',
  }));
  const resB = await handlerB(new Request('https://b64.example/pipeline'));
  const htmlB = await resB.text();
  assert.ok(!htmlB.includes('Secret Record'));
  assert.ok(htmlB.includes('아직 추적 중인 기회가 없습니다'));
  const resA = await handlerA(new Request('https://b64.example/pipeline'));
  const htmlA = await resA.text();
  assert.ok(htmlA.includes('Secret Record'));
});

test('pipeline delete removes record', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [], resolveAuth: createTestAuthResolver('del-user-12345678') });
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=ToDelete&vendor=Test&status=SAVED',
  }));
  const res1 = await handler(new Request('https://b64.example/pipeline'));
  const html1 = await res1.text();
  assert.ok(html1.includes('ToDelete'));
});

test('pipeline filter by status', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [], resolveAuth: createTestAuthResolver('filter-user-12345678') });
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Saved+One&vendor=V1&status=SAVED',
  }));
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Paid+One&vendor=V2&status=PAID&actualAmount=10&actualCurrency=USD',
  }));
  const res = await handler(new Request('https://b64.example/pipeline?status=PAID'));
  const html = await res.text();
  assert.ok(html.includes('Paid One'));
  assert.ok(!html.includes('Saved One'));
});

test('pipeline rejects direct request with spoofed identity (no trusted proxy)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/pipeline', {
    headers: { 'x-padiem-user-id': 'victim-user-12345678' },
  }));
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.ok(html.includes('INCOME_PIPELINE'));
  assert.ok(!html.includes('victim-user-12345678'));
});

test('pipeline rejects Bearer token (not trusted auth)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/pipeline', {
    headers: { 'Authorization': 'Bearer attacker-token-12345678' },
  }));
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.ok(html.includes('INCOME_PIPELINE'));
});

test('pipeline trusted auth grants access', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [], resolveAuth: createTestAuthResolver('trusted-user-12345678') });
  const res = await handler(new Request('https://b64.example/pipeline'));
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.ok(html.includes('INCOME_PIPELINE'));
  assert.ok(html.includes('아직 추적 중인 기회가 없습니다'));
});

test('pipeline unauthenticated POST to other routes returns 405', async () => {
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/browse', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save',
  }));
  assert.equal(res.status, 405);
});
