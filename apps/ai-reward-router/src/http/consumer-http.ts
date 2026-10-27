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
import { logoutSession, registerMember, signInMember } from '../identity/auth.js';
import { CredentialError } from '../identity/password.js';
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

function jsonErrorResponse(request: Request, status: number, error: string): Response {
  return responseForMethod(request, JSON.stringify({ error }), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}

function storageUnavailableResponse(request: Request): Response {
  return jsonErrorResponse(request, 503, 'storage_unavailable');
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
    if (request.method === 'POST' && !isIdentity && url.pathname !== '/pipeline' && url.pathname !== '/income') {
      return methodNotAllowed(request);
    }

    if (url.pathname === '/healthz') {
      return healthResponse(request);
    }

    const isBrowse = url.pathname === '/browse' || url.pathname === '/explore' || url.pathname === '/opportunities';
    const isDetail = url.pathname === '/detail' || url.pathname === '/opportunity';

    if (url.pathname !== '/' && url.pathname !== '/earn' && url.pathname !== '/today' && !isBrowse && !isDetail && url.pathname !== '/pipeline' && url.pathname !== '/income' && !isIdentity) {
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
      const origin = request.headers.get('origin');
      if (!origin || origin !== expectedOrigin) {
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
          const origin = request.headers.get('origin');
          if (!origin || origin !== expectedOrigin) {
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
