import { createConsumerHttpHandler } from './http/consumer-http.js';
import { loadVerifiedPublicOpportunities } from './public-supply/verified-public-opportunities.js';
import {
  createPadiemSessionAuthResolver,
  createChatSessionStatusProbe,
  createUnconfiguredLivenessProbe,
} from './income-pipeline/padiem-session-auth.js';
import {
  D1UserIncomeRepository,
  UnboundUserIncomeRepository,
  type D1DatabaseLike,
} from './income-pipeline/d1-user-income-repository.js';

/**
 * Server-owned bindings the income pipeline needs (issue #987). They are all
 * optional in the type so a deployment without them keeps failing closed
 * instead of crashing the isolate:
 *
 * - `PADIEM_SESSION_SECRET`: the same session secret value the B62 chat
 *   product uses (`PADIEM_CHAT_SESSION_SECRET`). It lets this Worker verify
 *   the signed `padiem_session` cookie with the exact B62 authority
 *   algorithm. Without it no request is authenticated.
 * - `PADIEM_CHAT_SERVICE`: service binding to the deployed chat product
 *   worker, declared exactly like the existing reference bridge
 *   (`reference/business-66-padiem-quote-v1/_worker.js`). REQUIRED for the
 *   income path: the liveness of every verified session is confirmed
 *   through chat's existing revocation-aware `GET /api/auth/status`, so
 *   logged-out or revoked canonical sessions are blocked. When the binding
 *   is absent every cookie-authenticated request is denied (fail closed) —
 *   the deployed B64 path never falls back to signature-only verification.
 *   Signature-only checking exists only in isolated test helpers.
 * - `PADIEM_B64_PUBLIC_BASE_URL`: reviewed public origin of this deployment
 *   (e.g. `https://chat.padiem.net` when B64 is served under the chat
 *   origin). Required for cookie-authenticated pipeline mutations to pass
 *   the same-origin guard.
 * - `B64_INCOME_DB`: Cloudflare D1 database binding for durable user income
 *   records. Without it pipeline storage answers 503 instead of silently
 *   using the non-durable in-memory prototype.
 */
export interface B64WorkerEnv {
  readonly PADIEM_SESSION_SECRET?: string;
  readonly PADIEM_CHAT_SERVICE?: { fetch(input: Request): Promise<Response> };
  readonly PADIEM_B64_PUBLIC_BASE_URL?: string;
  readonly B64_INCOME_DB?: D1DatabaseLike;
}

const INCOME_D1_BINDING_NAME = 'B64_INCOME_DB';
const INCOME_CHAT_BINDING_NAME = 'PADIEM_CHAT_SERVICE';

/** Reviewed-origins only: a non-https or unparseable value is ignored so the
 * same-origin guard fails closed instead of trusting a sloppy expectation. */
function reviewedBrowserOrigin(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== 'https:' || !parsed.host) return undefined;
    return parsed.origin;
  } catch {
    return undefined;
  }
}

/**
 * Deployment-safe default Worker entrypoint.
 *
 * The ad-click provider lane stays intentionally zero-supply: no provider is
 * LIVE_AUTHORIZED yet, so `/` renders the honest P0 state with zero real ad
 * reward cards until OWNER activation and production configuration complete.
 *
 * The public-supply lane serves manually curated, publicly verified
 * opportunities on /browse, /today and /detail. These link users to official
 * provider pages, pay PADIEM nothing, and never grant provider authority.
 *
 * The income pipeline lane authenticates through the existing PADIEM session
 * cookie (verified server-side) and persists user income records to the
 * deployment's D1 binding. Both dependencies fail closed when absent.
 */
export default {
  async fetch(request: Request, env: B64WorkerEnv = {}): Promise<Response> {
    // The deployed income path requires canonical-session liveness: with the
    // binding, probe chat's revocation-aware /api/auth/status; without it,
    // fail closed so a revoked session can never pass on its signature alone.
    const livenessProbe = env.PADIEM_CHAT_SERVICE
      ? createChatSessionStatusProbe({ chatService: env.PADIEM_CHAT_SERVICE })
      : createUnconfiguredLivenessProbe(INCOME_CHAT_BINDING_NAME);
    const handler = createConsumerHttpHandler({
      loadCandidates: () => [],
      loadPublicOpportunities: loadVerifiedPublicOpportunities,
      resolveAuth: createPadiemSessionAuthResolver({
        sessionSecret: env.PADIEM_SESSION_SECRET,
        sessionLivenessProbe: livenessProbe,
      }),
      incomeRepository: env.B64_INCOME_DB
        ? new D1UserIncomeRepository(env.B64_INCOME_DB)
        : new UnboundUserIncomeRepository(INCOME_D1_BINDING_NAME),
      expectedBrowserOrigin: reviewedBrowserOrigin(env.PADIEM_B64_PUBLIC_BASE_URL),
    });
    return handler(request);
  },
};
