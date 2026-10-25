import type { AuthResult, AuthResolver } from './auth.js';

/**
 * PADIEM consumer session verification for B64 (issue #987).
 *
 * This reuses the existing PADIEM login authority instead of introducing a
 * second login scheme: the signed `padiem_session` cookie that the B62 chat
 * product mints and verifies in `apps/padiem-chat/app/auth.py`. The token
 * format is `<b64url(payload)>.<b64url(sig)>`, where the signature is
 * `HMAC-SHA256(HMAC-SHA256(secret, purpose), body)` with the exact purpose
 * string `padiem-chat/session/v1`, and the payload is
 * `{"v":1,"uid":"usr_...","exp":<unix>,"sid"?:"<canonical session id>"}`.
 *
 * This module is the Workers-runtime port of that verifier
 * (`decode_session_claims`), following the same reuse precedent as
 * `apps/padiem-designer/app/identity.py`: same cookie, same secret, same
 * signing purpose — never a separate B64 credential or client-controlled
 * identity header. The session secret binding must hold the same value as the
 * chat product's `PADIEM_CHAT_SESSION_SECRET`.
 *
 * Delivery boundary (documented in DEPLOYMENT.md): the `padiem_session` cookie
 * is `HttpOnly; Secure; SameSite=Lax` with no Domain attribute, so it is
 * host-only for the chat origin. It reaches this Worker only when B64 is
 * served under that origin. Verification fails closed in every other case.
 */

export const PADIEM_SESSION_COOKIE_NAME = 'padiem_session';

/**
 * Verbatim signing purpose of the B62 session authority
 * (`apps/padiem-chat/app/auth.py`, create_session_token). A different purpose
 * string produces a different HMAC key, so a chat OAuth-state or Android
 * handoff token can never authenticate a session here.
 */
export const PADIEM_SESSION_TOKEN_PURPOSE = 'padiem-chat/session/v1';

const CANONICAL_SESSION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export interface VerifiedPadiemSession {
  readonly userId: string;
  readonly canonicalSessionId: string | null;
}

const UNAUTHENTICATED: AuthResult = Object.freeze({ authenticated: false, userId: null });

// --- base64url (implemented with Web-standard primitives so the same code
// runs in the Workers runtime and in node --test; no Buffer dependency) ---

const B64URL_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

const B64URL_CHAR_LOOKUP: Readonly<Record<string, number>> = (() => {
  const lookup: Record<string, number> = {};
  for (let i = 0; i < B64URL_ALPHABET.length; i++) {
    lookup[B64URL_ALPHABET[i]!] = i;
  }
  return Object.freeze(lookup);
})();

function b64urlDecode(text: string): Uint8Array | null {
  if (text.length % 4 === 1) return null;
  for (const ch of text) {
    if (!(ch in B64URL_CHAR_LOOKUP)) return null;
  }
  let bits = 0;
  let accumulator = 0;
  const bytes: number[] = [];
  for (const ch of text) {
    accumulator = (accumulator << 6) | B64URL_CHAR_LOOKUP[ch]!;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((accumulator >> bits) & 0xff);
    }
  }
  return new Uint8Array(bytes);
}

function utf8Bytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

async function hmacSha256(keyBytes: Uint8Array, messageBytes: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'raw',
    keyBytes as BufferSource,
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signature = await crypto.subtle.sign('HMAC', key, messageBytes as BufferSource);
  return new Uint8Array(signature);
}

function timingSafeEqualBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a[i]! ^ b[i]!;
  }
  return diff === 0;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Verifies one `padiem_session` token with the B62 session authority's
 * algorithm and returns its verified claims, or null when the token is not a
 * valid, unexpired session of that authority.
 */
export async function verifyPadiemSessionToken(
  token: string | null | undefined,
  sessionSecret: string | undefined,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Promise<VerifiedPadiemSession | null> {
  if (!token || !sessionSecret) return null;

  const separatorIndex = token.indexOf('.');
  if (separatorIndex <= 0) return null;
  const body = token.slice(0, separatorIndex);
  const signatureText = token.slice(separatorIndex + 1);

  const key = await hmacSha256(utf8Bytes(sessionSecret), utf8Bytes(PADIEM_SESSION_TOKEN_PURPOSE));
  const expectedSignature = await hmacSha256(key, utf8Bytes(body));
  const suppliedSignature = b64urlDecode(signatureText);
  if (!suppliedSignature || !timingSafeEqualBytes(expectedSignature, suppliedSignature)) {
    return null;
  }

  const payloadBytes = b64urlDecode(body);
  if (!payloadBytes) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payloadBytes));
  } catch {
    return null;
  }
  if (!isPlainObject(payload)) return null;

  if (payload['v'] !== 1) return null;

  const exp = payload['exp'];
  if (typeof exp !== 'number' || !Number.isInteger(exp) || exp < nowSeconds) return null;

  const uid = payload['uid'];
  if (typeof uid !== 'string' || !uid.startsWith('usr_') || uid.length > 80) return null;

  const sid = payload['sid'];
  if (sid === undefined) {
    return { userId: uid, canonicalSessionId: null };
  }
  if (typeof sid !== 'string' || !CANONICAL_SESSION_ID_RE.test(sid)) return null;
  return { userId: uid, canonicalSessionId: sid };
}

