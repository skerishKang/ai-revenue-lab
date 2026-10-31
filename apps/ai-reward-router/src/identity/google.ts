/**
 * B64 Google sign-in (issue #987) — a product-local adapter over the
 * repository's already-proven Google login contract
 * (`apps/padiem-chat/app/auth.py`), not a new auth engine:
 *
 * - the same authorization-code flow and the same parameter set
 *   (`response_type=code`, `scope=openid email profile`,
 *   `include_granted_scopes=true`);
 * - the same CSRF shape: a random state stored in a signed, HttpOnly cookie and
 *   compared constant-time against the query parameter;
 * - the same identity check: the `userinfo` response with
 *   `verified_email === true`, keyed on the account's stable `sub`.
 *
 * What is B64's own and is never borrowed from another product: the OAuth
 * client credentials, the redirect origin (`B64_PUBLIC_BASE_URL`), the state
 * cookie name and purpose, the session cookie, and the member id. Because the
 * signing goes through `hmac.ts` with the purpose
 * `b64-reward/oauth-state/v1`, a B64 state token verifies nowhere else and a
 * `chat.padiem.net` cookie verifies nowhere here.
 */

import {
  base64UrlToBytes,
  bytesToBase64Url,
  readB64Token,
  signB64Token,
  timingSafeEqualBytes,
  utf8Bytes,
} from './hmac.js';
import { normalizeEmail, EMAIL_MAX_CHARS, CredentialError } from './password.js';

export const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';
export const GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token';
export const GOOGLE_USERINFO_URL = 'https://www.googleapis.com/oauth2/v2/userinfo';

export const B64_OAUTH_STATE_COOKIE_NAME = 'b64_oauth_state';
export const B64_OAUTH_STATE_TOKEN_PURPOSE = 'b64-reward/oauth-state/v1';
export const B64_OAUTH_STATE_MAX_AGE_SECONDS = 600;
export const B64_GOOGLE_START_PATH = '/auth/google/start';
export const B64_GOOGLE_CALLBACK_PATH = '/auth/google/callback';

const MAX_GOOGLE_RESPONSE_BYTES = 1024 * 1024;
const GOOGLE_TOKEN_TIMEOUT_MS = 15_000;

/**
 * The account `sub` is the only durable key this login trusts, so it is held to
 * the repository's own bounded identifier grammar.
 */
const GOOGLE_SUB_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

export function isB64GoogleSubject(value: unknown): value is string {
  return typeof value === 'string' && GOOGLE_SUB_RE.test(value);
}

export class GoogleAuthError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(code);
    this.name = 'GoogleAuthError';
    this.status = status;
    this.code = code;
  }
}

export type GoogleFetch = (url: string, init: RequestInit) => Promise<Response>;

/** The runtime's own fetch; tests substitute it to pin the provider contract. */
export const defaultGoogleFetch: GoogleFetch = (url, init) => fetch(url, init);

/* ------------------------------- state cookie ------------------------------ */

function stateValue(): string {
  return bytesToBase64Url(crypto.getRandomValues(new Uint8Array(18)));
}

export async function mintB64OAuthState(options: {
  readonly sessionSecret: string;
  readonly nowSeconds?: number;
}): Promise<{ readonly state: string; readonly token: string }> {
  if (!options.sessionSecret) throw new GoogleAuthError(503, 'auth_unavailable');
  const nowSeconds = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  const state = stateValue();
  const token = await signB64Token(options.sessionSecret, B64_OAUTH_STATE_TOKEN_PURPOSE, {
    v: 1,
    state,
    exp: nowSeconds + B64_OAUTH_STATE_MAX_AGE_SECONDS,
  });
  return Object.freeze({ state, token });
}

/** True only when the query state equals the state this Worker signed into the cookie. */
export async function verifyB64OAuthState(options: {
  readonly sessionSecret: string | undefined;
  readonly state: string | null | undefined;
  readonly token: string | null | undefined;
  readonly nowSeconds?: number;
}): Promise<boolean> {
  if (!options.state || !options.token || !options.sessionSecret) return false;
  const claims = await readB64Token(
    options.sessionSecret,
    B64_OAUTH_STATE_TOKEN_PURPOSE,
    options.token,
    options.nowSeconds,
  );
  if (!claims) return false;
  const expected = claims['state'];
  if (typeof expected !== 'string' || expected.length === 0) return false;
  return timingSafeEqualBytes(utf8Bytes(expected), utf8Bytes(options.state));
}

function stateCookieAttributeString(token: string, maxAgeSeconds: number): string {
  return [
    `${B64_OAUTH_STATE_COOKIE_NAME}=${token}`,
    'Path=/',
    `Max-Age=${maxAgeSeconds}`,
    'HttpOnly',
    'SameSite=Lax',
    'Secure',
  ].join('; ');
}

export function b64OAuthStateCookieValue(token: string): string {
  return stateCookieAttributeString(token, B64_OAUTH_STATE_MAX_AGE_SECONDS);
}

export function b64OAuthStateClearCookieValue(): string {
  return stateCookieAttributeString('', 0);
}

/* ---------------------------- authorization request ------------------------ */

/**
 * The redirect target is derived from server configuration only, and only ever
 * the reviewed https origin — never from the request's own Host.
 */
