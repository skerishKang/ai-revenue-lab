import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY, assertAllowedRepository } from "./business-github-map.js";

const API_BASE = "https://api.github.com";
const GRAPHQL_URL = `${API_BASE}/graphql`;
const API_VERSION = "2026-03-10";
const ACCEPT = "application/vnd.github+json";
const USER_AGENT = "ai-revenue-portfolio-console";

export class GitHubApiError extends Error {
  constructor(code, status, message = "GitHub data is temporarily unavailable.", details = {}) {
    super(message); this.name = "GitHubApiError"; this.code = code; this.status = status; this.details = details;
  }
}

function issueSelection(mapping) {
  return `issue${mapping.issueNumber}: issue(number: ${mapping.issueNumber}) { number title state updatedAt url }`;
}
function pullRequestSelection(mapping) {
  return `pr${mapping.pullRequestNumber}: pullRequest(number: ${mapping.pullRequestNumber}) {
    number title state isDraft merged headRefOid baseRefName updatedAt url
    commits(last: 1) { nodes { commit { statusCheckRollup {
      state contexts(first: 100) { totalCount nodes {
        __typename
        ... on CheckRun { status conclusion }
        ... on StatusContext { state }
      } }
    } } } }
  }`;
}
const mapped = BUSINESS_GITHUB_MAP.filter((item) => item.repository === GITHUB_REPOSITORY);
export const STATUS_QUERY = `query PortfolioGithubStatus($owner: String!, $name: String!, $draftQuery: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner url
    defaultBranchRef { name target { ... on Commit { oid messageHeadline committedDate } } }
    issues(states: OPEN) { totalCount }
    pullRequests(states: OPEN) { totalCount }
    ${mapped.filter((item) => item.issueNumber).map(issueSelection).join("\n    ")}
    ${mapped.filter((item) => item.pullRequestNumber).map(pullRequestSelection).join("\n    ")}
  }
  draftPullRequests: search(query: $draftQuery, type: ISSUE, first: 1) { issueCount }
}`;

function rateLimitDetails(response) {
  return {
    retryAfter: response.headers.get("Retry-After") || null,
    resetAtEpochSeconds: response.headers.get("X-RateLimit-Reset") || null
  };
}
function isRateLimitedResponse(response) {
  return response.status === 429 || response.status === 403 || response.headers.get("X-RateLimit-Remaining") === "0";
}
function safeGraphQLErrors(errors) {
  return Array.isArray(errors) ? errors.map((error) => ({
    path: Array.isArray(error?.path) ? error.path.filter((part) => typeof part === "string" || Number.isInteger(part)) : [],
    type: typeof error?.type === "string" ? error.type : null
  })) : [];
}
function graphQlRateLimited(errors) {
  return Array.isArray(errors) && errors.some((error) => /rate.?limit|abuse|secondary/i.test(String(error?.message || "")));
}

export function normalizeStatusCheckRollup(rollup) {
  const contexts = rollup?.contexts?.nodes;
  if (!rollup || !Array.isArray(contexts) || contexts.length === 0) {
    return { state: "unavailable", source: "pr_head", total: 0, completed: 0 };
  }
  const failures = new Set(["FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"]);
  const success = new Set(["SUCCESS", "NEUTRAL", "SKIPPED"]);
  let failed = false; let pending = false; let completed = 0;
  for (const context of contexts) {
    const typename = String(context?.__typename || "");
    if (typename === "CheckRun") {
      const status = String(context?.status || "").toUpperCase();
      const conclusion = String(context?.conclusion || "").toUpperCase();
      if (status !== "COMPLETED") pending = true;
      else { completed += 1; if (failures.has(conclusion)) failed = true; else if (!success.has(conclusion)) pending = true; }
    } else if (typename === "StatusContext") {
      const state = String(context?.state || "").toUpperCase();
      if (failures.has(state)) { failed = true; completed += 1; }
      else if (state === "SUCCESS") completed += 1;
      else pending = true;
    } else pending = true;
  }
  return { state: failed ? "fail" : pending ? "pending" : "pass", source: "pr_head", total: contexts.length, completed };
}

export class GitHubClient {
  constructor({ authProvider, fetchImpl = fetch }) { this.authProvider = authProvider; this.fetchImpl = fetchImpl; }
  async graphql(repository, { retryAuth = true } = {}) {
    assertAllowedRepository(repository);
    const [owner, name] = repository.split("/");
    const token = await this.authProvider.getToken();
    const response = await this.fetchImpl(GRAPHQL_URL, {
      method: "POST",
      headers: { Accept: ACCEPT, Authorization: `Bearer ${token}`, "Content-Type": "application/json",
        "X-GitHub-Api-Version": API_VERSION, "User-Agent": USER_AGENT },
      body: JSON.stringify({ query: STATUS_QUERY, variables: { owner, name, draftQuery: `repo:${repository} is:pr is:open is:draft` } })
    });
    if (response.status === 401 && retryAuth) {
      this.authProvider.invalidate();
      await this.authProvider.getToken({ forceRefresh: true });
      return this.graphql(repository, { retryAuth: false });
    }
    if (isRateLimitedResponse(response)) {
      throw new GitHubApiError("UPSTREAM_RATE_LIMITED", response.status, "GitHub rate limit is temporarily preventing synchronization.", rateLimitDetails(response));
    }
    if (!response.ok) throw new GitHubApiError("GITHUB_REQUEST_FAILED", response.status);
    let payload;
    try { payload = await response.json(); } catch { throw new GitHubApiError("GITHUB_RESPONSE_INVALID", 502); }
    if (graphQlRateLimited(payload?.errors)) {
      throw new GitHubApiError("UPSTREAM_RATE_LIMITED", 403, "GitHub rate limit is temporarily preventing synchronization.");
    }
    if (!payload?.data) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
    return { data: payload.data, errors: safeGraphQLErrors(payload.errors) };
  }
  getStatusAggregation(repository = GITHUB_REPOSITORY) { return this.graphql(repository); }
}
