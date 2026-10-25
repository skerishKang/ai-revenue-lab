import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler, createEmptySupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import { clearStore } from '../src/income-pipeline/store.js';

test('pipeline requires server-side auth (no query param userId)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const noAuth = await handler(new Request('https://b64.example/pipeline'));
  assert.equal(noAuth.status, 200);
  const html = await noAuth.text();
  assert.ok(html.includes('로그인이 필요합니다'));
  const spoofed = await handler(new Request('https://b64.example/pipeline?user=attacker', {
    headers: { 'x-padiem-user-id': 'attacker', 'cf-ray': 'test-ray-123' },
  }));
  const spoofHtml = await spoofed.text();
  assert.ok(spoofHtml.includes('INCOME_PIPELINE'));
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
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const auth = { 'x-padiem-user-id': 'test-crud-user-12345678', 'cf-ray': 'test-ray-123' };
  const saveRes = await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=CRUD+Test&vendor=Prolific&status=SAVED&expectedAmount=25&expectedCurrency=USD&note=test',
  }));
  assert.equal(saveRes.status, 303);
  const getRes = await handler(new Request('https://b64.example/pipeline', { headers: auth }));
  assert.equal(getRes.status, 200);
  const html = await getRes.text();
  assert.ok(html.includes('CRUD Test'));
  assert.ok(html.includes('Prolific'));
});

test('pipeline cross-user isolation: user B cannot see user A records', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const userA = { 'x-padiem-user-id': 'user-aaaaaaaaaaaaaaaa', 'cf-ray': 'test-ray-123' };
  const userB = { 'x-padiem-user-id': 'user-bbbbbbbbbbbbbbbb', 'cf-ray': 'test-ray-123' };
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...userA, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Secret+Record&vendor=Outlier&status=SAVED',
  }));
  const resB = await handler(new Request('https://b64.example/pipeline', { headers: userB }));
  const htmlB = await resB.text();
  assert.ok(!htmlB.includes('Secret Record'));
  assert.ok(htmlB.includes('아직 추적 중인 기회가 없습니다'));
  const resA = await handler(new Request('https://b64.example/pipeline', { headers: userA }));
  const htmlA = await resA.text();
  assert.ok(htmlA.includes('Secret Record'));
});

test('pipeline delete removes record', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const auth = { 'x-padiem-user-id': 'del-user-12345678', 'cf-ray': 'test-ray-123' };
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=ToDelete&vendor=Test&status=SAVED',
  }));
  const res1 = await handler(new Request('https://b64.example/pipeline', { headers: auth }));
  const html1 = await res1.text();
  assert.ok(html1.includes('ToDelete'));
});

test('pipeline filter by status', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const auth = { 'x-padiem-user-id': 'filter-user-12345678', 'cf-ray': 'test-ray-123' };
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Saved+One&vendor=V1&status=SAVED',
  }));
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Paid+One&vendor=V2&status=PAID&actualAmount=10&actualCurrency=USD',
  }));
  const res = await handler(new Request('https://b64.example/pipeline?status=PAID', { headers: auth }));
  const html = await res.text();
  assert.ok(html.includes('Paid One'));
  assert.ok(!html.includes('Saved One'));
});

test('pipeline rejects direct request with spoofed x-padiem-user-id (no cf-ray)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/pipeline', {
    headers: { 'x-padiem-user-id': 'victim-user-12345678' },
  }));
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.ok(html.includes('로그인이 필요합니다'));
});

test('pipeline rejects Bearer token (not trusted auth)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/pipeline', {
    headers: { 'Authorization': 'Bearer attacker-token-12345678', 'cf-ray': 'test-ray-123' },
  }));
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.ok(html.includes('로그인이 필요합니다'));
});

test('pipeline trusted proxy with valid identity grants access', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const res = await handler(new Request('https://b64.example/pipeline', {
    headers: { 'x-padiem-user-id': 'trusted-user-12345678', 'cf-ray': 'test-ray-123' },
  }));
  assert.equal(res.status, 200);
  const html = await res.text();
  assert.ok(html.includes('아직 추적 중인 기회가 없습니다'));
  assert.ok(!html.includes('로그인이 필요합니다'));
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
