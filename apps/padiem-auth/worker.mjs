import { AuthState } from './state.mjs';
import { verifyGoogleIdToken } from './google-id-token.mjs';
import { issueAccessToken } from './access-token.mjs';
import { verifyClientAssertion } from './client-assertion.mjs';
import { profileClaimAllowlist, verifiedProfile, verifiedIssuedProfile } from './profile-claims.mjs';
import { AUTH_SKIN_ASSET_PREFIX, authSkinAsset, brandLoginPage, brandSignupCompletePage, brandSignupPage, padiemAccountLine, resolveBrand, resolveLang, resolveTheme } from './skin.mjs';
import { PLAIN_SIGNUP_COMPLETE_CSS, signupCompleteBody, signupCompleteRefresh, signupCompleteText } from './signup-complete.mjs';
import { addRecoveryLink, emailRecoveryEnabled as recoverySwitch, recoveryBody, recoveryPage, recoveryStrings, validRecoveryEmail, validRecoveryToken } from './email-recovery.mjs';
import { EMAIL_CONFIRMATION_TTL_SECONDS, confirmationPage, confirmationStrings, confirmationTokenDigest, validConfirmationDigest, validConfirmationToken } from './email-confirmation.mjs';

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
const digestHex = async (s) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(s)))].map(x => x.toString(16).padStart(2, '0')).join('');
export async function identityFingerprint(key, subject) {
  if (!key || key.algorithm?.name !== 'HMAC') throw new Error('identity key unavailable');
  return b64(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(`padiem-auth:google:v1\0${subject}`))));
}
export async function googleProductUserId(subject) {
  if (typeof subject !== 'string' || !/^[\x21-\x7e]{1,255}$/.test(subject)) throw new Error('invalid google subject');
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(`google:${subject}`)));
  return 'usr_' + [...hash].map(x => x.toString(16).padStart(2, '0')).join('').slice(0, 32);
}
// Separate HMAC domain so a password-account fingerprint can never collide
// with a Google-account fingerprint under the same identity key.
export async function passwordIdentityFingerprint(key, subject) {
  if (!key || key.algorithm?.name !== 'HMAC') throw new Error('identity key unavailable');
  const normalized = String(subject ?? '').trim().toLowerCase();
  return b64(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(`padiem-auth:password:v1\0${normalized}`))));
}
const epoch = () => Math.floor(Date.now() / 1000);
const headers = { 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' };
const json = (status, value) => new Response(JSON.stringify(value), { status, headers: { ...headers, 'content-type': 'application/json' } });

const SAFE_REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;
// #7551: the Chat password credential's creation time (ISO 8601).
const CREDENTIAL_EPOCH = /^[0-9][0-9T:.+\-Z]{9,39}$/;

function finishTokenTiming(response, timing, clientId) {
  if (!timing || clientId !== 'b62') return response;
  const values = {
    auth_client: timing.clientAuthMs || 0,
    auth_code: timing.codeExchangeMs || 0,
    auth_sign: timing.tokenSignMs || 0,
    auth_total: performance.now() - timing.started,
  };
  const serverTiming = Object.entries(values)
    .map(([name, duration]) => `${name};dur=${Math.max(0, duration).toFixed(2)}`)
    .join(', ');
  response.headers.set('server-timing', serverTiming);
  if (timing.requestId) {
    console.log(JSON.stringify({
      auth_stage: 'token_timing',
      request_id: timing.requestId,
      body_parse_ms: Number(timing.bodyParseMs.toFixed(2)),
      client_auth_ms: Number(values.auth_client.toFixed(2)),
      code_exchange_ms: Number(values.auth_code.toFixed(2)),
      token_sign_ms: Number(values.auth_sign.toFixed(2)),
      total_ms: Number(values.auth_total.toFixed(2)),
    }));
  }
  return response;
}

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

// A Python Worker answering over a service binding can hand back a Map (or a
// proxy with toJs) instead of a plain object; read it the same way either way.
function plainRpc(value) {
  if (value instanceof Map) return Object.fromEntries([...value].map(([k, v]) => [k, plainRpc(v)]));
  if (Array.isArray(value)) return value.map(plainRpc);
  if (value && typeof value === 'object' && typeof value.toJs === 'function') return plainRpc(value.toJs({ dict_converter: Object.fromEntries }));
  return value;
}

async function diagnosed(stage, operation) {
    try { return await operation(); }
    catch (error) {
      // Keep only the stage and status; exception text may contain sensitive data.
      console.error(JSON.stringify({ auth_stage: stage, status: 503 }));
      throw error;
    }
}

// #7542: one countable line per account check — whether the identity authority
// was asked for this sign-in, and how it answered. Only the client id, the
// sign-in method and closed words travel; never a fingerprint, subject, user id
// or account id. It changes nothing about the sign-in itself.
//   skipped_known  the person was already known here and the authority was not asked
//   called         the authority was asked and its answer was accepted
//   rejected       the authority was asked and refused, or answered in another shape
//   failed         the authority could not be reached
function logAccountCheck(productId, provider, known, outcome) {
  const product = typeof productId === 'string' && /^[a-z0-9-]{1,40}$/.test(productId) ? productId : 'other';
  const method = provider === 'password' ? 'password' : 'google';
  console.log(JSON.stringify({ auth_stage: 'identity_account_check', product, method, known: Boolean(known), outcome }));
}

async function verifyAccountDeletionRpc(request, secret, current) {
  if (typeof secret !== 'string' || secret.length < 32) return null;
  const path = new URL(request.url).pathname;
  const atText = request.headers.get('x-padiem-service-at') || '';
  const serviceId = request.headers.get('x-padiem-service-id') || '';
  const presented = request.headers.get('x-padiem-service-proof') || '';
  if (!new Set(['/internal/account-delete/prepare', '/internal/account-delete/complete', '/internal/account-delete/abort', '/internal/account-sessions/revoke']).has(path) ||
      request.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json' ||
      !/^(0|[1-9][0-9]{0,10})$/.test(atText) ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(serviceId) ||
      !/^v2=[a-f0-9]{64}$/.test(presented)) return null;
  const at = Number(atText);
  if (!Number.isSafeInteger(at) || Math.abs(current - at) > 300) return null;
  const length = Number(request.headers.get('content-length') || '0');
  if (length > 512) return null;
  const body = new Uint8Array(await request.arrayBuffer());
  if (!body.length || body.length > 512 || (length && length !== body.length)) return null;
  const signed = new Uint8Array([
    ...encoder.encode('v2\nPOST\n'),
    ...encoder.encode(path),
    10,
    ...encoder.encode(atText),
    10,
    ...encoder.encode(serviceId),
    10,
    ...body,
  ]);
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = [...new Uint8Array(await crypto.subtle.sign('HMAC', key, signed))].map(x => x.toString(16).padStart(2, '0')).join('');
  const expected = 'v2=' + mac;
  if (presented.length !== expected.length) return null;
  let mismatch = 0;
  for (let i = 0; i < expected.length; i++) mismatch |= expected.charCodeAt(i) ^ presented.charCodeAt(i);
  if (mismatch) return null;
  let payload;
  try { payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body)); } catch { return null; }
  return { serviceId, payload, at };
}

// padiem-auth is the CALLER here: the email signup/login forms prove the
// credential against Chat's internal password routes with the same v2 service
// proof envelope the account-delete receiver verifies (fresh UUID bound into
// the signature, ±300s clock window, ≤512-byte body).
async function passwordRpcHeaders(secret, path, body, current = epoch()) {
  const at = String(current);
  const serviceId = crypto.randomUUID();
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signed = new Uint8Array([
    ...encoder.encode('v2\nPOST\n'),
    ...encoder.encode(path),
    10,
    ...encoder.encode(at),
    10,
    ...encoder.encode(serviceId),
    10,
    ...body,
  ]);
  const mac = [...new Uint8Array(await crypto.subtle.sign('HMAC', key, signed))].map(x => x.toString(16).padStart(2, '0')).join('');
  return { 'content-type': 'application/json', 'x-padiem-service-at': at, 'x-padiem-service-id': serviceId, 'x-padiem-service-proof': `v2=${mac}` };
}

async function recoveryRpc({ secret, origin, fetcher = fetch, now = epoch() }, action, payload) {
  if (typeof secret !== 'string' || secret.length < 32 || typeof origin !== 'string' || !/^https:\/\/[^/]+\/?$/.test(origin)) throw new Error('recovery_rpc_unavailable');
  const path = `/internal/password-recovery/${action}`;
  const body = encoder.encode(JSON.stringify(payload));
  if (body.length > 4096) throw new Error('recovery_rpc_body_too_large');
  return fetcher(origin.replace(/\/+$/, '') + path, {
    method: 'POST', redirect: 'manual', body,
    headers: await passwordRpcHeaders(secret, path, body, now),
  });
}

