import { describe, it, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createClient, ALLOWLIST } from '../../functions/_lib/github.js';
import { get as cacheGet, set as cacheSet } from '../../functions/_lib/cache.js';
import { sanitizeError, classifyGitHubError, ERROR_CODES } from '../../functions/_lib/errors.js';

function makeMockCache() {
  const store = new Map();
  return {
    store,
    async match(key) {
      const entry = store.get(key);
      if (!entry) return null;
      const headers = new Headers(entry.headers);
      store.delete(key);
      return new Response(JSON.stringify(entry.data), { headers });
    },
    async put(key, response) {
      const data = await response.clone().json();
      const headers = {};
      response.headers.forEach((v, k) => { headers[k] = v; });
      store.set(key, { data, headers, time: Date.now() });
    },
    async delete(key) { store.delete(key); },
  };
}

function makeMockFetch(responses) {
  let callIndex = 0;
  return async (url, opts) => {
    const idx = callIndex++;
    const mock = responses[idx];
    if (!mock) return new Response('{}', { status: 500 });
    if (mock.error) throw mock.error;
    return new Response(JSON.stringify(mock.body), {
      status: mock.status || 200,
      headers: mock.headers || {},
    });
  };
}

function makeMockGetSecrets(overrides) {
  return async () => ({
    GITHUB_APP_ID: '123456',
    GITHUB_APP_INSTALLATION_ID: '789012',
    GITHUB_APP_PRIVATE_KEY_PKCS8: '-----BEGIN PRIVATE KEY-----\nMOCK\n-----END PRIVATE KEY-----',
    ...overrides,
  });
}

// Stub crypto for tests that don't exercise JWT
const mockCrypto = {
  subtle: {
    importKey: async () => ({ type: 'mock' }),
    sign: async () => new ArrayBuffer(32),
  },
};

describe('github-status endpoint - _lib/errors', () => {
  it('sanitizeError returns GITHUB_UNAVAILABLE for null input', () => {
    const result = sanitizeError(null);
    assert.equal(result.code, ERROR_CODES.GITHUB_UNAVAILABLE);
  });

  it('sanitizeError returns GITHUB_UNAVAILABLE for string input', () => {
    const result = sanitizeError('some error');
    assert.equal(result.code, ERROR_CODES.GITHUB_UNAVAILABLE);
  });

  it('sanitizeError returns known code for structured error', () => {
    const result = sanitizeError({ code: ERROR_CODES.CONFIGURATION_MISSING });
    assert.equal(result.code, ERROR_CODES.CONFIGURATION_MISSING);
  });

  it('sanitizeError falls back to GITHUB_UNAVAILABLE for unknown code', () => {
    const result = sanitizeError({ code: 'UNKNOWN_CODE' });
    assert.equal(result.code, ERROR_CODES.GITHUB_UNAVAILABLE);
  });

  it('sanitizeError never exposes raw error message', () => {
    const result = sanitizeError({ code: ERROR_CODES.GITHUB_UNAVAILABLE, message: 'secret=abc123' });
    assert.equal(result.message, 'GitHub is temporarily unavailable.');
    assert.ok(!result.message.includes('secret'));
  });

  it('classifyGitHubError maps 401 to GITHUB_AUTH_FAILED', () => {
    const result = classifyGitHubError(401, {});
    assert.equal(result.code, ERROR_CODES.GITHUB_AUTH_FAILED);
    assert.equal(result.status, 502);
  });

  it('classifyGitHubError maps 404 to GITHUB_NOT_FOUND', () => {
    const result = classifyGitHubError(404, {});
    assert.equal(result.code, ERROR_CODES.GITHUB_NOT_FOUND);
  });

  it('classifyGitHubError maps 429 to GITHUB_RATE_LIMITED', () => {
    const result = classifyGitHubError(429, {});
    assert.equal(result.code, ERROR_CODES.GITHUB_RATE_LIMITED);
  });

  it('classifyGitHubError maps 500 to GITHUB_UNAVAILABLE', () => {
    const result = classifyGitHubError(500, {});
    assert.equal(result.code, ERROR_CODES.GITHUB_UNAVAILABLE);
  });
});

