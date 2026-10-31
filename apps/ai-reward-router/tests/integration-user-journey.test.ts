import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import {
  createIdentityHarness,
  getWithCookie,
  joinMember,
  postForm,
  TEST_ORIGIN,
} from './helpers/b64-identity-harness.js';

/**
 * End-to-end user journey over the real HTTP boundary (#987 flows 6-12):
 * B64 account creation -> save -> status progression -> amounts -> reload ->
 * cross-member isolation -> logout blocking. Flows 1-5 (anonymous discovery)
 * are asserted at the start; browser-level capture of those flows is reported
 * separately in docs/screenshots.
 *
 * The identity half is B64's own (owner decision 2026-10-27): no PADIEM Chat
 * account and no other product's Worker appears anywhere in this journey.
 */
const PASSWORD = 'journey correct horse';

test('flows 6-12: join, save, status progression, amounts, reload, isolation, logout', async () => {
  const { handler, members, binding } = createIdentityHarness();
  const repo = new D1UserIncomeRepository(binding);
  const save = (form: Record<string, string>, cookie: string) => handler(postForm('/pipeline', form, cookie));

  // flow 6: a B64 member opens its own dashboard
  const memberA = await joinMember(handler, 'journey-a@example.com', PASSWORD);
  const firstRead = await handler(getWithCookie('/pipeline', memberA));
  assert.equal(firstRead.status, 200);
  assert.match(await firstRead.text(), /로그아웃/, 'the dashboard is the member view');
  const userA = (await members.findByEmail('journey-a@example.com'))!.id;

  // flow 7: save an opportunity with an expected amount
  const saved = await save({
    action: 'save', title: 'Telus AI Community', vendor: 'TELUS Digital',
    status: 'SAVED', expectedAmount: '40', expectedCurrency: 'USD',
  }, memberA);
  assert.equal(saved.status, 303, `save step: ${saved.status}`);
  let records = await repo.getByUser(userA);
  assert.equal(records.length, 1);
  const recordId = records[0]!.id;
  assert.equal(records[0]!.expectedAmount, 40);

  const base = {
    id: recordId, title: 'Telus AI Community', vendor: 'TELUS Digital',
    expectedAmount: '40', expectedCurrency: 'USD',
  };

  // flow 8: status progression along the canonical pipeline SAVED -> APPLIED
  assert.equal((await save({ ...base, action: 'save', status: 'APPLIED', appliedAt: '2026-10-25T10:00:00.000Z' }, memberA)).status, 303);
  records = await repo.getByUser(userA);
  assert.equal(records[0]!.status, 'APPLIED');

  // flow 9: record the actual payout along the canonical transition path
  // SAVED -> APPLIED -> ACCEPTED -> IN_PROGRESS -> COMPLETED -> PAID. Skipping
  // states must be refused by the domain transition table.
  assert.equal((await save({
    ...base, action: 'save', status: 'PAID', actualAmount: '42.5', actualCurrency: 'USD', paidAt: '2026-10-25T12:00:00.000Z',
  }, memberA)).status, 400, 'APPLIED -> PAID skips states and must be refused');
  records = await repo.getByUser(userA);
  assert.equal(records[0]!.status, 'APPLIED', 'a refused transition changes nothing');

  assert.equal((await save({ ...base, action: 'save', status: 'ACCEPTED', appliedAt: '2026-10-25T10:00:00.000Z' }, memberA)).status, 303);
  assert.equal((await save({ ...base, action: 'save', status: 'IN_PROGRESS', appliedAt: '2026-10-25T10:00:00.000Z' }, memberA)).status, 303);
  assert.equal((await save({
    ...base, action: 'save', status: 'COMPLETED', appliedAt: '2026-10-25T10:00:00.000Z',
    actualAmount: '42.5', actualCurrency: 'USD', completedAt: '2026-10-25T11:00:00.000Z',
  }, memberA)).status, 303, 'IN_PROGRESS -> COMPLETED');
  const completedPage = await handler(getWithCookie('/pipeline?status=COMPLETED', memberA));
  assert.match(await completedPage.text(), /지급 확인 전/, 'a completed but unpaid amount is not realised income (#987)');

  assert.equal((await save({
    ...base, action: 'save', status: 'PAID', actualAmount: '42.5', actualCurrency: 'USD',
    completedAt: '2026-10-25T11:00:00.000Z', paidAt: '2026-10-25T12:00:00.000Z',
  }, memberA)).status, 303, 'COMPLETED -> PAID');
  records = await repo.getByUser(userA);
  assert.equal(records[0]!.status, 'PAID');
  assert.equal(records[0]!.actualAmount, 42.5);
  assert.equal(records[0]!.actualCurrency, 'USD');

  // flow 10: a fresh dashboard render (reload) shows the persisted record
  const reloadHtml = await (await handler(getWithCookie('/pipeline?status=PAID', memberA))).text();
  assert.match(reloadHtml, /Telus AI Community/);
  assert.match(reloadHtml, /42\.5 USD/);

  // flow 11: member B cannot see, modify or delete member A's record
  const memberB = await joinMember(handler, 'journey-b@example.com', PASSWORD);
  assert.doesNotMatch(await (await handler(getWithCookie('/pipeline', memberB))).text(), /Telus AI Community/);
  assert.equal((await save({
    ...base, action: 'save', title: 'Hijacked', status: 'PAID',
    actualAmount: '999', actualCurrency: 'USD', paidAt: '2026-10-25T12:00:00.000Z',
  }, memberB)).status, 303);
  records = await repo.getByUser(userA);
  assert.equal(records[0]!.title, 'Telus AI Community', 'A record is untouched by B');
  assert.equal(records.length, 1);
  // Rows are keyed (user_id, id): B's forged save created B's OWN row under
  // that id, and B's delete can only ever remove that own row.
  const userB = (await members.findByEmail('journey-b@example.com'))!.id;
  assert.equal(await repo.delete(userB, recordId), true, 'B deletes only their own row');
  records = await repo.getByUser(userA);
  assert.equal(records.length, 1, "A record survives B's delete");
  assert.equal(records[0]!.status, 'PAID');

  // flow 12: after logout the same cookie grants nothing
  assert.equal((await handler(postForm('/logout', {}, memberA))).status, 303);
  assert.equal((await save({ action: 'save', title: 'PostLogout', vendor: 'V', status: 'SAVED' }, memberA)).status, 401,
    'a revoked session cannot save');
  const logoutHtml = await (await handler(getWithCookie('/pipeline', memberA))).text();
  assert.doesNotMatch(logoutHtml, /Telus AI Community/, 'a revoked session sees no private records');
  assert.match(logoutHtml, /수익 관리는 B64 계정으로 이용할 수 있습니다\./);
});

