// Deterministic HTTP fixture shared by the frozen pre-change capture and its
// current implementation comparison. Only random OAuth state bytes are fixed.
import { createHash } from 'node:crypto';

const ORIGIN = 'https://auth.padiem.net';
const REDIRECT = 'https://service.example.invalid/callback';
const opaque = 'a'.repeat(43);
const hash = value => createHash('sha256').update(value).digest('hex');

export async function offResponses(createApp, { enabled = false } = {}) {
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(7), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const cases = [
    { name: 'plain-login-ko', path: '/login', method: 'GET', client: 'b62', lang: 'ko' },
    { name: 'plain-signup-ko', path: '/signup', method: 'GET', client: 'b62', lang: 'ko' },
    { name: 'brand-login-en', path: '/login', method: 'GET', client: 'lovetree-4-0', lang: 'en' },
    { name: 'brand-signup-en', path: '/signup', method: 'GET', client: 'lovetree-4-0', lang: 'en' },
    { name: 'signup-ownership-refused', path: '/signup/password', refused: true },
    { name: 'signup-existing-chat', path: '/signup/password', rpcStatus: 409 },
    { name: 'login-wrong-password', path: '/login/password', rpcStatus: 401 },
    { name: 'login-epoch-refused', path: '/login/password', refused: true },
    { name: 'login-deleted', path: '/login/password', deleted: true },
    { name: 'signup-success', path: '/signup/password' },
    { name: 'login-success', path: '/login/password' },
  ];
  const output = [];
  const originalRandom = crypto.getRandomValues;
  try {
    for (const entry of cases) {
      let sequence = 0;
      crypto.getRandomValues = array => { for (let i = 0; i < array.length; i++) array[i] = (i + sequence * 17) % 256; sequence++; return array; };
      const client = entry.client || 'b62';
      const login = { client, redirect: REDIRECT, service_state: opaque, service_challenge: opaque };
      const registry = {
        async passwordBindingRefused() { return entry.refused === true; },
        async identityIsDeleted() { return entry.deleted === true; },
        async clearIdentityDeletion() { return true; },
        async pendingChatAccountDeletions() { return []; },
        async resolveAccount() { return { state: 'active', account_id: 'sub_existing' }; },
      };
      const session = {
        async createLogin() {}, async beginPasswordAttempt() { return { ok: true, login }; },
        async consumeLogin() { return login; }, async createCode() {},
      };
      const app = createApp({ clients: {
        b62: { id: 'b62', password_login: true, redirect_uris: [REDIRECT] },
        'lovetree-4-0': { id: 'lovetree-4-0', password_login: true, redirect_uris: [REDIRECT] },
      }, identityKey, emailRecoveryEnabled: enabled,
      passwordRpcSecret: 'synthetic-password-rpc-secret-32chars', passwordRpcOrigin: 'https://chat.example.invalid',
      stateFor: id => id === 'google-account-registry' ? registry : session, now: () => 1000,
      fetcher: async () => entry.rpcStatus
        ? Response.json({ error: { code: entry.rpcStatus === 409 ? 'account_exists' : 'invalid_credentials' } }, { status: entry.rpcStatus })
        : Response.json({ ok: true, product_user_id: 'usr_existing', credential_epoch: '2026-11-12T00:00:00+00:00' }),
      });
      let request;
      if (entry.method === 'GET') {
        const params = new URLSearchParams({ client_id: client, redirect_uri: REDIRECT, state: opaque, code_challenge: opaque, code_challenge_method: 'S256' });
        request = new Request(`${ORIGIN}${entry.path}?${params}`, { headers: { 'accept-language': entry.lang } });
      } else {
        request = new Request(`${ORIGIN}${entry.path}?state=${opaque}.${opaque}`, {
          method: 'POST', headers: { cookie: `__Host-padiem-auth-state=${opaque}`, 'content-type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ email: 'owner@example.invalid', password: 'synthetic-safe-password', name: 'Example' }),
        });
      }
      const response = await app.fetch(request);
      const body = await response.text();
      output.push({ name: entry.name, status: response.status, headers_sha256: hash(JSON.stringify([...response.headers])), body_sha256: hash(body), body });
    }
  } finally { crypto.getRandomValues = originalRandom; }
  return output;
}