const esc = (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const pageStyle = `*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f5f6f8;font-family:system-ui,-apple-system,'Malgun Gothic',sans-serif;color:#1c1e21}main{width:100%;max-width:360px;margin:24px;padding:32px 28px;background:#fff;border-radius:12px;box-shadow:0 1px 4px rgba(0,0,0,.08)}h1{font-size:20px;margin:0 0 20px;text-align:center}.btn{display:block;width:100%;padding:12px;border-radius:8px;border:1px solid #dadce0;background:#fff;font-size:15px;text-align:center;text-decoration:none;color:#1c1e21;cursor:pointer}.btn+.btn{margin-top:10px}.btn-primary{background:#1a73e8;border-color:#1a73e8;color:#fff}form{margin:0}label{display:block;font-size:13px;margin:12px 0 4px;color:#5f6368}input{width:100%;padding:11px;border:1px solid #dadce0;border-radius:8px;font-size:15px}.message{margin:0 0 12px;padding:10px;border-radius:8px;background:#fce8e6;color:#c5221f;font-size:14px}.link{display:block;margin-top:16px;text-align:center;font-size:14px;color:#1a73e8;text-decoration:none}.padiem-account-line{margin:18px 0 0;text-align:center;font-size:11px;line-height:1.6;color:#5f6368}`;
const page = (title, body, lang = 'ko', head = '') => `<!doctype html><html lang="${lang === 'en' ? 'en' : 'ko'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)}</title><meta name="referrer" content="no-referrer"><style>${pageStyle}</style>${head}</head><body><main>${body}<p class="padiem-account-line">${esc(padiemAccountLine(lang))}</p></main></body></html>`;
const emailFields = (message) => `${message ? `<p class="message">${esc(message)}</p>` : ''}<label for="email">이메일</label><input id="email" name="email" type="email" required maxlength="255" autocomplete="username"><label for="password">비밀번호</label><input id="password" name="password" type="password" required maxlength="128" autocomplete="current-password">`;
const loginFormPage = (action, message, lang = 'ko', signupHref = '') => page('로그인', `<h1>이메일로 로그인</h1><form method="post" action="${esc(action)}">${emailFields(message)}<button class="btn btn-primary" type="submit">로그인</button></form>${signupHref ? `<a class="link" href="${esc(signupHref)}">이메일로 회원가입</a>` : ''}`, lang);
const signupFormPage = (action, message, lang = 'ko', loginHref = '') => page('회원가입', `<h1>이메일로 회원가입</h1><form method="post" action="${esc(action)}">${message ? `<p class="message">${esc(message)}</p>` : ''}<label for="name">이름(선택)</label><input id="name" name="name" type="text" maxlength="160" autocomplete="name">${emailFields('')}<button class="btn btn-primary" type="submit">회원가입</button></form>${loginHref ? `<a class="link" href="${esc(loginHref)}">이메일로 로그인</a>` : ''}`, lang);
const messagePage = (message, lang = 'ko') => page('안내', `<h1>안내</h1><p class="message" style="background:#e8f0fe;color:#1c1e21">${esc(message)}</p>`, lang);
const htmlPage = (status, body, extra = {}) => new Response(body, { status, headers: { ...headers, 'content-type': 'text/html; charset=utf-8', 'referrer-policy': 'no-referrer', ...extra } });
// #7679: the one screen an email signup lands on before returning to the
// service. A registered brand renders it inside its own skin.
const signupCompletePage = ({ brand, theme, lang, email, continueHref }) => {
  if (brand) return brandSignupCompletePage({ brand, theme, lang, email, continueHref });
  const text = signupCompleteText(lang);
  return page(text.title, signupCompleteBody({ text, action: text.action, email, href: continueHref, buttonClass: 'btn btn-primary' }), lang, `${signupCompleteRefresh(continueHref)}<style>${PLAIN_SIGNUP_COMPLETE_CSS}</style>`);
};
const loginChoicePage = (googleHref, formAction, signupHref, lang = 'ko') => page('로그인', `<h1>PADIEM 로그인</h1><a class="btn" href="${esc(googleHref)}">Google로 계속</a><form method="post" action="${esc(formAction)}">${emailFields('')}<button class="btn" type="submit">이메일로 로그인</button></form><a class="link" href="${esc(signupHref)}">이메일로 회원가입</a>`, lang);

// Per-IP fixed-minute window for the email form POST. The window uses the
// replay-memory DO (claimAssertion): N slots per (ip, minute), each claimed at
// most once, so the check is durable and serialized without a new primitive.
async function allowPasswordAttempt(stateFor, ip, now, limit = 10) {
  if (!ip) return true;
  const windowIndex = Math.floor(now / 60);
  const gate = stateFor('password-login-gate');
  for (let i = 0; i < limit; i++) {
    if (await gate.claimAssertion({ key: `password-login:${ip}:${windowIndex}:${i}`, expires: (windowIndex + 1) * 60, now })) return true;
  }
  return false;
}

// Shared by the signed prepare endpoint and recovery inside the registry DO.
// The caller owns the operation token; beginAccountDeletion returns a boolean.
async function prepareAccountDeletion(registry, stateFor, { accountId, now, lockToken = crypto.randomUUID() }) {
  const locked = await registry.beginAccountDeletion({ accountId, lockToken, now, leaseSeconds: 300 });
  if (locked !== true) return { ok: false, error: 'account_deletion_busy' };
  try {
    const sessions = await registry.indexedAccountSessions({ accountId });
    if (!Array.isArray(sessions)) throw new Error('session_index_unavailable');
    let revokedSessions = 0;
    for (const row of sessions) {
      if (!row || !opaque.test(row.object_id ?? '') || !opaque.test(row.session_id ?? '')) throw new Error('invalid_session_index');
      const revoked = await stateFor(row.object_id).forceRevokeForAccountDeletion({ id: row.session_id });
      if (revoked !== true) throw new Error('session_revoke_failed');
      revokedSessions++;
    }
    return { ok: true, lockToken, revokedSessions };
  } catch {
    try { await registry.releaseAccountDeletion({ accountId, lockToken }); } catch { /* the lease expires */ }
    return { ok: false, error: 'account_deletion_unavailable' };
  }
}

function chatDeletionFlusher({ passwordRpcSecret, passwordRpcOrigin, fetcher = fetch, now = epoch }) {
  const passwordRpcConfigured = typeof passwordRpcSecret === 'string' && passwordRpcSecret.length >= 32 &&
    typeof passwordRpcOrigin === 'string' && /^https:\/\/[^/]+\/?$/.test(passwordRpcOrigin);
  // Last-link deletion must also remove the Chat account that owns the
  // password credential, AFTER finalizeAccountDeletion commits the tombstone.
  async function deleteChatAccount(productUserId) {
    if (!passwordRpcConfigured) return;
    const path = '/internal/account-delete';
    const body = encoder.encode(JSON.stringify({ product_user_id: productUserId }));
    const headers = await passwordRpcHeaders(passwordRpcSecret, path, body, now());
    const response = await fetcher(passwordRpcOrigin.replace(/\/+$/, '') + path, { method: 'POST', redirect: 'manual', headers, body });
    if (response.status !== 200) throw new Error('chat account delete failed');
  }
  return async function flushPendingChatDeletions(registry, accountIdHash) {
    if (!passwordRpcConfigured) return;
    const pending = await registry.pendingChatAccountDeletions(accountIdHash ? { accountIdHash } : {});
    if (!Array.isArray(pending) || !pending.length) return;
    for (const productUserId of pending) {
      await deleteChatAccount(productUserId);
      await registry.completeChatAccountDeletion({ productUserId });
    }
  };
}

function stateBindingFor(env) {
  return (name) => new Proxy({}, { get(_target, method) { return async (args) => {
    const stub = env.AUTH_STATE.get(env.AUTH_STATE.idFromName(name));
    const response = await stub.fetch(`https://internal/${method}`, { method: 'POST', body: JSON.stringify(args) });
    if (!response.ok) throw new Error('state failed');
    return (await response.json()).value;
  }; } });
}

const deletedGoogleAccountResponse = (request) => htmlPage(403, messagePage('탈퇴한 계정입니다. 다시 시작하려면 새 계정으로 가입해 주세요.', resolveLang(request.headers.get('accept-language'))));
const DELETED_ACCOUNT = Object.freeze({ state: 'deleted' });

// An adapter is injected in tests; the deployed entry point below only uses DO bindings.
export function createApp({ clients, googleClientId, googleClientSecret, identityKey, refreshKey, adminSecret, accountDeleteRpcSecret, passwordRpcSecret, passwordRpcOrigin, signingKey, signingKid, jwks, stateFor, fetcher = fetch, now = epoch, emailRecoveryEnabled = false, passwordFindEnabled = false, emailConfirmationEnabled = false, defer }) {
  const passwordRpcConfigured = typeof passwordRpcSecret === 'string' && passwordRpcSecret.length >= 32 &&
    typeof passwordRpcOrigin === 'string' && /^https:\/\/[^/]+\/?$/.test(passwordRpcOrigin);
  const passwordChoiceEnabled = (client) => client?.password_login === true && passwordRpcConfigured;
  const recoveryEnabled = recoverySwitch(emailRecoveryEnabled) && passwordRpcConfigured;
  // #7679 password find widens the same mailed proof to live accounts. It has
  // its own switch and does nothing unless the recovery surface is on too.
  const findEnabled = recoveryEnabled && recoverySwitch(passwordFindEnabled);
  const passwordPage = (status, body, lang, extra = {}) => htmlPage(status, recoveryEnabled ? addRecoveryLink(body, lang, findEnabled) : body, extra);
  // #7679: the optional confirmation mail after an email signup, on its own switch.
  const confirmEnabled = passwordRpcConfigured && recoverySwitch(emailConfirmationEnabled);
  // Asks Chat to mail one link and keeps only the digest Chat reports for it.
  // The registry admits the mail first (live account, not confirmed, budgets).
  async function sendEmailConfirmation({ registry, fingerprint, epoch, email, lang, source, current }) {
    const sourceDigest = b64(new Uint8Array(await crypto.subtle.sign('HMAC', identityKey, encoder.encode(`padiem-auth:email-confirmation-source:v1\0${source || 'unknown'}`))));
    if (await registry.reserveEmailConfirmation({ fingerprint, epoch, sourceDigest, now: current }) !== true) return;
    const path = '/internal/email-confirmation/send';
    const body = encoder.encode(JSON.stringify({ email, lang: lang === 'en' ? 'en' : 'ko' }));
    const response = await fetcher(passwordRpcOrigin.replace(/\/+$/, '') + path, { method: 'POST', redirect: 'manual', headers: await passwordRpcHeaders(passwordRpcSecret, path, body, current), body });
    const data = response.status === 200 ? await response.json() : null;
    if (data?.ok !== true || !validConfirmationDigest(data.token_digest)) return;
    await registry.recordEmailConfirmationToken({ fingerprint, epoch, tokenDigest: data.token_digest, expires: current + EMAIL_CONFIRMATION_TTL_SECONDS, now: current });
  }
  const flushPendingChatDeletions = chatDeletionFlusher({ passwordRpcSecret, passwordRpcOrigin, fetcher, now });
  async function verifyClient(params, client, current) {
    const assertion = one(params, 'client_assertion');
    if (one(params, 'client_assertion_type') !== 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer') throw new Error('bad client authentication');
    await verifyClientAssertion({ assertion, clientId: client.id, jwks: client.jwks, audience: `${ORIGIN}/token`, now: current,
      claim: (x) => stateFor('client-assertion-replay').claimAssertion(x) });
  }
  async function app(request) {
    const url = new URL(request.url), current = now();
    if (url.pathname === '/password/recovery' || url.pathname.startsWith('/password/recovery/')) {
      if (!recoveryEnabled) return json(404, { error: 'not_found' });
      const lang = resolveLang(request.headers.get('accept-language'));
      const text = recoveryStrings(lang, findEnabled);
      if (request.method === 'GET' && (url.pathname === '/password/recovery' || url.pathname === '/password/recovery/confirm')) {
        return htmlPage(200, recoveryPage(url.pathname.endsWith('/confirm') ? 'confirm' : 'request', lang, findEnabled));
      }
      if (request.method === 'POST' && url.pathname === '/password/recovery/request') {
        const submitted = recoveryBody(request).then(body => new URLSearchParams(body));
        const work = async () => {
          try {
            const form = await submitted;
            const email = one(form, 'email').trim().toLowerCase();
            if (validRecoveryEmail(email)) {
              const source = request.headers.get('cf-connecting-ip') || 'unknown';
              const sourceDigest = b64(new Uint8Array(await crypto.subtle.sign('HMAC', identityKey, encoder.encode(`padiem-auth:email-recovery-source:v1\0${source}`))));
              const rpc = action => payload => recoveryRpc({ secret: passwordRpcSecret, origin: passwordRpcOrigin, fetcher, now: current }, action, payload);
              let candidate = null, mode = null;
              try {
                const status = await rpc('status')({ email });
                const data = status.status === 200 ? await status.json() : null;
                if (data?.ok === true && data.available === true) {
                  candidate = await stateFor('google-account-registry').emailRecoveryCandidate({ fingerprint: await passwordIdentityFingerprint(identityKey, email), now: current });
                } else if (findEnabled && data?.ok === true && data.present === true) {
                  // #7679: a live credential asks for a password change. The
                  // registry judges it in the same call as a restoration.
                  candidate = await stateFor('google-account-registry').emailRecoveryCandidate({ fingerprint: await passwordIdentityFingerprint(identityKey, email), now: current, mode: 'reset' });
                  if (candidate) mode = 'reset';
                }
              } catch { /* still charge the request budget without approval */ }
              await rpc('request')({ email, source_digest: sourceDigest, account_id: candidate?.account_id ?? null, credential_epoch: candidate?.credential_epoch ?? null, ...(mode ? { mode } : {}) });
            }
          } catch { console.error(JSON.stringify({ auth_stage: 'email_recovery_request_unavailable' })); }
        };
        // #7679: with password find on, the answer leaves before any lookup or
        // mail starts, so how long it takes says nothing about the address.
        if (findEnabled && typeof defer === 'function') { await submitted.catch(() => {}); defer(work()); }
        else await work();
        // Same bytes for an unknown address, throttling, RPC or mail failure.
        return htmlPage(202, recoveryPage('requested', lang, findEnabled));
      }
      if (request.method === 'POST' && url.pathname === '/password/recovery/confirm') {
        let data;
        try {
          if (request.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new Error('invalid');
          data = JSON.parse(await recoveryBody(request));
        } catch { return json(400, { ok: false, error: 'password_recovery_invalid', message: text.invalid }); }
        if (!data || Object.keys(data).sort().join(',') !== 'new_password,token' || !validRecoveryToken(data.token) || typeof data.new_password !== 'string' || data.new_password.length > 128) {
          return json(400, { ok: false, error: 'password_recovery_invalid', message: text.invalid });
        }
        let result;
        try { result = await stateFor('google-account-registry').completeEmailRecovery({ token: data.token, newPassword: data.new_password, now: current }); }
        catch { result = { status: 503 }; }
        if (result?.ok === true) return json(200, { ok: true, message: text.complete });
        if (result?.status === 503) return json(503, { ok: false, error: 'password_recovery_unavailable', message: text.unavailable });
        if (result?.error === 'password_recovery_password_invalid') return json(400, { ok: false, error: result.error, message: text.passwordInvalid });
        return json(400, { ok: false, error: 'password_recovery_invalid', message: text.invalid });
      }
      return json(404, { error: 'not_found' });
    }
    if (url.pathname === '/email/confirm') {
      if (!confirmEnabled) return json(404, { error: 'not_found' });
      const text = confirmationStrings(resolveLang(request.headers.get('accept-language')));
      if (request.method === 'GET') return htmlPage(200, confirmationPage(resolveLang(request.headers.get('accept-language'))));
      if (request.method !== 'POST') return json(404, { error: 'not_found' });
      // Expired, used, unknown and malformed links share this one answer.
      const refused = () => json(400, { ok: false, error: 'email_confirmation_invalid', message: text.invalid });
      let data;
      try {
        if (request.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new Error('invalid');
        data = JSON.parse(await recoveryBody(request));
      } catch { return refused(); }
      if (!data || Object.keys(data).join(',') !== 'token' || !validConfirmationToken(data.token)) return refused();
      let confirmed;
      try { confirmed = await stateFor('google-account-registry').completeEmailConfirmation({ tokenDigest: await confirmationTokenDigest(data.token), now: current }); }
      catch { return json(503, { ok: false, error: 'email_confirmation_unavailable', message: text.unavailable }); }
      return confirmed === true ? json(200, { ok: true, message: text.complete }) : refused();
    }
    const tokenTiming = url.pathname === '/token' && request.method === 'POST'
      ? { started: performance.now(), requestId: '', bodyParseMs: 0, clientAuthMs: 0, codeExchangeMs: 0, tokenSignMs: 0 }
      : null;
    const traceId = request.headers.get('x-request-id') || '';
    if (tokenTiming && SAFE_REQUEST_ID.test(traceId)) tokenTiming.requestId = traceId;
    if (['/internal/account-delete/prepare', '/internal/account-delete/complete', '/internal/account-delete/abort'].includes(url.pathname) && request.method === 'POST') {
      if (!accountDeleteRpcSecret) return json(404, { error: 'not_found' });
      const verified = await verifyAccountDeletionRpc(request, accountDeleteRpcSecret, current);
      if (!verified) return json(401, { error: 'unauthorized' });
      const payload = verified.payload;
      const operationId = payload?.operation_id;
      if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
          Object.keys(payload).length !== 2 ||
          !/^sub_[A-Za-z0-9_-]{1,128}$/.test(payload.account_id ?? '') ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(operationId ?? '')) {
        return json(400, { error: 'invalid_request' });
      }
      const registry = stateFor('google-account-registry');
      const claimed = await registry.claimAssertion({
        key: `account-delete-rpc:${verified.serviceId}`,
        expires: verified.at + 600,
        now: current,
      });
      if (claimed !== true) return json(409, { error: 'request_replayed' });
      const accountId = payload.account_id;
      const lockToken = operationId;
      if (url.pathname === '/internal/account-delete/abort') {
        const aborted = await registry.releaseAccountDeletion({ accountId, lockToken });
        return aborted === true
          ? json(200, { ok: true, aborted: true })
          : json(409, { error: 'account_deletion_lock_missing' });
      }
      if (url.pathname === '/internal/account-delete/complete') {
        const accountIdHash = await digestHex(accountId);
        const completed = await registry.finalizeAccountDeletion({ accountId, accountIdHash, lockToken, now: current });
        if (completed !== true) return json(409, { error: 'account_deletion_lock_missing' });
        try {
          await flushPendingChatDeletions(registry, accountIdHash);
        } catch {
          return json(503, { error: 'account_deletion_unavailable' });
        }
        return json(200, { ok: true, deleted: true });
      }
      const prepared = await prepareAccountDeletion(registry, stateFor, { accountId, lockToken, now: current });
      if (!prepared.ok) return json(prepared.error === 'account_deletion_busy' ? 409 : 503, { error: prepared.error });
      return json(200, { ok: true, prepared: true, revoked_sessions: prepared.revokedSessions });
    }
    // #7078: Chat password change/reset revokes this user's padiem-auth
    // sessions (refresh included) through the same signed internal envelope.
    // The mapping is Chat user id -> canonical account(s); an account with no
    // shared login simply resolves to zero rows and the call is a no-op.
    if (url.pathname === '/internal/account-sessions/revoke' && request.method === 'POST') {
      if (!accountDeleteRpcSecret) return json(404, { error: 'not_found' });
      const verified = await verifyAccountDeletionRpc(request, accountDeleteRpcSecret, current);
      if (!verified) return json(401, { error: 'unauthorized' });
      const payload = verified.payload;
      const keys = payload && typeof payload === 'object' && !Array.isArray(payload) ? Object.keys(payload) : [];
      const allowedKeys = keys.every(k => k === 'product_id' || k === 'product_user_id' || k === 'account_id');
      if (!allowedKeys ||
          payload.product_id !== 'b62' ||
          !/^usr_[A-Za-z0-9_-]{1,79}$/.test(payload.product_user_id ?? '') ||
          ('account_id' in payload && !/^sub_[A-Za-z0-9_-]+$/.test(payload.account_id ?? ''))) {
        return json(400, { error: 'invalid_request' });
      }
      const registry = stateFor('google-account-registry');
      const claimed = await registry.claimAssertion({
        key: `account-sessions-revoke:${verified.serviceId}`,
        expires: verified.at + 600,
        now: current,
      });
      if (claimed !== true) return json(409, { error: 'request_replayed' });
      try {
        const mappedIds = await registry.accountIdsForChatUser({ productUserId: payload.product_user_id });
        if (!Array.isArray(mappedIds)) throw new Error('account_index_unavailable');
        const accountIds = [...new Set([...mappedIds, ...(payload.account_id ? [payload.account_id] : [])])];
        let revokedSessions = 0;
        let accounts = 0;
        for (const accountId of accountIds) {
          if (!/^sub_[A-Za-z0-9_-]+$/.test(accountId ?? '')) continue;
          const account = await registry.accountById(accountId);
          if (!account || account.state !== 'active') continue;
          const sessions = await registry.indexedAccountSessions({ accountId });
          if (!Array.isArray(sessions)) throw new Error('session_index_unavailable');
          accounts++;
          for (const row of sessions) {
            if (!row || !opaque.test(row.object_id ?? '') || !opaque.test(row.session_id ?? '')) throw new Error('invalid_session_index');
            const revoked = await stateFor(row.object_id).forceRevokeForAccountDeletion({ id: row.session_id });
            if (revoked !== true) throw new Error('session_revoke_failed');
            revokedSessions++;
          }
        }
        return json(200, { ok: true, accounts, revoked_sessions: revokedSessions });
      } catch {
        return json(503, { error: 'session_revoke_unavailable' });
      }
    }
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
      const registry = stateFor('google-account-registry');
      await registry.setAccountStatus({ accountId: body.account_id, blocked: true });
      const sessions = await registry.indexedAccountSessions({ accountId: body.account_id });
      if (Array.isArray(sessions)) {
        for (const row of sessions) {
          if (row && opaque.test(row.object_id ?? '') && opaque.test(row.session_id ?? '')) {
            await stateFor(row.object_id).forceRevokeForAccountDeletion({ id: row.session_id });
          }
        }
      }
      return json(200, { ok: true });
    }
    if (url.pathname === '/.well-known/jwks.json' && request.method === 'GET') {
      const keys = (jwks?.keys || []).map(({ kty, crv, x, y, kid, use, alg }) => ({ kty, crv, x, y, kid, use, alg }));
      return json(200, { keys });
    }
    // Login-skin fonts and images. They are part of this Worker (there is no
    // static-asset binding) and are served from the auth origin so the login
    // page never makes an external request.
    if (url.pathname.startsWith(AUTH_SKIN_ASSET_PREFIX) && request.method === 'GET') {
      const asset = authSkinAsset(url.pathname.slice(AUTH_SKIN_ASSET_PREFIX.length));
      if (!asset) return json(404, { error: 'not_found' });
      return new Response(asset.bytes, { headers: { 'cache-control': 'public, max-age=86400', 'content-type': asset.type, 'x-content-type-options': 'nosniff' } });
    }
    if ((url.pathname === '/login' || url.pathname === '/login/google' || url.pathname === '/signup') && request.method === 'GET') {
      const id = one(url.searchParams, 'client_id'), returnTo = one(url.searchParams, 'redirect_uri');
      const serviceState = one(url.searchParams, 'state'), challenge = one(url.searchParams, 'code_challenge');
      const client = clients[id];
      if (!validClient.test(id) || !client || client.id !== id || !client.redirect_uris.includes(returnTo) ||
          !opaque.test(serviceState) || !opaque.test(challenge) || one(url.searchParams, 'code_challenge_method') !== 'S256') return json(400, { error: 'invalid_request' });
      // The skin, if any, is fixed by the registered client_id. lt_theme only
      // picks a registered brand's light/dark variant; it never selects a brand
      // and an unknown value stays on the brand's default (night).
      const brand = resolveBrand(id);
      const theme = resolveTheme(brand, one(url.searchParams, 'lt_theme'));
      const lang = resolveLang(request.headers.get('accept-language'));
      const fields = profileClaimAllowlist(client);
      const object = random(), stateSecret = random(), browser = random(), nonce = random(), verifier = random();
      await stateFor(object).createLogin({ stateDigest: await digest(stateSecret), browserDigest: await digest(browser), client: id, redirect: returnTo, serviceState, serviceChallenge: challenge, googleNonce: nonce, googleVerifier: verifier, expires: current + 600 });
      const cookieSet = cookieHeader(browser, 600);
      // The email choice/signup screens create exactly the same login state and
      // browser cookie as the Google redirect does; the email form POST later
      // consumes that same state. Email entry stays OFF unless the client opts
      // in (password_login) and the Chat verification RPC is configured.
      if (passwordChoiceEnabled(client)) {
        const carry = new URLSearchParams({ client_id: id, redirect_uri: returnTo, state: serviceState, code_challenge: challenge, code_challenge_method: 'S256' });
        if (brand) carry.set('lt_theme', theme);
        if (url.pathname === '/login' && one(url.searchParams, 'provider') !== 'google') {
          const formAction = `/login/password?state=${encodeURIComponent(`${object}.${stateSecret}`)}`;
          const body = brand
            ? brandLoginPage({ brand, theme, lang, googleHref: `/login/google?${carry}`, formAction, signupHref: `/signup?${carry}` })
            : loginChoicePage(`/login/google?${carry}`, formAction, `/signup?${carry}`, lang);
          return passwordPage(200, body, lang, { 'set-cookie': cookieSet });
        }
        if (url.pathname === '/signup') {
          const formAction = `/signup/password?state=${encodeURIComponent(`${object}.${stateSecret}`)}`;
          const body = brand
            ? brandSignupPage({ brand, theme, lang, formAction, loginHref: `/login?${carry}` })
            : signupFormPage(formAction, '', lang, `/login?${carry}`);
          return passwordPage(200, body, lang, { 'set-cookie': cookieSet });
        }
      }
      if (url.pathname === '/signup') return json(404, { error: 'not_found' });
      const google = new URL('https://accounts.google.com/o/oauth2/v2/auth');
      const values = { client_id: googleClientId, redirect_uri: CALLBACK, response_type: 'code', scope: fields.length ? 'openid email profile' : 'openid', state: `${object}.${stateSecret}`, nonce, code_challenge: await digest(verifier), code_challenge_method: 'S256' };
      for (const [k, v] of Object.entries(values)) google.searchParams.set(k, v);
      return redirect(google.href, { 'set-cookie': cookieSet });
    }
    if ((url.pathname === '/login/password' || url.pathname === '/signup/password') && request.method === 'POST') {
      if (!passwordRpcConfigured) return json(404, { error: 'not_found' });
      const register = url.pathname === '/signup/password';
      const state = split(one(url.searchParams, 'state')), browser = cookieValue(request);
      if (!state || !opaque.test(browser)) return json(400, { error: 'invalid_request' });
      const contentLength = Number(request.headers.get('content-length') || '0');
      if (contentLength > 4096) return json(400, { error: 'invalid_request' });
      const form = new URLSearchParams(await request.text());
      const email = one(form, 'email').trim().toLowerCase();
      const password = one(form, 'password');
      const name = one(form, 'name').trim().slice(0, 160);
      const action = `${register ? '/signup/password' : '/login/password'}?state=${encodeURIComponent(state.join('.'))}`;
      const lang = resolveLang(request.headers.get('accept-language'));
      const formError = (message) => passwordPage(200, register ? signupFormPage(action, message, lang) : loginFormPage(action, message, lang), lang);
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 255 || password.length < 1 || password.length > 128 ||
          (register && /[\x00-\x1f\x7f]/.test(name))) {
        return formError(register ? '이메일과 비밀번호 형식을 확인해 주세요.' : '이메일 주소와 비밀번호를 입력해 주세요.');
      }
      if (!await allowPasswordAttempt(stateFor, request.headers.get('cf-connecting-ip'), current)) {
        return htmlPage(429, messagePage('로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.', lang));
      }
      const attempt = await diagnosed('password_attempt_failed', async () =>
        stateFor(state[0]).beginPasswordAttempt({ stateDigest: await digest(state[1]), browserDigest: await digest(browser), now: current, maxAttempts: 5 }));
      if (!attempt.ok && attempt.reason === 'exhausted') {
        return htmlPage(429, messagePage('시도 횟수가 초과되었습니다. 처음부터 다시 로그인해 주세요.', lang));
      }
      if (!attempt.ok) return json(400, { error: 'invalid_request' });
      // The pending login record already carries the validated client and its
      // redirect/PKCE values, so a form error re-renders the same skin without a
      // new lookup and without trusting anything from the submitted form except
      // the cosmetic lt_theme value.
      const brand = resolveBrand(attempt.login?.client);
      const theme = resolveTheme(brand, one(form, 'lt_theme'));
      const carry = new URLSearchParams({
        client_id: attempt.login.client, redirect_uri: attempt.login.redirect,
        state: attempt.login.service_state, code_challenge: attempt.login.service_challenge,
        code_challenge_method: 'S256',
      });
      if (brand) carry.set('lt_theme', theme);
      const errorPage = (message) => passwordPage(200, register
        ? (brand
          ? brandSignupPage({ brand, theme, lang, formAction: action, loginHref: `/login?${carry}`, message })
          : signupFormPage(action, message, lang, `/login?${carry}`))
        : (brand
          ? brandLoginPage({ brand, theme, lang, formAction: action, signupHref: `/signup?${carry}`, message, showGoogle: false })
          : loginFormPage(action, message, lang, `/signup?${carry}`)), lang);
      const registry = stateFor('google-account-registry');
      const passwordFingerprint = await passwordIdentityFingerprint(identityKey, email);
      const ownershipUnproven = () => errorPage(recoveryEnabled ? recoveryStrings(lang, findEnabled).refused : register
        ? '이미 PADIEM 계정이 있는 이메일입니다. 로그인해 주세요.'
        : '이 이메일의 PADIEM 계정을 확인할 수 없습니다. 처음 가입한 방법으로 로그인하거나 문의해 주세요.');
      // #7551: a signup never attaches to a live account; checked before the
      // Chat credential is created so a refused signup leaves nothing behind.
      if (register && await registry.passwordBindingRefused({ fingerprint: passwordFingerprint, epoch: '', register: true })) {
        return ownershipUnproven();
      }
      // Prove deletion before touching the credential: a deleted identity is a
      // distinct outcome from a wrong password, and it must not mint a new sub_.
      if (!register && await registry.identityIsDeleted({ fingerprint: passwordFingerprint })) {
        return errorPage('탈퇴한 계정입니다. 같은 이메일로 새로 가입해 주세요.');
      }
      if (register) {
        try {
          await flushPendingChatDeletions(registry);
        } catch {
          return htmlPage(503, messagePage('지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.', lang));
        }
      }
      const rpcPath = register ? '/internal/password-register' : '/internal/password-verify';
      const payload = register ? { email, password, name } : { email, password };
      const rpcBody = encoder.encode(JSON.stringify(payload));
      let response;
      try {
        response = await fetcher(passwordRpcOrigin.replace(/\/+$/, '') + rpcPath, { method: 'POST', redirect: 'manual', headers: await passwordRpcHeaders(passwordRpcSecret, rpcPath, rpcBody, current), body: rpcBody });
      } catch {
        return htmlPage(503, messagePage('로그인 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.', lang));
      }
      if (response.status !== 200) {
        if (response.status === 401 && !register) return errorPage('이메일 또는 비밀번호가 올바르지 않습니다.');
        let code = '';
        try { code = String((await response.json())?.error?.code || ''); } catch { /* status-only fallback */ }
        if (response.status === 409 || code === 'account_exists') return errorPage(recoveryEnabled ? recoveryStrings(lang, findEnabled).refused : '이미 사용 중인 이메일입니다.');
        if (response.status === 400 && code.startsWith('invalid_')) return errorPage('입력 정보를 확인해 주세요.');
        return htmlPage(503, messagePage('지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.', lang));
      }
      let data;
      try { data = await response.json(); } catch { return htmlPage(503, messagePage('지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.', lang)); }
      if (data?.ok !== true || !/^usr_[A-Za-z0-9_-]{1,79}$/.test(data.product_user_id ?? '') ||
          !CREDENTIAL_EPOCH.test(data.credential_epoch ?? '')) {
        return htmlPage(503, messagePage('지금은 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.', lang));
      }
      const credentialEpoch = data.credential_epoch;
      if (await registry.passwordBindingRefused({ fingerprint: passwordFingerprint, epoch: credentialEpoch, register })) {
        return ownershipUnproven();
      }
      if (register) await registry.clearIdentityDeletion({ fingerprint: passwordFingerprint });
      const pending = await diagnosed('login_state_read_failed', async () =>
        stateFor(state[0]).consumeLogin({ stateDigest: await digest(state[1]), browserDigest: await digest(browser), now: current }));
      if (!pending) return json(400, { error: 'invalid_callback' });
      if (!clients[pending.client]?.redirect_uris?.includes(pending.redirect)) return json(400, { error: 'invalid_callback' });
      const account = await diagnosed('identity_lookup_failed', async () => {
        const result = await registry.resolveAccount({ fingerprint: passwordFingerprint, productId: pending.client, userId: data.product_user_id, subject: email, provider: 'password', now: current, allowRecreate: register, credentialEpoch, register });
        if (!result || result.state !== 'active' || !/^sub_[A-Za-z0-9_-]+$/.test(result.account_id ?? '')) throw new Error('identity authority failed');
        return result;
      });
      // #7679: the optional confirmation mail. It never delays or fails the
      // signup; where the runtime allows it the work runs after the answer.
      if (register && confirmEnabled) {
        const mail = sendEmailConfirmation({ registry, fingerprint: passwordFingerprint, epoch: credentialEpoch, email, lang, source: request.headers.get('cf-connecting-ip'), current })
          .catch(() => { console.error(JSON.stringify({ auth_stage: 'email_confirmation_unavailable' })); });
        if (typeof defer === 'function') defer(mail); else await mail;
      }
      const codeSecret = random(), codeDigest = await digest(codeSecret);
      const fields = profileClaimAllowlist(clients[pending.client]);
      let encryptedProfile;
      if (fields.length) {
        // A password login proves the credential against Chat's internal
        // /internal/password-verify, not the mailbox: by itself the profile
        // never claims a verified email. Operator allowlists key on a verified
        // email, so email_verified stays false. Chat's shared-profile provision
        // accepts email_verified:false when the verified access token carries
        // amr:['pwd'] (with the empty name/picture shape kept as transitional
        // fallback).
        // #7679: the one exception is an address its owner confirmed through
        // the mailed link, for the credential the account was linked with, and
        // only while that switch is on.
        const emailConfirmed = confirmEnabled && !register && fields.includes('email_verified') &&
          await registry.passwordEmailConfirmed({ fingerprint: passwordFingerprint, epoch: credentialEpoch }) === true;
        const claims = { email, email_verified: emailConfirmed, name: '', picture: '' };
        const profile = Object.fromEntries(fields.map(field => [field, claims[field]]));
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const aad = encoder.encode(`profile:${pending.client}:${codeDigest}`);
        const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad }, refreshKey, encoder.encode(JSON.stringify(profile)));
        encryptedProfile = `${b64(iv)}.${b64(new Uint8Array(cipher))}`;
      }
      await diagnosed('code_issue_failed', async () => stateFor(state[0]).createCode({ digest: codeDigest, client: pending.client, redirect: pending.redirect, challenge: pending.service_challenge, subject: account.account_id, accountId: account.account_id, expires: current + 60, encryptedProfile, amr: 'pwd' }));
      const target = new URL(pending.redirect);
      target.searchParams.set('code', `${state[0]}.${codeSecret}`);
      target.searchParams.set('state', pending.service_state);
      const leave = { 'set-cookie': cookieHeader('', 0), 'referrer-policy': 'no-referrer' };
      // #7679: a finished email signup shows one confirmation screen that
      // carries the same return address; a login still returns at once.
      if (register) return htmlPage(200, signupCompletePage({ brand, theme, lang, email, continueHref: target.href }), leave);
      return redirect(target.href, leave);
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
      if (await stateFor('google-account-registry').identityIsDeleted({ fingerprint: await identityFingerprint(identityKey, identity.sub) })) {
        return deletedGoogleAccountResponse(request);
      }
      const account = await diagnosed('identity_lookup_failed', async () => {
        const userId = await googleProductUserId(identity.sub);
        const fingerprint = await identityFingerprint(identityKey, identity.sub);
        const result = await stateFor('google-account-registry').resolveAccount({ fingerprint, productId: pending.client, userId, subject: identity.sub, now: current });
        if (result?.state === 'deleted') return result;
        if (!result || result.state !== 'active' || !/^sub_[A-Za-z0-9_-]+$/.test(result.account_id ?? '')) throw new Error('identity authority failed');
        return result;
      });
      if (account.state === 'deleted') return deletedGoogleAccountResponse(request);
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
      await diagnosed('code_issue_failed', async () => stateFor(state[0]).createCode({ digest: codeDigest, client: pending.client, redirect: pending.redirect, challenge: pending.service_challenge, subject: account.account_id, accountId: account.account_id, expires: current + 60, encryptedProfile, amr: 'google' }));
      const target = new URL(pending.redirect); target.searchParams.set('code', `${state[0]}.${codeSecret}`); target.searchParams.set('state', pending.service_state);
      return redirect(target.href, { 'set-cookie': cookieHeader('', 0), 'referrer-policy': 'no-referrer' });
    }
    if ((url.pathname === '/token' || url.pathname === '/logout') && request.method === 'POST') {
      const bodyStarted = performance.now();
      const params = new URLSearchParams(await request.text());
      const id = one(params, 'client_id'), client = clients[id];
      if (tokenTiming) tokenTiming.bodyParseMs = performance.now() - bodyStarted;
      if (!client || client.id !== id) return json(401, { error: 'invalid_client' });
      const clientAuthStarted = performance.now();
      try { await verifyClient(params, client, current); } catch { return json(401, { error: 'invalid_client' }); }
      finally { if (tokenTiming) tokenTiming.clientAuthMs = performance.now() - clientAuthStarted; }
      let subject, accountId, object, sessionId, profile, amr = ['google'], nextSecret = random();
      if (url.pathname === '/token' && one(params, 'grant_type') === 'authorization_code') {
        const code = split(one(params, 'code')), verifier = one(params, 'code_verifier'), returnTo = one(params, 'redirect_uri');
        if (!code || !opaque.test(verifier) || !client.redirect_uris.includes(returnTo)) return json(400, { error: 'invalid_grant' });
        object = code[0]; sessionId = random();
        const codeExchangeStarted = performance.now();
        const result = await diagnosed('session_storage_failed', async () => stateFor(object).exchangeCode({ codeDigest: await digest(code[1]), client: id, redirect: returnTo, challenge: await digest(verifier), now: current, id: sessionId, expires: current + 30 * 24 * 3600, refreshDigest: await digest(nextSecret) }));
        if (tokenTiming) tokenTiming.codeExchangeMs = performance.now() - codeExchangeStarted;
        if (!result) return json(400, { error: 'invalid_grant' });
        subject = result.subject;
        accountId = result.accountId;
        amr = result.amr === 'pwd' ? ['pwd'] : ['google'];
        const profileStarted = performance.now();
        try {
          const indexed = await stateFor('google-account-registry').indexAccountSession({
            accountId, objectId: object, sessionId, expires: current + 30 * 24 * 3600, now: current,
          });
          if (indexed !== true) throw new Error('session_index_failed');
        } catch (error) {
          try { await stateFor(object).forceRevokeForAccountDeletion({ id: sessionId }); } catch { /* fail closed */ }
          throw error;
        }
        const fields = profileClaimAllowlist(client);
        if (fields.length) {
          if (typeof result.encryptedProfile !== 'string') throw new Error('profile unavailable');
          const [iv, cipher, extra] = result.encryptedProfile.split('.');
          if (!iv || !cipher || extra !== undefined) throw new Error('invalid profile');
          const aad = encoder.encode(`profile:${id}:${await digest(code[1])}`);
          const plain = await crypto.subtle.decrypt({name:'AES-GCM',iv:un64(iv),additionalData:aad}, refreshKey, un64(cipher));
          profile = verifiedIssuedProfile(JSON.parse(new TextDecoder().decode(plain)), fields);
        }
        if (tokenTiming) tokenTiming.profileMs = performance.now() - profileStarted;
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
        const refreshAmr = snapshot.amr === 'pwd' ? ['pwd'] : ['google'];
        const access = await issueAccessToken({ key: signingKey, kid: signingKid, issuer: ORIGIN, audience: id, subject: snapshot.subject, accountId: snapshot.account_id, sessionId, now: current, amr: refreshAmr });
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
      const tokenSignStarted = performance.now();
      const access = await issueAccessToken({ key: signingKey, kid: signingKid, issuer: ORIGIN, audience: id, subject, accountId, sessionId, now: current, amr });
      if (tokenTiming) tokenTiming.tokenSignMs = performance.now() - tokenSignStarted;
      const response = { access_token: access, token_type: 'Bearer', expires_in: 900, refresh_token: `${object}.${sessionId}.${nextSecret}` };
      if (profile) { response.account_id = accountId; response.profile = profile; }
      return finishTokenTiming(json(200, response), tokenTiming, id);
    }
    return json(404, { error: 'not_found' });
  }
  return { async fetch(request) { try { return await app(request); } catch { return json(503, { error: 'authentication_unavailable' }); } } };
}

