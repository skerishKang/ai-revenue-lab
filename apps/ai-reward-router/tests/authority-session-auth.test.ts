import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createAuthoritySessionAuthResolver,
  extractCookieSessionId,
  type ControlPlaneIdentityAuthority,
} from '../src/income-pipeline/authority-session-auth.js';

/**
 * Focused tests for the Control Plane authority session resolver
 * (issue #987): the deployment authentication path that resolves the
 * cookie's canonical session id against the identity authority — WITHOUT
 * the chat session signing secret — and blocks everything the authority
 * does not positively confirm as an active b62 session of a user.
 */

const SUB = 'sub_livecanonicalsubject01';
const UID = 'usr_resolved_via_authority';

function makeCookieToken(sid: string, uid = 'usr_forged_by_attacker'): string {
  // Payload is plain base64url JSON — deliberately built WITHOUT a valid HMAC
  // signature to prove the resolver derives identity from the AUTHORITY, not
  // from cookie contents.
  const payload = Buffer.from(JSON.stringify({ v: 1, uid, exp: 4000604799, sid }), 'utf8')
    .toString('base64url');
  return `${payload}.nosignature`;
}

function activeSession(payloadSessionId: string) {
  return {
    session_id: payloadSessionId,
    product_id: 'b62',
    subject: { subject_type: 'user', subject_id: SUB },
    issued_at: '2026-10-25T10:00:00.000Z',
    expires_at: '2096-09-02T10:00:00.000Z',
    state: 'active',
    revision: 1,
  };
}

interface AuthorityScript {
  sessionResponse?: unknown;
  linkResponse?: unknown;
  sessionThrows?: boolean;
  linkThrows?: boolean;
  seenSessionId?: string;
  seenSubject?: string;
}

function scriptedAuthority(script: AuthorityScript): ControlPlaneIdentityAuthority & {
  calls: string[];
  seenSessionId?: string;
  seenSubject?: string;
} {
  const calls: string[] = [];
  const fake: ControlPlaneIdentityAuthority & { calls: string[]; seenSessionId?: string; seenSubject?: string } = {
    calls,
    async resolve_auth_session(payload: { session_id: string }) {
      calls.push(`resolve_auth_session:${payload.session_id}`);
      fake.seenSessionId = payload.session_id;
      if (script.sessionThrows) throw new Error('durable unavailable');
      return script.sessionResponse ?? { ok: true, session: activeSession(payload.session_id) };
    },
    async resolve_product_user_for_subject(payload: { product_id: string; canonical_subject_id: string }) {
      calls.push(`resolve_product_user_for_subject:${payload.canonical_subject_id}`);
      fake.seenSubject = payload.canonical_subject_id;
      if (script.linkThrows) throw new Error('durable unavailable');
      return script.linkResponse ?? { ok: true, product_user_id: UID };
    },
  };
  return fake;
}

function underTest(authority: ControlPlaneIdentityAuthority) {
  return createAuthoritySessionAuthResolver({ identityAuthority: authority });
}

const SID = 'sess_0123456789abcdef0123456789abcdef';

test('extractCookieSessionId reads only the sid claim and never trusts the payload uid', () => {
  const token = makeCookieToken(SID, 'usr_attacker_claim');
  const sid = extractCookieSessionId(token);
  assert.equal(sid, SID);
  // tampered sid shapes are refused before any authority call
  assert.equal(extractCookieSessionId(makeCookieToken('../../etc')), null);
  assert.equal(extractCookieSessionId(makeCookieToken('')), null);
  assert.equal(extractCookieSessionId('garbage'), null);
  assert.equal(extractCookieSessionId('AAAA.nosignature'), null, 'payload without sid is unusable');
});

test('resolver authenticates through the authority and uses ONLY its product user id', async () => {
  const authority = scriptedAuthority({});
  const underTestInstance = underTest(authority);
  const result = await underTestInstance(
    new Request('https://chat.padiem.net/pipeline', { headers: { cookie: `padiem_session=${makeCookieToken(SID, 'usr_attacker_claim')}` } }),
  );
  assert.deepEqual(result, { authenticated: true, userId: UID });
  assert.equal(authority.seenSessionId, SID);
  assert.equal(authority.seenSubject, SUB);
  assert.deepEqual(
    authority.calls.map((c) => c.split(':')[0]),
    ['resolve_auth_session', 'resolve_product_user_for_subject'],
  );
});

