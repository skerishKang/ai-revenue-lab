import type { AuthResolver } from '../income-pipeline/auth.js';
import type { B64MemberStore } from './member-store.js';
import {
  b64GoogleRedirectUri,
  defaultGoogleFetch,
  exchangeGoogleCode,
  fetchGoogleVerifiedIdentity,
  type B64GoogleIdentity,
  type GoogleFetch,
} from './google.js';
import { normalizeEmail, hashPassword, validatePassword, verifyPassword } from './password.js';
import {
  B64_SESSION_COOKIE_NAME,
  B64_SESSION_MAX_AGE_SECONDS,
  b64SessionCookieValue,
  mintB64SessionToken,
  newB64MemberId,
  newB64SessionId,
  verifyB64SessionToken,
} from './session.js';

/**
 * B64's own identity boundary (issue #987). Two things must both hold for a
 * request to be a member: the cookie carries a valid B64 signature that has not
 * expired, AND the session row behind it is still unrevoked in D1. The
 * signature alone would let a logged-out token live out its full Max-Age, so
 * the row is what makes logout and revocation actually take effect.
 */

export function extractCookieValue(cookieHeader: string, name: string): string | null {
  let match: string | null = null;
  for (const part of cookieHeader.split(';')) {
    const separator = part.indexOf('=');
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() !== name) continue;
    match = part.slice(separator + 1).trim();
  }
  return match;
}

export interface B64AuthResolverOptions {
  readonly sessionSecret: string | undefined;
  readonly members: B64MemberStore;
}

const UNAUTHENTICATED = Object.freeze({ authenticated: false, userId: null });

export function createB64AuthResolver(options: B64AuthResolverOptions): AuthResolver {
  return async (request: Request) => {
    const { sessionSecret, members } = options;
    if (!sessionSecret) return UNAUTHENTICATED;
    const cookieHeader = request.headers.get('cookie');
    if (cookieHeader === null) return UNAUTHENTICATED;
    const claims = await verifyB64SessionToken(
      extractCookieValue(cookieHeader, B64_SESSION_COOKIE_NAME),
      sessionSecret,
    );
    if (claims === null) return UNAUTHENTICATED;
    let session;
    try {
      session = await members.findLiveSession(claims.sessionId);
    } catch {
      // A storage failure is not an authentication failure to paper over, and
      // it is never treated as "authenticated".
      return UNAUTHENTICATED;
    }
    if (session === null) return UNAUTHENTICATED;
    if (session.memberId !== claims.memberId) return UNAUTHENTICATED;
    return Object.freeze({ authenticated: true, userId: claims.memberId });
  };
}

export interface B64IssuedSession {
  readonly memberId: string;
  readonly cookieHeader: string;
}

/**
 * Registers a member and opens its first session. The password never leaves
 * this function in the clear: only the PBKDF2 verifier is stored.
 */
export async function registerMember(options: {
  readonly store: B64MemberStore;
  readonly sessionSecret: string;
  readonly email: unknown;
  readonly password: unknown;
}): Promise<B64IssuedSession> {
  const email = normalizeEmail(options.email);
  const passwordHash = await hashPassword(validatePassword(options.password));
  const memberId = newB64MemberId();
  const createdAt = new Date().toISOString();
  await options.store.createMember({ id: memberId, email, passwordHash, createdAt });
  return openSession({ store: options.store, sessionSecret: options.sessionSecret, memberId });
}

/**
 * Verifies a candidate against the stored hash. An unknown address still pays
 * one full KDF (`verifyPassword` runs the fixed dummy verifier), so the answer
 * does not come cheaper for an address that is not registered.
 */
