import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject } from '../worker.mjs';

const origin = 'https://auth.padiem.net';
const SECRET = 'synthetic-account-delete-secret-32chars';
const PATH = '/internal/account-sessions/revoke';
const SESSION_ONE = 'A'.repeat(43);
const SESSION_TWO = 'B'.repeat(43);
const OBJ_ONE = 'O'.repeat(43);
const OBJ_TWO = 'P'.repeat(43);

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    sql: {
      exec(q, ...p) {
        const stmt = db.prepare(q);
        if (stmt.columns().length) return { toArray: () => stmt.all(...p) };
        stmt.run(...p);
        return { toArray: () => [] };
      },
    },
    transactionSync(fn) {
      db.exec('BEGIN');
      try { const out = fn(); db.exec('COMMIT'); return out; } catch (error) { db.exec('ROLLBACK'); throw error; }
    },
  };
}

async function setup() {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey);
  publicSigning.kid = 'auth';
  const objects = new Map();
  let queue = Promise.resolve();
  const stateFor = (id) => {
    if (!objects.has(id)) {
      const state = {
        storage: storage(),
        blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; },
      };
      objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, {}) : new AuthState(state));
    }
    return objects.get(id);
  };
  const app = createApp({
    clients: {},
    googleClientId: 'google-client',
    googleClientSecret: 'synthetic',
    identityKey,
    refreshKey,
    adminSecret: 'synthetic-admin-secret',
    accountDeleteRpcSecret: SECRET,
    passwordRpcSecret: 'synthetic-password-rpc-secret-32chars-min',
    passwordRpcOrigin: 'https://chat.padiem.net',
    signingKey: signing.privateKey,
    signingKid: 'auth',
    jwks: { keys: [publicSigning] },
    stateFor,
    now: () => 1000,
    fetcher: async () => { throw new Error('no fetch expected'); },
  });
  return { app, stateFor, objects };
}

function signedHeaders(body) {
  const at = '1000';
  const serviceId = randomUUID();
  const raw = Buffer.from(JSON.stringify(body));
  const canonical = Buffer.concat([
    Buffer.from(`v2\nPOST\n${PATH}\n${at}\n${serviceId}\n`, 'utf8'),
    raw,
  ]);
  const proof = 'v2=' + createHmac('sha256', SECRET).update(canonical).digest('hex');
  return {
    headers: {
      'content-type': 'application/json',
      'content-length': String(raw.length),
      'x-padiem-service-at': at,
      'x-padiem-service-id': serviceId,
      'x-padiem-service-proof': proof,
    },
    raw,
  };
}

async function seed(stateFor) {
  const registry = stateFor('google-account-registry');
  registry.putAccount({ fingerprint: 'fp1', accountId: 'sub_one', productUserId: 'usr_one', now: 900 });
  registry.putAccount({ fingerprint: 'fp2', accountId: 'sub_two', productUserId: 'usr_two', now: 900 });
  const one = stateFor(OBJ_ONE);
  const two = stateFor(OBJ_TWO);
  one.createSession({ id: SESSION_ONE, client: 'b62', subject: 'sub_one', accountId: 'sub_one', expires: 5000, digest: 'digest-one' });
  two.createSession({ id: SESSION_TWO, client: 'b62', subject: 'sub_two', accountId: 'sub_two', expires: 5000, digest: 'digest-two' });
  registry.indexAccountSession({ accountId: 'sub_one', objectId: OBJ_ONE, sessionId: SESSION_ONE, expires: 5000, now: 1000 });
  registry.indexAccountSession({ accountId: 'sub_two', objectId: OBJ_TWO, sessionId: SESSION_TWO, expires: 5000, now: 1000 });
}

function revoked(state, id) {
  return state.sql.exec('SELECT revoked FROM sessions WHERE id=?', id).toArray()[0]?.revoked === 1;
}

test('revokes only the mapped Chat user sessions and reports the count', async () => {
  const { app, stateFor } = await setup();
  await seed(stateFor);
  const signed = signedHeaders({ product_id: 'b62', product_user_id: 'usr_one' });
  const response = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signed.headers, body: signed.raw,
  }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, accounts: 1, revoked_sessions: 1 });
  assert.equal(revoked(stateFor(OBJ_ONE), SESSION_ONE), true);
  assert.equal(revoked(stateFor(OBJ_TWO), SESSION_TWO), false);
});