export function b64GoogleRedirectUri(publicBaseUrl: string | undefined): string {
  if (!publicBaseUrl) throw new GoogleAuthError(503, 'auth_unavailable');
  let parsed: URL;
  try {
    parsed = new URL(publicBaseUrl);
  } catch {
    throw new GoogleAuthError(503, 'auth_unavailable');
  }
  if (parsed.protocol !== 'https:' || !parsed.host) {
    throw new GoogleAuthError(503, 'auth_unavailable');
  }
  return parsed.origin + B64_GOOGLE_CALLBACK_PATH;
}

export function b64GoogleAuthorizationUrl(options: {
  readonly clientId: string | undefined;
  readonly redirectUri: string;
  readonly state: string;
}): string {
  if (!options.clientId) throw new GoogleAuthError(503, 'auth_unavailable');
  const params = new URLSearchParams({
    client_id: options.clientId,
    redirect_uri: options.redirectUri,
    response_type: 'code',
    scope: 'openid email profile',
    state: options.state,
    include_granted_scopes: 'true',
  });
  return `${GOOGLE_AUTH_URL}?${params.toString()}`;
}

/* --------------------------- provider round trip --------------------------- */

async function boundedJson(response: Response, code: string): Promise<Record<string, unknown>> {
  if (response.status < 200 || response.status >= 300) throw new GoogleAuthError(502, code);
  let raw = '';
  if (response.body) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let received = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        received += value?.byteLength ?? 0;
        if (received > MAX_GOOGLE_RESPONSE_BYTES) {
          await reader.cancel().catch(() => undefined);
          throw new GoogleAuthError(502, code);
        }
        raw += decoder.decode(value, { stream: true });
      }
      raw += decoder.decode();
    } catch (error) {
      if (error instanceof GoogleAuthError) throw error;
      // A body that is not UTF-8 is a broken provider response, not a login.
      await reader.cancel().catch(() => undefined);
      throw new GoogleAuthError(502, code);
    }
  }
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new GoogleAuthError(502, code);
  }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) {
    throw new GoogleAuthError(502, code);
  }
  return data as Record<string, unknown>;
}

async function postJson(url: string, form: URLSearchParams, fetchImpl: GoogleFetch): Promise<Response> {
  const signal = AbortSignal.timeout(GOOGLE_TOKEN_TIMEOUT_MS);
  try {
    return await fetchImpl(url, {
      method: 'POST',
      body: form,
      headers: { 'content-type': 'application/x-www-form-urlencoded', accept: 'application/json' },
      redirect: 'manual',
      signal,
    });
  } catch {
    throw new GoogleAuthError(502, 'auth_provider_error');
  }
}

/** Exchanges the authorization code. The client secret is never returned. */
export async function exchangeGoogleCode(options: {
  readonly code: string;
  readonly clientId: string | undefined;
  readonly clientSecret: string | undefined;
  readonly redirectUri: string;
  readonly fetchImpl: GoogleFetch;
}): Promise<string> {
  if (!options.code) throw new GoogleAuthError(502, 'auth_provider_error');
  if (!options.clientId || !options.clientSecret) throw new GoogleAuthError(503, 'auth_unavailable');
  const response = await postJson(
    GOOGLE_TOKEN_URL,
    new URLSearchParams({
      client_id: options.clientId,
      client_secret: options.clientSecret,
      code: options.code,
      grant_type: 'authorization_code',
      redirect_uri: options.redirectUri,
    }),
    options.fetchImpl,
  );
  const data = await boundedJson(response, 'auth_provider_error');
  const token = data['access_token'];
  if (typeof token !== 'string' || token.length === 0) {
    throw new GoogleAuthError(502, 'auth_provider_error');
  }
  return token;
}

export interface B64GoogleIdentity {
  readonly googleSub: string;
  readonly email: string;
}

/**
 * Reads the verified identity. An unverified address is refused, so a Google
 * account that has not confirmed its email can never become a B64 member.
 */
export async function fetchGoogleVerifiedIdentity(options: {
  readonly accessToken: string;
  readonly fetchImpl: GoogleFetch;
}): Promise<B64GoogleIdentity> {
  let response: Response;
  try {
    response = await options.fetchImpl(GOOGLE_USERINFO_URL, {
      method: 'GET',
      headers: { authorization: `Bearer ${options.accessToken}`, accept: 'application/json' },
      redirect: 'manual',
      signal: AbortSignal.timeout(GOOGLE_TOKEN_TIMEOUT_MS),
    });
  } catch {
    throw new GoogleAuthError(502, 'auth_provider_error');
  }
  const data = await boundedJson(response, 'auth_provider_error');
  const subject = data['id'];
  const email = data['email'];
  const verified = data['verified_email'];
  if (
    !isB64GoogleSubject(subject) ||
    typeof email !== 'string' ||
    email.length === 0 ||
    email.length > EMAIL_MAX_CHARS ||
    verified !== true
  ) {
    throw new GoogleAuthError(403, 'auth_identity_unverified');
  }
  try {
    return Object.freeze({ googleSub: subject, email: normalizeEmail(email) });
  } catch (error) {
    if (error instanceof CredentialError) throw new GoogleAuthError(403, 'auth_identity_unverified');
    throw error;
  }
}
