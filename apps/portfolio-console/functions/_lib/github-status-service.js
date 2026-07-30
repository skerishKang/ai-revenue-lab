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
import { GitHubAuthError } from "./github-app-auth.js";
import { getDiscoveryPoolSpecs } from "./business-github-query.js";
import { mergeBusinessFacts, createMergedPayload, SCHEMA_VERSION } from "./business-fact-merger.js";
import { safeError, validDiagnosticCode } from "./response.js";

const PHASES = Object.freeze(["ui", "ux", "backend"]);

const refreshFlights = new Map();

const UNKNOWN_INTERNAL = "UNKNOWN_INTERNAL";

const API_CODE_TO_DIAGNOSTIC = Object.freeze({
  GITHUB_REQUEST_FAILED: "GITHUB_GRAPHQL_REQUEST_FAILED",
  GITHUB_RESPONSE_INVALID: "GITHUB_GRAPHQL_RESPONSE_INVALID",
  GRAPHQL_DATA_UNAVAILABLE: "GITHUB_GRAPHQL_DATA_UNAVAILABLE",
  UPSTREAM_RATE_LIMITED: "GITHUB_GRAPHQL_RATE_LIMITED",
  GITHUB_GRAPHQL_AUTH_FAILED: "GITHUB_GRAPHQL_AUTH_FAILED",
  GITHUB_GRAPHQL_TRANSPORT_FAILED: "GITHUB_GRAPHQL_TRANSPORT_FAILED",
  GITHUB_DATA_PROCESSING_FAILED: "GITHUB_DATA_PROCESSING_FAILED",
});

const AUTH_ERROR_TO_DIAGNOSTIC = Object.freeze({
  CRYPTO_UNAVAILABLE: "CRYPTO_UNAVAILABLE",
  PRIVATE_KEY_INVALID: "PRIVATE_KEY_INVALID",
  JWT_SIGNING_FAILED: "JWT_SIGNING_FAILED",
  INSTALLATION_TOKEN_REQUEST_FAILED: "INSTALLATION_TOKEN_REQUEST_FAILED",
  INSTALLATION_TOKEN_EXCHANGE_FAILED: "INSTALLATION_TOKEN_EXCHANGE_FAILED",
  INSTALLATION_TOKEN_RESPONSE_INVALID: "INSTALLATION_TOKEN_RESPONSE_INVALID",
});

function resolveDiagnosticCode(error) {
  if (!error || typeof error !== "object") return UNKNOWN_INTERNAL;
  if (error instanceof GitHubAuthError) return validDiagnosticCode(AUTH_ERROR_TO_DIAGNOSTIC[error.code] || UNKNOWN_INTERNAL);
  if (error instanceof GitHubApiError) return validDiagnosticCode(API_CODE_TO_DIAGNOSTIC[error.code] || UNKNOWN_INTERNAL);
  return UNKNOWN_INTERNAL;
}

function errorPaths(errors) {
  return (errors || []).map((e) => (Array.isArray(e.path) ? e.path.map(String) : []));
}

function upstreamErrorResult(error, cached, ageMs, staleTtlSeconds) {
  const rateLimited = error instanceof GitHubApiError && error.code === "UPSTREAM_RATE_LIMITED";
  const code = rateLimited ? "UPSTREAM_RATE_LIMITED" : "UPSTREAM_UNAVAILABLE";
  const diagnostic = resolveDiagnosticCode(error);
  if (cached && ageMs <= staleTtlSeconds * 1000) {
    return {
      payload: { ...cached.snapshot, ok: true, stale: true, errors: [...(cached.snapshot.errors || []), safeError(code, rateLimited ? "GitHub rate limits prevented refresh; showing the last successful snapshot." : "GitHub data could not be refreshed; showing the last successful snapshot.", diagnostic)] },
      status: 200, cacheState: "stale",
    };
  }
  console.log(JSON.stringify({ event: "portfolio_github_sync_failed", diagnosticCode: diagnostic }));
  return {
    payload: { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false, error: safeError(code, rateLimited ? "GitHub rate limits are temporarily preventing synchronization." : "GitHub data is temporarily unavailable.", diagnostic), businesses: [] },
    status: rateLimited ? 503 : 502, cacheState: "unavailable",
  };
}