test('forged cookie uid cannot select a user — the authority answer wins', async () => {
  // Two tokens with the SAME sid but different attacker-chosen uid claims must
  // resolve to the SAME authority-derived user.
  const authority = scriptedAuthority({});
  const underTestInstance = underTest(authority);
  const first = await underTestInstance(
    new Request('https://chat.padiem.net/pipeline', { headers: { cookie: `padiem_session=${makeCookieToken(SID, 'usr_victim_0000')}` } }),
  );
  const second = await underTestInstance(
    new Request('https://chat.padiem.net/pipeline', { headers: { cookie: `padiem_session=${makeCookieToken(SID, 'usr_victim_1111')}` } }),
  );
  assert.deepEqual(first, second);
  assert.equal((first as { userId: string }).userId, UID);
});

test('every authority rejection fails closed', async () => {
  const cases: readonly [string, AuthorityScript][] = [
    ['unknown session id', { sessionResponse: { ok: false, error: { code: 'canonical_auth_session_not_found', message: 'x' } } }],
    ['revoked session', {
      sessionResponse: { ok: true, session: { ...activeSession(SID), state: 'revoked', revision: 2 } },
    }],
    ['expired session (authority field)', {
      sessionResponse: { ok: true, session: { ...activeSession(SID), state: 'expired' } },
    }],
    ['expiry in the past', {
      sessionResponse: { ok: true, session: { ...activeSession(SID), expires_at: '2020-01-01T00:00:00.000Z' } },
    }],
    ['wrong product', {
      sessionResponse: { ok: true, session: { ...activeSession(SID), product_id: 'b54-padiem-claw' } },
    }],
    ['subject not a user', {
      sessionResponse: { ok: true, session: { ...activeSession(SID), subject: { subject_type: 'service', subject_id: SUB } } },
    }],
    ['session id echo mismatch', {
      sessionResponse: { ok: true, session: activeSession('sess_different0123456789abcdef') },
    }],
    ['malformed session response', { sessionResponse: { unexpected: true } }],
    ['reverse lookup not ok', { linkResponse: { ok: false, error: { code: 'canonical_product_identity_link_not_active', message: 'x' } } }],
    ['reverse lookup uid malformed', { linkResponse: { ok: true, product_user_id: 'attacker_plain' } }],
  ];
  for (const entry of cases) {
    const label = entry[0]!;
    const script = entry[1]!;
    const underTestInstance = underTest(scriptedAuthority(script));
    const result = await underTestInstance(
      new Request('https://chat.padiem.net/pipeline', { headers: { cookie: `padiem_session=${makeCookieToken(SID)}` } }),
    );
    assert.deepEqual(result, { authenticated: false, userId: null }, label);
  }
});

test('authority transport failures fail closed (never open)', async () => {
  for (const entry of [
    ['session rpc throws', { sessionThrows: true } as AuthorityScript],
    ['link rpc throws', { linkThrows: true } as AuthorityScript],
  ] as const) {
    const label = entry[0];
    const script = entry[1];
    const underTestInstance = underTest(scriptedAuthority(script));
    const result = await underTestInstance(
      new Request('https://chat.padiem.net/pipeline', { headers: { cookie: `padiem_session=${makeCookieToken(SID)}` } }),
    );
    assert.deepEqual(result, { authenticated: false, userId: null }, label);
  }
});

test('a missing authority binding denies every request (fail closed)', async () => {
  const underTestInstance = createAuthoritySessionAuthResolver({ identityAuthority: undefined });
  for (const [label, headers] of [
    ['session cookie', { cookie: `padiem_session=${makeCookieToken(SID)}` }],
    ['no headers', {}],
    ['forged bearer only', { authorization: 'Bearer anything' }],
  ] as const) {
    const result = await underTestInstance(new Request('https://chat.padiem.net/pipeline', { headers }));
    assert.deepEqual(result, { authenticated: false, userId: null });
  }
});

test('requests without the session cookie keep their unauthenticated semantics', async () => {
  const underTestInstance = underTest(scriptedAuthority({}));
  const result = await underTestInstance(new Request('https://chat.padiem.net/pipeline'));
  assert.deepEqual(result, { authenticated: false, userId: null });
  assert.equal(scriptedAuthority({}).calls.length >= 0, true);
});

test('revoked sessions are blocked even while the reverse link still exists', async () => {
  // The link row (sub_ -> usr_) can outlive the session revocation; the
  // session state check must run FIRST and alone must deny access.
  const authority = scriptedAuthority({
    sessionResponse: { ok: true, session: { ...activeSession(SID), state: 'revoked', revision: 3 } },
    linkResponse: { ok: true, product_user_id: UID },
  });
  const underTestInstance = underTest(authority);
  const result = await underTestInstance(
    new Request('https://chat.padiem.net/pipeline', { headers: { cookie: `padiem_session=${makeCookieToken(SID)}` } }),
  );
  assert.deepEqual(result, { authenticated: false, userId: null });
  assert.deepEqual(authority.calls.map((c) => c.split(':')[0]), ['resolve_auth_session'], 'no reverse lookup runs for a revoked session');
});
