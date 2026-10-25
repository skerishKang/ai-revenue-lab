import type { AuthResult, AuthResolver } from './auth.js';
import { PADIEM_SESSION_COOKIE_NAME } from './padiem-session-auth.js';

/**
 * Control-Plane identity-authority session resolver for B64 (issue #987).
 *
 * This is the deployment authentication path approved by CENTRAL: B64 does
 * NOT possess the chat session signing secret. Instead it resolves the
 * incoming `padiem_session` cookie's canonical session id against the shared
 * Control Plane identity authority — the same authority already bound by
 * padiem-chat, padiem-ai-engine and padiem-voice-stt — and uses ONLY the
 * server-verified identity it returns:
 *
 *   1. parse the cookie payload (base64url JSON) and extract the `sid`
 *      claim — WITHOUT verifying the HMAC. The signed `uid` claim in the
 *      payload is attacker-malleable and is deliberately IGNORED here;
 *   2. `resolve_auth_session({session_id: sid})` — the authority looks the
 *      session up by exact match (session_id is `sess_` + 32 hex chars from
 *      its CSPRNG, a 128-bit bearer secret, so a forged sid simply misses);
 *   3. verify the server-owned fields: `session_id` matches the request,
 *      `product_id` is `b62` (the cookie is a B62 session), the subject is a
 *      `user`, the state is `active`, and `expires_at` is in the future —
 *      the authority does not filter state/expiry itself, callers must
 *      (the engine and voice-stt resolvers enforce the same checks);
 *   4. `resolve_product_user_for_subject({product_id: "b62",
 *      canonical_subject_id})` — the read-only reverse lookup returns the
 *      linked `usr_…` product user id, which becomes the pipeline userId.
 *
 * Every failure — missing binding, malformed cookie, unknown session,
 * revoked/expired state, product/subject mismatch, reverse-lookup failure —
 * yields the same fail-closed unauthenticated result as the rest of B64.
 *
 * Binding targets: `padiem-control-plane-identity` (the existing identity
 * authority worker; RPC methods are plain async methods on its
 * `WorkerEntrypoint` gateway, callable cross-language per the Cloudflare
 * service-binding RPC documentation).
 */

export const B62_PRODUCT_ID = 'b62';

const CANONICAL_SESSION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const PRODUCT_USER_ID_RE = /^usr_[A-Za-z0-9_-]{1,80}$/;

/**
 * Structural surface of the Control Plane identity authority service
 * binding. Mirrors the named-RPC invocation pattern used by the existing
 * Python consumers (chat `control_plane_identity_worker.py`,
 * engine `auth_session_scope_authority.py`, voice-stt
 * `voice_stt_caller_auth.py`): call the named method with ONE payload
 * object and read the `{"ok": boolean, ...}` envelope.
 */
export interface ControlPlaneIdentityAuthority {
  resolve_auth_session(payload: { session_id: string }): Promise<unknown>;
  resolve_product_user_for_subject(payload: {
    product_id: string;
    canonical_subject_id: string;
  }): Promise<unknown>;
}

function timingSafeExtractCookieValue(cookieHeader: string, name: string): string | null {
  let match: string | null = null;
  for (const part of cookieHeader.split(';')) {
    const separator = part.indexOf('=');
    if (separator < 0) continue;
    if (part.slice(0, separator).trim() !== name) continue;
    match = part.slice(separator + 1).trim();
  }
  return match;
}

const B64URL_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

function b64urlDecode(text: string): Uint8Array | null {
  if (text.length % 4 === 1) return null;
  for (const ch of text) {
    if (!B64URL_ALPHABET.includes(ch)) return null;
  }
  let bits = 0;
  let accumulator = 0;
  const bytes: number[] = [];
  for (const ch of text) {
    accumulator = (accumulator << 6) | B64URL_ALPHABET.indexOf(ch);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((accumulator >> bits) & 0xff);
    }
  }
  return new Uint8Array(bytes);
}

/**
 * Extracts ONLY the canonical session id (`sid`) from the signed cookie
 * payload. The HMAC signature is NOT verified here — it cannot be, B64 has
 * no secret — and the signed `uid` claim is deliberately discarded: the
 * payload body is attacker-malleable, so the identity must come from the
 * authority, not from the cookie.
 */