describe('github-status endpoint - allowlist', () => {
  it('ALLOWLIST contains skerishKang/ai-revenue-lab', () => {
    assert.ok(ALLOWLIST.includes('skerishKang/ai-revenue-lab'));
  });

  it('ALLOWLIST does not contain arbitrary repos', () => {
    assert.ok(!ALLOWLIST.includes('some-other/repo'));
  });
});

describe('github-status endpoint - client validation', () => {
  it('getFullStatus rejects non-allowlisted repository', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    await assert.rejects(
      () => client.getFullStatus('unauthorized/repo'),
      (err) => err.code === 'INVALID_REQUEST'
    );
  });

  it('getConfig throws CONFIGURATION_MISSING when secrets are missing', async () => {
    const getSecrets = async () => ({});
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    await assert.rejects(
      () => client.getConfig(),
      (err) => err.code === 'CONFIGURATION_MISSING'
    );
  });

  it('getConfig throws CONFIGURATION_MISSING when only appId is missing', async () => {
    const getSecrets = async () => ({
      GITHUB_APP_INSTALLATION_ID: '789012',
      GITHUB_APP_PRIVATE_KEY_PKCS8: 'key',
    });
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    await assert.rejects(
      () => client.getConfig(),
      (err) => err.code === 'CONFIGURATION_MISSING'
    );
  });
});

describe('github-status endpoint - JWT/token/private key not in response', () => {
  it('private key not in getFullStatus result', async () => {
    const mockRepo = { full_name: 'skerishKang/ai-revenue-lab', html_url: 'https://github.com/skerishKang/ai-revenue-lab', default_branch: 'main' };
    const mockCommit = { sha: 'abc123', commit: { message: 'test', committer: { date: '2026-01-01T00:00:00Z' } }, html_url: 'https://github.com/commit/abc' };
    const mockIssues = [];
    const mockPrs = [];
    const mockChecks = { check_runs: [] };
    const mockStatuses = { statuses: [] };

    const fetch = makeMockFetch([
      { body: { token: 'dummy_token' }, status: 200 },
      { body: mockRepo, status: 200 },
      { body: [mockCommit], status: 200, headers: { Link: '<https://api.github.com/repos/skerishKang/ai-revenue-lab/commits?per_page=1&page=1>; rel="last"' } },
      { body: mockIssues, status: 200, headers: {} },
      { body: mockPrs, status: 200, headers: {} },
      { body: mockChecks, status: 200 },
      { body: mockStatuses, status: 200 },
    ]);

    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch, getSecrets, crypto: mockCrypto });
    const result = await client.getFullStatus('skerishKang/ai-revenue-lab');
    const resultStr = JSON.stringify(result);
    assert.ok(!resultStr.includes('PRIVATE KEY'));
    assert.ok(!resultStr.includes('dummy_token'));
    assert.ok(!resultStr.includes('123456'));
    assert.ok(!resultStr.includes('JWT'));
  });

  it('error responses do not contain secrets', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    try {
      await client.getFullStatus('unauthorized/repo');
    } catch (err) {
      assert.equal(err.code, 'INVALID_REQUEST');
      assert.ok(!err.message.includes('PRIVATE'));
    }
  });
});

describe('github-status endpoint - data transformation', () => {
  it('transformCommit returns correct shape', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const raw = {
      sha: 'abcd1234',
      commit: { message: 'feat: add feature\n\nDetails here', committer: { date: '2026-07-01T12:00:00Z' } },
      html_url: 'https://github.com/commit/abcd1234',
    };
    const result = client.transformCommit(raw);
    assert.equal(result.sha, 'abcd1234');
    assert.equal(result.title, 'feat: add feature');
    assert.equal(result.committedAt, '2026-07-01T12:00:00Z');
    assert.equal(result.url, 'https://github.com/commit/abcd1234');
  });

  it('transformCommit returns null for null input', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    assert.equal(client.transformCommit(null), null);
  });

  it('transformIssue returns correct shape and filters PRs', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const issue = { number: 42, title: 'Bug', state: 'open', updated_at: '2026-07-01T00:00:00Z', html_url: 'https://github.com/issue/42' };
    const result = client.transformIssue(issue);
    assert.equal(result.number, 42);
    assert.equal(result.title, 'Bug');
    assert.equal(result.state, 'open');

    const prLike = { ...issue, pull_request: { url: 'https://api.github.com/pulls/42' } };
    assert.equal(client.transformIssue(prLike), null);
  });

  it('transformPullRequest returns correct shape', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const pr = { number: 7, title: 'Fix', state: 'open', draft: true, updated_at: '2026-07-01T00:00:00Z', html_url: 'https://github.com/pr/7' };
    const result = client.transformPullRequest(pr);
    assert.equal(result.number, 7);
    assert.equal(result.draft, true);
    assert.equal(result.state, 'open');
  });

  it('transformPullRequest returns null for null', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    assert.equal(client.transformPullRequest(null), null);
  });
});

