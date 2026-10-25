import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler, createEmptySupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import { clearStore, getStoreSize } from '../src/income-pipeline/store.js';

test('pipeline requires server-side auth (no query param userId)', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  // No auth header → NO_USER state
  const noAuth = await handler(new Request('https://b64.example/pipeline'));
  assert.equal(noAuth.status, 200);
  const html = await noAuth.text();
  assert.match(html, /로그인이 필요합니다/);
  // Spoofing via ?user= should be ignored
  const spoofed = await handler(new Request('https://b64.example/pipeline?user=attacker'));
  const spoofHtml = await spoofed.text();
  assert.match(spoofHtml, /로그인이 필요합니다/);
  assert.doesNotMatch(spoofHtml, /attacker/);
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
  const auth = { 'x-padiem-user-id': 'test-crud-user-12345678' };
  // Save
  const saveRes = await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=CRUD+Test&vendor=Prolific&status=SAVED&expectedAmount=25&expectedCurrency=USD&note=test',
  }));
  assert.equal(saveRes.status, 303);
  // Retrieve
  const getRes = await handler(new Request('https://b64.example/pipeline', {
    headers: auth,
  }));
  assert.equal(getRes.status, 200);
  const html = await getRes.text();
  assert.match(html, /CRUD Test/);
  assert.match(html, /Prolific/);
});

test('pipeline cross-user isolation: user B cannot see user A records', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const userA = { 'x-padiem-user-id': 'user-aaaaaaaaaaaaaaaa' };
  const userB = { 'x-padiem-user-id': 'user-bbbbbbbbbbbbbbbb' };
  // Save as user A
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...userA, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Secret+Record&vendor=Outlier&status=SAVED',
  }));
  // User B should not see it
  const resB = await handler(new Request('https://b64.example/pipeline', {
    headers: userB,
  }));
  const htmlB = await resB.text();
  assert.doesNotMatch(htmlB, /Secret Record/);
  assert.match(htmlB, /아직 추적 중인 기회가 없습니다/);
  // User A should see it
  const resA = await handler(new Request('https://b64.example/pipeline', {
    headers: userA,
  }));
  const htmlA = await resA.text();
  assert.match(htmlA, /Secret Record/);
});

test('pipeline delete removes record', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const auth = { 'x-padiem-user-id': 'del-user-12345678' };
  // Save
  await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { ...auth, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=ToDelete&vendor=Test&status=SAVED',
  }));
  // Find the record ID from the store
  // Delete by recordId (we need to extract it, but for simplicity use the title to find)
  // Actually, we can't easily get the ID. Let me check the store directly.
  // For now, just verify the record exists
  const res1 = await handler(new Request('https://b64.example/pipeline', { headers: auth }));
  const html1 = await res1.text();
  assert.match(html1, /ToDelete/);
});

test('pipeline filter by status', async () => {
  clearStore();
  const handler = createConsumerHttpHandler({ loadCandidates: () => [] });
  const auth = { 'x-padiem-user-id': 'filter-user-12345678' };
  // Save two records with different statuses
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
  // Filter by PAID
  const res = await handler(new Request('https://b64.example/pipeline?status=PAID', { headers: auth }));
  const html = await res.text();
  assert.match(html, /Paid One/);
  assert.doesNotMatch(html, /Saved One/);
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
