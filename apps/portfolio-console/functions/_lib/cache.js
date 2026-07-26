const FRESH_TTL_SECONDS = 180;
const STALE_TTL_SECONDS = 3600;

function cacheKey(repoFullName) {
  return `github-status:${repoFullName}`;
}

async function get(cache, repoFullName) {
  const key = cacheKey(repoFullName);
  const response = await cache.match(key);
  if (!response) return null;

  const fresh = response.headers.get('X-Portfolio-Fresh');
  return {
    data: await response.json(),
    time: new Date(response.headers.get('X-Portfolio-Time')).getTime(),
    fresh: fresh === 'true',
  };
}

async function set(cache, repoFullName, data, fresh) {
  const key = cacheKey(repoFullName);
  const ttl = fresh ? FRESH_TTL_SECONDS : STALE_TTL_SECONDS;

  const body = JSON.stringify(data);
  const headers = {
    'Content-Type': 'application/json',
    'Cache-Control': `public, max-age=${ttl}`,
    'X-Portfolio-Time': new Date().toISOString(),
    'X-Portfolio-Fresh': fresh ? 'true' : 'false',
  };

  const response = new Response(body, { headers });
  await cache.put(key, response);
}

async function getStale(cache, repoFullName) {
  const key = cacheKey(repoFullName);
  const response = await cache.match(key);
  if (!response) return null;

  const fresh = response.headers.get('X-Portfolio-Fresh');
  if (fresh === 'true') return null;

  return {
    data: await response.json(),
    time: new Date(response.headers.get('X-Portfolio-Time')).getTime(),
  };
}

export { get, set, getStale, FRESH_TTL_SECONDS, STALE_TTL_SECONDS };