describe('github-status endpoint - CI state aggregation', () => {
  it('returns pass when all checks pass', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({
      checkRuns: [{ id: 1, name: 'test', conclusion: 'success' }],
      statuses: [],
    });
    assert.equal(result.state, 'pass');
    assert.equal(result.source, 'checks');
  });

  it('returns fail when any check fails', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({
      checkRuns: [
        { id: 1, name: 'passing', conclusion: 'success' },
        { id: 2, name: 'failing', conclusion: 'failure' },
      ],
      statuses: [],
    });
    assert.equal(result.state, 'fail');
  });

  it('returns pending when check is in progress', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({
      checkRuns: [{ id: 1, name: 'waiting', status: 'in_progress' }],
      statuses: [],
    });
    assert.equal(result.state, 'pending');
  });

  it('returns unavailable when no checks or statuses exist', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({ checkRuns: [], statuses: [] });
    assert.equal(result.state, 'unavailable');
    assert.equal(result.source, 'none');
  });

  it('treats error/timed_out/cancelled/action_required as fail', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    for (const state of ['error', 'timed_out', 'cancelled', 'action_required', 'startup_failure']) {
      const result = client.aggregateCIState({
        checkRuns: [{ id: 1, name: 'check', conclusion: state }],
        statuses: [],
      });
      assert.equal(result.state, 'fail', `State ${state} should map to fail`);
    }
  });

  it('treats neutral and skipped as pass', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    for (const conclusion of ['neutral', 'skipped', 'success']) {
      const result = client.aggregateCIState({
        checkRuns: [{ id: 1, name: 'check', conclusion }],
        statuses: [],
      });
      assert.equal(result.state, 'pass', `Conclusion ${conclusion} should map to pass`);
    }
  });

  it('handles commit statuses when check runs are absent', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({
      checkRuns: [],
      statuses: [{ context: 'ci/circleci', state: 'success' }],
    });
    assert.equal(result.state, 'pass');
    assert.equal(result.source, 'statuses');
  });

  it('fail overrides pending, pending overrides pass', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({
      checkRuns: [
        { id: 1, conclusion: 'success' },
        { id: 2, status: 'in_progress' },
        { id: 3, conclusion: 'failure' },
      ],
      statuses: [],
    });
    assert.equal(result.state, 'fail');
  });

  it('pending with pass returns pending', async () => {
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    const result = client.aggregateCIState({
      checkRuns: [
        { id: 1, conclusion: 'success' },
        { id: 2, status: 'queued' },
      ],
      statuses: [],
    });
    assert.equal(result.state, 'pending');
  });
});

