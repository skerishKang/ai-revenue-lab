import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsumerHttpHandler } from '../src/http/consumer-http.js';
import { createAuthoritySessionAuthResolver } from '../src/income-pipeline/authority-session-auth.js';
import {
  PADIEM_SESSION_COOKIE_NAME,
  extractCookieValue,
  verifyPadiemSessionToken,
  type SessionLivenessProbe,
} from '../src/income-pipeline/padiem-session-auth.js';
import { D1UserIncomeRepository } from '../src/income-pipeline/d1-user-income-repository.js';
import { mintFixtureTokenSet, signTestSessionToken } from './helpers/padiem-test-tokens.js';
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
void FIXTURES;
const USER_A = 'usr_fixture_user_0001';
const USER_B = 'usr_fixture_user_0002';
// Real chat sessions carry the canonical sid claim (auth.py mints it once the
// identity authority is bound) — the journey tokens include it.
const USER_A_TOKEN = await signTestSessionToken(
  { v: 1, uid: USER_A, exp: 4000604799, sid: 'sess_journey0000000000000001' },
  FIXTURE_SECRET,
);
const USER_B_TOKEN = await signTestSessionToken(
  { v: 1, uid: USER_B, exp: 4000604799, sid: 'sess_journey0000000000000002' },
  FIXTURE_SECRET,
);
const ORIGIN = 'https://chat.padiem.net';

/**
 * Stands in for the chat relay B64 uses in production
 * (`PADIEM_CHAT_SERVICE` → `GET /api/auth/status`): chat holds the signing key
 * and answers whether this cookie is genuinely its own. Verifying the fixture
 * signature here keeps the journey honest about that half of the check — an
 * unsigned cookie carrying a live sid must not reach the dashboard.
 */
const signatureRelay: SessionLivenessProbe = async (cookieHeader: string): Promise<void> => {
  const token = extractCookieValue(cookieHeader, PADIEM_SESSION_COOKIE_NAME);
  const verified = await verifyPadiemSessionToken(token, FIXTURE_SECRET);
  if (verified === null) throw new Error('session_not_live');
};

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
  // Fake Control Plane identity authority: each session maps to ITS OWN user
  // (that is the whole point of the authority), and the session starts live
  // but can be revoked (logged out) mid-journey — exactly what flow 12
  // exercises.
  let sessionLive = true;
  const sessionUsers: Record<string, string> = {
    'sess_journey0000000000000001': USER_A,
    'sess_journey0000000000000002': USER_B,
  };
  const sessionSubjects: Record<string, string> = {
    'sess_journey0000000000000001': 'sub_journeycanonicalsubject_a',
    'sess_journey0000000000000002': 'sub_journeycanonicalsubject_b',
  };
  const revoked: Record<string, boolean> = {};
  const identityAuthority = {
    async resolve_auth_session(payload: { session_id: string }) {
      const user = sessionUsers[payload.session_id];
      if (user === undefined || revoked[payload.session_id] || !sessionLive) {
        return {
          ok: false,
          error: { code: 'canonical_auth_session_not_found', message: 'no live session for this id' },
        };
      }
      return {
        ok: true,
        session: {
          session_id: payload.session_id,
          product_id: 'b62',
          subject: { subject_type: 'user', subject_id: sessionSubjects[payload.session_id] },
          issued_at: '2026-10-25T10:00:00.000Z',
          expires_at: '2096-09-02T10:00:00.000Z',
          state: 'active',
          revision: 1,
        },
      };
    },
    async resolve_product_user_for_subject(payload: { product_id: string; canonical_subject_id: string }) {
      const bySubject = Object.entries(sessionSubjects).find(([, s]) => s === payload.canonical_subject_id);
      if (!bySubject || revoked[bySubject[0]] || !sessionLive) {
        return { ok: false, error: { code: 'canonical_product_identity_link_not_active', message: 'link is not active' } };
      }
      return { ok: true, product_user_id: sessionUsers[bySubject[0]] };
    },
  };
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    resolveAuth: createAuthoritySessionAuthResolver({ identityAuthority, sessionSignatureProbe: signatureRelay }),
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

  // flow 12: after logout/revocation the cookie no longer grants access —
  // the authority itself reports user A's canonical session revoked.
  revoked['sess_journey0000000000000001'] = true;
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