export function extractCookieSessionId(token: string): string | null {
  const separatorIndex = token.indexOf('.');
  if (separatorIndex <= 0) return null;
  const body = token.slice(0, separatorIndex);
  const payloadBytes = b64urlDecode(body);
  if (!payloadBytes) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(payloadBytes));
  } catch {
    return null;
  }
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) return null;
  const sid = (payload as Record<string, unknown>)['sid'];
  if (typeof sid !== 'string' || !CANONICAL_SESSION_ID_RE.test(sid)) return null;
  return sid;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

interface AuthoritySession {
  sessionId: string;
  subjectType: string;
  subjectId: string;
  state: string;
  expiresAt: string;
}

function parseSessionSnapshot(response: unknown, requestedSessionId: string): AuthoritySession | null {
  if (!isPlainObject(response) || response['ok'] !== true) return null;
  const session = response['session'];
  if (!isPlainObject(session)) return null;
  const sessionId = session['session_id'];
  const productId = session['product_id'];
  const subject = session['subject'];
  const state = session['state'];
  const expiresAt = session['expires_at'];
  if (typeof sessionId !== 'string' || sessionId !== requestedSessionId) return null;
  if (typeof productId !== 'string' || productId !== B62_PRODUCT_ID) return null;
  if (!isPlainObject(subject)) return null;
  const subjectType = subject['subject_type'];
  const subjectId = subject['subject_id'];
  if (typeof subjectType !== 'string' || subjectType !== 'user') return null;
  if (typeof subjectId !== 'string' || !subjectId.startsWith('sub_')) return null;
  if (typeof state !== 'string' || state !== 'active') return null;
  if (typeof expiresAt !== 'string') return null;
  const expiryMs = Date.parse(expiresAt);
  if (!Number.isFinite(expiryMs) || expiryMs <= Date.now()) return null;
  return { sessionId, subjectType, subjectId, state, expiresAt };
}

function parseProductUserId(response: unknown): string | null {
  if (!isPlainObject(response) || response['ok'] !== true) return null;
  const productUserId = response['product_user_id'];
  if (typeof productUserId !== 'string' || !PRODUCT_USER_ID_RE.test(productUserId)) return null;
  return productUserId;
}

const UNAUTHENTICATED: AuthResult = Object.freeze({ authenticated: false, userId: null });

export interface AuthoritySessionAuthResolverOptions {
  /**
   * Server-owned service binding to the Control Plane identity authority
   * (`padiem-control-plane-identity`). When absent the resolver fails
   * closed: no request is ever authenticated.
   */
  readonly identityAuthority: ControlPlaneIdentityAuthority | undefined;
}

/**
 * Builds the `resolveAuth` dependency that identifies B64 callers through the
 * existing Control Plane identity authority — without possessing the chat
 * session signing secret. See the module docstring for the exact contract.
 */
export function createAuthoritySessionAuthResolver(
  options: AuthoritySessionAuthResolverOptions,
): AuthResolver {
  const authority = options.identityAuthority;
  return async (request: Request): Promise<AuthResult> => {
    if (!authority) return UNAUTHENTICATED;
    const cookieHeader = request.headers.get('cookie');
    if (cookieHeader === null) return UNAUTHENTICATED;
    const token = timingSafeExtractCookieValue(cookieHeader, PADIEM_SESSION_COOKIE_NAME);
    if (token === null) return UNAUTHENTICATED;
    const sessionId = extractCookieSessionId(token);
    if (sessionId === null) return UNAUTHENTICATED;

    let sessionResponse: unknown;
    try {
      sessionResponse = await authority.resolve_auth_session({ session_id: sessionId });
    } catch {
      return UNAUTHENTICATED;
    }
    const session = parseSessionSnapshot(sessionResponse, sessionId);
    if (session === null) return UNAUTHENTICATED;

    let linkResponse: unknown;
    try {
      linkResponse = await authority.resolve_product_user_for_subject({
        product_id: B62_PRODUCT_ID,
        canonical_subject_id: session.subjectId,
      });
    } catch {
      return UNAUTHENTICATED;
    }
    const userId = parseProductUserId(linkResponse);
    if (userId === null) return UNAUTHENTICATED;

    return Object.freeze({ authenticated: true, userId });
  };
}
