import { createClient } from '../_lib/github.js';
import { get as cacheGet, set as cacheSet, FRESH_TTL_SECONDS } from '../_lib/cache.js';
import { sanitizeError, classifyGitHubError, ERROR_CODES } from '../_lib/errors.js';

export async function onRequest(context) {
  const { request, env, caches } = context;

  if (request.method !== 'GET') {
    return new Response(JSON.stringify({
      error: { code: 'INVALID_REQUEST', message: 'Only GET is allowed.' },
    }), {
      status: 405,
      headers: { 'Content-Type': 'application/json', Allow: 'GET' },
    });
  }

  const cache = caches?.default;
  if (!cache) {
    return new Response(JSON.stringify({
      error: { code: 'CACHE_UNAVAILABLE', message: 'Internal cache is unavailable.' },
    }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const secrets = {
    GITHUB_APP_ID: env?.GITHUB_APP_ID,
    GITHUB_APP_INSTALLATION_ID: env?.GITHUB_APP_INSTALLATION_ID,
    GITHUB_APP_PRIVATE_KEY_PKCS8: env?.GITHUB_APP_PRIVATE_KEY_PKCS8,
  };

  const getSecrets = async () => secrets;

  const client = createClient({
    fetch: globalThis.fetch,
    getSecrets,
    crypto: globalThis.crypto,
  });

  const repoFullName = 'skerishKang/ai-revenue-lab';

  try {
    const cached = await cacheGet(cache, repoFullName);
    if (cached && cached.fresh) {
      const syncedAt = new Date(cached.time).toISOString();
      const response = buildFreshResponse(cached.data, syncedAt);
      return buildOkResponse(response, 'HIT');
    }

    const data = await client.getFullStatus(repoFullName);
    const syncedAt = new Date().toISOString();
    await cacheSet(cache, repoFullName, data, true);

    const response = buildFreshResponse(data, syncedAt);
    return buildOkResponse(response, 'MISS');
  } catch (err) {
    if (err.code === 'CONFIGURATION_MISSING') {
      return new Response(JSON.stringify({
        error: sanitizeError(err),
      }), { status: 503, headers: { 'Content-Type': 'application/json' } });
    }

    const staleCached = await cacheGet(cache, repoFullName);
    if (staleCached && !staleCached.fresh) {
      const syncedAt = new Date(staleCached.time).toISOString();
      const response = buildFreshResponse(staleCached.data, syncedAt);
      response.stale = true;
      response.error = sanitizeError(err);
      return buildOkResponse(response, 'STALE');
    }

    const sanitized = sanitizeError(err);
    return new Response(JSON.stringify({ error: sanitized }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

function buildFreshResponse(repoData, syncedAt) {
  return {
    schemaVersion: 1,
    syncedAt,
    stale: false,
    repositories: [repoData],
  };
}

function buildOkResponse(body, cacheStatus) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'X-Portfolio-Cache': cacheStatus,
      'Cache-Control': `public, max-age=${FRESH_TTL_SECONDS}`,
    },
  });
}