/** Returns the value of the last `name` cookie, mirroring the B62 parser's
 * later-occurrence-wins behaviour for duplicated cookie names. */
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

export interface PadiemSessionAuthResolverOptions {
  /**
   * Server-owned session secret. Must hold the same value as the chat
   * product's `PADIEM_CHAT_SESSION_SECRET`. When it is absent or empty the
   * resolver fails closed: no request is ever authenticated.
   */
  readonly sessionSecret?: string | undefined;
  /**
   * Optional canonical-session liveness probe (logout/revocation blocking).
   * When present it is called with the request's raw `Cookie` header after
   * the offline signature check passes; resolving means the canonical session
   * is live, throwing means the request is treated as unauthenticated.
   * When it is absent the resolver falls back to the offline signature and
   * expiry check only, exactly like the existing in-repo precedent
   * (`apps/padiem-designer/app/identity.py`).
   */
  readonly sessionLivenessProbe?: SessionLivenessProbe | undefined;
}

/**
 * Probes whether the session carried by one raw `Cookie` header is still
 * canonical-live. Resolving = live; throwing = not live or not verifiable.
 */
export type SessionLivenessProbe = (cookieHeader: string) => Promise<void>;

/**
 * Structural surface of a Cloudflare service binding used for the liveness
 * probe. Matches the only existing non-Python caller in this repository
 * (`reference/business-66-padiem-quote-v1/_worker.js` lines 440-447), which
 * calls `binding.fetch(new Request(target, init))` on the `PADIEM_CHAT_SERVICE`
 * binding.
 */
export interface ServiceBindingLike {
  fetch(input: Request): Promise<Response>;
}

export interface ChatSessionStatusProbeOptions {
  /** Service binding to the deployed chat product worker. */
  readonly chatService: ServiceBindingLike;
  /**
   * Origin the chat product is served on. Defaults to the chat product's
   * reviewed public origin. It is only used to build the relay request URL
   * for the service binding; the binding itself delivers the request.
   */
  readonly chatOrigin?: string | undefined;
}

const DEFAULT_CHAT_ORIGIN = 'https://chat.padiem.net';

/**
 * Builds a liveness probe over the chat product's existing
 * `GET /api/auth/status` endpoint, reusing the one proven "second product
 * verifies a chat session" relay in this repository: the cookie header is
 * forwarded unchanged and `authenticated` in the response is the
 * revocation-aware verdict (chat's `current_user_id` consults the session
 * revocation guard, so a logged-out or revoked canonical session answers
 * `authenticated: false`). The probe passes ONLY on an ok response whose
 * body says `authenticated: true`; everything else — non-ok, unparsable,
 * auth store not ready, revoked/expired session — throws, so the resolver
 * fails closed.
 */
export function createChatSessionStatusProbe(
  options: ChatSessionStatusProbeOptions,
): SessionLivenessProbe {
  const origin = options.chatOrigin ?? DEFAULT_CHAT_ORIGIN;
  return async (cookieHeader: string): Promise<void> => {
    const target = new URL('/api/auth/status', origin);
    let response: Response;
    try {
      response = await options.chatService.fetch(
        new Request(target, {
          method: 'GET',
          headers: { cookie: cookieHeader, accept: 'application/json' },
          redirect: 'manual',
        }),
      );
    } catch {
      throw new Error('session_liveness_unavailable');
    }
    if (!response.ok) {
      throw new Error('session_liveness_unavailable');
    }
    let status: unknown;
    try {
      status = await response.json();
    } catch {
      throw new Error('session_liveness_unavailable');
    }
    if (
      status === null ||
      typeof status !== 'object' ||
      (status as Record<string, unknown>)['authenticated'] !== true
    ) {
      throw new Error('session_not_live');
    }
  };
}

/**
 * Builds the `resolveAuth` dependency that connects the existing PADIEM
 * login to B64's income pipeline: the verified `uid` claim of the signed
 * `padiem_session` cookie becomes the pipeline `userId`. No request header,
 * query parameter or body field can select the user.
 */
export function createPadiemSessionAuthResolver(
  options: PadiemSessionAuthResolverOptions,
): AuthResolver {
  const secret = options.sessionSecret;
  const livenessProbe = options.sessionLivenessProbe;
  return (request: Request): Promise<AuthResult> => {
    const cookieHeader = request.headers.get('cookie');
    const token = cookieHeader === null ? null : extractCookieValue(cookieHeader, PADIEM_SESSION_COOKIE_NAME);
    return verifyPadiemSessionToken(token, secret).then((claims) => {
      if (!claims || cookieHeader === null) return UNAUTHENTICATED;
      if (!livenessProbe) {
        return Object.freeze({ authenticated: true, userId: claims.userId });
      }
      // The offline signature is valid: the remaining question is whether the
      // canonical session behind it is still live. Any probe failure (network,
      // non-ok, revoked/expired session) keeps the request unauthenticated.
      return livenessProbe(cookieHeader)
        .then(() => Object.freeze({ authenticated: true, userId: claims.userId }) as AuthResult)
        .catch(() => UNAUTHENTICATED);
    });
  };
}
