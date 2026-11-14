// Deterministic HTTP fixture for the email recovery surface with the #7652
// switch ON and password find (#7679) OFF. The frozen capture was taken from
// the code before password find existed; the comparison runs the same calls
// against the current code. The finished signup is left to its own test.
import { createHash } from 'node:crypto';
import { offResponses } from './email-recovery-off-fixture.mjs';

const ORIGIN = 'https://auth.padiem.net';
const TOKEN = 't'.repeat(43);
const hash = value => createHash('sha256').update(value).digest('hex');

export async function findOffResponses(createApp, options = {}) {
  const identityKey = await crypto.subtle.importKey('raw', new Uint8Array(32).fill(7), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const forms = (await offResponses(config => createApp({ ...config, ...options }), { enabled: true })).filter(entry => entry.name !== 'signup-success');
  const cases = [
    { name: 'recovery-request-page-ko', method: 'GET', path: '/password/recovery', lang: 'ko' },
    { name: 'recovery-request-page-en', method: 'GET', path: '/password/recovery', lang: 'en' },
    { name: 'recovery-confirm-page-ko', method: 'GET', path: '/password/recovery/confirm', lang: 'ko' },
    { name: 'recovery-confirm-page-en', method: 'GET', path: '/password/recovery/confirm', lang: 'en' },
    { name: 'recovery-request-absent-target', method: 'POST', path: '/password/recovery/request', lang: 'ko', available: true, candidate: true },
    { name: 'recovery-request-absent-not-target', method: 'POST', path: '/password/recovery/request', lang: 'ko', available: true, candidate: false },
    { name: 'recovery-request-live-account', method: 'POST', path: '/password/recovery/request', lang: 'en', available: false, candidate: true },
    { name: 'recovery-request-invalid-email', method: 'POST', path: '/password/recovery/request', lang: 'ko', email: 'not-an-email' },
    { name: 'recovery-confirm-malformed', method: 'POST', path: '/password/recovery/confirm', lang: 'ko', body: '{"token":1}' },
    { name: 'recovery-confirm-refused', method: 'POST', path: '/password/recovery/confirm', lang: 'en', result: { status: 400 } },
    { name: 'recovery-confirm-password-refused', method: 'POST', path: '/password/recovery/confirm', lang: 'ko', result: { status: 400, error: 'password_recovery_password_invalid' } },
    { name: 'recovery-confirm-unavailable', method: 'POST', path: '/password/recovery/confirm', lang: 'ko', result: { status: 503 } },
    { name: 'recovery-confirm-complete', method: 'POST', path: '/password/recovery/confirm', lang: 'en', result: { ok: true } },
  ];
  const output = forms.map(({ body, ...record }) => ({ ...record, body }));
  for (const entry of cases) {
    const calls = [];
    const registry = {
      async emailRecoveryCandidate(input) { calls.push(['candidate', Object.keys(input).sort()]); return entry.candidate ? { account_id: 'sub_existing', credential_epoch: '2026-11-12T00:00:00+00:00' } : null; },
      async completeEmailRecovery(input) { calls.push(['complete', Object.keys(input).sort()]); return entry.result; },
    };
    const app = createApp({ clients: {}, identityKey, emailRecoveryEnabled: true, ...options,
      passwordRpcSecret: 'synthetic-password-rpc-secret-32chars', passwordRpcOrigin: 'https://chat.example.invalid',
      stateFor: () => registry, now: () => 1000,
      fetcher: async (address, init) => {
        const action = new URL(address).pathname.split('/').at(-1);
        calls.push([action, JSON.parse(Buffer.from(init.body).toString())]);
        return Response.json(action === 'status' ? { ok: true, available: entry.available === true } : { ok: true });
      },
    });
    const headers = { 'accept-language': entry.lang, 'cf-connecting-ip': '192.0.2.7' };
    let request;
    if (entry.method === 'GET') request = new Request(`${ORIGIN}${entry.path}`, { headers });
    else if (entry.path.endsWith('/request')) request = new Request(`${ORIGIN}${entry.path}`, { method: 'POST', headers, body: new URLSearchParams({ email: entry.email || 'owner@example.invalid' }) });
    else request = new Request(`${ORIGIN}${entry.path}`, { method: 'POST', headers: { ...headers, 'content-type': 'application/json' }, body: entry.body || JSON.stringify({ token: TOKEN, new_password: 'synthetic-safe-password' }) });
    const response = await app.fetch(request);
    const body = await response.text();
    output.push({ name: entry.name, status: response.status, headers_sha256: hash(JSON.stringify([...response.headers])), body_sha256: hash(body), calls_sha256: hash(JSON.stringify(calls)), body });
  }
  return output;
}
