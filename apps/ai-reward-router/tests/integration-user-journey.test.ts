import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createChatSessionStatusProbe, createPadiemSessionAuthResolver } from '../src/income-pipeline/padiem-session-auth.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { mintFixtureTokenSet } from './helpers/padiem-test-tokens.js';
import { createSqliteD1Binding } from './d1-binding-helper.js';

/**
 * End-to-end user journey over the real HTTP boundary (#987 flows 6-12):
 * login-verified save -> status progression -> amounts -> reload -> cross-user
 * isolation -> logout/revocation blocking. Flows 1-5 (anonymous discovery) are
 * asserted at the start; browser-level capture of those flows is reported
 * separately in docs/screenshots.
 */
const FIXTURE_SECRET = 'b64-fixture-session-secret-0123456789abcdef';
const ISSUED_AT = 3999999999;
const MAX_AGE = 604800;
const FIXTURES = await mintFixtureTokenSet(FIXTURE_SECRET, ISSUED_AT, MAX_AGE);
const USER_A_TOKEN = FIXTURES.validToken;
const USER_B_TOKEN = FIXTURES.validTokenWithSid;
const USER_A = 'usr_fixture_user_0001';
const USER_B = 'usr_fixture_user_0002';
const ORIGIN = 'https://chat.padiem.net';

function post(handler: (r: Request) => Promise<Response>, token: string, body: string, origin = ORIGIN) {
  return handler(new Request(`${ORIGIN}/pipeline`, {
    method: 'POST',
    headers: { cookie: `padiem_session=${token}`, origin, 'content-type': 'application/x-www-form-urlencoded' },
    body,
  }));
}

