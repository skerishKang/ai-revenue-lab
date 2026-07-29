/*  github-status-service.js  —  Phase 2A service (PR #193 extended)
 *
 *  Unified alias contract: issue{N}, prSearch{N}, fallbackPr{N}
 *
 *  PR #193 contract preserved:
 *    - fresh cache TTL ~180s, stale retention ~86400s
 *    - single-flight token exchange + status refresh
 *    - safe error normalization, no raw upstream reflection
 */

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";
import { GitHubApiError } from "./github-client.js";
import { getPrSearchAliases } from "./business-github-query.js";
import { mergeBusinessFacts, createMergedPayload, SCHEMA_VERSION } from "./business-fact-merger.js";
import { safeError } from "./response.js";

const refreshFlights = new Map();

function errorPaths(errors) {
  return (errors || []).map((e) => (Array.isArray(e.path) ? e.path.map(String) : []));
}

function upstreamErrorResult(error, cached, ageMs, staleTtlSeconds) {
  const rateLimited = error instanceof GitHubApiError && error.code === "UPSTREAM_RATE_LIMITED";
  const code = rateLimited ? "UPSTREAM_RATE_LIMITED" : "UPSTREAM_UNAVAILABLE";
  if (cached && ageMs <= staleTtlSeconds * 1000) {
    return {
      payload: { ...cached.snapshot, ok: true, stale: true, errors: [...(cached.snapshot.errors || []), safeError(code, rateLimited ? "GitHub rate limits prevented refresh; showing the last successful snapshot." : "GitHub data could not be refreshed; showing the last successful snapshot.")] },
      status: 200, cacheState: "stale",
    };
  }
  return {
    payload: { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false, error: safeError(code, rateLimited ? "GitHub rate limits are temporarily preventing synchronization." : "GitHub data is temporarily unavailable."), businesses: [] },
    status: rateLimited ? 503 : 502, cacheState: "unavailable",
  };
}

export function createGitHubStatusService({
  client, cache, now = () => Date.now(), freshTtlSeconds = 180, staleTtlSeconds = 86400, singleFlightKey = GITHUB_REPOSITORY,
  identitySource = null,  // Map<number, {uiStatus, uxStatus, backendStatus}>
}) {
  async function loadFresh() {
    const aggregate = await client.getStatusAggregation(GITHUB_REPOSITORY);
    const root = aggregate?.data || {};
    const repositoryData = root.repository;
    if (!repositoryData) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);

    const paths = errorPaths(aggregate.errors);

    // Collect phase issue search results: merge the bounded dual aliases
    // (prSearchRefs{N} + prSearchRelated{N}), deduplicated by PR number.
    // Refs candidates keep priority order; truncation is flagged when either
    // alias reports more results than the bounded page returned.
    const phaseIssueResults = {};
    const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
    for (const m of mappedEntries) {
      for (const phase of ["uiPhaseIssue", "uxPhaseIssue", "bePhaseIssue"]) {
        const issueNum = m[phase];
        if (!issueNum || phaseIssueResults[`prSearch${issueNum}`]) continue;
        const [refsAlias, relatedAlias] = getPrSearchAliases(issueNum);
        const refsResult = root[refsAlias] || { nodes: [] };
        const relatedResult = root[relatedAlias] || { nodes: [] };
        const seen = new Set();
        const nodes = [];
        for (const node of [...(refsResult.nodes || []), ...(relatedResult.nodes || [])]) {
          const prNumber = Number(node?.number);
          if (!Number.isInteger(prNumber) || seen.has(prNumber)) continue;
          seen.add(prNumber);
          nodes.push(node);
        }
        const truncated = Number(refsResult.issueCount || 0) > (refsResult.nodes || []).length
          || Number(relatedResult.issueCount || 0) > (relatedResult.nodes || []).length;
        phaseIssueResults[`prSearch${issueNum}`] = { nodes, truncated };
      }
    }

    // Merge facts for each mapped Business
    const businessFacts = mappedEntries.map((mapping) => mergeBusinessFacts({
      mapping,
      repositoryData,
      phaseIssueResults,
      fallbackPrNode: mapping.fallbackPrNumber ? repositoryData[`fallbackPr${mapping.fallbackPrNumber}`] : null,
      identitySource,
    }));

    // Collect diagnostics
    const errors = [];
    for (const fact of businessFacts) {
      if (fact.error) errors.push({ businessNumber: fact.number, code: fact.error.code, message: fact.error.message });
    }
    if ((aggregate.errors || []).length && errors.length === 0) {
      errors.push(safeError("GRAPHQL_PARTIAL", "Some GitHub fields are unavailable."));
    }

    const merged = createMergedPayload({ businessFacts, repositoryData, syncedAt: new Date(now()).toISOString(), stale: false });
    merged.errors = errors;
    return merged;
  }

  async function storeFreshSnapshot(snapshot) {
    let result;
    try { result = await cache.set(snapshot); } catch { result = { persisted: false, errorCode: "CACHE_WRITE_FAILED" }; }
    if (result?.persisted !== false) return snapshot;
    const degraded = { ...snapshot, errors: [...(snapshot.errors || []), safeError("CACHE_WRITE_FAILED", "The latest GitHub snapshot could not be persisted.")] };
    if (typeof cache.setMemory === "function") cache.setMemory(degraded);
    return degraded;
  }

  async function refreshSingleFlight() {
    const existing = refreshFlights.get(singleFlightKey);
    if (existing) return existing;
    const flight = (async () => storeFreshSnapshot(await loadFresh()))();
    refreshFlights.set(singleFlightKey, flight);
    try { return await flight; } finally { if (refreshFlights.get(singleFlightKey) === flight) refreshFlights.delete(singleFlightKey); }
  }

  return {
    async getStatus() {
      const cached = await cache.get();
      const ageMs = cached ? now() - cached.storedAtMs : Number.POSITIVE_INFINITY;
      if (cached && ageMs <= freshTtlSeconds * 1000) return { payload: { ...cached.snapshot, stale: false }, status: 200, cacheState: "fresh" };
      try {
        const snapshot = await refreshSingleFlight();
        return { payload: snapshot, status: 200, cacheState: "miss" };
      } catch (error) { return upstreamErrorResult(error, cached, ageMs, staleTtlSeconds); }
    },
  };
}
