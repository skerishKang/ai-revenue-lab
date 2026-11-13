// Synthetic auth Worker harness shared by the #347 orbit tests and the
// screenshot tool. It mirrors the production wiring closely enough to render
// the real login/signup screens: three registered clients, a password RPC stub,
// and an in-memory SQLite state object. No real account, cookie or network
// request is involved.
import { DatabaseSync } from 'node:sqlite';
import { AuthState } from '../state.mjs';
import { createApp, AuthStateObject } from '../worker.mjs';

export const url = 'https://auth.padiem.net';
export const REDIRECT = 'https://lovetree.example/auth/callback';
export const EN = { 'accept-language': 'en-US,en;q=0.9,ko;q=0.8' };

const b64 = (x) => Buffer.from(x).toString('base64url');
const rand = () => b64(crypto.getRandomValues(new Uint8Array(32)));
const sum = async (x) => b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(x)));

function storage() {
  const db = new DatabaseSync(':memory:');
  return { sql: { exec(q, ...p) { const stmt = db.prepare(q); if (stmt.columns().length) { const rows = stmt.all(...p); return { toArray: () => rows }; } stmt.run(...p); return { toArray: () => [] }; } },
    transactionSync(fn) { db.exec('BEGIN'); try { const out = fn(); db.exec('COMMIT'); return out; } catch (e) { db.exec('ROLLBACK'); throw e; } } };
}

// The random per-request query values are the only variable part of a page.
export const normalise = (html) => html
  .replace(/code_challenge=[A-Za-z0-9_-]+/g, 'code_challenge=CHALLENGE')
  .replace(/state=[A-Za-z0-9._%-]+/g, 'state=STATE');

export async function createSkinHarness() {
  const signing = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const refreshKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(8), 'AES-GCM', false, ['encrypt', 'decrypt']);
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(9), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const publicSigning = await crypto.subtle.exportKey('jwk', signing.publicKey); publicSigning.kid = 'auth';
  const clientKey = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
  const publicClient = await crypto.subtle.exportKey('jwk', clientKey.publicKey); publicClient.kid = 'client';
  const objects = new Map();
  let queue = Promise.resolve();
  const authority = {
    async resolve_or_create_product_link(v) {
      return { ok: true, link: { state: 'active', product_id: v.product_id, product_user_id: v.product_user_id, canonical_subject_id: 'sub_existing' } };
    },
  };
  const stateFor = (id) => {
    if (!objects.has(id)) {
      const state = { storage: storage(), blockConcurrencyWhile(fn) { const next = queue.then(fn); queue = next.catch(() => {}); return next; } };
      objects.set(id, id === 'google-account-registry' ? new AuthStateObject(state, { IDENTITY_AUTHORITY: authority }) : new AuthState(state));
    }
    return objects.get(id);
  };
  const app = createApp({
    clients: {
      'lovetree-4-0': { id: 'lovetree-4-0', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
      brandless: { id: 'brandless', password_login: true, redirect_uris: [REDIRECT], jwks: { keys: [publicClient] } },
    },
    googleClientId: 'google-client', googleClientSecret: 'synthetic', identityKey, refreshKey,
    adminSecret: 'synthetic-admin-secret', accountDeleteRpcSecret: 'synthetic-account-delete-secret-32chars',
    passwordRpcSecret: 'synthetic-password-rpc-secret-32chars-min', passwordRpcOrigin: 'https://chat.padiem.net',
    signingKey: signing.privateKey, signingKid: 'auth', jwks: { keys: [publicSigning] },
    stateFor, now: () => 1000,
    async fetcher() { throw new Error('unexpected fetch'); },
  });
  async function begin(path = '/login', clientId = 'lovetree-4-0', extra = {}, headers = {}) {
    const q = new URLSearchParams({ client_id: clientId, redirect_uri: REDIRECT, state: rand(), code_challenge: await sum(rand()), code_challenge_method: 'S256' });
    if (extra.lt_theme) q.set('lt_theme', extra.lt_theme);
    const response = await app.fetch(new Request(`${url}${path}?${q}`, { headers }));
    return { response, html: await response.text() };
  }
  return { app, begin, stateObjects: objects };
}
