import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";
import { GitHubApiError, normalizeStatusCheckRollup } from "./github-client.js";
import { safeError } from "./response.js";

const SCHEMA_VERSION = 1;
const refreshFlights = new Map();

function iso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
function latestIso(...values) {
  const parsed = values.map((value) => Date.parse(value || "")).filter(Number.isFinite);
  return parsed.length ? new Date(Math.max(...parsed)).toISOString() : null;
}
function normalizeIssue(issue) {
  if (!issue) return null;
  return { number: Number(issue.number), title: String(issue.title || ""), state: String(issue.state || "").toLowerCase(),
    updatedAt: iso(issue.updatedAt), url: String(issue.url || "") };
}
function normalizePullRequest(pr) {
  if (!pr) return null;
  return { number: Number(pr.number), title: String(pr.title || ""), state: String(pr.state || "").toLowerCase(),
    draft: Boolean(pr.isDraft), merged: Boolean(pr.merged), headSha: String(pr.headRefOid || ""),
    baseRef: String(pr.baseRefName || ""), updatedAt: iso(pr.updatedAt), url: String(pr.url || "") };
}
function safeDiagnostic(number, code, message) { return { businessNumber: number, code, message }; }
function aliasFor(mapping, kind) { return `${kind}${kind === "issue" ? mapping.issueNumber : mapping.pullRequestNumber}`; }
function errorPaths(errors) { return (errors || []).map((error) => Array.isArray(error.path) ? error.path.map(String) : []); }
function pathTouches(paths, alias) { return paths.some((path) => path.includes(alias)); }
function pathTouchesChecks(paths, alias) {
  return paths.some((path) => path.includes(alias) && (path.includes("statusCheckRollup") || path.includes("commits")));
}
function unmappedBusiness(mapping) {
  return { number: mapping.number, connectionState: "unmapped", repository: null, issue: null, pullRequest: null,
    checks: { state: "unavailable", source: "none", total: 0, completed: 0 }, activityAt: null, error: null };
}
function normalizeBusiness(mapping, repositoryData, paths) {
  if (!mapping.repository) return { business: unmappedBusiness(mapping), diagnostics: [] };
  const diagnostics = [];
  const issueAlias = mapping.issueNumber ? aliasFor(mapping, "issue") : null;
  const prAlias = mapping.pullRequestNumber ? aliasFor(mapping, "pr") : null;
  const issueData = issueAlias ? repositoryData?.[issueAlias] : null;
  const prData = prAlias ? repositoryData?.[prAlias] : null;
  let issue = normalizeIssue(issueData);
  let pullRequest = normalizePullRequest(prData);
  let checks = { state: "unavailable", source: pullRequest ? "pr_head_rollup" : "none", total: 0, completed: 0 };

  if (issueAlias && (!issueData || pathTouches(paths, issueAlias))) {
    if (!issueData) issue = null;
    diagnostics.push(safeDiagnostic(mapping.number, "ISSUE_UNAVAILABLE", "Mapped Issue status is unavailable."));
  }
  if (prAlias && (!prData || (pathTouches(paths, prAlias) && !pathTouchesChecks(paths, prAlias)))) {
    if (!prData) pullRequest = null;
    diagnostics.push(safeDiagnostic(mapping.number, "PULL_REQUEST_UNAVAILABLE", "Mapped pull request status is unavailable."));
  }
  if (pullRequest) {
    const rollup = prData?.commits?.nodes?.[0]?.commit?.statusCheckRollup || null;
    if (pathTouchesChecks(paths, prAlias)) {
      diagnostics.push(safeDiagnostic(mapping.number, "CHECKS_UNAVAILABLE", "Checks are unavailable for the mapped pull request."));
    } else {
      checks = normalizeStatusCheckRollup(rollup);
    }
  }
  const connectionState = diagnostics.length ? "partial" : "connected";
  return {
    business: { number: mapping.number, connectionState, repository: mapping.repository, issue, pullRequest, checks,
      activityAt: latestIso(issue?.updatedAt, pullRequest?.updatedAt),
      error: diagnostics.length ? { code: diagnostics[0].code, message: diagnostics[0].message } : null },
    diagnostics
  };
}
function upstreamErrorResult(error, cached, ageMs, staleTtlSeconds) {
  const rateLimited = error instanceof GitHubApiError && error.code === "UPSTREAM_RATE_LIMITED";
  const code = rateLimited ? "UPSTREAM_RATE_LIMITED" : "UPSTREAM_UNAVAILABLE";
  const staleMessage = rateLimited
    ? "GitHub rate limits prevented refresh; showing the last successful snapshot."
    : "GitHub data could not be refreshed; showing the last successful snapshot.";
  if (cached && ageMs <= staleTtlSeconds * 1000) {
    return { payload: { ...cached.snapshot, ok: true, stale: true,
      errors: [...(cached.snapshot.errors || []), safeError(code, staleMessage)] }, status: 200, cacheState: "stale" };
  }
  return { payload: { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false,
    error: safeError(code, rateLimited ? "GitHub rate limits are temporarily preventing synchronization." : "GitHub data is temporarily unavailable."), businesses: [] },
    status: rateLimited ? 503 : 502, cacheState: "unavailable" };
}