test('unknown Chat user is a bounded no-op', async () => {
  const { app, stateFor } = await setup();
  await seed(stateFor);
  const signed = signedHeaders({ product_id: 'b62', product_user_id: 'usr_unknown' });
  const response = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signed.headers, body: signed.raw,
  }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, accounts: 0, revoked_sessions: 0 });
});

test('refuses unsigned calls and non-Chat product payloads', async () => {
  const { app } = await setup();
  const unsigned = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}',
  }));
  assert.equal(unsigned.status, 401);
  const signed = signedHeaders({ product_id: 'b61', product_user_id: 'usr_one' });
  const invalid = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signed.headers, body: signed.raw,
  }));
  assert.equal(invalid.status, 400);
});

test('the same signed call cannot be replayed', async () => {
  const { app, stateFor } = await setup();
  await seed(stateFor);
  const signed = signedHeaders({ product_id: 'b62', product_user_id: 'usr_one' });
  const first = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signed.headers, body: signed.raw,
  }));
  assert.equal(first.status, 200);
  const second = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signed.headers, body: signed.raw,
  }));
  assert.equal(second.status, 409);
});

test('Google b62 resolveAccount indexes product_user_id and optional account_id revokes pre-indexed sessions', async () => {
  const { app, stateFor } = await setup();
  const registry = stateFor('google-account-registry');
  registry.env = {
    IDENTITY_AUTHORITY: {
      async resolve_or_create_product_link(req) {
        return {
          ok: true,
          link: {
            state: 'active',
            product_id: req.product_id,
            product_user_id: req.product_user_id,
            canonical_subject_id: 'sub_google_b62',
          },
        };
      },
    },
  };
  await registry.resolveAccount({
    fingerprint: 'fp-google-b62',
    productId: 'b62',
    userId: 'usr_google_one',
    subject: 'google-sub-1',
    provider: 'google',
    now: 950,
  });
  const googleSession = 'G'.repeat(43);
  stateFor(OBJ_ONE).createSession({
    id: googleSession, client: 'b62', subject: 'sub_google_b62', accountId: 'sub_google_b62',
    expires: 5000, digest: 'digest-google',
  });
  registry.indexAccountSession({
    accountId: 'sub_google_b62', objectId: OBJ_ONE, sessionId: googleSession, expires: 5000, now: 1000,
  });

  const signed = signedHeaders({ product_id: 'b62', product_user_id: 'usr_google_one' });
  const response = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signed.headers, body: signed.raw,
  }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, accounts: 1, revoked_sessions: 1 });
  assert.equal(revoked(stateFor(OBJ_ONE), googleSession), true);

  // Pre-existing Google account without an account_chat_users row is still
  // revoked when the caller also supplies its verified canonical account_id.
  registry.putAccount({ fingerprint: 'fp-legacy-google', accountId: 'sub_legacy_g', now: 900 });
  const legacySession = 'L'.repeat(43);
  stateFor(OBJ_TWO).createSession({
    id: legacySession, client: 'b62', subject: 'sub_legacy_g', accountId: 'sub_legacy_g',
    expires: 5000, digest: 'digest-legacy-g',
  });
  registry.indexAccountSession({
    accountId: 'sub_legacy_g', objectId: OBJ_TWO, sessionId: legacySession, expires: 5000, now: 1000,
  });
  const signedWithAccount = signedHeaders({
    product_id: 'b62', product_user_id: 'usr_unmapped_legacy', account_id: 'sub_legacy_g',
  });
  const res2 = await app.fetch(new Request(origin + PATH, {
    method: 'POST', headers: signedWithAccount.headers, body: signedWithAccount.raw,
  }));
  assert.equal(res2.status, 200);
  assert.deepEqual(await res2.json(), { ok: true, accounts: 1, revoked_sessions: 1 });
  assert.equal(revoked(stateFor(OBJ_TWO), legacySession), true);
});

test('account-block marks indexed sessions revoked immediately', async () => {
  const { app, stateFor } = await setup();
  await seed(stateFor);
  const res = await app.fetch(new Request(origin + '/internal/account-block', {
    method: 'POST',
    headers: {
      authorization: 'Bearer synthetic-admin-secret',
      'content-type': 'application/json',
    },
    body: JSON.stringify({ account_id: 'sub_one' }),
  }));
  assert.equal(res.status, 200);
  assert.equal(revoked(stateFor(OBJ_ONE), SESSION_ONE), true);
  assert.equal(revoked(stateFor(OBJ_TWO), SESSION_TWO), false);
});