test('flows 1-5: anonymous discovery flow stays fully usable without any session', async () => {
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: (await import('../src/public-supply/verified-public-opportunities.js')).loadVerifiedPublicOpportunities,
  });

  const home = await handler(new Request(`${TEST_ORIGIN}/`));
  assert.equal(home.status, 200);
  assert.match(await home.text(), /수익 기회 보기/);

  const today = await handler(new Request(`${TEST_ORIGIN}/today`));
  assert.equal(today.status, 200);

  const search = await handler(new Request(`${TEST_ORIGIN}/browse?q=Prolific`));
  assert.equal(search.status, 200);
  assert.match(await search.text(), /Prolific 유료 온라인 리서치 참여/);

  const detail = await handler(new Request(`${TEST_ORIGIN}/detail?id=pub-telus-korea-ai-community`));
  assert.equal(detail.status, 200);
  const detailHtml = await detail.text();
  assert.match(detailHtml, /TELUS Digital AI Community/);

  // flow 5: the outbound provider link is present, https, never proxied
  const ctaMatch = detailHtml.match(/href="(https:\/\/[^"]+)"[^>]*rel="noopener noreferrer nofollow"/);
  assert.ok(ctaMatch, 'an https provider link with nofollow rel exists on the detail page');
  assert.ok(ctaMatch[1]!.startsWith('https://'), 'provider links are direct https, no credential passthrough');
});
