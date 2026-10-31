import { createConsumerHttpHandler } from '../../src/http/consumer-http.js';
import { createB64AuthResolver } from '../../src/identity/auth.js';
import { D1B64MemberStore } from '../../src/identity/member-store.js';
import { D1UserIncomeRepository } from '../../src/income-pipeline/d1-user-income-repository.js';
import {
  B64_SESSION_COOKIE_NAME,
  mintB64SessionToken,
  newB64MemberId,
  newB64SessionId,
} from '../../src/identity/session.js';
import { createSqliteD1Binding } from '../d1-binding-helper.js';

/**
 * Test harness for B64's own identity boundary (#987). It runs the real HTTP
 * handler over a real SQLite D1 binding with both migrations applied, so a
 * green journey means the account, session and income rows actually work
 * together — not a stubbed resolver.
 */
export const TEST_SESSION_SECRET = 'b64-test-session-secret-0123456789abcdef';
export const TEST_ORIGIN = 'https://b64.example.test';
export const DAY_SECONDS = 86_400;

export interface IdentityHarness {
  readonly handler: (request: Request) => Promise<Response>;
  readonly members: D1B64MemberStore;
  readonly binding: ReturnType<typeof createSqliteD1Binding>['binding'];
}

export function createIdentityHarness(): IdentityHarness {
  const { binding } = createSqliteD1Binding();
  const members = new D1B64MemberStore(binding);
  const handler = createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: () => [],
    resolveAuth: createB64AuthResolver({ sessionSecret: TEST_SESSION_SECRET, members }),
    memberStore: members,
    sessionSecret: TEST_SESSION_SECRET,
    incomeRepository: new D1UserIncomeRepository(binding),
    expectedBrowserOrigin: TEST_ORIGIN,
  });
  return { handler, members, binding };
}

export function postForm(path: string, form: Record<string, string>, cookie?: string): Request {
  const headers: Record<string, string> = {
    'content-type': 'application/x-www-form-urlencoded',
    origin: TEST_ORIGIN,
  };
  if (cookie) headers.cookie = cookie;
  return new Request(`${TEST_ORIGIN}${path}`, {
    method: 'POST',
    headers,
    body: new URLSearchParams(form).toString(),
  });
}

export function getWithCookie(path: string, cookie?: string): Request {
  return new Request(`${TEST_ORIGIN}${path}`, cookie ? { headers: { cookie } } : {});
}

/** The `b64_session=…` pair a successful join/login set, ready to replay. */
export function sessionCookieOf(response: Response): string {
  const raw = response.headers.get('set-cookie');
  if (!raw) throw new Error('no set-cookie on the identity response');
  const pair = raw.split(';')[0]!;
  if (!pair.startsWith(`${B64_SESSION_COOKIE_NAME}=`)) throw new Error(`unexpected cookie: ${pair}`);
  return pair;
}

export async function joinMember(handler: IdentityHarness['handler'], email: string, password: string): Promise<string> {
  const response = await handler(postForm('/join', { email, password }));
  if (response.status !== 303) throw new Error(`join failed with ${response.status}`);
  return sessionCookieOf(response);
}

/**
 * Mints a cookie directly, bypassing /join. Used to prove the boundary refuses
 * tokens that were never backed by a live session row, or whose row is gone.
 */
export async function rawSessionCookie(input: {
  readonly memberId?: string;
  readonly sessionId?: string;
  readonly expiresInSeconds?: number;
  readonly secret?: string;
} = {}): Promise<{ cookie: string; memberId: string; sessionId: string }> {
  const memberId = input.memberId ?? newB64MemberId();
  const sessionId = input.sessionId ?? newB64SessionId();
  const token = await mintB64SessionToken({
    sessionSecret: input.secret ?? TEST_SESSION_SECRET,
    memberId,
    sessionId,
    expiresAtSeconds: Math.floor(Date.now() / 1000) + (input.expiresInSeconds ?? DAY_SECONDS),
  });
  return { cookie: `${B64_SESSION_COOKIE_NAME}=${token}`, memberId, sessionId };
}

export { newB64MemberId, newB64SessionId };
