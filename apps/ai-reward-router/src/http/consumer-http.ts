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
import type { PublicOpportunity, PublicOpportunityLoader } from '../public-supply/domain.js';
import { loadVerifiedPublicOpportunities } from '../public-supply/verified-public-opportunities.js';

export type ConsumerCandidateLoader = (
  request: Request,
) => Promise<readonly AdClickConsumerCandidate[]> | readonly AdClickConsumerCandidate[];

export interface ConsumerHttpDependencies {
  readonly loadCandidates: ConsumerCandidateLoader;
  /**
   * Optional public-supply lane: manually curated, publicly verified opportunities.
   * The public lane never grants provider authority; it only links users to
   * official provider pages and pays PADIEM nothing.
   */
  readonly loadPublicOpportunities?: PublicOpportunityLoader;
}

const SECURITY_HEADERS = Object.freeze({
  'cache-control': 'no-store',
  'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
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

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return methodNotAllowed(request);
    }

    if (url.pathname === '/healthz') {
      return healthResponse(request);
    }

    const isBrowse = url.pathname === '/browse' || url.pathname === '/explore' || url.pathname === '/opportunities';
    const isDetail = url.pathname === '/detail' || url.pathname === '/opportunity';

    if (url.pathname !== '/' && url.pathname !== '/earn' && url.pathname !== '/today' && !isBrowse && !isDetail) {
      return notFound(request);
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
      const html = renderAdClickFirstTodayRouteWeb(todayViewModel);
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
      const html = renderAdClickFirstBrowseWeb(browseViewModel);
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
        return responseForMethod(request, renderAdClickFirstOpportunityDetailWeb(detailViewModel), {
          status: 404,
          headers: { 'content-type': 'text/html; charset=utf-8' },
        });
      }
      const html = renderAdClickFirstOpportunityDetailWeb(detailViewModel);
      return responseForMethod(request, html, {
        status: 200,
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    const homeViewModel = buildAdClickFirstConsumerHome(candidates);
    const html = renderAdClickFirstConsumerWeb(homeViewModel);

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
