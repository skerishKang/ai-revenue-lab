/**
 * Server-side auth boundary for the INCOME PIPELINE.
 *
 * SECURITY: This module does NOT accept arbitrary client-supplied tokens as
 * user identity. In production, the PADIEM auth middleware (Cloudflare Access
 * or PADIEM session service) verifies the user's session and sets a trusted
 * header (X-Padiem-User-Id) on the request BEFORE it reaches this Worker.
 *
 * The trusted header is STRIPPED from all client requests by the edge proxy.
 * Clients cannot set it. If the header is absent, auth fails closed.
 *
 * This is NOT a full auth system — it is a boundary that trusts a verified
 * upstream identity. The actual session verification happens in the PADIEM
 * auth middleware, which is outside this Worker's scope.
 */

export interface AuthResult {
  readonly authenticated: boolean;
  readonly userId: string | null;
}

const TRUSTED_USER_HEADER = 'x-padiem-user-id';

export function resolveUserId(request: Request): AuthResult {
  // Only accept server-verified user identity from a trusted header.
  // This header is set by the PADIEM auth middleware, NOT by the client.
  // Clients cannot set this header — it is stripped by the edge proxy.
  const trustedUserId = request.headers.get(TRUSTED_USER_HEADER);
  if (!trustedUserId) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  const trimmed = trustedUserId.trim();
  if (!trimmed || trimmed.length < 1 || trimmed.length > 256) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  // Basic format validation: alphanumeric + hyphens/underscores/dots
  if (!/^[a-zA-Z0-9._-]+$/.test(trimmed)) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  return Object.freeze({ authenticated: true, userId: trimmed });
}

export function requireAuth(request: Request): AuthResult {
  return resolveUserId(request);
}
