import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createPadiemSessionAuthResolver,
  extractCookieValue,
  verifyPadiemSessionToken,
} from '../src/income-pipeline/padiem-session-auth.js';
import { mintFixtureTokenSet, mintWithRealChatAuthority } from './helpers/padiem-test-tokens.js';

/**
 * Session verification test suite.
 *
 * Tokens are minted at RUNTIME, never committed: signed HMAC blobs are
 * indistinguishable from real credentials to secret scanners, and the
 * repository rules keep credential-like material out of source. The
 * deterministic reject/accept matrix below runs everywhere via the TS
 * minting helper; the cross-language matrix additionally mints with the REAL
 * B62 authority (apps/padiem-chat/app/auth.py) through a python subprocess
 * and is skipped only when python or the chat app is unavailable.
 */
const FIXTURE_SECRET = 'b64-fixture-session-secret-0123456789abcdef';
const ISSUED_AT = 3999999999;
const MAX_AGE = 604800; // chat default; exp = 4000604799
const AUTHORIZED_AT = ISSUED_AT + 100;

const FIXTURES = await mintFixtureTokenSet(FIXTURE_SECRET, ISSUED_AT, MAX_AGE);
const { validToken, validTokenWithSid } = FIXTURES;

const REJECTED_TOKENS: readonly [string, string][] = [
  ['expired token', FIXTURES.expiredToken],
  ['wrong purpose (oauth-state token)', FIXTURES.wrongPurposeToken],
  ['wrong secret', FIXTURES.wrongSecretToken],
  ['uid without usr_ prefix', FIXTURES.badUidToken],
  ['uid longer than 80 chars', FIXTURES.longUidToken],
  ['empty uid', FIXTURES.emptyUidToken],
  ['malformed sid', FIXTURES.badSidToken],
  ['wrong payload version', FIXTURES.wrongVersionToken],
  ['non-dict payload', FIXTURES.nonDictPayloadToken],
  ['tampered body', FIXTURES.tamperedBodyToken],
  ['tampered signature', FIXTURES.tamperedSigToken],
];

test('verifier accepts well-formed signed session tokens', async () => {
  const claims = await verifyPadiemSessionToken(validToken, FIXTURE_SECRET, AUTHORIZED_AT);
  assert.ok(claims);
  assert.equal(claims.userId, 'usr_fixture_user_0001');
  assert.equal(claims.canonicalSessionId, null);

  const claimsWithSid = await verifyPadiemSessionToken(validTokenWithSid, FIXTURE_SECRET, AUTHORIZED_AT);
  assert.ok(claimsWithSid);
  assert.equal(claimsWithSid.userId, 'usr_fixture_user_0002');
  assert.equal(claimsWithSid.canonicalSessionId, 'sess_FixtureCanonical-0001');
});

test('verifier rejects every out-of-contract token', async () => {
  for (const [label, token] of REJECTED_TOKENS) {
    const claims = await verifyPadiemSessionToken(token, FIXTURE_SECRET, AUTHORIZED_AT);
    assert.equal(claims, null, `expected rejection: ${label}`);
  }
});

