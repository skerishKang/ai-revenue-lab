import { AuthState } from './state.mjs';
import { verifyGoogleIdToken } from './google-id-token.mjs';
import { issueAccessToken } from './access-token.mjs';
import { verifyClientAssertion } from './client-assertion.mjs';
import { profileClaimAllowlist, verifiedProfile } from './profile-claims.mjs';

const ORIGIN = 'https://auth.padiem.net';
const CALLBACK = `${ORIGIN}/oauth/google/callback`;
const encoder = new TextEncoder();
const opaque = /^[A-Za-z0-9_-]{43}$/;
const validClient = /^[A-Za-z0-9_-]+$/;
const cookie = '__Host-padiem-auth-state';
const b64 = (a) => btoa(String.fromCharCode(...a)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const un64 = (s) => Uint8Array.from(atob(s.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(s.length / 4) * 4, '=')), c => c.charCodeAt(0));
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const digest = async (s) => b64(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(s))));
export async function identityFingerprint(key, subject) {
  if (!key || key.algorithm?.name !== 'HMAC') throw new Error('identity key unavailable');
  return b64(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(`padiem-auth:google:v1\0${subject}`))));
}
export async function googleProductUserId(subject) {
  if (typeof subject !== 'string' || !/^[\x21-\x7e]{1,255}$/.test(subject)) throw new Error('invalid google subject');
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(`google:${subject}`)));
  return 'usr_' + [...hash].map(x => x.toString(16).padStart(2, '0')).join('').slice(0, 32);
}
const epoch = () => Math.floor(Date.now() / 1000);
const headers = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };
const json = (status, value) => new Response(JSON.stringify(value), { status, headers: { ...headers, 'content-type': 'application/json' } });
const redirect = (location, extra = {}) => new Response(null, { status: 302, headers: { ...headers, location, ...extra } });
const split = (token) => {
  if (typeof token !== 'string') return null;
  const parts = token.split('.');
  return parts.length === 2 && parts.every(x => opaque.test(x)) ? parts : null;
};
const cookieValue = (request) => {
  const matches = (request.headers.get('cookie') || '').split(';').map(x => x.trim()).filter(x => x.startsWith(`${cookie}=`));
  return matches.length === 1 ? matches[0].slice(cookie.length + 1) : '';
};
const cookieHeader = (value, maxAge) => `${cookie}=${value}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
function one(params, name) {
  const values = params.getAll(name);
  return values.length === 1 ? values[0] : '';
}

async function diagnosed(stage, operation) {
    try { return await operation(); }
    catch (error) {
      // Keep only the stage and status; exception text may contain sensitive data.
      console.error(JSON.stringify({ auth_stage: stage, status: 503 }));
      throw error;
    }
}

// An adapter is injected in tests; the deployed entry point below only uses DO bindings.
export function createApp({ clients, googleClientId, googleClientSecret, identityKey, refreshKey, adminSecret, signingKey, signingKid, jwks, stateFor, fetcher = fetch, now = epoch }) {
  async function verifyClient(params, client, current) {
    const assertion = one(params, 'client_assertion');
    if (one(params, 'client_assertion_type') !== 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer') throw new Error('bad client authentication');
    await verifyClientAssertion({ assertion, clientId: client.id, jwks: client.jwks, audience: `${ORIGIN}/token`, now: current,
      claim: (x) => stateFor('client-assertion-replay').claimAssertion(x) });
  }
  async function app(request) {
    const url = new URL(request.url), current = now();
    if (url.pathname === '/internal/account-block' && request.method === 'POST') {
      if (!adminSecret) return json(404, { error: 'not_found' });
      const presented = request.headers.get('authorization') || '';
      const expected = `Bearer ${adminSecret}`;
      if (presented.length !== expected.length) return json(401, { error: 'unauthorized' });
      let mismatch = 0;
      for (let i = 0; i < expected.length; i++) mismatch |= presented.charCodeAt(i) ^ expected.charCodeAt(i);
      if (mismatch) return json(401, { error: 'unauthorized' });
      const body = await request.json();
      if (!body || Object.keys(body).length !== 1 || !/^sub_[A-Za-z0-9_-]+$/.test(body.account_id ?? '')) return json(400, { error: 'invalid_request' });
      await stateFor('google-account-registry').setAccountStatus({ accountId: body.account_id, blocked: true });
      return json(200, { ok: true });
    }
    if (url.pathname === '/.well-known/jwks.json' && request.method === 'GET') {
      const keys = (jwks?.keys || []).map(({ kty, crv, x, y, kid, use, alg }) => ({ kty, crv, x, y, kid, use, alg }));
      return json(200, { keys });
    }
    if (url.pathname === '/login' && request.method === 'GET') {
      const id = one(url.searchParams, 'client_id'), returnTo = one(url.searchParams, 'redirect_uri');
      const serviceState = one(url.searchParams, 'state'), challenge = one(url.searchParams, 'code_challenge');
      const client = clients[id];
      if (!validClient.test(id) || !client || client.id !== id || !client.redirect_uris.includes(returnTo) ||
          !opaque.test(serviceState) || !opaque.test(challenge) || one(url.searchParams, 'code_challenge_method') !== 'S256') return json(400, { error: 'invalid_request' });
      const fields = profileClaimAllowlist(client);
      const object = random(), stateSecret = random(), browser = random(), nonce = random(), verifier = random();
      await stateFor(object).createLogin({ stateDigest: await digest(stateSecret), browserDigest: await digest(browser), client: id, redirect: returnTo, serviceState, serviceChallenge: challenge, googleNonce: nonce, googleVerifier: verifier, expires: current + 600 });
      const google = new URL('https://accounts.google.com/o/oauth2/v2/auth');
      const values = { client_id: googleClientId, redirect_uri: CALLBACK, response_type: 'code', scope: fields.length ? 'openid email profile' : 'openid', state: `${object}.${stateSecret}`, nonce, code_challenge: await digest(verifier), code_challenge_method: 'S256' };
      for (const [k, v] of Object.entries(values)) google.searchParams.set(k, v);
      return redirect(google.href, { 'set-cookie': cookieHeader(browser, 600) });
    }
    if (url.pathname === '/oauth/google/callback' && request.method === 'GET') {
      const state = split(one(url.searchParams, 'state')), browser = cookieValue(request), code = one(url.searchParams, 'code');
      if (!state || !opaque.test(browser) || !code) return json(400, { error: 'invalid_callback' });
      const pending = await diagnosed('login_state_read_failed', async () => stateFor(state[0]).consumeLogin({ stateDigest: await digest(state[1]), browserDigest: await digest(browser), now: current }));
      if (!pending) return json(400, { error: 'invalid_callback' });
      if (!clients[pending.client]?.redirect_uris?.includes(pending.redirect)) return json(400, { error: 'invalid_callback' });
      const googleToken = await diagnosed('google_token_exchange_failed', async () => {
        const response = await diagnosed('google_fetch_failed', () => fetcher('https://oauth2.googleapis.com/token', { method: 'POST', redirect: 'manual', headers: { 'content-type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: googleClientId, client_secret: googleClientSecret, redirect_uri: CALLBACK, grant_type: 'authorization_code', code, code_verifier: pending.google_verifier }) }));
        if (!response.ok) {
          console.error(JSON.stringify({ auth_stage: 'google_token_exchange_failed', status: response.status }));
          throw new Error('google token endpoint failed');
        }
        return diagnosed('google_response_parse_failed', () => response.json());
      });
      const identity = await diagnosed('google_id_token_verification_failed', async () => {
        const keyResponse = await fetcher('https://www.googleapis.com/oauth2/v3/certs', { redirect: 'manual' });
        if (!keyResponse.ok) throw new Error('google keys unavailable');
        return verifyGoogleIdToken({ token: googleToken.id_token, jwks: await keyResponse.json(), clientId: googleClientId, nonce: pending.google_nonce, now: now(), profile: profileClaimAllowlist(clients[pending.client]).length > 0 });
      });
      const account = await diagnosed('identity_lookup_failed', async () => {
        const userId = await googleProductUserId(identity.sub);
        const fingerprint = await identityFingerprint(identityKey, identity.sub);
        const result = await stateFor('google-account-registry').resolveAccount({ fingerprint, productId: pending.client, userId, subject: identity.sub });
        if (!result || result.state !== 'active' || !/^sub_[A-Za-z0-9_-]+$/.test(result.account_id ?? '')) throw new Error('identity authority failed');
        return result;
      });
      const codeSecret = random(), codeDigest = await digest(codeSecret);
      const fields = profileClaimAllowlist(clients[pending.client]);
      let encryptedProfile;
      if (fields.length) {
        const profile = verifiedProfile(identity.profile, fields);
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const aad = encoder.encode(`profile:${pending.client}:${codeDigest}`);
        const cipher = await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:aad}, refreshKey, encoder.encode(JSON.stringify(profile)));
        encryptedProfile = `${b64(iv)}.${b64(new Uint8Array(cipher))}`;
      }
      await diagnosed('code_issue_failed', async () => stateFor(state[0]).createCode({ digest: codeDigest, client: pending.client, redirect: pending.redirect, challenge: pending.service_challenge, subject: account.account_id, accountId: account.account_id, expires: current + 60, encryptedProfile }));
      const target = new URL(pending.redirect); target.searchParams.set('code', `${state[0]}.${codeSecret}`); target.searchParams.set('state', pending.service_state);
      return redirect(target.href, { 'set-cookie': cookieHeader('', 0), 'referrer-policy': 'no-referrer' });
    }
    if ((url.pathname === '/token' || url.pathname === '/logout') && request.method === 'POST') {
      const params = new URLSearchParams(await request.text());
      const id = one(params, 'client_id'), client = clients[id];
      if (!client || client.id !== id) return json(401, { error: 'invalid_client' });
      try { await verifyClient(params, client, current); } catch { return json(401, { error: 'invalid_client' }); }
      let subject, accountId, object, sessionId, profile, nextSecret = random();
      if (url.pathname === '/token' && one(params, 'grant_type') === 'authorization_code') {
        const code = split(one(params, 'code')), verifier = one(params, 'code_verifier'), returnTo = one(params, 'redirect_uri');
        if (!code || !opaque.test(verifier) || !client.redirect_uris.includes(returnTo)) return json(400, { error: 'invalid_grant' });
        object = code[0]; sessionId = random();
        const result = await diagnosed('session_storage_failed', async () => stateFor(object).exchangeCode({ codeDigest: await digest(code[1]), client: id, redirect: returnTo, challenge: await digest(verifier), now: current, id: sessionId, expires: current + 30 * 24 * 3600, refreshDigest: await digest(nextSecret) }));
        if (!result) return json(400, { error: 'invalid_grant' });
        subject = result.subject;
        accountId = result.accountId;
        const fields = profileClaimAllowlist(client);
        if (fields.length) {
          if (typeof result.encryptedProfile !== 'string') throw new Error('profile unavailable');
          const [iv, cipher, extra] = result.encryptedProfile.split('.');
          if (!iv || !cipher || extra !== undefined) throw new Error('invalid profile');
          const aad = encoder.encode(`profile:${id}:${await digest(code[1])}`);
          const plain = await crypto.subtle.decrypt({name:'AES-GCM',iv:un64(iv),additionalData:aad}, refreshKey, un64(cipher));
          profile = verifiedProfile(JSON.parse(new TextDecoder().decode(plain)), fields);
        }
      } else {
        const token = one(params, 'refresh_token').split('.');
        if (token.length !== 3 || !token.every(x => opaque.test(x))) return json(400, { error: 'invalid_grant' });
        [object, sessionId] = token;
        if (url.pathname === '/logout') {
          const revoked = await stateFor(object).revoke({ id: sessionId, client: id, digest: await digest(token[2]), now: current });
          return revoked ? json(200, { ok: true }) : json(400, { error: 'invalid_grant' });
        }
        if (one(params, 'grant_type') !== 'refresh_token') return json(400, { error: 'invalid_grant' });
        const oldDigest = await digest(token[2]);
        const snapshot = await stateFor(object).inspectRefresh({ id: sessionId, client: id, digest: oldDigest, now: current });
        if (!snapshot) return json(400, { error: 'invalid_grant' });
        const account = await stateFor('google-account-registry').accountById(snapshot.account_id);
        if (!account || account.state !== 'active') return json(400, { error: 'invalid_grant' });
        const access = await issueAccessToken({ key: signingKey, kid: signingKid, issuer: ORIGIN, audience: id, subject: snapshot.subject, accountId: snapshot.account_id, sessionId, now: current });
        const response = { access_token: access, token_type: 'Bearer', expires_in: 900, refresh_token: `${object}.${sessionId}.${nextSecret}` };
        const iv = crypto.getRandomValues(new Uint8Array(12)), aad = encoder.encode(`${id}:${sessionId}`);
        const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad }, refreshKey, encoder.encode(JSON.stringify(response)));
        const result = await stateFor(object).rotate({ id: sessionId, client: id, digest: oldDigest, replacement: await digest(nextSecret), encryptedResult: `${b64(iv)}.${b64(new Uint8Array(cipher))}`, now: current });
        if (!result.ok) return json(400, { error: 'invalid_grant' });
        const currentAccount = await stateFor('google-account-registry').accountById(result.accountId);
        if (!currentAccount || currentAccount.state !== 'active') return json(400, { error: 'invalid_grant' });
        const [storedIv, storedCipher] = result.encryptedResult.split('.');
        const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: un64(storedIv), additionalData: aad }, refreshKey, un64(storedCipher));
        return json(200, JSON.parse(new TextDecoder().decode(plain)));
      }
      const access = await issueAccessToken({ key: signingKey, kid: signingKid, issuer: ORIGIN, audience: id, subject, accountId, sessionId, now: current });
      const response = { access_token: access, token_type: 'Bearer', expires_in: 900, refresh_token: `${object}.${sessionId}.${nextSecret}` };
      if (profile) { response.account_id = accountId; response.profile = profile; }
      return json(200, response);
    }
    return json(404, { error: 'not_found' });
  }
  return { async fetch(request) { try { return await app(request); } catch { return json(503, { error: 'authentication_unavailable' }); } } };
}

const methods = new Set(['createLogin', 'consumeLogin', 'claimAssertion', 'createCode', 'exchangeCode', 'inspectRefresh', 'rotate', 'revoke', 'resolveAccount', 'accountById', 'setAccountStatus']);
export class AuthStateObject extends AuthState {
  constructor(state, env) { super(state); this.state = state; this.env = env; }
  async createCode(input) {
    if (input.encryptedProfile) await this.storage.setAlarm(input.expires * 1000);
    return super.createCode(input);
  }
  async alarm() { this.clearExpiredProfiles(Math.floor(Date.now() / 1000)); }
  async resolveAccount({ fingerprint, productId, userId, subject }) {
    // DO serialization prevents two concurrent first logins from issuing two
    // authority calls or binding one fingerprint to different accounts.
    return this.state.blockConcurrencyWhile(async () => {
      const current = this.accountByFingerprint(fingerprint);
      if (current && (current.state !== 'active' || productId !== 'b62')) return current;
      const linked = await diagnosed('identity_authority_rpc_failed', async () => {
        const result = await this.env.IDENTITY_AUTHORITY.resolve_or_create_product_link({ product_id: productId, product_user_id: userId, auth_provider: 'google', provider_subject: subject });
        if (result?.ok !== true || result?.link?.state !== 'active' || result?.link?.product_id !== productId || result?.link?.product_user_id !== userId || !/^sub_[A-Za-z0-9_-]+$/.test(result?.link?.canonical_subject_id ?? '')) throw new Error('identity authority failed');
        return result;
      });
      if (current && current.account_id !== linked.link.canonical_subject_id) throw new Error('identity_conflict');
      return diagnosed('account_mapping_storage_failed', async () => this.putAccount({ fingerprint, accountId: linked.link.canonical_subject_id }));
    });
  }
  async fetch(request) {
    const action = new URL(request.url).pathname.slice(1);
    if (request.method !== 'POST' || !methods.has(action)) return json(404, { error: 'not_found' });
    try { return json(200, { value: (await this[action](await request.json())) ?? null }); } catch { return json(500, { error: 'state_failure' }); }
  }
}

export default {
  async fetch(request, env) {
    try {
      // The public key endpoint remains available during bootstrap before the
      // Google client secret and per-service login configuration are installed.
      if (request.method === 'GET' && new URL(request.url).pathname === '/.well-known/jwks.json') {
        const data = JSON.parse(env.PADIEM_AUTH_JWKS);
        if (!Array.isArray(data?.keys) || !data.keys.length) return json(503, { error: 'authentication_unavailable' });
        const keys = data.keys.map(({ kty, crv, x, y, kid, use, alg }) => ({ kty, crv, x, y, kid, use, alg }));
        return json(200, { keys });
      }
      const clients = JSON.parse(env.PADIEM_AUTH_CLIENTS);
      const jwks = JSON.parse(env.PADIEM_AUTH_JWKS);
      const signingKey = await crypto.subtle.importKey('jwk', JSON.parse(env.PADIEM_AUTH_ES256_PRIVATE_JWK), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
      const identityBytes = Uint8Array.from(atob(env.PADIEM_AUTH_IDENTITY_HMAC_KEY.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(env.PADIEM_AUTH_IDENTITY_HMAC_KEY.length / 4) * 4, '=')), c => c.charCodeAt(0));
      if (identityBytes.length !== 32) throw new Error('identity key must be 32 bytes');
      const identityKey = await crypto.subtle.importKey('raw', identityBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
      const refreshBytes = un64(env.PADIEM_AUTH_REFRESH_ENCRYPTION_KEY);
      if (refreshBytes.length !== 32) throw new Error('refresh key must be 32 bytes');
      const refreshKey = await crypto.subtle.importKey('raw', refreshBytes, 'AES-GCM', false, ['encrypt', 'decrypt']);
      if (!env.GOOGLE_CLIENT_ID || !env.GOOGLE_CLIENT_SECRET || !env.PADIEM_AUTH_SIGNING_KID || !env.AUTH_STATE || !env.IDENTITY_AUTHORITY) throw new Error('missing binding');
      const stateFor = (name) => new Proxy({}, { get(_target, method) { return async (args) => {
        const stub = env.AUTH_STATE.get(env.AUTH_STATE.idFromName(name));
        const response = await stub.fetch(`https://internal/${method}`, { method: 'POST', body: JSON.stringify(args) });
        if (!response.ok) throw new Error('state failed');
        return (await response.json()).value;
      }; } });
      return await createApp({ clients, googleClientId: env.GOOGLE_CLIENT_ID, googleClientSecret: env.GOOGLE_CLIENT_SECRET, identityKey, refreshKey, adminSecret: env.PADIEM_AUTH_ADMIN_SECRET, signingKey, signingKid: env.PADIEM_AUTH_SIGNING_KID, jwks, stateFor }).fetch(request);
    } catch { return json(503, { error: 'authentication_unavailable' }); }
  }
};

