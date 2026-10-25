export interface AuthResult {
  readonly authenticated: boolean;
  readonly userId: string | null;
}

export type AuthResolver = (request: Request) => AuthResult;

export function defaultAuthResolver(_request: Request): AuthResult {
  return Object.freeze({ authenticated: false, userId: null });
}

export function createTestAuthResolver(userId: string): AuthResolver {
  return (_request: Request) =>
    Object.freeze({ authenticated: true, userId });
}
