/**
 * Minimal server-side auth boundary for the INCOME PIPELINE.
 *
 * Reuses the concept of PADIEM identity without inventing a new auth system.
 * In production, this would verify a signed token/cookie against the PADIEM
 * auth service. For now, it reads a Bearer token from the Authorization header
 * and fails closed when absent or malformed.
 *
 * NEVER use client-controlled identifiers (query params, body fields) as userId.
 */

export interface AuthResult {
  readonly authenticated: boolean;
  readonly userId: string | null;
}

export function resolveUserId(request: Request): AuthResult {
  const authHeader = request.headers.get('authorization');
  if (!authHeader) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  const parts = authHeader.split(' ');
  if (parts.length !== 2 || parts[0]!.toLowerCase() !== 'bearer') {
    return Object.freeze({ authenticated: false, userId: null });
  }

  const token = parts[1]!.trim();
  if (!token || token.length < 8 || token.length > 256) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  // Basic format validation: alphanumeric + hyphens/underscores/dots
  if (!/^[a-zA-Z0-9._-]+$/.test(token)) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  // In production, verify token against PADIEM auth service.
  // For now, the token is treated as a user identifier (placeholder).
  return Object.freeze({ authenticated: true, userId: token });
}

export function requireAuth(request: Request): AuthResult {
  return resolveUserId(request);
}
