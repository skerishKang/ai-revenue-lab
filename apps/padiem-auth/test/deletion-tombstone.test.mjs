import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject, passwordIdentityFingerprint } from '../worker.mjs';

const ORIGIN = 'https://auth.padiem.net';
const REDIRECT = 'https://lovetree.example/auth/callback';
const DELETE_RPC_SECRET = 'synthetic-account-delete-secret-32chars';
const PASSWORD_RPC_SECRET = 'synthetic-password-rpc-secret-32chars-min';
const EMAIL = 'user@example.invalid';
const PASSWORD = 'correct-horse-battery';

const b64 = x => Buffer.from(x).toString('base64url');
const j64 = x => b64(JSON.stringify(x));
const sum = async x => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const sha256 = async x => [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)))]
  .map(b => b.toString(16).padStart(2, '0')).join('');

function storage() {
  const db = new DatabaseSync(':memory:');
  return {
    sql: {
      exec(q, ...p) {
        const stmt = db.prepare(q);
        if (stmt.columns().length) return { toArray: () => stmt.all(...p) };
        stmt.run(...p);
        return { toArray: () => [] };
      }
    },
    transactionSync(fn) {
      db.exec('BEGIN');
      try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; }
    }
  };
}

function signedDeletionRequest(accountId, {
  at = 1000,
  serviceId = randomUUID(),
  operationId = randomUUID(),
  path = '/internal/account-delete/prepare',
  secret = DELETE_RPC_SECRET
} = {}) {
  const body = Buffer.from(JSON.stringify({ account_id: accountId, operation_id: operationId }));
  const canonical = Buffer.concat([
    Buffer.from(`v2\nPOST\n${path}\n${at}\n${serviceId}\n`, 'utf8'),
    body
  ]);
  const proof = 'v2=' + createHmac('sha256', secret).update(canonical).digest('hex');
  return new Request(`${ORIGIN}${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-padiem-service-at': String(at),
      'x-padiem-service-id': serviceId,
      'x-padiem-service-proof': proof
    },
    body
  });
}

function registryWith(authorityCalls) {
  const authority = {
    async resolve_or_create_product_link(v) {
      authorityCalls.push(v);
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_new' } };
    }
  };
  const state = { storage: storage(), blockConcurrencyWhile(fn) { return fn(); } };
  return new AuthStateObject(state, { IDENTITY_AUTHORITY: authority });
}

test('last-link deletion records a fingerprint tombstone and no longer maps the account', async () => {
  const registry = registryWith([]);
  registry.putAccount({ fingerprint: 'fp-email', accountId: 'sub_old' });
  assert.equal(await registry.beginAccountDeletion({ accountId: 'sub_old', lockToken: 'op', now: 1000 }), true);
  assert.equal(await registry.finalizeAccountDeletion({ accountId: 'sub_old', accountIdHash: await sha256('sub_old'), lockToken: 'op', now: 1000 }), true);
  assert.equal(registry.identityIsDeleted({ fingerprint: 'fp-email' }), true);
  assert.equal(registry.accountByFingerprint('fp-email'), null);
});

test('a tombstoned identity cannot mint a new sub on login, but explicit sign-up may', async () => {
  const calls = [];
  const registry = registryWith(calls);
  registry.putAccount({ fingerprint: 'fp-email', accountId: 'sub_old' });
  await registry.beginAccountDeletion({ accountId: 'sub_old', lockToken: 'op', now: 1000 });
  await registry.finalizeAccountDeletion({ accountId: 'sub_old', accountIdHash: await sha256('sub_old'), lockToken: 'op', now: 1000 });
  await assert.rejects(
    () => registry.resolveAccount({ fingerprint: 'fp-email', productId: 'lovetree-4-0', userId: 'usr_test', subject: 'user@example.test', provider: 'password', now: 1100 }),
    /identity_deleted/
  );
  assert.equal(calls.length, 0, 'login must not reach the identity authority');
  registry.clearIdentityDeletion({ fingerprint: 'fp-email' });
  const created = await registry.resolveAccount({ fingerprint: 'fp-email', productId: 'lovetree-4-0', userId: 'usr_test', subject: 'user@example.test', provider: 'password', now: 1200, allowRecreate: true });
  assert.equal(created.account_id, 'sub_new');
  assert.equal(calls.length, 1);
});

test('passwordIdentityFingerprint normalizes email case and surrounding whitespace', async () => {
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const fpCanonical = await passwordIdentityFingerprint(identityKey, 'user@example.invalid');
  const fpUpper = await passwordIdentityFingerprint(identityKey, '  USER@Example.Invalid \n');
  assert.equal(fpUpper, fpCanonical);
});

async function setupFullFlow() {
  const google = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
  const googleJwk = await crypto.subtle.exportKey('jwk', google.publicKey); googleJwk.kid = 'google';
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const clientKey = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', clientKey.publicKey); publicClient.kid = 'client';

  let subjectSeq = 0;
  let userSeq = 0;
  let googleNonce = '';
  let failNextChatDelete = false;
  const chatUsers = new Map(); // email -> { userId, password }
  const chatCalls = [];
  const authorityCalls = [];
  const activeLinksBySubject = new Map(); // sub_ -> [{ product_id, product_user_id, state: 'active' }]

  const authority = {
    async resolve_or_create_product_link(v) {
      authorityCalls.push(v);
      const subId = `sub_gen_${++subjectSeq}`;
      const link = { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: subId };
      activeLinksBySubject.set(subId, [{ product_id: v.product_id, product_user_id: v.product_user_id, state: 'active' }]);
      return { ok: true, link };
    },
    async list_active_product_links_for_subject({ canonical_subject_id }) {
      return { ok: true, links: activeLinksBySubject.get(canonical_subject_id) || [] };
    }
  };

  const objects = new Map();
  let queue = Promise.resolve();
  const stateFor = id => {
    if (!objects.has(id)) {
      const state = {
        storage: storage(),
        blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; }
      };
      objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state));
    }
    return objects.get(id);
  };

  const app = createApp({
    clients: {
      'lovetree-4-0': { id: 'lovetree-4-0', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
      b62: { id: 'b62', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
    },
    googleClientId: 'google-client',
    googleClientSecret: 'synthetic',
    identityKey,
    refreshKey,
    adminSecret: 'synthetic-admin-secret',
    accountDeleteRpcSecret: DELETE_RPC_SECRET,
    passwordRpcSecret: PASSWORD_RPC_SECRET,
    passwordRpcOrigin: 'https://chat.padiem.net',
    signingKey: signing.privateKey,
    signingKid: 'auth',
    jwks: { keys: [publicSigning] },
    stateFor,
    now: () => 1000,
    async fetcher(address, options = {}) {
      const parsed = new URL(address);
      if (address.includes('googleapis.com/token')) {
        const h = j64({ alg: 'RS256', kid: 'google' });
        const p = j64({ iss: 'https://accounts.google.com', aud: 'google-client', sub: 'google-sub-1', email: EMAIL, email_verified: true, name: 'Test User', picture: '', nonce: googleNonce, iat: 999, exp: 1100 });
        const input = `${h}.${p}`;
        const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', google.privateKey, new TextEncoder().encode(input));
        return Response.json({ id_token: `${input}.${b64(sig)}` });
      }
      if (address.includes('googleapis.com/oauth2/v3/certs')) {
        return Response.json({ keys: [googleJwk] });
      }
      const path = parsed.pathname;
      const body = Buffer.from(options.body);
      const h = options.headers;
      const canonical = Buffer.concat([Buffer.from(`v2\nPOST\n${path}\n${h['x-padiem-service-at']}\n${h['x-padiem-service-id']}\n`, 'utf8'), body]);
      const proofValid = h['x-padiem-service-proof'] === 'v2=' + createHmac('sha256', PASSWORD_RPC_SECRET).update(canonical).digest('hex');
      const payload = JSON.parse(body.toString());
      chatCalls.push({ path, payload, proofValid });
      if (!proofValid) return Response.json({ error: { code: 'unauthorized' } }, { status: 401 });

      if (path === '/internal/password-register') {
        if (chatUsers.has(payload.email)) {
          return Response.json({ error: { code: 'account_exists' } }, { status: 409 });
        }
        const userId = `usr_chat_${++userSeq}`;
        chatUsers.set(payload.email, { userId, password: payload.password });
        return Response.json({ ok: true, product_user_id: userId });
      }
      if (path === '/internal/password-verify') {
        const rec = chatUsers.get(payload.email);
        if (!rec || rec.password !== payload.password) {
          return Response.json({ error: { code: 'invalid_credentials' } }, { status: 401 });
        }
        return Response.json({ ok: true, product_user_id: rec.userId });
      }
      if (path === '/internal/account-delete') {
        if (failNextChatDelete) {
          failNextChatDelete = false;
          return Response.json({ error: { code: 'account_delete_failed' } }, { status: 503 });
        }
        let deleted = false;
        for (const [emailKey, rec] of chatUsers.entries()) {
          if (rec.userId === payload.product_user_id) {
            chatUsers.delete(emailKey);
            deleted = true;
          }
        }
        return Response.json({ ok: true, deleted, already_deleted: !deleted });
      }
      throw new Error('unexpected fetch: ' + address);
    }
  });

  async function begin(path = '/login', clientId = 'lovetree-4-0') {
    const verifier = rand(), state = rand();
    const q = new URLSearchParams({ client_id: clientId, redirect_uri: REDIRECT, state, code_challenge: await sum(verifier), code_challenge_method: 'S256' });
    const response = await app.fetch(new Request(`${ORIGIN}${path}?${q}`));
    if (response.status === 302) {
      const loc = new URL(response.headers.get('location'));
      googleNonce = loc.searchParams.get('nonce') || '';
      return { verifier, state, response, googleState: loc.searchParams.get('state'), cookie: response.headers.get('set-cookie')?.split(';')[0] || '' };
    }
    const html = await response.text();
    const actionPath = path === '/signup' ? '/signup/password' : '/login/password';
    const match = html.match(new RegExp(actionPath.replace('/', '\\/') + '\\?state=([A-Za-z0-9._%-]+)'));
    return { verifier, state, response, html, cookie: response.headers.get('set-cookie')?.split(';')[0] || '', formState: match ? decodeURIComponent(match[1]) : '' };
  }

  async function postForm(actionPath, formState, cookie, fields) {
    return app.fetch(new Request(`${ORIGIN}${actionPath}?state=${encodeURIComponent(formState)}`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded', cookie },
      body: new URLSearchParams(fields)
    }));
  }

  return {
    app,
    begin,
    postForm,
    stateFor,
    chatUsers,
    chatCalls,
    authorityCalls,
    activeLinksBySubject,
    setFailNextChatDelete(val) { failNextChatDelete = val; }
  };
}

test('full lifecycle: signup -> prepare/abort keeps Chat data -> complete tombstones then deletes Chat -> email & Google login refused -> explicit signup creates fresh account', async () => {
  const f = await setupFullFlow();

  // 1. Explicit email signup on LoveTree creates usr_chat_1 and sub_gen_1.
  const signup1 = await f.begin('/signup', 'lovetree-4-0');
  const reg1 = await f.postForm('/signup/password', signup1.formState, signup1.cookie, { name: 'Alice', email: EMAIL, password: PASSWORD });
  assert.equal(reg1.status, 302);
  assert.equal(f.chatUsers.get(EMAIL)?.userId, 'usr_chat_1');
  assert.equal(f.authorityCalls.length, 1);

  // 2. Prepare + abort must NOT delete the Chat account (fixes 1)b order hazard).
  const abortOp = randomUUID();
  const prepAbort = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: abortOp, path: '/internal/account-delete/prepare' }));
  assert.equal(prepAbort.status, 200);
  assert.equal(f.chatCalls.some(c => c.path === '/internal/account-delete'), false, 'prepare must never call Chat /internal/account-delete');
  const aborted = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: abortOp, path: '/internal/account-delete/abort' }));
  assert.equal(aborted.status, 200);
  assert.equal(f.chatUsers.has(EMAIL), true, 'Chat account must survive an aborted prepare');

  // 3. Prepare -> authority link removal -> complete records tombstone FIRST, then deletes Chat account.
  const delOp = randomUUID();
  const prep = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: delOp, path: '/internal/account-delete/prepare' }));
  assert.equal(prep.status, 200);
  assert.equal(f.chatUsers.has(EMAIL), true, 'Chat account still untouched after prepare');
  f.activeLinksBySubject.delete('sub_gen_1');
  const comp = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: delOp, path: '/internal/account-delete/complete' }));
  assert.equal(comp.status, 200);
  assert.deepEqual(await comp.json(), { ok: true, deleted: true });
  assert.equal(f.chatUsers.has(EMAIL), false, 'Chat account deleted during complete');
  const deleteCalls = f.chatCalls.filter(c => c.path === '/internal/account-delete');
  assert.equal(deleteCalls.length, 1);
  assert.deepEqual(deleteCalls[0].payload, { product_user_id: 'usr_chat_1' });

  // 4. Email login with the deleted email (even with uppercase) is refused on both LoveTree and Chat screens, with a visible signup link.
  const callsBeforeLogin = f.chatCalls.length;
  const loginLt = await f.begin('/login', 'lovetree-4-0');
  const deniedLt = await f.postForm('/login/password', loginLt.formState, loginLt.cookie, { email: 'USER@Example.Invalid', password: PASSWORD });
  assert.equal(deniedLt.status, 200);
  const deniedLtHtml = await deniedLt.text();
  assert.ok(deniedLtHtml.includes('탈퇴한 계정입니다. 같은 이메일로 새로 가입해 주세요.'));
  assert.ok(deniedLtHtml.includes('/signup?'));

  const loginChat = await f.begin('/login', 'b62');
  const deniedChat = await f.postForm('/login/password', loginChat.formState, loginChat.cookie, { email: EMAIL, password: PASSWORD });
  assert.equal(deniedChat.status, 200);
  const deniedChatHtml = await deniedChat.text();
  assert.ok(deniedChatHtml.includes('탈퇴한 계정입니다. 같은 이메일로 새로 가입해 주세요.'));
  assert.ok(deniedChatHtml.includes('/signup?'), 'plain Chat login error screen must also link to /signup');
  assert.equal(f.chatCalls.length, callsBeforeLogin, 'tombstoned email login must not call Chat /internal/password-verify');
  assert.equal(f.authorityCalls.length, 1, 'tombstoned email login must not call identity authority');

  // 5. Explicit signup with the same email clears the tombstone and creates a fresh Chat user (usr_chat_2) and fresh canonical subject (sub_gen_2).
  const signup2 = await f.begin('/signup', 'lovetree-4-0');
  const reg2 = await f.postForm('/signup/password', signup2.formState, signup2.cookie, { name: 'Alice Reborn', email: EMAIL, password: 'new-password-12345' });
  assert.equal(reg2.status, 302);
  assert.equal(f.chatUsers.get(EMAIL)?.userId, 'usr_chat_2');
  assert.equal(f.authorityCalls.length, 2);
  assert.equal(f.authorityCalls[1].product_user_id, 'usr_chat_2');

  // 6. Google login -> delete -> Google login refused with 403.
  const gStart = await f.begin('/login/google', 'lovetree-4-0');
  const gCb1 = await f.app.fetch(new Request(`${ORIGIN}/oauth/google/callback?state=${encodeURIComponent(gStart.googleState)}&code=gcode1`, { headers: { cookie: gStart.cookie } }));
  assert.equal(gCb1.status, 302);
  assert.equal(f.authorityCalls.length, 3); // sub_gen_3

  const gDelOp = randomUUID();
  assert.equal((await f.app.fetch(signedDeletionRequest('sub_gen_3', { operationId: gDelOp, path: '/internal/account-delete/prepare' }))).status, 200);
  assert.equal((await f.app.fetch(signedDeletionRequest('sub_gen_3', { operationId: gDelOp, path: '/internal/account-delete/complete' }))).status, 200);

  const gStart2 = await f.begin('/login/google', 'lovetree-4-0');
  const gCb2 = await f.app.fetch(new Request(`${ORIGIN}/oauth/google/callback?state=${encodeURIComponent(gStart2.googleState)}&code=gcode2`, { headers: { cookie: gStart2.cookie } }));
  assert.equal(gCb2.status, 403);
  assert.ok((await gCb2.text()).includes('탈퇴한 계정입니다.'));
  assert.equal(f.authorityCalls.length, 3, 'tombstoned Google callback must not call identity authority');
});

test('mid-failure retry: if Chat /internal/account-delete fails during complete, tombstone is still committed and retry completes Chat cleanup', async () => {
  const f = await setupFullFlow();

  // Sign up user
  const signup = await f.begin('/signup', 'lovetree-4-0');
  const reg = await f.postForm('/signup/password', signup.formState, signup.cookie, { name: 'Retry User', email: EMAIL, password: PASSWORD });
  assert.equal(reg.status, 302);
  assert.equal(f.chatUsers.get(EMAIL)?.userId, 'usr_chat_1');

  // Prepare succeeds
  const opId = randomUUID();
  const prep = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: opId, path: '/internal/account-delete/prepare' }));
  assert.equal(prep.status, 200);

  // First complete call: simulate Chat /internal/account-delete returning 503
  f.setFailNextChatDelete(true);
  const comp1 = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: opId, path: '/internal/account-delete/complete' }));
  assert.equal(comp1.status, 503);

  // Even though Chat delete failed, the tombstone is ALREADY committed: login is blocked so user never sees an empty/half-deleted account!
  const loginAttempt = await f.begin('/login', 'lovetree-4-0');
  const denied = await f.postForm('/login/password', loginAttempt.formState, loginAttempt.cookie, { email: EMAIL, password: PASSWORD });
  assert.equal(denied.status, 200);
  assert.ok((await denied.text()).includes('탈퇴한 계정입니다.'));
  assert.equal(f.authorityCalls.length, 1);

  // Retry of /internal/account-delete/complete succeeds idempotently and deletes the Chat user!
  const comp2 = await f.app.fetch(signedDeletionRequest('sub_gen_1', { operationId: opId, path: '/internal/account-delete/complete' }));
  assert.equal(comp2.status, 200);
  assert.deepEqual(await comp2.json(), { ok: true, deleted: true });
  assert.equal(f.chatUsers.has(EMAIL), false);
  assert.deepEqual(f.stateFor('google-account-registry').pendingChatAccountDeletions(), []);
});
