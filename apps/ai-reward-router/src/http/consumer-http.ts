import {
  buildAdClickFirstConsumerHome,
  buildAdClickFirstTodayRoute,
  buildAdClickFirstBrowse,
  buildAdClickFirstOpportunityDetail,
  type BuildAdClickFirstBrowseOptions,
  type ConsumerBrowseCategory,
} from '../ad-click-first/consumer-home.js';
import type { AdClickConsumerCandidate } from '../ad-click-first/consumer-card.js';
import {
  renderAdClickFirstConsumerWeb,
  renderAdClickFirstTodayRouteWeb,
  renderAdClickFirstBrowseWeb,
  renderAdClickFirstOpportunityDetailWeb,
} from '../ad-click-first/consumer-web.js';
import {
  buildIncomePipelineViewModel,
  renderIncomePipelineWeb,
} from '../income-pipeline/consumer-view.js';
import { defaultAuthResolver, type AuthResolver, type AuthResult } from '../income-pipeline/auth.js';
import {
  B64_SESSION_COOKIE_NAME,
  b64SessionClearCookieValue,
} from '../identity/session.js';
import {
  B64MemberExistsError,
  type B64MemberStore,
} from '../identity/member-store.js';
import { extractCookieValue, logoutSession, registerMember, signInMember, signInWithGoogle } from '../identity/auth.js';
import {
  B64_GOOGLE_CALLBACK_PATH,
  B64_GOOGLE_START_PATH,
  B64_OAUTH_STATE_COOKIE_NAME,
  GoogleAuthError,
  b64GoogleAuthorizationUrl,
  b64GoogleRedirectUri,
  b64OAuthStateClearCookieValue,
  b64OAuthStateCookieValue,
  mintB64OAuthState,
  verifyB64OAuthState,
  type GoogleFetch,
} from '../identity/google.js';
import { CredentialError } from '../identity/password.js';
import { isB64SuperAdmin } from '../identity/admin.js';
import { renderB64AdminConsole } from '../ops/admin-view.js';
import type { B64OperationsSnapshot } from '../ops/operations-snapshot.js';
import {
  AYET_S2S_CALLBACK_PATH,
  AYET_S2S_SECURITY_HASH_HEADER,
  ayetS2SParametersFromUrl,
  AyetCallbackDisabled,
  AyetCallbackUnconfigured,
  handleAyetS2SCallback,
} from '../ad-click-first/ayet-callback.js';
import {
  RewardEventStorageError,
  UnboundRewardEventStore,
  type RewardEventStore,
} from '../ad-click-first/reward-event-store.js';
import type { ProviderRuntimeMode } from '../ad-click-first/provider-runtime-config.js';
import { getRepository, type UserIncomeRepository } from '../income-pipeline/store.js';
import { validateUserIncomeRecord, isValidIncomePipelineTransition } from '../income-pipeline/domain.js';
import type { UserIncomeRecord, UserIncomeLoader, IncomePipelineStatus } from '../income-pipeline/domain.js';

import type { PublicOpportunity, PublicOpportunityLoader } from '../public-supply/domain.js';
import { loadVerifiedPublicOpportunities } from '../public-supply/verified-public-opportunities.js';
import {
  isThemeToggleRequest,
  readThemeFromCookie,
  themeCookieHeaderValue,
  themeToggleHref,
  toggleTheme,
  type B64Theme,
} from '../ui/theme.js';

interface ConsumerThemeInfo {
  readonly theme: B64Theme;
  readonly themeToggleHref: string;
  readonly googleLoginAvailable: boolean;
}

export type ConsumerCandidateLoader = (
  request: Request,
) => Promise<readonly AdClickConsumerCandidate[]> | readonly AdClickConsumerCandidate[];