export function createGitHubStatusService({ client, cache, now = () => Date.now(), freshTtlSeconds = 180, staleTtlSeconds = 86400,
  singleFlightKey = GITHUB_REPOSITORY }) {
  async function loadFresh() {
    const aggregate = await client.getStatusAggregation(GITHUB_REPOSITORY);
    const root = aggregate?.data || {};
    const repositoryData = root.repository;
    if (!repositoryData) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
    const paths = errorPaths(aggregate.errors);
    const businessResults = BUSINESS_GITHUB_MAP.map((mapping) => normalizeBusiness(mapping, repositoryData, paths));
    const errors = businessResults.flatMap((result) => result.diagnostics);
    if ((aggregate.errors || []).length && errors.length === 0) {
      errors.push(safeError("GRAPHQL_PARTIAL", "Some GitHub fields are unavailable."));
    }
    const branch = repositoryData.defaultBranchRef;
    const commit = branch?.target || {};
    return { ok: true, schemaVersion: SCHEMA_VERSION, syncedAt: new Date(now()).toISOString(), stale: false,
      repository: { fullName: String(repositoryData.nameWithOwner || GITHUB_REPOSITORY), url: String(repositoryData.url || `https://github.com/${GITHUB_REPOSITORY}`),
        defaultBranch: String(branch?.name || "main"), latestSha: String(commit.oid || ""),
        latestCommitTitle: String(commit.messageHeadline || ""), latestCommitAt: iso(commit.committedDate) },
      summary: { openIssues: Number(repositoryData.issues?.totalCount || 0),
        openPullRequests: Number(repositoryData.pullRequests?.totalCount || 0),
        draftPullRequests: Number(root.draftPullRequests?.issueCount || 0) },
      businesses: businessResults.map((result) => result.business), errors };
  }
  async function storeFreshSnapshot(snapshot) {
    let result;
    try {
      result = await cache.set(snapshot);
    } catch {
      result = { persisted: false, errorCode: "CACHE_WRITE_FAILED" };
    }
    if (result?.persisted !== false) return snapshot;
    const degraded = { ...snapshot,
      errors: [...(snapshot.errors || []), safeError("CACHE_WRITE_FAILED", "The latest GitHub snapshot could not be persisted.")] };
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
  return { async getStatus() {
    const cached = await cache.get();
    const ageMs = cached ? now() - cached.storedAtMs : Number.POSITIVE_INFINITY;
    if (cached && ageMs <= freshTtlSeconds * 1000) {
      return { payload: { ...cached.snapshot, stale: false }, status: 200, cacheState: "fresh" };
    }
    try {
      const snapshot = await refreshSingleFlight();
      return { payload: snapshot, status: 200, cacheState: "miss" };
    } catch (error) { return upstreamErrorResult(error, cached, ageMs, staleTtlSeconds); }
  } };
}