export async function signInMember(options: {
  readonly store: B64MemberStore;
  readonly sessionSecret: string;
  readonly email: unknown;
  readonly password: unknown;
}): Promise<B64IssuedSession | null> {
  let email: string;
  try {
    email = normalizeEmail(options.email);
  } catch {
    await verifyPassword(typeof options.password === 'string' ? options.password : '', null);
    return null;
  }
  const member = await options.store.findByEmail(email);
  const ok = await verifyPassword(
    typeof options.password === 'string' ? options.password : '',
    member?.passwordHash ?? null,
  );
  if (!ok || member === null) return null;
  return openSession({ store: options.store, sessionSecret: options.sessionSecret, memberId: member.id });
}

async function openSession(options: {
  readonly store: B64MemberStore;
  readonly sessionSecret: string;
  readonly memberId: string;
}): Promise<B64IssuedSession> {
  const sessionId = newB64SessionId();
  const nowSeconds = Math.floor(Date.now() / 1000);
  const expiresAtSeconds = nowSeconds + B64_SESSION_MAX_AGE_SECONDS;
  const token = await mintB64SessionToken({
    sessionSecret: options.sessionSecret,
    memberId: options.memberId,
    sessionId,
    expiresAtSeconds,
  });
  await options.store.createSession({
    id: sessionId,
    memberId: options.memberId,
    expiresAt: new Date(expiresAtSeconds * 1000).toISOString(),
    revokedAt: null,
  });
  return Object.freeze({ memberId: options.memberId, cookieHeader: b64SessionCookieValue(token) });
}

/**
 * Signs a Google-verified visitor in with the session machinery above — the
 * same signed `b64_session` cookie and the same D1 session row a password login
 * gets, so logout and revocation work identically (#987 reuse).
 *
 * The provider subject is the only account key. An unknown subject becomes a
 * new B64 member; a matching email address never attaches the login to an
 * existing email/password member, because that would merge two people's
 * ledgers on the strength of a string.
 */
export async function signInWithGoogle(options: {
  readonly store: B64MemberStore;
  readonly sessionSecret: string;
  readonly clientId: string | undefined;
  readonly clientSecret: string | undefined;
  readonly publicBaseUrl: string | undefined;
  readonly code: string;
  readonly fetchImpl?: GoogleFetch;
}): Promise<B64IssuedSession> {
  const redirectUri = b64GoogleRedirectUri(options.publicBaseUrl);
  const fetchImpl = options.fetchImpl ?? defaultGoogleFetch;
  const accessToken = await exchangeGoogleCode({
    code: options.code,
    clientId: options.clientId,
    clientSecret: options.clientSecret,
    redirectUri,
    fetchImpl,
  });
  const identity = await fetchGoogleVerifiedIdentity({ accessToken, fetchImpl });
  const linked = await options.store.findMemberIdByGoogleSub(identity.googleSub);
  const memberId = linked ?? (await linkNewGoogleMember(options.store, identity));
  return openSession({ store: options.store, sessionSecret: options.sessionSecret, memberId });
}

async function linkNewGoogleMember(
  store: B64MemberStore,
  identity: B64GoogleIdentity,
): Promise<string> {
  const memberId = newB64MemberId();
  try {
    await store.linkGoogleMember({
      googleSub: identity.googleSub,
      memberId,
      email: identity.email,
      linkedAt: new Date().toISOString(),
    });
  } catch (error) {
    // Two first-time logins for one subject: the row that won the race names
    // the member, and the just-minted id is simply never used.
    const winner = await store.findMemberIdByGoogleSub(identity.googleSub);
    if (winner !== null) return winner;
    throw error;
  }
  return memberId;
}

/**
 * Revokes one session row. The caller clears the cookie on the way out; the
 * row is what keeps a copied token from working after this returns.
 */
export async function logoutSession(options: {
  readonly store: B64MemberStore;
  readonly sessionSecret: string;
  readonly cookieHeader: string | null;
}): Promise<void> {
  const { sessionSecret } = options;
  if (!sessionSecret || options.cookieHeader === null) return;
  const claims = await verifyB64SessionToken(
    extractCookieValue(options.cookieHeader, B64_SESSION_COOKIE_NAME),
    sessionSecret,
  );
  if (claims === null) return;
  await options.store.revokeSession(claims.sessionId);
}