export interface ConsumerHttpDependencies {
  readonly loadCandidates: ConsumerCandidateLoader;
  readonly resolveAuth?: AuthResolver;
  /**
   * B64's own member and session store. Without it the identity endpoints
   * answer 503 instead of falling back to a non-durable account store.
   */
  readonly memberStore?: B64MemberStore | undefined;
  /** B64's own session signing secret (`B64_SESSION_SECRET`). */
  readonly sessionSecret?: string | undefined;
  /**
   * B64's OWN Google OAuth client (`B64_GOOGLE_CLIENT_ID` /
   * `B64_GOOGLE_CLIENT_SECRET`, issue #987). These are B64's credentials on
   * B64's own redirect origin; another product's client id, redirect URI or
   * login cookie is never accepted. Missing either one means the Google entry
   * is not offered and the endpoints answer 503 rather than half-working.
   */
  readonly googleClientId?: string | undefined;
  readonly googleClientSecret?: string | undefined;
  /** Provider transport seam. Production uses the runtime fetch; tests pin it. */
  readonly googleFetch?: GoogleFetch;
  /**
   * ayeT server-to-server reward postback (#987). The verification and state
   * rules already existed as pure functions; these three are the connection.
   * With no store, no key or a `DISABLED` mode the callback answers 503 and
   * writes nothing, so the product keeps booting before any provider account
   * exists.
   */
  readonly rewardEvents?: RewardEventStore | undefined;
  readonly ayetMode?: ProviderRuntimeMode | undefined;
  readonly ayetPublisherApiKey?: string | undefined;
  /** `B64_AYET_REWARDED_ADSLOT_ID`; empty means the adslot is not chosen yet. */
  readonly ayetRewardedAdslotId?: string | undefined;
  /**
   * Operator authority (#6001). `B64_ADMIN_EMAIL` is the single administrator
   * address, supplied as server configuration and never committed or logged;
   * unset means nobody is an administrator. The snapshot reader is the only
   * production data the console can see, and it is read-only by construction.
   */
  readonly adminEmail?: string | undefined;
  readonly operationsSnapshot?: (() => Promise<B64OperationsSnapshot>) | undefined;
  /**
   * Server-owned, per-deployment storage dependency; default remains prototype.
   * Production wiring must inject a durable repository (D1); the in-memory
   * prototype default exists for tests and local prototypes only.
   */
  readonly incomeRepository?: UserIncomeRepository;
  /**
   * Exact reviewed browser origin (scheme + host + port) cookie-authenticated
   * pipeline mutations must come from, mirroring the repository's single
   * reviewed origin-isolation policy (#3476) for the `b64_session` cookie.
   * Derived from server configuration only — never from the request's own
   * Host/Origin. When a pipeline mutation carries the session cookie and this
   * is not configured, the request is denied 503 (fail closed).
   */
  readonly expectedBrowserOrigin?: string | undefined;
  /**
   * Optional public-supply lane: manually curated, publicly verified opportunities.
   * The public lane never grants provider authority; it only links users to
   * official provider pages and earns B64 nothing.
   */
  readonly loadPublicOpportunities?: PublicOpportunityLoader;
  /**
   * Optional income-pipeline lane: user income tracking records.
   * Requires a userId for user isolation. Returns empty when no user is identified.
   */
  readonly loadIncomeRecords?: UserIncomeLoader;
}

/**
 * B64's own account endpoints. They are POST-only because the consumer surface
 * runs under `script-src 'none'`: the forms that reach them live on /pipeline,
 * and a stray GET lands back on the dashboard instead of a blank page.
 */
const IDENTITY_PATHS: ReadonlySet<string> = Object.freeze(new Set(['/join', '/login', '/logout']));

/**
 * The Google round trip. Both halves are GET-only navigations: `/start` sends
 * the browser to Google with a signed state cookie, `/callback` refuses
 * anything whose `state` does not match that cookie. A form post to either is
 * refused 405 by the method rule below.
 */
const GOOGLE_PATHS: ReadonlySet<string> = Object.freeze(new Set([B64_GOOGLE_START_PATH, B64_GOOGLE_CALLBACK_PATH]));

/**
 * The provider's own inbound reward callback. It is GET-only (ayeT calls it
 * server-to-server with query parameters and a signature header), carries no
 * browser cookie, and is authenticated by the publisher signature alone — so it
 * is deliberately outside the identity paths, which are POST-only.
 */
/**
 * The operator's read-only status surface (#6001). GET only: it reports state
 * and changes nothing, so it needs no CSRF token and no mutation path.
 */
const ADMIN_PATHS: ReadonlySet<string> = Object.freeze(new Set(['/admin', '/admin/status']));

const PROVIDER_CALLBACK_PATHS: ReadonlySet<string> = Object.freeze(new Set([AYET_S2S_CALLBACK_PATH]));