const methods = new Set(['createLogin', 'consumeLogin', 'beginPasswordAttempt', 'claimAssertion', 'createCode', 'exchangeCode', 'inspectRefresh', 'rotate', 'revoke', 'forceRevokeForAccountDeletion', 'indexAccountSession', 'beginAccountDeletion', 'indexedAccountSessions', 'releaseAccountDeletion', 'finalizeAccountDeletion', 'pruneAccountDeletionAudit', 'nextAccountDeletionAuditExpiry', 'resolveAccount', 'accountById', 'setAccountStatus', 'identityIsDeleted', 'clearIdentityDeletion', 'recordAccountChatUsers', 'accountIdsForChatUser', 'pendingChatAccountDeletions', 'completeChatAccountDeletion', 'passwordBindingRefused', 'emailRecoveryCandidate', 'completeEmailRecovery', 'passwordEmailConfirmed', 'reserveEmailConfirmation', 'recordEmailConfirmationToken', 'completeEmailConfirmation']);
export class AuthStateObject extends AuthState {
  constructor(state, env, { recoveryFetcher = fetch, recoveryStateFor = stateBindingFor(env) } = {}) {
    super(state); this.state = state; this.env = env;
    this.recoveryFetcher = recoveryFetcher; this.recoveryStateFor = recoveryStateFor;
  }
  // The one judgment for a mailed proof. 'restore' (#7606) brings back the
  // credential of a Chat-only withdrawal; 'reset' (#7679 password find) changes
  // the password of a live credential and exists only while its switch is on.
  // Both need a live, unblocked, undeleted account that was linked with a
  // password, and at least one product still using it.
  async emailRecoveryCandidate({ fingerprint, now, mode = 'restore' }) {
    if (!recoverySwitch(this.env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED)) return null;
    if (mode !== 'restore' && !(mode === 'reset' && recoverySwitch(this.env.PADIEM_AUTH_PASSWORD_FIND_ENABLED))) return null;
    const candidate = this.passwordRecoveryAccount({ fingerprint, now });
    if (!candidate || !CREDENTIAL_EPOCH.test(candidate.credential_epoch)) return null;
    // A surviving common account has another active product link. A stale
    // auth mapping after last-link deletion is not proof that it survived.
    const result = plainRpc(await this.env.IDENTITY_AUTHORITY.list_active_product_links_for_subject({ canonical_subject_id: candidate.account_id }));
    const links = Array.isArray(result) ? result : result?.ok === true ? result.links : null;
    // A restoration needs the Chat link to be gone; a password change does not.
    if (!Array.isArray(links) || !links.length || links.some(link => !link || link.state !== 'active' || typeof link.product_id !== 'string' || (mode === 'restore' && link.product_id === 'b62'))) return null;
    return candidate;
  }
  // #7679: a password change ends the sessions of every other common account
  // this Chat user is recorded under, the same set the signed revoke route
  // covers for Chat's own password change (#7078). The proven account itself
  // is revoked under its lock by prepareAccountDeletion.
  async revokeMappedAccountSessions({ productUserId, except }) {
    try {
      for (const accountId of this.accountIdsForChatUser({ productUserId })) {
        if (accountId === except) continue;
        const account = this.accountById(accountId);
        if (!account || account.state !== 'active') continue;
        const sessions = this.indexedAccountSessions({ accountId });
        if (!Array.isArray(sessions)) return false;
        for (const row of sessions) {
          if (!row || !opaque.test(row.object_id ?? '') || !opaque.test(row.session_id ?? '')) return false;
          if (await this.recoveryStateFor(row.object_id).forceRevokeForAccountDeletion({ id: row.session_id }) !== true) return false;
        }
      }
      return true;
    } catch { return false; }
  }
  async completeEmailRecovery({ token, newPassword, now }) {
    if (!recoverySwitch(this.env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED)) return { status: 404 };
    if (!validRecoveryToken(token) || typeof newPassword !== 'string' || newPassword.length > 128 || !Number.isSafeInteger(now)) return { status: 400 };
    return this.state.blockConcurrencyWhile(async () => {
      const rpc = (action, payload) => recoveryRpc({
        secret: this.env.PADIEM_AUTH_PASSWORD_RPC_SECRET, origin: this.env.PADIEM_CHAT_PASSWORD_RPC_ORIGIN,
        fetcher: this.recoveryFetcher, now,
      }, action, payload);
      const response = await rpc('inspect', { token, new_password: newPassword });
      if (response.status !== 200) {
        const failure = await response.json();
        if (response.status === 400 && failure?.error?.code === 'invalid_password') return { status: 400, error: 'password_recovery_password_invalid' };
        return { status: response.status >= 500 ? 503 : 400 };
      }
      const proof = await response.json();
      if (proof?.ok !== true || !validRecoveryEmail(proof.email) || proof.email !== proof.email.trim().toLowerCase() ||
          !/^sub_[A-Za-z0-9_-]+$/.test(proof.account_id ?? '') || !CREDENTIAL_EPOCH.test(proof.credential_epoch ?? '')) return { status: 400 };
      // #7679: Chat names a proof that belongs to a live credential. It is
      // honoured only while password find is on and is re-judged below like
      // any other proof.
      const reset = proof.mode === 'reset';
      if (reset && (!recoverySwitch(this.env.PADIEM_AUTH_PASSWORD_FIND_ENABLED) || !/^usr_[0-9a-f]{32}$/.test(proof.product_user_id ?? ''))) return { status: 400 };
      const bytes = un64(this.env.PADIEM_AUTH_IDENTITY_HMAC_KEY);
      if (bytes.length !== 32) throw new Error('identity_key_unavailable');
      const key = await crypto.subtle.importKey('raw', bytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
      const fingerprint = await passwordIdentityFingerprint(key, proof.email);
      const candidate = await this.emailRecoveryCandidate(reset ? { fingerprint, now, mode: 'reset' } : { fingerprint, now });
      if (!candidate || candidate.account_id !== proof.account_id || candidate.credential_epoch !== proof.credential_epoch) return { status: 400 };
      const availability = await rpc('status', { email: proof.email });
      if (availability.status !== 200) return { status: 503 };
      const current = await availability.json();
      if (current?.ok !== true || (reset ? current.present !== true : current.available !== true)) return { status: 400 };
      // The registry remains serialized across revocation and Chat's atomic
      // completion. Its existing lock also refuses new session indexing.
      const prepared = await prepareAccountDeletion(this, this.recoveryStateFor, { accountId: candidate.account_id, now });
      if (!prepared.ok) return { status: 503 };
      try {
        if (reset && !await this.revokeMappedAccountSessions({ productUserId: proof.product_user_id, except: candidate.account_id })) return { status: 503 };
        const completed = await rpc('complete', { token, new_password: newPassword, account_id: candidate.account_id, credential_epoch: candidate.credential_epoch });
        const answer = await completed.json();
        if (completed.status === 400 && answer?.error?.code === 'invalid_password') return { status: 400, error: 'password_recovery_password_invalid' };
        if (completed.status !== 200) return { status: completed.status >= 500 ? 503 : 400 };
        // Recovery creates a fresh product-local identity so a deleted Chat
        // cookie can never become valid again. The signed Chat result must
        // retain the proven common account and logical credential generation.
        if (answer?.ok !== true || !/^usr_[0-9a-f]{32}$/.test(answer.product_user_id ?? '') ||
            answer.account_id !== candidate.account_id || answer.credential_epoch !== candidate.credential_epoch) return { status: 503 };
        // A password change keeps the local identity it was proven for.
        if (reset && answer.product_user_id !== proof.product_user_id) return { status: 503 };
        return { ok: true };
      } finally {
        await this.releaseAccountDeletion({ accountId: candidate.account_id, lockToken: prepared.lockToken });
      }
    });
  }
  async createCode(input) {
    if (input.encryptedProfile) await this.storage.setAlarm(input.expires * 1000);
    return super.createCode(input);
  }
  async alarm() {
    const now = Math.floor(Date.now() / 1000);
    this.clearExpiredProfiles(now);
    this.pruneAccountDeletionAudit({ now });
    const next = this.nextAccountDeletionAuditExpiry();
    if (next && typeof this.storage.setAlarm === 'function') await this.storage.setAlarm(Math.max(Date.now() + 1000, next * 1000));
  }
  async beginAccountDeletion(input) {
    const locked = super.beginAccountDeletion(input);
    if (locked && typeof this.env?.IDENTITY_AUTHORITY?.list_active_product_links_for_subject === 'function') {
      try {
        const result = plainRpc(await this.env.IDENTITY_AUTHORITY.list_active_product_links_for_subject({ canonical_subject_id: input.accountId }));
        const links = Array.isArray(result?.links) ? result.links : (Array.isArray(result) ? result : []);
        const productUserIds = links.map(link => link?.product_user_id).filter(id => typeof id === 'string' && /^usr_[A-Za-z0-9_-]{1,79}$/.test(id));
        if (productUserIds.length) this.recordAccountChatUsers({ accountId: input.accountId, productUserIds });
      } catch { /* prepare never fails on optional link snapshot */ }
    }
    return locked;
  }
  async finalizeAccountDeletion(input) {
    const finalized = super.finalizeAccountDeletion(input);
    if (finalized) {
      const next = this.nextAccountDeletionAuditExpiry();
      if (next && typeof this.storage.setAlarm === 'function') await this.storage.setAlarm(Math.max(Date.now() + 1000, next * 1000));
    }
    return finalized;
  }
  async recoverDeletedAccount(accountId, now) {
    let stage = 'account_deletion_record_check';
    let prepared;
    try {
      const decision = plainRpc(await this.env.COMMON_LOGIN_DELETION_RECORD.resolve_subject_removed_by_account_deletion({ canonical_subject_id: accountId }));
      if (decision?.ok !== true || decision?.removed_by_account_deletion !== true) {
        console.error(JSON.stringify({ auth_stage: stage }));
        return false;
      }
      stage = 'account_deletion_recovery_prepare';
      // Use this registry directly: a fetch to this same DO would deadlock
      // while resolveAccount holds blockConcurrencyWhile.
      prepared = await prepareAccountDeletion(this, stateBindingFor(this.env), { accountId, now });
      if (!prepared.ok) throw new Error('account_deletion_prepare_failed');
      stage = 'account_deletion_recovery_finalize';
      const accountIdHash = await digestHex(accountId);
      const completed = await this.finalizeAccountDeletion({ accountId, accountIdHash, lockToken: prepared.lockToken, now });
      if (completed !== true) throw new Error('account_deletion_finalize_failed');
      stage = 'account_deletion_recovery_chat_cleanup';
      await chatDeletionFlusher({ passwordRpcSecret: this.env.PADIEM_AUTH_PASSWORD_RPC_SECRET, passwordRpcOrigin: this.env.PADIEM_CHAT_PASSWORD_RPC_ORIGIN, now: () => now })(this, accountIdHash);
      console.log(JSON.stringify({ auth_stage: 'account_deletion_recovery_complete' }));
      return true;
    } catch {
      if (prepared?.ok) {
        try { await this.releaseAccountDeletion({ accountId, lockToken: prepared.lockToken }); }
        catch { console.error(JSON.stringify({ auth_stage: 'account_deletion_recovery_abort' })); }
      }
      console.error(JSON.stringify({ auth_stage: stage }));
      return false;
    }
  }
  async resolveAccount({ fingerprint, productId, userId, subject, provider = 'google', now = Math.floor(Date.now() / 1000), allowRecreate = false, credentialEpoch = null, register = false }) {
    // DO serialization prevents two concurrent first logins from issuing two
    // authority calls or binding one fingerprint to different accounts.
    return this.state.blockConcurrencyWhile(async () => {
      if (!allowRecreate && this.identityIsDeleted({ fingerprint })) throw new Error('identity_deleted');
      if (provider === 'password') {
        // #7551: re-checked under the same serialization that binds.
        if (typeof credentialEpoch !== 'string' || !credentialEpoch) throw new Error('credential_epoch_required');
        if (this.passwordBindingRefused({ fingerprint, epoch: credentialEpoch, register })) throw new Error('identity_ownership_unproven');
      }
      const result = await this.resolveAccountUnchecked({ fingerprint, productId, userId, subject, provider, now });
      if (provider === 'password') this.recordPasswordCredentialEpoch({ fingerprint, epoch: credentialEpoch });
      return result;
    });
  }
  async resolveAccountUnchecked({ fingerprint, productId, userId, subject, provider, now }) {
    {
      const current = this.accountByFingerprint(fingerprint);
      if (current && (current.state !== 'active' || productId !== 'b62')) {
        if ((productId === 'b62' || provider === 'password') && typeof userId === 'string' && /^usr_[A-Za-z0-9_-]{1,79}$/.test(userId)) {
          this.recordAccountChatUsers({ accountId: current.account_id, productUserIds: [userId] });
        }
        logAccountCheck(productId, provider, true, 'skipped_known');
        return current;
      }
      let checked = 'failed';
      const linked = await diagnosed('identity_authority_rpc_failed', async () => {
        const request = { product_id: productId, product_user_id: userId, auth_provider: provider, provider_subject: subject };
        if (current) request.expected_canonical_subject_id = current.account_id;
        const result = plainRpc(await this.env.IDENTITY_AUTHORITY.resolve_or_create_product_link(request));
        if (result?.ok !== true || result?.link?.state !== 'active' || result?.link?.product_id !== productId || result?.link?.product_user_id !== userId || !/^sub_[A-Za-z0-9_-]+$/.test(result?.link?.canonical_subject_id ?? '')) {
          // Only the authority's closed error code and the product id: no subject, fingerprint or user id.
          const code = typeof result?.error?.code === 'string' && /^[a-z0-9_]{1,64}$/.test(result.error.code) ? result.error.code : (result?.ok === true ? 'link_shape_mismatch' : 'unknown');
          const shape = result === null ? 'null' : typeof result === 'object' ? (result.constructor?.name || 'object') + ':' + Object.keys(result).sort().join(',') : typeof result;
          const errorKeys = result && typeof result.error === 'object' && result.error ? Object.keys(result.error).sort().join(',') : '';
          console.error(JSON.stringify({ auth_stage: 'identity_authority_rejected', product: productId, code, shape, error_keys: errorKeys, expected_subject_sent: Boolean(current) }));
          checked = 'rejected';
          if (provider === 'google' && productId === 'b62' && current && result?.ok === false && code === 'identity_rebind_forbidden' &&
              await this.recoverDeletedAccount(current.account_id, now)) {
            return DELETED_ACCOUNT;
          }
          throw new Error('identity authority failed');
        }
        checked = 'called';
        return result;
      }).finally(() => logAccountCheck(productId, provider, Boolean(current), checked));
      if (linked === DELETED_ACCOUNT) return linked;
      if (current && current.account_id !== linked.link.canonical_subject_id) throw new Error('identity_conflict');
      return diagnosed('account_mapping_storage_failed', async () => this.putAccount({ fingerprint, accountId: linked.link.canonical_subject_id, productUserId: (productId === 'b62' || provider === 'password') ? userId : undefined, now }));
    }
  }
  async fetch(request) {
    const action = new URL(request.url).pathname.slice(1);
    if (request.method !== 'POST' || !methods.has(action)) return json(404, { error: 'not_found' });
    if (['emailRecoveryCandidate', 'completeEmailRecovery'].includes(action) && !recoverySwitch(this.env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED)) return json(404, { error: 'not_found' });
    if (['passwordEmailConfirmed', 'reserveEmailConfirmation', 'recordEmailConfirmationToken', 'completeEmailConfirmation'].includes(action) && !recoverySwitch(this.env.PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED)) return json(404, { error: 'not_found' });
    try { return json(200, { value: (await this[action](await request.json())) ?? null }); } catch { return json(500, { error: 'state_failure' }); }
  }
}

export default {
  async fetch(request, env, ctx) {
    try {
      const path = new URL(request.url).pathname;
      if ((path === '/password/recovery' || path.startsWith('/password/recovery/')) && !recoverySwitch(env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED)) return json(404, { error: 'not_found' });
      if (path === '/email/confirm' && !recoverySwitch(env.PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED)) return json(404, { error: 'not_found' });
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
      const stateFor = stateBindingFor(env);
      return await createApp({ clients, googleClientId: env.GOOGLE_CLIENT_ID, googleClientSecret: env.GOOGLE_CLIENT_SECRET, identityKey, refreshKey, adminSecret: env.PADIEM_AUTH_ADMIN_SECRET, accountDeleteRpcSecret: env.PADIEM_ACCOUNT_DELETE_RPC_SECRET, passwordRpcSecret: env.PADIEM_AUTH_PASSWORD_RPC_SECRET, passwordRpcOrigin: env.PADIEM_CHAT_PASSWORD_RPC_ORIGIN, signingKey, signingKid: env.PADIEM_AUTH_SIGNING_KID, jwks, stateFor, emailRecoveryEnabled: env.PADIEM_AUTH_EMAIL_RECOVERY_ENABLED, passwordFindEnabled: env.PADIEM_AUTH_PASSWORD_FIND_ENABLED, emailConfirmationEnabled: env.PADIEM_AUTH_EMAIL_CONFIRMATION_ENABLED, defer: typeof ctx?.waitUntil === 'function' ? work => ctx.waitUntil(work) : undefined }).fetch(request);
    } catch { return json(503, { error: 'authentication_unavailable' }); }
  }
};

