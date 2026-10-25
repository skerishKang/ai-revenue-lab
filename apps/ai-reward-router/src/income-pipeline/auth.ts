export interface AuthResult {
  readonly authenticated: boolean;
  readonly userId: string | null;
}

const TRUSTED_USER_HEADER = 'x-padiem-user-id';
const CLOUDFLARE_RAY_HEADER = 'cf-ray';

export function resolveUserId(request: Request): AuthResult {
  const cfRay = request.headers.get(CLOUDFLARE_RAY_HEADER);
  const isTrustedProxy = cfRay !== null && cfRay.trim().length > 0;

  if (!isTrustedProxy) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  const trustedUserId = request.headers.get(TRUSTED_USER_HEADER);
  if (!trustedUserId) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  const trimmed = trustedUserId.trim();
  if (!trimmed || trimmed.length < 1 || trimmed.length > 256) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  if (!/^[a-zA-Z0-9._-]+$/.test(trimmed)) {
    return Object.freeze({ authenticated: false, userId: null });
  }

  return Object.freeze({ authenticated: true, userId: trimmed });
}

export function requireAuth(request: Request): AuthResult {
  return resolveUserId(request);
}

export function isTrustedProxyRequest(request: Request): boolean {
  const cfRay = request.headers.get(CLOUDFLARE_RAY_HEADER);
  return cfRay !== null && cfRay.trim().length > 0;
}
