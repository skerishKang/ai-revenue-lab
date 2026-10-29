import { AuthState } from './state.mjs';
import { verifyGoogleIdToken } from './google-id-token.mjs';
import { issueAccessToken } from './access-token.mjs';
import { verifyClientAssertion } from './client-assertion.mjs';

const ORIGIN = 'https://auth.padiem.net';
const CALLBACK = `${ORIGIN}/oauth/google/callback`;
const encoder = new TextEncoder();
const opaque = /^[A-Za-z0-9_-]{43}$/;
const validClient = /^[A-Za-z0-9_-]+$/;
const cookie = '__Host-padiem-auth-state';
const b64 = (a) => btoa(String.fromCharCode(...a)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const digest = async (s) => b64(new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(s))));
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

// An adapter is injected in tests; the deployed entry point below only uses DO bindings.
export function createApp({ clients, googleClientId, googleClientSecret, signingKey, signingKid, jwks, stateFor, fetcher = fetch, now = epoch }) {
  async function verifyClient(params, client, current) {
    const assertion = one(params, 'client_assertion');
    if (one(params, 'client_assertion_type') !== 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer') throw new Error('bad client authentication');
    await verifyClientAssertion({ assertion, clientId: client.id, jwks: client.jwks, audience: `${ORIGIN}/token`, now: current,
      claim: (x) => stateFor('client-assertion-replay').claimAssertion(x) });
  }
  async function app(request) {
    const url = new URL(request.url), current = now();
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
      const object = random(), stateSecret = random(), browser = random(), nonce = random(), verifier = random();
      await stateFor(object).createLogin({ stateDigest: await digest(stateSecret), browserDigest: await digest(browser), client: id, redirect: returnTo, serviceState, serviceChallenge: challenge, googleNonce: nonce, googleVerifier: verifier, expires: current + 600 });
      const google = new URL('https://accounts.google.com/o/oauth2/v2/auth');
      const values = { client_id: googleClientId, redirect_uri: CALLBACK, response_type: 'code', scope: 'openid', state: `${object}.${stateSecret}`, nonce, code_challenge: await digest(verifier), code_challenge_method: 'S256' };
      for (const [k, v] of Object.entries(values)) google.searchParams.set(k, v);
      return redirect(google.href, { 'set-cookie': cookieHeader(browser, 600) });
    }
    if (url.pathname === '/oauth/google/callback' && request.method === 'GET') {
      const state = split(one(url.searchParams, 'state')), browser = cookieValue(request), code = one(url.searchParams, 'code');
      if (!state || !opaque.test(browser) || !code) return json(400, { error: 'invalid_callback' });
      const pending = await stateFor(state[0]).consumeLogin({ stateDigest: await digest(state[1]), browserDigest: await digest(browser), now: current });
      if (!pending) return json(400, { error: 'invalid_callback' });
      if (!clients[pending.client]?.redirect_uris?.includes(pending.redirect)) return json(400, { error: 'invalid_callback' });
      const response = await fetcher('https://oauth2.googleapis.com/token', { method: 'POST', redirect: 'error', headers: { 'content-type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: googleClientId, client_secret: googleClientSecret, redirect_uri: CALLBACK, grant_type: 'authorization_code', code, code_verifier: pending.google_verifier }) });
      if (!response.ok) throw new Error('google token endpoint failed');
      const googleToken = await response.json();
      const keyResponse = await fetcher('https://www.googleapis.com/oauth2/v3/certs', { redirect: 'error' });
      if (!keyResponse.ok) throw new Error('google keys unavailable');
      const identity = await verifyGoogleIdToken({ token: googleToken.id_token, jwks: await keyResponse.json(), clientId: googleClientId, nonce: pending.google_nonce, now: current });
      const userId = await googleProductUserId(identity.sub);
      const fingerprint = await digest(`google:${identity.sub}`);
      const account = await stateFor('google-account-registry').resolveAccount({ fingerprint, productId: pending.client, userId, subject: identity.sub });
      if (!account || account.state !== 'active' || !/^sub_[A-Za-z0-9_-]+$/.test(account.account_id ?? '')) throw new Error('identity authority failed');
      const codeSecret = random();
      await stateFor(state[0]).createCode({ digest: await digest(codeSecret), client: pending.client, redirect: pending.redirect, challenge: pending.service_challenge, subject: identity.sub, accountId: account.account_id, expires: current + 60 });
      const target = new URL(pending.redirect); target.searchParams.set('code', `${state[0]}.${codeSecret}`); target.searchParams.set('state', pending.service_state);
      return redirect(target.href, { 'set-cookie': cookieHeader('', 0), 'referrer-policy': 'no-referrer' });
    }
    if ((url.pathname === '/token' || url.pathname === '/logout') && request.method === 'POST') {
      const params = new URLSearchParams(await request.text());
      const id = one(params, 'client_id'), client = clients[id];
      if (!client || client.id !== id) return json(401, { error: 'invalid_client' });
      try { await verifyClient(params, client, current); } catch { return json(401, { error: 'invalid_client' }); }
      let subject, accountId, object, sessionId, nextSecret = random();
      if (url.pathname === '/token' && one(params, 'grant_type') === 'authorization_code') {
        const code = split(one(params, 'code')), verifier = one(params, 'code_verifier'), returnTo = one(params, 'redirect_uri');
        if (!code || !opaque.test(verifier) || !client.redirect_uris.includes(returnTo)) return json(400, { error: 'invalid_grant' });
        object = code[0]; sessionId = random();
        const result = await stateFor(object).exchangeCode({ codeDigest: await digest(code[1]), client: id, redirect: returnTo, challenge: await digest(verifier), now: current, id: sessionId, expires: current + 30 * 24 * 3600, refreshDigest: await digest(nextSecret) });
        if (!result) return json(400, { error: 'invalid_grant' });
        subject = result.subject;
        accountId = result.accountId;
      } else {
        const token = one(params, 'refresh_token').split('.');
        if (token.length !== 3 || !token.every(x => opaque.test(x))) return json(400, { error: 'invalid_grant' });
        [object, sessionId] = token;
        if (url.pathname === '/logout') {
          const revoked = await stateFor(object).revoke({ id: sessionId, client: id, digest: await digest(token[2]), now: current });
          return revoked ? json(200, { ok: true }) : json(400, { error: 'invalid_grant' });
        }
        if (one(params, 'grant_type') !== 'refresh_token') return json(400, { error: 'invalid_grant' });
        const result = await stateFor(object).rotate({ id: sessionId, client: id, digest: await digest(token[2]), replacement: await digest(nextSecret), now: current });
        if (!result.ok) return json(400, { error: 'invalid_grant' });
        subject = result.subject;
        accountId = result.accountId;
        // A disabled product link must not keep receiving 30 days of fresh access.
        // A failed authority call closes the flow; the rotated credential was not
        // returned, so recovery requires a new login instead of a fail-open grant.
        const account = await stateFor('google-account-registry').accountById(accountId);
        if (!account || account.state !== 'active') {
          await stateFor(object).revoke({ id: sessionId, client: id, digest: await digest(nextSecret), now: current });
          return json(400, { error: 'invalid_grant' });
        }
      }
      const access = await issueAccessToken({ key: signingKey, kid: signingKid, issuer: ORIGIN, audience: id, subject, accountId, sessionId, now: current });
      return json(200, { access_token: access, token_type: 'Bearer', expires_in: 900, refresh_token: `${object}.${sessionId}.${nextSecret}` });
    }
    return json(404, { error: 'not_found' });
  }
  return { async fetch(request) { try { return await app(request); } catch { return json(503, { error: 'authentication_unavailable' }); } } };
}

const methods = new Set(['createLogin', 'consumeLogin', 'claimAssertion', 'createCode', 'exchangeCode', 'rotate', 'revoke', 'resolveAccount', 'accountById']);
export class AuthStateObject extends AuthState {
  constructor(state, env) { super(state); this.state = state; this.env = env; }
  async resolveAccount({ fingerprint, productId, userId, subject }) {
    // DO serialization prevents two concurrent first logins from issuing two
    // authority calls or binding one fingerprint to different accounts.
    return this.state.blockConcurrencyWhile(async () => {
      const current = this.accountByFingerprint(fingerprint);
      if (current) return current;
      const linked = await this.env.IDENTITY_AUTHORITY.resolve_or_create_product_link({ product_id: productId, product_user_id: userId, auth_provider: 'google', provider_subject: subject });
      if (linked?.ok !== true || linked?.link?.state !== 'active' || linked?.link?.product_id !== productId || linked?.link?.product_user_id !== userId || !/^sub_[A-Za-z0-9_-]+$/.test(linked?.link?.canonical_subject_id ?? '')) throw new Error('identity authority failed');
      return this.putAccount({ fingerprint, accountId: linked.link.canonical_subject_id });
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
      const clients = JSON.parse(env.PADIEM_AUTH_CLIENTS);
      const jwks = JSON.parse(env.PADIEM_AUTH_JWKS);
      const signingKey = await crypto.subtle.importKey('jwk', JSON.parse(env.PADIEM_AUTH_ES256_PRIVATE_JWK), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
      if (!env.GOOGLE_CLIENT_ID || !env.GOOGLE_CLIENT_SECRET || !env.PADIEM_AUTH_SIGNING_KID || !env.AUTH_STATE || !env.IDENTITY_AUTHORITY) throw new Error('missing binding');
      const stateFor = (name) => new Proxy({}, { get(_target, method) { return async (args) => {
        const stub = env.AUTH_STATE.get(env.AUTH_STATE.idFromName(name));
        const response = await stub.fetch(`https://internal/${method}`, { method: 'POST', body: JSON.stringify(args) });
        if (!response.ok) throw new Error('state failed');
        return (await response.json()).value;
      }; } });
      return await createApp({ clients, googleClientId: env.GOOGLE_CLIENT_ID, googleClientSecret: env.GOOGLE_CLIENT_SECRET, signingKey, signingKid: env.PADIEM_AUTH_SIGNING_KID, jwks, stateFor }).fetch(request);
    } catch { return json(503, { error: 'authentication_unavailable' }); }
  }
};
