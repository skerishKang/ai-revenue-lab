import { createConsumerHttpHandler } from './http/consumer-http.js';
import { loadVerifiedPublicOpportunities } from './public-supply/verified-public-opportunities.js';
import { createB64AuthResolver } from './identity/auth.js';
import { D1B64MemberStore, UnboundB64MemberStore } from './identity/member-store.js';
import {
  PROVIDER_RUNTIME_MODES,
  type ProviderRuntimeMode,
} from './ad-click-first/provider-runtime-config.js';
import { D1RewardEventStore, UnboundRewardEventStore } from './ad-click-first/reward-event-store.js';
import {
  D1UserIncomeRepository,
  UnboundUserIncomeRepository,
  type D1DatabaseLike,
} from './income-pipeline/d1-user-income-repository.js';

/**
 * Server-owned configuration the income pipeline needs (issue #987). Every
 * entry is optional in the type so a deployment without it keeps failing closed
 * instead of crashing the isolate:
 *
 * - `B64_SESSION_SECRET`: B64's own session signing key. B64 is an independent
 *   business (owner decision 2026-10-27), so it holds its own key and verifies
 *   its own cookies — no PADIEM Chat secret is copied here, and a token minted
 *   for B64 carries the B64 purpose string that keeps it out of any other
 *   product's verifier. Without it no request is authenticated.
 * - `B64_INCOME_DB`: the product's Cloudflare D1 database. It carries both the
 *   income records (`b64_user_income`) and B64's own accounts and sessions
 *   (`b64_member`, `b64_session`), so member data never leaves this database.
 *   Without it pipeline storage and account endpoints answer 503 instead of
 *   silently using the non-durable in-memory prototype.
 * - `B64_PUBLIC_BASE_URL`: the exact reviewed public origin of this deployment,
 *   required by the same-origin guard on cookie mutations. It is a
 *   configuration value, not a hard-coded assumption: moving B64 to its own
 *   registered domain is a one-line change here plus a redeploy.
 * - `B64_GOOGLE_CLIENT_ID` / `B64_GOOGLE_CLIENT_SECRET` (#987): B64's OWN
 *   Google OAuth client, registered on the redirect
 *   `<B64_PUBLIC_BASE_URL>/auth/google/callback`. They are the credentials a
 *   Google login needs, and nothing else: no other product's client id, login
 *   endpoint or session cookie is referenced anywhere in this Worker. Left
 *   unset, the Google entry is not offered and `/auth/google/*` answers 503 —
 *   the site keeps working for every other request.
 */
export interface B64WorkerEnv {
  readonly B64_SESSION_SECRET?: string;
  readonly B64_INCOME_DB?: D1DatabaseLike;
  readonly B64_PUBLIC_BASE_URL?: string;
  readonly B64_GOOGLE_CLIENT_ID?: string;
  readonly B64_GOOGLE_CLIENT_SECRET?: string;
  /**
   * ayeT reward postback (#987). Names are already fixed by
   * `provider-runtime-config.ts`; only the values are missing, so nothing is
   * guessed here. An absent or unrecognised `B64_AYET_MODE` is treated as
   * DISABLED rather than throwing at boot: a typo in a production variable must
   * fail closed, and a crashing isolate would take the whole consumer site
   * down with it.
   */
  readonly B64_AYET_MODE?: string;
  readonly B64_AYET_PUBLISHER_API_KEY?: string;
  readonly B64_AYET_REWARDED_ADSLOT_ID?: string;
}

const INCOME_D1_BINDING_NAME = 'B64_INCOME_DB';

function ayetMode(value: string | undefined): ProviderRuntimeMode {
  const trimmed = (value ?? '').trim();
  return PROVIDER_RUNTIME_MODES.includes(trimmed as ProviderRuntimeMode)
    ? trimmed as ProviderRuntimeMode
    : 'DISABLED';
}

/** Reviewed origins only: a non-https or unparseable value is ignored so the
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
 * provider pages, pay B64 nothing, and never grant provider authority.
 *
 * The income pipeline lane authenticates B64's own members: a B64-signed cookie
 * whose session row is still live in D1. Anonymous visitors can browse
 * everything; only the member's own records are ever readable.
 */
export default {
  async fetch(request: Request, env: B64WorkerEnv = {}): Promise<Response> {
    const members = env.B64_INCOME_DB
      ? new D1B64MemberStore(env.B64_INCOME_DB)
      : new UnboundB64MemberStore(INCOME_D1_BINDING_NAME);
    const handler = createConsumerHttpHandler({
      loadCandidates: () => [],
      loadPublicOpportunities: loadVerifiedPublicOpportunities,
      resolveAuth: createB64AuthResolver({
        sessionSecret: env.B64_SESSION_SECRET,
        members,
      }),
      memberStore: members,
      sessionSecret: env.B64_SESSION_SECRET,
      googleClientId: env.B64_GOOGLE_CLIENT_ID,
      googleClientSecret: env.B64_GOOGLE_CLIENT_SECRET,
      incomeRepository: env.B64_INCOME_DB
        ? new D1UserIncomeRepository(env.B64_INCOME_DB)
        : new UnboundUserIncomeRepository(INCOME_D1_BINDING_NAME),
      expectedBrowserOrigin: reviewedBrowserOrigin(env.B64_PUBLIC_BASE_URL),
      rewardEvents: env.B64_INCOME_DB
        ? new D1RewardEventStore(env.B64_INCOME_DB)
        : new UnboundRewardEventStore(INCOME_D1_BINDING_NAME),
      ayetMode: ayetMode(env.B64_AYET_MODE),
      ayetPublisherApiKey: env.B64_AYET_PUBLISHER_API_KEY,
      ayetRewardedAdslotId: env.B64_AYET_REWARDED_ADSLOT_ID,
    });
    return handler(request);
  },
};
