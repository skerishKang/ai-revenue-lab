/*  github-status-service.js  —  GitHub status service (PR #193 extended for Phase 2A)
 *
 *  PR #193 contract preserved:
 *    - fresh cache TTL ~180 seconds
 *    - stale retention ~86400 seconds
 *    - single-flight token exchange
 *    - single-flight status refresh
 *    - safe error normalization
 *    - no raw upstream error reflection
 */

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";
import { GitHubApiError } from "./github-client.js";
import { mergeBusinessFacts, createMergedPayload, SCHEMA_VERSION } from "./business-fact-merger.js";
import { safeError } from "./response.js";

const refreshFlights = new Map();

function iso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function safeDiagnostic(number, code, message) {
  return { businessNumber: number, code, message };
}

function errorPaths(errors) {
  return (errors || []).map((error) =>
    Array.isArray(error.path) ? error.path.map(String) : []
  );
}

function pathTouches(paths, alias) {
  return paths.some((path) => path.includes(alias));
}

function upstreamErrorResult(error, cached, ageMs, staleTtlSeconds) {
  const rateLimited = error instanceof GitHubApiError && error.code === "UPSTREAM_RATE_LIMITED";
  const code = rateLimited ? "UPSTREAM_RATE_LIMITED" : "UPSTREAM_UNAVAILABLE";
  const staleMessage = rateLimited
    ? "GitHub rate limits prevented refresh; showing the last successful snapshot."
    : "GitHub data could not be refreshed; showing the last successful snapshot.";
  if (cached && ageMs <= staleTtlSeconds * 1000) {
    return {
      payload: {
        ...cached.snapshot,
        ok: true,
        stale: true,
        errors: [...(cached.snapshot.errors || []), safeError(code, staleMessage)],
      },
      status: 200,
      cacheState: "stale",
    };
  }
  return {
    payload: {
      ok: false,
      schemaVersion: SCHEMA_VERSION,
      syncedAt: null,
      stale: false,
      error: safeError(
        code,
        rateLimited
          ? "GitHub rate limits are temporarily preventing synchronization."
          : "GitHub data is temporarily unavailable."
      ),
      businesses: [],
    },
    status: rateLimited ? 503 : 502,
    cacheState: "unavailable",
  };
}

export function createGitHubStatusService({
  client,
  cache,
  now = () => Date.now(),
  freshTtlSeconds = 180,
  staleTtlSeconds = 86400,
  singleFlightKey = GITHUB_REPOSITORY,
}) {
  async function loadFresh() {
    const aggregate = await client.getStatusAggregation(GITHUB_REPOSITORY);
    const root = aggregate?.data || {};
    const repositoryData = root.repository;
    if (!repositoryData) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);

    const paths = errorPaths(aggregate.errors);
    const phaseIssueResults = {};

    // Collect phase issue search results
    const phaseIssues = new Set();
    const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
    for (const m of mappedEntries) {
      if (m.uiPhaseIssue) phaseIssues.add(m.uiPhaseIssue);
      if (m.uxPhaseIssue) phaseIssues.add(m.uxPhaseIssue);
      if (m.bePhaseIssue) phaseIssues.add(m.bePhaseIssue);
    }
    for (const issueNum of phaseIssues) {
      phaseIssueResults[`prSearch${issueNum}`] = root[`prSearch${issueNum}`] || { nodes: [] };
    }

    // Merge facts for each mapped Business
    const businessFacts = mappedEntries.map((mapping) => {
      return mergeBusinessFacts({
        mapping,
        issueData: mapping.issueNumber ? repositoryData[`i${mapping.issueNumber}`] : null,
        phaseIssueResults,
        fallbackPrNode: mapping.fallbackPrNumber ? repositoryData[`fp${mapping.fallbackPrNumber}`] : null,
        repositoryData,
        paths,
      });
    });

    // Collect diagnostics
    const errors = [];
    for (const fact of businessFacts) {
      if (fact.error) {
        errors.push(safeDiagnostic(fact.number, fact.error.code, fact.error.message));
      }
    }
    if ((aggregate.errors || []).length && errors.length === 0) {
      errors.push(safeError("GRAPHQL_PARTIAL", "Some GitHub fields are unavailable."));
    }

    // Create merged payload
    const merged = createMergedPayload({
      businessFacts,
      repositoryData,
      syncedAt: new Date(now()).toISOString(),
      stale: false,
    });
    merged.errors = errors;

    return merged;
  }

  async function storeFreshSnapshot(snapshot) {
    let result;
    try {
      result = await cache.set(snapshot);
    } catch {
      result = { persisted: false, errorCode: "CACHE_WRITE_FAILED" };
    }
    if (result?.persisted !== false) return snapshot;
    const degraded = {
      ...snapshot,
      errors: [...(snapshot.errors || []), safeError("CACHE_WRITE_FAILED", "The latest GitHub snapshot could not be persisted.")],
    };
    if (typeof cache.setMemory === "function") cache.setMemory(degraded);
    return degraded;
  }

  async function refreshSingleFlight() {
    const existing = refreshFlights.get(singleFlightKey);
    if (existing) return existing;
    const flight = (async () => storeFreshSnapshot(await loadFresh()))();
    refreshFlights.set(singleFlightKey, flight);
    try {
      return await flight;
    } finally {
      if (refreshFlights.get(singleFlightKey) === flight) refreshFlights.delete(singleFlightKey);
    }
  }

  return {
    async getStatus() {
      const cached = await cache.get();
      const ageMs = cached ? now() - cached.storedAtMs : Number.POSITIVE_INFINITY;
      if (cached && ageMs <= freshTtlSeconds * 1000) {
        return { payload: { ...cached.snapshot, stale: false }, status: 200, cacheState: "fresh" };
      }
      try {
        const snapshot = await refreshSingleFlight();
        return { payload: snapshot, status: 200, cacheState: "miss" };
      } catch (error) {
        return upstreamErrorResult(error, cached, ageMs, staleTtlSeconds);
      }
    },
  };
}