const SECURITY_HEADERS = Object.freeze({
  'cache-control': 'no-store',
  'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  'cross-origin-opener-policy': 'same-origin',
  'referrer-policy': 'no-referrer',
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'DENY',
});

function withSecurityHeaders(headers?: HeadersInit): Headers {
  const output = new Headers(headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    output.set(name, value);
  }
  return output;
}

function responseForMethod(request: Request, body: string, init: ResponseInit): Response {
  return new Response(request.method === 'HEAD' ? null : body, {
    ...init,
    headers: withSecurityHeaders(init.headers),
  });
}

function healthResponse(request: Request): Response {
  const body = JSON.stringify({
    service: 'b64-ai-reward-router',
    status: 'ok',
    consumerMode: 'AD_CLICK_FIRST',
    supplyActivation: 'OWNER_ACTION_PENDING',
    providerPermissionGranted: false,
  });

  return responseForMethod(request, body, {
    status: 200,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function methodNotAllowed(request: Request): Response {
  return responseForMethod(request, 'Method Not Allowed', {
    status: 405,
    headers: {
      allow: 'GET, HEAD',
      'content-type': 'text/plain; charset=utf-8',
    },
  });
}

function notFound(request: Request): Response {
  return responseForMethod(request, 'Not Found', {
    status: 404,
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
}

function supplyUnavailable(request: Request): Response {
  return responseForMethod(request, 'Reward supply is temporarily unavailable.', {
    status: 503,
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'retry-after': '60',
    },
  });
}

function carriesB64SessionCookie(cookieHeader: string): boolean {
  for (const part of cookieHeader.split(';')) {
    const separator = part.indexOf('=');
    const name = separator < 0 ? part : part.slice(0, separator);
    if (name.trim() === B64_SESSION_COOKIE_NAME) return true;
  }
  return false;
}

/**
 * The #3476 origin boundary, applied to the request shapes B64 actually
 * receives.
 *
 * A fetch/XHR mutation carries the document's real Origin, so an exact compare
 * against the reviewed origin is the whole check. B64's consumer surface runs
 * under `script-src 'none'`, so every mutation is instead a top-level HTML form
 * POST, and a top-level form POST arrives with `Origin: null` — measured on
 * Chrome 154 against the live Worker on 2026-10-28, where it made the visitor's
 * own Save/Login/Logout buttons answer 403.
 *
 * The fallback keeps the boundary where #3476 put it. `Sec-Fetch-Site` is a
 * forbidden request header, so a cross-site document cannot set it, and the
 * same-site sibling that SameSite=Lax still carries the cookie to — the exact
 * case this guard exists for — reports `same-site`, not `same-origin`. The
 * request must also be addressed to the reviewed origin. A non-browser caller
 * can forge both headers and still needs that member's own session cookie,
 * which is not ambient browser authority. Everything else stays denied.
 */
function mutationOriginAccepted(request: Request, url: URL, expectedOrigin: string): boolean {
  const origin = request.headers.get('origin');
  if (origin === expectedOrigin) return true;
  if (origin !== null && origin !== '' && origin !== 'null') return false;
  return request.headers.get('sec-fetch-site') === 'same-origin' && url.origin === expectedOrigin;
}

function jsonErrorResponse(request: Request, status: number, error: string): Response {
  return responseForMethod(request, JSON.stringify({ error }), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function storageUnavailableResponse(request: Request): Response {
  return jsonErrorResponse(request, 503, 'storage_unavailable');
}

/**
 * A Google callback response always drops the single-use state cookie, whether
 * the login succeeded or not — a state that has been presented once is spent.
 */
function googleCallbackErrorResponse(request: Request, status: number, error: string): Response {
  const headers = withSecurityHeaders({ 'content-type': 'application/json; charset=utf-8' });
  headers.append('set-cookie', b64OAuthStateClearCookieValue());
  return responseForMethod(request, JSON.stringify({ error }), { status, headers });
}

/** Everything the Google flow needs, or null: the flow is all-or-nothing. */
interface GoogleFlowConfig {
  readonly members: B64MemberStore;
  readonly sessionSecret: string;
  readonly clientId: string;
  readonly clientSecret: string;
  readonly redirectOrigin: string;
}

function googleFlowConfig(dependencies: ConsumerHttpDependencies): GoogleFlowConfig | null {
  const { memberStore, sessionSecret, googleClientId, googleClientSecret, expectedBrowserOrigin } = dependencies;
  if (!memberStore || !sessionSecret || !googleClientId || !googleClientSecret || !expectedBrowserOrigin) {
    return null;
  }
  return Object.freeze({
    members: memberStore,
    sessionSecret,
    clientId: googleClientId,
    clientSecret: googleClientSecret,
    redirectOrigin: expectedBrowserOrigin,
  });
}

/** Redirect target for a theme toggle: same route without the theme parameter. */
function themeRedirectTarget(url: URL): string {
  const params = new URLSearchParams(url.searchParams);
  params.delete('theme');
  const query = params.toString();
  return query ? `${url.pathname}?${query}` : url.pathname;
}

/**
 * Creates the deployable B64 consumer HTTP boundary.
 *
 * Candidate loading is injectable so a future live provider integration can be wired
 * without weakening the existing consumer-card policy filter. The default Worker
 * entrypoint deliberately injects an empty loader until OWNER live activation occurs.
 */
export function createConsumerHttpHandler(
  dependencies: ConsumerHttpDependencies,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    let url: URL;
    try {
      url = new URL(request.url);
    } catch {
      return notFound(request);
    }

    if (request.method !== 'GET' && request.method !== 'HEAD' && request.method !== 'POST') {
      return methodNotAllowed(request);
    }

    const isIdentity = IDENTITY_PATHS.has(url.pathname);
    const isGoogle = GOOGLE_PATHS.has(url.pathname);
    const isProviderCallback = PROVIDER_CALLBACK_PATHS.has(url.pathname);
    const isAdmin = ADMIN_PATHS.has(url.pathname);
    if (request.method === 'POST' && !isIdentity && url.pathname !== '/pipeline' && url.pathname !== '/income') {
      return methodNotAllowed(request);
    }

    if (url.pathname === '/healthz') {
      return healthResponse(request);
    }

    const isBrowse = url.pathname === '/browse' || url.pathname === '/explore' || url.pathname === '/opportunities';
    const isDetail = url.pathname === '/detail' || url.pathname === '/opportunity';

    if (url.pathname !== '/' && url.pathname !== '/earn' && url.pathname !== '/today' && !isBrowse && !isDetail && url.pathname !== '/pipeline' && url.pathname !== '/income' && !isIdentity && !isGoogle && !isProviderCallback && !isAdmin) {
      return notFound(request);
    }

    // Theme handling (issue #5822): the consumer surface runs under
    // script-src 'none', so the sun/moon toggle is a plain same-origin link.
    // A toggle link flips the persisted `b64_theme` cookie server-side and
    // returns to the same route (filters intact) with a 303; every render
    // then uses the stored theme, Light being the first-visit default.
    const cookieHeader = request.headers.get('cookie');
    const theme = readThemeFromCookie(cookieHeader);
    if (isThemeToggleRequest(url)) {
      if (request.method === 'POST') {
        return methodNotAllowed(request);
      }
      return new Response(null, {
        status: 303,
        headers: withSecurityHeaders({
          location: themeRedirectTarget(url),
          'set-cookie': themeCookieHeaderValue(toggleTheme(theme)),
        }),
      });
    }
    const themeInfo: ConsumerThemeInfo = {
      theme,
      themeToggleHref: themeToggleHref(url.pathname, url.searchParams),
      googleLoginAvailable: googleFlowConfig(dependencies) !== null,
    };

    if (isIdentity) {
      if (request.method !== 'POST') {
        return new Response(null, {
          status: 303,
          headers: withSecurityHeaders({ location: '/pipeline' }),
        });
      }
      // Join, sign-in and sign-out each create or destroy a member cookie, so
      // they are same-origin mutations even when no session exists yet — a
      // cross-site form could otherwise log a visitor into an attacker's
      // account.
      const expectedOrigin = dependencies.expectedBrowserOrigin;
      if (!expectedOrigin) {
        return jsonErrorResponse(request, 503, 'origin_guard_unavailable');
      }
      if (!mutationOriginAccepted(request, url, expectedOrigin)) {
        return jsonErrorResponse(request, 403, 'origin_rejected');
      }
      const { memberStore, sessionSecret } = dependencies;
      if (!memberStore || !sessionSecret) {
        return jsonErrorResponse(request, 503, 'identity_unavailable');
      }

      if (url.pathname === '/logout') {
        try {
          await logoutSession({ store: memberStore, sessionSecret, cookieHeader });
        } catch {
          return storageUnavailableResponse(request);
        }
        return new Response(null, {
          status: 303,
          headers: withSecurityHeaders({
            location: '/pipeline',
            'set-cookie': b64SessionClearCookieValue(),
          }),
        });
      }

      const formData = await request.formData().catch(() => null);
      if (!formData) {
        return responseForMethod(request, 'Bad Request', {
          status: 400,
          headers: { 'content-type': 'text/plain; charset=utf-8' },
        });
      }
      const email = formData.get('email');
      const password = formData.get('password');
      try {
        const issued = url.pathname === '/join'
          ? await registerMember({ store: memberStore, sessionSecret, email, password })
          : await signInMember({ store: memberStore, sessionSecret, email, password });
        if (issued === null) {
          return jsonErrorResponse(request, 401, 'invalid_credentials');
        }
        return new Response(null, {
          status: 303,
          headers: withSecurityHeaders({
            location: '/pipeline',
            'set-cookie': issued.cookieHeader,
          }),
        });
      } catch (error) {
        if (error instanceof CredentialError) return jsonErrorResponse(request, 400, error.code);
        if (error instanceof B64MemberExistsError) return jsonErrorResponse(request, 409, 'member_exists');
        return storageUnavailableResponse(request);
      }
    }

    if (isGoogle) {
      const config = googleFlowConfig(dependencies);
      if (config === null) {
        // No B64 Google client on this deployment: refuse rather than send a
        // visitor to a login that cannot complete. The entry link is already
        // hidden for this case.
        return jsonErrorResponse(request, 503, 'auth_unavailable');
      }
      if (url.pathname === B64_GOOGLE_START_PATH) {
        const issued = await mintB64OAuthState({ sessionSecret: config.sessionSecret });
        const headers = withSecurityHeaders({
          location: b64GoogleAuthorizationUrl({
            clientId: config.clientId,
            redirectUri: b64GoogleRedirectUri(config.redirectOrigin),
            state: issued.state,
          }),
        });
        headers.append('set-cookie', b64OAuthStateCookieValue(issued.token));
        return new Response(null, { status: 303, headers });
      }

      const code = url.searchParams.get('code');
      const state = url.searchParams.get('state');
      const stateToken = cookieHeader === null
        ? null
        : extractCookieValue(cookieHeader, B64_OAUTH_STATE_COOKIE_NAME);
      const stateVerified = await verifyB64OAuthState({
        sessionSecret: config.sessionSecret,
        state,
        token: stateToken,
      });
      // No code (Google reported a refusal) and a state mismatch are the same
      // answer: this callback was not produced by a /start this Worker issued.
      if (!stateVerified || !code) {
        return googleCallbackErrorResponse(request, 403, 'invalid_state');
      }
      try {
        const issued = await signInWithGoogle({
          store: config.members,
          sessionSecret: config.sessionSecret,
          clientId: config.clientId,
          clientSecret: config.clientSecret,
          publicBaseUrl: config.redirectOrigin,
          code,
          fetchImpl: dependencies.googleFetch,
        });
        const headers = withSecurityHeaders({ location: '/pipeline' });
        headers.append('set-cookie', issued.cookieHeader);
        headers.append('set-cookie', b64OAuthStateClearCookieValue());
        return new Response(null, { status: 303, headers });
      } catch (error) {
        if (error instanceof GoogleAuthError) {
          return googleCallbackErrorResponse(request, error.status, error.code);
        }
        return googleCallbackErrorResponse(request, 503, 'storage_unavailable');
      }
    }

    if (isProviderCallback) {
      // The provider authenticates itself with its signature; there is no
      // cookie and no browser here. Storage and configuration failures answer
      // 503 so the provider retries instead of silently losing an event.
      const outcome = await handleAyetS2SCallback(
        {
          mode: dependencies.ayetMode ?? 'DISABLED',
          publisherApiKey: dependencies.ayetPublisherApiKey,
          rewardedAdslotId: dependencies.ayetRewardedAdslotId,
          signingSecret: dependencies.sessionSecret,
          rewardEvents: dependencies.rewardEvents ?? new UnboundRewardEventStore('B64_INCOME_DB'),
        },
        {
          parameters: ayetS2SParametersFromUrl(url),
          securityHash: request.headers.get(AYET_S2S_SECURITY_HASH_HEADER),
          observedAt: new Date().toISOString(),
        },
      ).catch((error: unknown) => {
        if (error instanceof AyetCallbackDisabled || error instanceof AyetCallbackUnconfigured) {
          return { status: 503, body: '', decision: 'PROVIDER_UNAVAILABLE' } as const;
        }
        if (error instanceof RewardEventStorageError) {
          return { status: 503, body: '', decision: 'STORAGE_UNAVAILABLE' } as const;
        }
        throw error;
      });
      return responseForMethod(request, outcome.body, {
        status: outcome.status,
        headers: { 'content-type': 'text/plain; charset=utf-8' },
      });
    }

    if (isAdmin) {
      const resolveAuth = dependencies.resolveAuth ?? defaultAuthResolver;
      const auth = await resolveAuth(request);
      if (!auth.authenticated || typeof auth.userId !== 'string') {
        return jsonErrorResponse(request, 401, 'unauthenticated');
      }
      const { memberStore, adminEmail, operationsSnapshot } = dependencies;
      if (!memberStore || !operationsSnapshot) {
        return jsonErrorResponse(request, 503, 'admin_unavailable');
      }
      let administrator = false;
      try {
        administrator = await isB64SuperAdmin({ adminEmail, members: memberStore, memberId: auth.userId });
      } catch {
        // "could not check" is reported as unavailable rather than quietly
        // answered as a grant or a denial.
        return jsonErrorResponse(request, 503, 'admin_unavailable');
      }
      if (!administrator) {
        return jsonErrorResponse(request, 403, 'admin_forbidden');
      }
      let snapshot: B64OperationsSnapshot;
      try {
        snapshot = await operationsSnapshot();
      } catch {
        return jsonErrorResponse(request, 503, 'admin_unavailable');
      }
      if (url.pathname === '/admin/status') {
        return responseForMethod(request, JSON.stringify(snapshot), {
          status: 200,
          headers: { 'content-type': 'application/json; charset=utf-8' },
        });
      }
      return responseForMethod(request, renderB64AdminConsole(snapshot, theme), {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    let candidates: readonly AdClickConsumerCandidate[];
    try {
      candidates = await dependencies.loadCandidates(request);
    } catch {
      return supplyUnavailable(request);
    }

    // The public lane degrades to an honest empty state when its loader fails;
    // the ad-click lane above already failed closed with 503.
    const publicLoader: PublicOpportunityLoader | undefined = dependencies.loadPublicOpportunities;
    let publicOpportunities: readonly PublicOpportunity[] = [];
    if (publicLoader) {
      try {
        publicOpportunities = await publicLoader(request);
      } catch {
        publicOpportunities = [];
      }
    }

    if (url.pathname === '/today') {
      const todayViewModel = buildAdClickFirstTodayRoute(candidates, { publicOpportunities });
      const html = renderAdClickFirstTodayRouteWeb(todayViewModel, themeInfo);
      return responseForMethod(request, html, {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    if (isBrowse) {
      const categoryParam = url.searchParams.get('category');
      const validCategories: ConsumerBrowseCategory[] = ['ALL', 'AD_CLICK', 'SURVEY', 'USABILITY', 'MICROTASK', 'SHORT_GIG'];
      const category = (validCategories.includes(categoryParam as ConsumerBrowseCategory) ? categoryParam : 'ALL') as ConsumerBrowseCategory;
      const query = url.searchParams.get('q') ?? '';
      const maxRaw = url.searchParams.get('maxSeconds');
      const maxSeconds = maxRaw && Number.isFinite(Number(maxRaw)) && Number(maxRaw) > 0 ? Number(maxRaw) : null;
      const browseOptions: BuildAdClickFirstBrowseOptions = { category, query, maxSeconds, publicOpportunities };
      const browseViewModel = buildAdClickFirstBrowse(candidates, browseOptions);
      const html = renderAdClickFirstBrowseWeb(browseViewModel, themeInfo);
      return responseForMethod(request, html, {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    if (isDetail) {
      const id = url.searchParams.get('id') ?? '';
      if (!id) {
        return notFound(request);
      }
      const detailViewModel = buildAdClickFirstOpportunityDetail(candidates, id, { publicOpportunities });
      if (!detailViewModel.found) {
        return responseForMethod(request, renderAdClickFirstOpportunityDetailWeb(detailViewModel, themeInfo), {
          status: 404,
          headers: { 'content-type': 'text/html; charset=utf-8' },
        });
      }
      const html = renderAdClickFirstOpportunityDetailWeb(detailViewModel, themeInfo);
      return responseForMethod(request, html, {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    if (url.pathname === '/pipeline' || url.pathname === '/income') {
      // Same-origin guard for cookie-authenticated mutations (#3476 policy,
      // mirrored from apps/padiem-chat/app/same_origin_guard.py): SameSite=Lax
      // is a site boundary, not an origin boundary, so a request carrying the
      // `b64_session` cookie must present an Origin header exactly equal to
      // the reviewed deployment origin. Missing Origin is denied (fail
      // closed); an unconfigured expected origin denies everything with 503
      // rather than weakening to "allow without expectation". Requests without
      // the session cookie carry no ambient browser authority, are not CSRF
      // subjects, and keep their existing auth error semantics (401 below).
      if (request.method === 'POST') {
        const cookieHeader = request.headers.get('cookie');
        if (cookieHeader !== null && carriesB64SessionCookie(cookieHeader)) {
          const expectedOrigin = dependencies.expectedBrowserOrigin;
          if (!expectedOrigin) {
            return jsonErrorResponse(request, 503, 'origin_guard_unavailable');
          }
          if (!mutationOriginAccepted(request, url, expectedOrigin)) {
            return jsonErrorResponse(request, 403, 'origin_rejected');
          }
        }
      }

      const resolveAuth = dependencies.resolveAuth ?? defaultAuthResolver;
      const auth = await resolveAuth(request);
      const userId = auth.authenticated ? auth.userId : null;

      // Handle POST for CRUD operations
      if (request.method === 'POST') {
        if (!userId) {
          return responseForMethod(request, JSON.stringify({ error: 'unauthorized' }), {
            status: 401,
            headers: { 'content-type': 'application/json; charset=utf-8' },
          });
        }
        // Parse form data
        const formData = await request.formData().catch((e) => { console.error('formData error:', e?.message); return null; });
        if (!formData) {
          return responseForMethod(request, 'Bad Request', { status: 400, headers: { 'content-type': 'text/plain; charset=utf-8' } });
        }
        const action = formData.get('action')?.toString();
        if (action === 'save') {
          const recordId = formData.get('id')?.toString() ?? crypto.randomUUID();
          const now = new Date().toISOString();
          let record: UserIncomeRecord = {
            id: recordId,
            userId,
            opportunityId: formData.get('opportunityId')?.toString() || null,
            externalRef: formData.get('externalRef')?.toString() || null,
            sourceType: (formData.get('sourceType')?.toString() as any) || 'MANUAL',
            title: formData.get('title')?.toString() || '',
            vendor: formData.get('vendor')?.toString() || '',
            status: (formData.get('status')?.toString() as any) || 'SAVED',
            expectedAmount: formData.get('expectedAmount') ? Number(formData.get('expectedAmount')) : null,
            expectedCurrency: (formData.get('expectedCurrency')?.toString() as any) || null,
            actualAmount: formData.get('actualAmount') ? Number(formData.get('actualAmount')) : null,
            actualCurrency: (formData.get('actualCurrency')?.toString() as any) || null,
            appliedAt: formData.get('appliedAt')?.toString() || null,
            acceptedAt: formData.get('acceptedAt')?.toString() || null,
            completedAt: formData.get('completedAt')?.toString() || null,
            paidAt: formData.get('paidAt')?.toString() || null,
            expiresAt: formData.get('expiresAt')?.toString() || null,
            note: formData.get('note')?.toString() || null,
            sourceUrl: formData.get('sourceUrl')?.toString() || null,
            createdAt: now,
            updatedAt: now,
          };
          const errors = validateUserIncomeRecord(record);
          if (errors.length > 0) {
            return responseForMethod(request, JSON.stringify({ errors }), {
              status: 400,
              headers: { 'content-type': 'application/json; charset=utf-8' },
            });
          }
          const repo = dependencies.incomeRepository ?? getRepository();
          // Guard: if updating, verify ownership. Storage failures fail
          // closed with 503 — never silently degraded to empty data or the
          // non-durable prototype.
          let existingRecords: readonly UserIncomeRecord[];
          try {
            existingRecords = await repo.getByUser(userId);
          } catch {
            return storageUnavailableResponse(request);
          }
          const existingRecord = existingRecords.find((r) => r.id === recordId);
          if (existingRecord && existingRecord.userId !== userId) {
            return responseForMethod(request, JSON.stringify({ error: 'forbidden' }), {
              status: 403,
              headers: { 'content-type': 'application/json; charset=utf-8' },
            });
          }
          // Validate state transition on update
          if (existingRecord && !isValidIncomePipelineTransition(existingRecord.status, record.status)) {
            return responseForMethod(request, JSON.stringify({ error: 'invalid_transition' }), {
              status: 400,
              headers: { 'content-type': 'application/json; charset=utf-8' },
            });
          }
          if (existingRecord) {
            record = { ...record, createdAt: existingRecord.createdAt };
          }
          try {
            await repo.save(record);
          } catch {
            return storageUnavailableResponse(request);
          }
          return new Response(null, {
            status: 303,
            headers: { location: '/pipeline', ...Object.fromEntries(withSecurityHeaders(new Headers()).entries()) },
          });
        }
        if (action === 'delete') {
          const recordId = formData.get('recordId')?.toString();
          if (recordId) {
            const repo = dependencies.incomeRepository ?? getRepository();
            let existingRecords: readonly UserIncomeRecord[];
            try {
              existingRecords = await repo.getByUser(userId);
            } catch {
              return storageUnavailableResponse(request);
            }
            const existingRecord = existingRecords.find((r) => r.id === recordId);
            if (existingRecord && existingRecord.userId !== userId) {
              return jsonErrorResponse(request, 403, 'forbidden');
            }
            try {
              await repo.delete(userId, recordId);
            } catch {
              return storageUnavailableResponse(request);
            }
          }
          return new Response(null, {
            status: 303,
            headers: { location: '/pipeline', ...Object.fromEntries(withSecurityHeaders(new Headers()).entries()) },
          });
        }
        return responseForMethod(request, 'Bad Request', { status: 400, headers: { 'content-type': 'text/plain; charset=utf-8' } });
      }

      // GET: render dashboard
      let records: readonly UserIncomeRecord[] = [];
      if (userId) {
        const repo = dependencies.incomeRepository ?? getRepository();
        try {
          records = await repo.getByUser(userId);
        } catch {
          return storageUnavailableResponse(request);
        }
      }
      const filterStatus = url.searchParams.get('status') as IncomePipelineStatus | null;
      const filterVendor = url.searchParams.get('vendor');
      const pipelineViewModel = buildIncomePipelineViewModel({
        userId,
        records,
        filters: { status: filterStatus, vendor: filterVendor },
        availableOpportunities: publicOpportunities,
      });
      const html = renderIncomePipelineWeb(pipelineViewModel, themeInfo);
      return responseForMethod(request, html, {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    const homeViewModel = buildAdClickFirstConsumerHome(candidates, { publicOpportunities });
    const html = renderAdClickFirstConsumerWeb(homeViewModel, themeInfo);
    return responseForMethod(request, html, {
      status: 200,
      headers: { 'content-type': 'text/html; charset=utf-8' },
    });
  };
}

export function createEmptySupplyConsumerHttpHandler(): (request: Request) => Promise<Response> {
  return createConsumerHttpHandler({ loadCandidates: () => [] });
}

/**
 * Public-supply consumer boundary: the ad-click lane stays honest zero-supply
 * (no provider approval), while verified, manually curated public opportunities
 * are served on /browse, /today and /detail. This does not grant any B2B
 * provider authority.
 */
export function createPublicSupplyConsumerHttpHandler(): (request: Request) => Promise<Response> {
  return createConsumerHttpHandler({
    loadCandidates: () => [],
    loadPublicOpportunities: loadVerifiedPublicOpportunities,
  });
}
