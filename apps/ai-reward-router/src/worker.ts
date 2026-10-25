import { createConsumerHttpHandler } from './http/consumer-http.js';
import { loadVerifiedPublicOpportunities } from './public-supply/verified-public-opportunities.js';
import {
  createAuthoritySessionAuthResolver,
  type ControlPlaneIdentityAuthority,
} from './income-pipeline/authority-session-auth.js';
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
 * - `CONTROL_PLANE_IDENTITY`: service binding to the shared Control Plane
 *   identity authority (`padiem-control-plane-identity`), already bound by
 *   padiem-chat, padiem-ai-engine and padiem-voice-stt. REQUIRED for the
 *   income path: B64 resolves the incoming `padiem_session` cookie's
 *   canonical session id against it and uses ONLY the server-verified
 *   identity (`resolve_auth_session` → `resolve_product_user_for_subject`),
 *   so logged-out, revoked, expired or forged sessions are all blocked and
 *   no client-supplied claim is trusted. When the binding is absent every
 *   cookie-authenticated request is denied (fail closed).
 * - `PADIEM_B64_PUBLIC_BASE_URL`: reviewed public origin of this deployment
 *   (e.g. `https://chat.padiem.net` when B64 is served under the chat
 *   origin). Required for cookie-authenticated pipeline mutations to pass
 *   the same-origin guard.
 * - `B64_INCOME_DB`: Cloudflare D1 database binding for durable user income
 *   records. Without it pipeline storage answers 503 instead of silently
 *   using the non-durable in-memory prototype.
 *
 * The chat session signing secret is deliberately NOT bound: B64 verifies
 * identity through the authority, never with the signing key (Plan B confirmed
 * 2026-10-26; the offline signature verifier remains only in isolated tests).
 */
export interface B64WorkerEnv {
  readonly CONTROL_PLANE_IDENTITY?: ControlPlaneIdentityAuthority;
  readonly PADIEM_B64_PUBLIC_BASE_URL?: string;
  readonly B64_INCOME_DB?: D1DatabaseLike;
}

const INCOME_D1_BINDING_NAME = 'B64_INCOME_DB';

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
 * cookie resolved against the Control Plane identity authority and persists
 * user income records to the deployment's D1 binding. Both dependencies fail
 * closed when absent.
 */
export default {
  async fetch(request: Request, env: B64WorkerEnv = {}): Promise<Response> {
    // The deployed income path requires server-verified identity: with the
    // binding, resolve the cookie's canonical session against the authority
    // (session → subject → product user id). Without it, fail closed so no
    // client-supplied claim can ever select the user. The resolver itself
    // denies everything when the authority is absent.
    const handler = createConsumerHttpHandler({
      loadCandidates: () => [],
      loadPublicOpportunities: loadVerifiedPublicOpportunities,
      resolveAuth: createAuthoritySessionAuthResolver({
        identityAuthority: env.CONTROL_PLANE_IDENTITY,
      }),
      incomeRepository: env.B64_INCOME_DB
        ? new D1UserIncomeRepository(env.B64_INCOME_DB)
        : new UnboundUserIncomeRepository(INCOME_D1_BINDING_NAME),
      expectedBrowserOrigin: reviewedBrowserOrigin(env.PADIEM_B64_PUBLIC_BASE_URL),
    });
    return handler(request);
  },
};