export function createGitHubStatusService({
  client, cache, now = () => Date.now(), freshTtlSeconds = 180, staleTtlSeconds = 86400, singleFlightKey = GITHUB_REPOSITORY,
  identitySource = null,  // Map<number, {uiStatus, uxStatus, backendStatus}>
}) {
  async function loadFresh() {
    const aggregate = await client.getStatusAggregation(GITHUB_REPOSITORY);
    try {
    const root = aggregate?.data || {};
    const repositoryData = root.repository;
    if (!repositoryData) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);

    const paths = errorPaths(aggregate.errors);

    // Build one merged candidate pool per (Business, phase) pair from the four
    // bounded alias families (marker → refs → related → convention). Nodes are
    // deduped by PR number in discovery-priority order; a pool is truncated
    // when ANY contributing alias reports more results than its bounded page
    // returned, and truncatedPools records which families are unresolved.
    const aliasState = new Map();
    const resolveAlias = (alias) => {
      if (!aliasState.has(alias)) {
        const result = root[alias] || { nodes: [] };
        const nodes = Array.isArray(result.nodes) ? result.nodes : [];
        aliasState.set(alias, { nodes, truncated: Number(result.issueCount || 0) > nodes.length });
      }
      return aliasState.get(alias);
    };

    const discoveryPools = {};
    const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
    for (const m of mappedEntries) {
      for (const phase of PHASES) {
        const specs = getDiscoveryPoolSpecs(m, phase);
        if (!specs.length) continue;
        const seen = new Set();
        const nodes = [];
        const truncatedPools = [];
        for (const spec of specs) {
          const aliasResult = resolveAlias(spec.alias);
          if (aliasResult.truncated) truncatedPools.push(spec.pool);
          for (const node of aliasResult.nodes) {
            const prNumber = Number(node?.number);
            if (!Number.isInteger(prNumber) || seen.has(prNumber)) continue;
            seen.add(prNumber);
            nodes.push(node);
          }
        }
        discoveryPools[`${m.number}:${phase}`] = { nodes, truncated: truncatedPools.length > 0, truncatedPools };
      }
    }

    // Merge facts for each mapped Business (phase-scoped fallback nodes)
    const businessFacts = mappedEntries.map((mapping) => {
      const nums = mapping.fallbackPrNumbers || {};
      const fallbackPrNodes = {
        ui: nums.ui ? (repositoryData[`fallbackPr${nums.ui}`] || null) : null,
        ux: nums.ux ? (repositoryData[`fallbackPr${nums.ux}`] || null) : null,
        backend: nums.backend ? (repositoryData[`fallbackPr${nums.backend}`] || null) : null,
      };
      return mergeBusinessFacts({
        mapping,
        repositoryData,
        discoveryPools,
        fallbackPrNodes,
        identitySource,
      });
    });

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
    } catch (error) {
      if (error instanceof GitHubAuthError || error instanceof GitHubApiError) throw error;
      throw new GitHubApiError("GITHUB_DATA_PROCESSING_FAILED", 502);
    }
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
      let cached;
      try { cached = await cache.get(); } catch {
        return {
          payload: { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false, error: safeError("UPSTREAM_UNAVAILABLE", "GitHub data is temporarily unavailable.", "CACHE_READ_FAILED"), businesses: [] },
          status: 502, cacheState: "unavailable",
        };
      }
      const ageMs = cached ? now() - cached.storedAtMs : Number.POSITIVE_INFINITY;
      if (cached && ageMs <= freshTtlSeconds * 1000) return { payload: { ...cached.snapshot, stale: false }, status: 200, cacheState: "fresh" };
      try {
        const snapshot = await refreshSingleFlight();
        return { payload: snapshot, status: 200, cacheState: "miss" };
      } catch (error) { return upstreamErrorResult(error, cached, ageMs, staleTtlSeconds); }
    },
  };
}