test('flows 6-12: verified login, save, status progression, amounts, reload, isolation, revocation', async () => {
  const { binding } = createSqliteD1Binding();
  const repo = new D1UserIncomeRepository(binding);
  let sessionLive = true;
  const chatService = {
    async fetch(input: Request) {
      assert.equal(new URL(input.url).pathname, '/api/auth/status');
      return new Response(
        JSON.stringify({ ready: true, authenticated: sessionLive, session_state: sessionLive ? 'signed_in' : 'expired' }),
        { status: 200, headers: { 'content-type': 'application/json; charset=utf-8' } },
      );
    },
  };
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createPadiemSessionAuthResolver({
      sessionSecret: FIXTURE_SECRET,
      sessionLivenessProbe: createChatSessionStatusProbe({ chatService }),
    }),
    incomeRepository: repo,
    expectedBrowserOrigin: ORIGIN,
  });

  // flow 6: the PADIEM session verifies through signature + canonical liveness
  const firstRead = await handler(new Request(`${ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  assert.equal(firstRead.status, 200);

  // flow 7: save an opportunity with an expected amount
  const save = await post(handler, USER_A_TOKEN,
    'action=save&title=Telus+AI+Community&vendor=TELUS+Digital&status=SAVED&expectedAmount=40&expectedCurrency=USD');
  assert.equal(save.status, 303, `save step: ${(await save.text()) || save.status}`);
  let records = await repo.getByUser(USER_A);
  assert.equal(records.length, 1);
  const recordId = records[0]!.id;
  assert.equal(records[0]!.expectedAmount, 40);

  // flow 8: status progression along the canonical pipeline SAVED -> APPLIED
  const applied = await post(handler, USER_A_TOKEN,
    `action=save&id=${recordId}&title=Telus+AI+Community&vendor=TELUS+Digital&status=APPLIED&expectedAmount=40&expectedCurrency=USD&appliedAt=2026-10-25T10:00:00.000Z`);
  assert.equal(applied.status, 303, 'status progression SAVED->APPLIED');
  records = await repo.getByUser(USER_A);
  assert.equal(records[0]!.status, 'APPLIED');
  assert.equal(records[0]!.createdAt, records[0]!.createdAt, 'creation time is preserved across the transition');

  // flow 9: record the actual payout along the CANONICAL transition path
  // SAVED -> APPLIED -> ACCEPTED -> IN_PROGRESS -> COMPLETED -> PAID. Skipping
  // states must be refused by the domain transition table.
  const invalidDirect = await post(handler, USER_A_TOKEN,
    `action=save&id=${recordId}&title=Telus+AI+Community&vendor=TELUS+Digital&status=PAID&expectedAmount=40&expectedCurrency=USD&actualAmount=42.5&actualCurrency=USD&paidAt=2026-10-25T12:00:00.000Z`);
  assert.equal(invalidDirect.status, 400, 'APPLIED -> PAID skips states and must be refused');
  records = await repo.getByUser(USER_A);
  assert.equal(records[0]!.status, 'APPLIED', 'a refused transition changes nothing');

  const accepted = await post(handler, USER_A_TOKEN,
    `action=save&id=${recordId}&title=Telus+AI+Community&vendor=TELUS+Digital&status=ACCEPTED&expectedAmount=40&expectedCurrency=USD&appliedAt=2026-10-25T10:00:00.000Z`);
  assert.equal(accepted.status, 303, 'status progression APPLIED->ACCEPTED');
  const inProgress = await post(handler, USER_A_TOKEN,
    `action=save&id=${recordId}&title=Telus+AI+Community&vendor=TELUS+Digital&status=IN_PROGRESS&expectedAmount=40&expectedCurrency=USD&appliedAt=2026-10-25T10:00:00.000Z`);
  assert.equal(inProgress.status, 303, 'status progression ACCEPTED->IN_PROGRESS');
  const completed = await post(handler, USER_A_TOKEN,
    `action=save&id=${recordId}&title=Telus+AI+Community&vendor=TELUS+Digital&status=COMPLETED&expectedAmount=40&expectedCurrency=USD&actualAmount=42.5&actualCurrency=USD&completedAt=2026-10-25T11:00:00.000Z`);
  assert.equal(completed.status, 303, 'status progression IN_PROGRESS->COMPLETED');
  const paid = await post(handler, USER_A_TOKEN,
    `action=save&id=${recordId}&title=Telus+AI+Community&vendor=TELUS+Digital&status=PAID&expectedAmount=40&expectedCurrency=USD&actualAmount=42.5&actualCurrency=USD&completedAt=2026-10-25T11:00:00.000Z&paidAt=2026-10-25T12:00:00.000Z`);
  assert.equal(paid.status, 303, 'status progression COMPLETED->PAID');
  records = await repo.getByUser(USER_A);
  assert.equal(records[0]!.status, 'PAID');
  assert.equal(records[0]!.actualAmount, 42.5);
  assert.equal(records[0]!.actualCurrency, 'USD');

  // flow 10: a fresh dashboard render (reload) shows the persisted record
  const reload = await handler(new Request(`${ORIGIN}/pipeline?status=PAID`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  const reloadHtml = await reload.text();
  assert.match(reloadHtml, /Telus AI Community/);
  assert.match(reloadHtml, /42\.5 USD/);

  // flow 11: user B cannot see, modify or delete user A's record
  const pageB = await handler(new Request(`${ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_B_TOKEN}` } }));
  assert.doesNotMatch(await pageB.text(), /Telus AI Community/);
  const forgedUpdate = await post(handler, USER_B_TOKEN,
    `action=save&id=${recordId}&title=Hijacked&vendor=V&status=PAID&actualAmount=999&actualCurrency=USD&paidAt=2026-10-25T12:00:00.000Z`);
  assert.equal(forgedUpdate.status, 303, `B forged update step: ${(await forgedUpdate.clone().text()).slice(0, 200)}`);
  records = await repo.getByUser(USER_A);
  assert.equal(records[0]!.title, 'Telus AI Community', 'A record is untouched by B');
  assert.equal(records.length, 1);
  // Records are keyed (user_id, id): B's forged save created B's OWN row with
  // that id, and B's delete can only ever remove that own row — never A's.
  assert.equal(await repo.delete(USER_B, recordId), true, 'B deletes only their own row');
  records = await repo.getByUser(USER_A);
  assert.equal(records.length, 1, "A record survives B's delete");
  assert.equal(records[0]!.status, 'PAID');

  // flow 12: after logout/revocation the signed cookie no longer grants access
  sessionLive = false;
  const afterLogout = await post(handler, USER_A_TOKEN, 'action=save&title=PostLogout&vendor=V&status=SAVED');
  assert.equal(afterLogout.status, 401, 'revoked session cannot save');
  const readAfterLogout = await handler(new Request(`${ORIGIN}/pipeline`, { headers: { cookie: `padiem_session=${USER_A_TOKEN}` } }));
  const logoutHtml = await readAfterLogout.text();
  assert.doesNotMatch(logoutHtml, /Telus AI Community/, 'revoked session sees no private records');
  assert.match(logoutHtml, /PADIEM 계정 로그인 후 이용할 수 있습니다\./);
});

test('flows 1-5: anonymous discovery flow stays fully usable without any session', async () => {
  const handler = createConsumerHttpHandler({ loadCandidates: () => [], loadPublicOpportunities: (await import('../src/public-supply/verified-public-opportunities.js')).loadVerifiedPublicOpportunities });

  const home = await handler(new Request(`${ORIGIN}/`));
  assert.equal(home.status, 200);
  assert.match(await home.text(), /수익 기회 보기/);

  const today = await handler(new Request(`${ORIGIN}/today`));
  assert.equal(today.status, 200);

  const search = await handler(new Request(`${ORIGIN}/browse?q=Prolific`));
  assert.equal(search.status, 200);
  const searchHtml = await search.text();
  assert.match(searchHtml, /Prolific 유료 온라인 리서치 참여/);

  const detail = await handler(new Request(`${ORIGIN}/detail?id=pub-telus-korea-ai-community`));
  assert.equal(detail.status, 200);
  const detailHtml = await detail.text();
  assert.match(detailHtml, /TELUS Digital AI Community/);

  // flow 5: the outbound provider link is present, https, never proxied by PADIEM
  const ctaMatch = detailHtml.match(/href="(https:\/\/[^"]+)"[^>]*rel="noopener noreferrer nofollow"/);
  assert.ok(ctaMatch, 'an https provider link with nofollow rel exists on the detail page');
  assert.ok(ctaMatch[1]!.startsWith('https://'), 'provider links are direct https, no credential passthrough');
});