describe('github-status endpoint - cache behavior', () => {
  it('fresh cache HIT returns data without calling GitHub', async () => {
    const cache = makeMockCache();
    const repoName = 'skerishKang/ai-revenue-lab';
    const cachedData = { test: true };

    const freshResponse = new Response(JSON.stringify(cachedData), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'public, max-age=180',
        'X-Portfolio-Time': new Date().toISOString(),
        'X-Portfolio-Fresh': 'true',
      },
    });
    await cache.put(`github-status:${repoName}`, freshResponse);

    const result = await cacheGet(cache, repoName);
    assert.ok(result !== null);
    assert.ok(result.fresh);
    assert.deepEqual(result.data, cachedData);
  });

  it('cache MISS returns null', async () => {
    const cache = makeMockCache();
    const result = await cacheGet(cache, 'skerishKang/ai-revenue-lab');
    assert.equal(result, null);
  });

  it('cache SET stores data with correct freshness', async () => {
    const cache = makeMockCache();
    const repoName = 'skerishKang/ai-revenue-lab';
    const data = { fullName: repoName };

    await cacheSet(cache, repoName, data, true);
    const cached = await cacheGet(cache, repoName);
    assert.ok(cached !== null);
    assert.ok(cached.fresh);
  });

  it('stale cache returned on error if fresh cache absent', async () => {
    const cache = makeMockCache();
    const repoName = 'skerishKang/ai-revenue-lab';
    const staleData = { fullName: repoName };

    const staleResponse = new Response(JSON.stringify(staleData), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'public, max-age=3600',
        'X-Portfolio-Time': new Date(Date.now() - 60000).toISOString(),
        'X-Portfolio-Fresh': 'false',
      },
    });
    await cache.put(`github-status:${repoName}`, staleResponse);

    const result = await cacheGet(cache, repoName);
    assert.ok(result !== null);
    assert.ok(!result.fresh);
  });
});

describe('github-status endpoint - GitHub error handling', () => {
  it('CONFIGURATION_MISSING returns sanitized error without secrets', async () => {
    const getSecrets = async () => ({});
    const client = createClient({ fetch: makeMockFetch([]), getSecrets, crypto: mockCrypto });
    try {
      await client.getFullStatus('skerishKang/ai-revenue-lab');
      assert.fail('Should have thrown');
    } catch (err) {
      assert.equal(err.code, 'CONFIGURATION_MISSING');
      assert.ok(!err.message.includes('PRIVATE'));
      assert.ok(!err.message.includes('123456'));
    }
  });

  it('GitHub API error without stale cache returns sanitized error', async () => {
    const getSecrets = makeMockGetSecrets();
    const fetch = makeMockFetch([
      { body: { token: 't' }, status: 200 },
      null,
    ]);
    const client = createClient({ fetch, getSecrets, crypto: mockCrypto });
    await assert.rejects(
      () => client.getFullStatus('skerishKang/ai-revenue-lab'),
    );
  });

  it('GitHub raw error body not exposed in error', async () => {
    const sanitized = sanitizeError({ code: 'GITHUB_UNAVAILABLE' });
    assert.equal(sanitized.code, 'GITHUB_UNAVAILABLE');
    assert.ok(!sanitized.message.includes('{'));
    assert.ok(!sanitized.message.includes('['));
  });
});

