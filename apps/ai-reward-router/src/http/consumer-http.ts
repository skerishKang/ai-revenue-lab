import { buildAdClickFirstConsumerHome } from '../ad-click-first/consumer-home.js';
import type { AdClickConsumerCandidate } from '../ad-click-first/consumer-card.js';
import { renderAdClickFirstConsumerWeb } from '../ad-click-first/consumer-web.js';

export type ConsumerCandidateLoader = (
  request: Request,
) => Promise<readonly AdClickConsumerCandidate[]> | readonly AdClickConsumerCandidate[];

export interface ConsumerHttpDependencies {
  readonly loadCandidates: ConsumerCandidateLoader;
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

    if (url.pathname !== '/' && url.pathname !== '/earn') {
      return notFound(request);
    }

    let candidates: readonly AdClickConsumerCandidate[];
    try {
      candidates = await dependencies.loadCandidates(request);
    } catch {
      return supplyUnavailable(request);
    }

    const viewModel = buildAdClickFirstConsumerHome(candidates);
    const html = renderAdClickFirstConsumerWeb(viewModel);

    return responseForMethod(request, html, {
      status: 200,
      headers: { 'content-type': 'text/html; charset=utf-8' },
    });
  };
}

export function createEmptySupplyConsumerHttpHandler(): (request: Request) => Promise<Response> {
  return createConsumerHttpHandler({ loadCandidates: () => [] });
}