test('verifier fails closed on missing inputs and malformed shapes', async () => {
  assert.equal(await verifyPadiemSessionToken(validToken, undefined, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken(validToken, '', AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken(null, FIXTURE_SECRET, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken('', FIXTURE_SECRET, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken('not-a-token', FIXTURE_SECRET, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken('.no-body', FIXTURE_SECRET, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken('body-only', FIXTURE_SECRET, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken(`${validToken}.extra`, FIXTURE_SECRET, AUTHORIZED_AT), null);
  assert.equal(await verifyPadiemSessionToken('!!!.####', FIXTURE_SECRET, AUTHORIZED_AT), null);
});

test('verifier honours expiry at the exact second boundary like the Python authority', async () => {
  // exp = ISSUED_AT + MAX_AGE: valid at exp, invalid at exp+1 (Python: exp < now).
  assert.ok(await verifyPadiemSessionToken(validToken, FIXTURE_SECRET, ISSUED_AT + MAX_AGE));
  assert.equal(await verifyPadiemSessionToken(validToken, FIXTURE_SECRET, ISSUED_AT + MAX_AGE + 1), null);
});

test('cookie parser returns the last occurrence of the session cookie', () => {
  assert.equal(
    extractCookieValue('other=1; padiem_session=abc; another=2', 'padiem_session'),
    'abc',
  );
  assert.equal(
    extractCookieValue('padiem_session=first; padiem_session=second', 'padiem_session'),
    'second',
  );
  assert.equal(extractCookieValue('other=1', 'padiem_session'), null);
  assert.equal(extractCookieValue('padiem_session_extra=x; padiem_session=ok', 'padiem_session'), 'ok');
});

test('resolver authenticates the verified uid from the session cookie only', async () => {
  const resolver = createPadiemSessionAuthResolver({ sessionSecret: FIXTURE_SECRET });
  const request = new Request('https://b64.example/pipeline', {
    headers: {
      cookie: `padiem_session=${validToken}`,
      // forged client identity headers must be irrelevant
      'x-padiem-user-id': 'usr_attacker_999',
      authorization: 'Bearer attacker-token',
    },
  });
  const result = await resolver(request);
  assert.deepEqual(result, { authenticated: true, userId: 'usr_fixture_user_0001' });
});

test('resolver fails closed without a valid cookie or secret', async () => {
  const resolver = createPadiemSessionAuthResolver({ sessionSecret: FIXTURE_SECRET });
  for (const [label, headers] of [
    ['no cookie', {}],
    ['unrelated cookie', { cookie: 'other=1' }],
    ['wrong cookie name', { cookie: 'padiem_sessionx=x' }],
    ['expired session', { cookie: `padiem_session=${FIXTURES.expiredToken}` }],
    ['forged bearer only', { authorization: 'Bearer whatever' }],
    ['forged identity header only', { 'x-padiem-user-id': 'usr_victim_0001' }],
  ] as const) {
    const result = await resolver(new Request('https://b64.example/pipeline', { headers }));
    assert.deepEqual(result, { authenticated: false, userId: null }, label);
  }

  const noSecret = createPadiemSessionAuthResolver({ sessionSecret: undefined });
  const withValidCookie = await noSecret(
    new Request('https://b64.example/pipeline', { headers: { cookie: `padiem_session=${validToken}` } }),
  );
  assert.deepEqual(withValidCookie, { authenticated: false, userId: null });
});

test('resolver keeps the verified purpose: a chat oauth-state token is not a session', async () => {
  const resolver = createPadiemSessionAuthResolver({ sessionSecret: FIXTURE_SECRET });
  const result = await resolver(
    new Request('https://b64.example/pipeline', { headers: { cookie: `padiem_session=${FIXTURES.wrongPurposeToken}` } }),
  );
  assert.deepEqual(result, { authenticated: false, userId: null });
});

test('cross-language: tokens minted by the REAL B62 authority verify identically', async (t) => {
  const realValid = await mintWithRealChatAuthority(FIXTURE_SECRET, 'usr_real_authority_user', ISSUED_AT, MAX_AGE);
  const realWithSid = await mintWithRealChatAuthority(
    FIXTURE_SECRET,
    'usr_real_authority_user_2',
    ISSUED_AT,
    MAX_AGE,
    'sess_RealCanonical-0001',
  );
  if (realValid === null || realWithSid === null) {
    t.skip('python or apps/padiem-chat/app/auth.py unavailable in this environment');
    return;
  }
  const claims = await verifyPadiemSessionToken(realValid, FIXTURE_SECRET, AUTHORIZED_AT);
  assert.ok(claims, 'the TS verifier must accept a token the real Python authority minted');
  assert.equal(claims.userId, 'usr_real_authority_user');
  assert.equal(claims.canonicalSessionId, null);

  const claimsWithSid = await verifyPadiemSessionToken(realWithSid, FIXTURE_SECRET, AUTHORIZED_AT);
  assert.ok(claimsWithSid);
  assert.equal(claimsWithSid.userId, 'usr_real_authority_user_2');
  assert.equal(claimsWithSid.canonicalSessionId, 'sess_RealCanonical-0001');

  // The real authority's expired token must be rejected here as well.
  const realExpired = await mintWithRealChatAuthority(FIXTURE_SECRET, 'usr_real_authority_user', 1000000000, MAX_AGE);
  if (realExpired !== null) {
    assert.equal(await verifyPadiemSessionToken(realExpired, FIXTURE_SECRET, AUTHORIZED_AT), null);
  }
});