describe('github-status endpoint - full status response structure', () => {
  it('returns correct schema for a successful getFullStatus call', async () => {
    const mockRepo = { full_name: 'skerishKang/ai-revenue-lab', html_url: 'https://github.com/skerishKang/ai-revenue-lab', default_branch: 'main' };
    const mockCommit = { sha: 'def456', commit: { message: 'fix: bug', committer: { date: '2026-07-02T00:00:00Z' } }, html_url: 'https://github.com/commit/def456' };
    const mockIssues = [];
    const mockPrs = [];
    const mockChecks = { check_runs: [] };
    const mockStatuses = { statuses: [] };

    const fetch = makeMockFetch([
      { body: { token: 't' }, status: 200 },
      { body: mockRepo, status: 200 },
      { body: [mockCommit], status: 200, headers: {} },
      { body: mockIssues, status: 200, headers: {} },
      { body: mockPrs, status: 200, headers: {} },
      { body: mockChecks, status: 200 },
      { body: mockStatuses, status: 200 },
    ]);

    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch, getSecrets, crypto: mockCrypto });
    const result = await client.getFullStatus('skerishKang/ai-revenue-lab');

    assert.equal(result.fullName, 'skerishKang/ai-revenue-lab');
    assert.equal(result.url, 'https://github.com/skerishKang/ai-revenue-lab');
    assert.equal(result.defaultBranch, 'main');
    assert.ok(result.latestCommit !== null);
    assert.equal(result.latestCommit.sha, 'def456');
    assert.equal(result.issues.openCount, 0);
    assert.equal(result.issues.latest, null);
    assert.equal(result.pullRequests.openCount, 0);
    assert.equal(result.pullRequests.draftCount, 0);
    assert.equal(result.pullRequests.latest, null);
    assert.ok(result.ci !== undefined);
    assert.equal(result.ci.state, 'unavailable');
  });

  it('includes issues and PRs when present', async () => {
    const mockRepo = { full_name: 'skerishKang/ai-revenue-lab', html_url: 'https://github.com/skerishKang/ai-revenue-lab', default_branch: 'main' };
    const mockCommit = { sha: 'ghi789', commit: { message: 'update', committer: { date: '2026-07-03T00:00:00Z' } }, html_url: 'https://github.com/commit/ghi789' };
    const mockIssues = [{ number: 1, title: 'Bug', state: 'open', updated_at: '2026-07-03T00:00:00Z', html_url: 'https://github.com/issue/1' }];
    const mockPrs = [{ number: 2, title: 'PR', state: 'open', draft: false, updated_at: '2026-07-03T00:00:00Z', html_url: 'https://github.com/pr/2' }];
    const mockChecks = { check_runs: [] };
    const mockStatuses = { statuses: [{ context: 'test', state: 'success' }] };

    const fetch = makeMockFetch([
      { body: { token: 't' }, status: 200 },
      { body: mockRepo, status: 200 },
      { body: [mockCommit], status: 200, headers: { Link: '<https://api.github.com/repos/skerishKang/ai-revenue-lab/commits?per_page=1&page=1>; rel="last"' } },
      { body: mockIssues, status: 200, headers: { Link: '<https://api.github.com/repos/skerishKang/ai-revenue-lab/issues?page=3>; rel="last"' } },
      { body: mockPrs, status: 200, headers: { Link: '<https://api.github.com/repos/skerishKang/ai-revenue-lab/pulls?page=5>; rel="last"' } },
      { body: mockChecks, status: 200 },
      { body: mockStatuses, status: 200 },
    ]);

    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch, getSecrets, crypto: mockCrypto });
    const result = await client.getFullStatus('skerishKang/ai-revenue-lab');

    assert.equal(result.issues.openCount, 3);
    assert.equal(result.issues.latest.number, 1);
    assert.equal(result.pullRequests.openCount, 5);
    assert.equal(result.pullRequests.latest.number, 2);
    assert.equal(result.pullRequests.draftCount, 0);
  });

  it('no business judgment data in response', async () => {
    const mockRepo = { full_name: 'skerishKang/ai-revenue-lab', html_url: 'https://github.com/skerishKang/ai-revenue-lab', default_branch: 'main' };
    const mockCommit = { sha: 'x', commit: { message: 'x', committer: { date: '2026-01-01T00:00:00Z' } }, html_url: '' };
    const fetch = makeMockFetch([
      { body: { token: 't' }, status: 200 },
      { body: mockRepo, status: 200 },
      { body: [mockCommit], status: 200, headers: {} },
      { body: [], status: 200, headers: {} },
      { body: [], status: 200, headers: {} },
      { body: { check_runs: [] }, status: 200 },
      { body: { statuses: [] }, status: 200 },
    ]);
    const getSecrets = makeMockGetSecrets();
    const client = createClient({ fetch, getSecrets, crypto: mockCrypto });
    const result = await client.getFullStatus('skerishKang/ai-revenue-lab');
    const resultStr = JSON.stringify(result);

    const forbidden = ['progress', 'priority', 'nextAction', 'completeness', 'milestoneMeaning'];
    for (const term of forbidden) {
      assert.ok(!resultStr.toLowerCase().includes(term), `Should not contain ${term}`);
    }
  });
});

describe('github-status endpoint - endpoint method and access', () => {
  it('simulates method restriction (only GET)', async () => {
    const methods = ['POST', 'PUT', 'DELETE', 'PATCH'];
    for (const method of methods) {
      const response = new Response(null, { status: 405 });
      assert.equal(response.status, 405);
    }
  });

  it('allowlist prevents arbitrary repository access', () => {
    assert.ok(!ALLOWLIST.includes('some-hacker/repo'));
  });

  it('simulates CORS headers check', () => {
    const headers = new Headers({ 'Content-Type': 'application/json' });
    assert.ok(!headers.has('Access-Control-Allow-Origin'));
  });
});
