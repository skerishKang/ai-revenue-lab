export interface AuthResult {
  readonly authenticated: boolean;
  readonly userId: string | null;
}

/**
 * Resolves the server-verified identity of one request. Synchronous resolvers
 * (e.g. `createTestAuthResolver`) keep working; asynchronous resolvers are
 * allowed because B64's own verification (`src/identity/auth.ts`) performs its
 * constant-time HMAC comparison and session lookup with promise-based WebCrypto
 * and D1 reads.
 */
export type AuthResolver = (request: Request) => AuthResult | Promise<AuthResult>;

export function defaultAuthResolver(_request: Request): AuthResult {
  return Object.freeze({ authenticated: false, userId: null });
}

export function createTestAuthResolver(userId: string): AuthResolver {
  return (_request: Request) =>
    Object.freeze({ authenticated: true, userId });
}
