/*  github-client.js  —  GitHub GraphQL client (PR #193 extended for Phase 2A)
 *
 *  Extended to use the dynamic query builder for 55 Business mapping.
 *
 *  PR #193 contract preserved:
 *    - single-flight token exchange
 *    - single-flight status refresh
 *    - explicit GraphQL pagination
 *    - safe error normalization
 *    - no raw upstream error reflection
 *    - fixed repository allowlist
 */

import { GITHUB_REPOSITORY, BUSINESS_GITHUB_MAP, assertAllowedRepository } from "./business-github-map.js";
import { buildStatusQuery, getRequestBudget } from "./business-github-query.js";
import { safeError } from "./response.js";

/* Re-export STATUS_QUERY for test backward compatibility (PR #193 contract) */
export const STATUS_QUERY = buildStatusQuery({ prSearchLimit: 10 });

const API_BASE = "https://api.github.com";
const GRAPHQL_URL = `${API_BASE}/graphql`;
const API_VERSION = "2026-03-10";
const ACCEPT = "application/vnd.github+json";
const USER_AGENT = "ai-revenue-portfolio-console";

export class GitHubApiError extends Error {
  constructor(code, status, message = "GitHub data is temporarily unavailable.", details = {}) {
    super(message);
    this.name = "GitHubApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function rateLimitDetails(response) {
  return {
    retryAfter: response.headers.get("Retry-After") || null,
    resetAtEpochSeconds: response.headers.get("X-RateLimit-Reset") || null,
  };
}

function isRateLimitedResponse(response) {
  return response.status === 429 || response.status === 403 || response.headers.get("X-RateLimit-Remaining") === "0";
}

function safeGraphQLErrors(errors) {
  return Array.isArray(errors)
    ? errors.map((error) => ({
        path: Array.isArray(error?.path) ? error.path.filter((part) => typeof part === "string" || Number.isInteger(part)) : [],
        type: typeof error?.type === "string" ? error.type : null,
      }))
    : [];
}

function graphQlRateLimited(errors) {
  return Array.isArray(errors) && errors.some((error) => /rate.?limit|abuse|secondary/i.test(String(error?.message || "")));
}

export function normalizeStatusCheckRollup(rollup) {
  if (!rollup) return { state: "unavailable", source: "pr_head_rollup", total: 0, completed: 0 };
  const contexts = Array.isArray(rollup?.contexts?.nodes) ? rollup.contexts.nodes : [];
  const reportedTotal = Number(rollup?.contexts?.totalCount);
  const total = Number.isFinite(reportedTotal) && reportedTotal >= 0 ? Math.floor(reportedTotal) : contexts.length;
  const aggregateState = String(rollup.state || "").toUpperCase();
  const normalizedState =
    aggregateState === "SUCCESS" ? "pass"
    : aggregateState === "FAILURE" || aggregateState === "ERROR" ? "fail"
    : aggregateState === "PENDING" || aggregateState === "EXPECTED" ? "pending"
    : "unavailable";
  const terminalStatusStates = new Set(["SUCCESS", "FAILURE", "ERROR"]);
  let completed = 0;
  for (const context of contexts) {
    const typename = String(context?.__typename || "");
    if (typename === "CheckRun") {
      if (String(context?.status || "").toUpperCase() === "COMPLETED") completed += 1;
    } else if (typename === "StatusContext") {
      if (terminalStatusStates.has(String(context?.state || "").toUpperCase())) completed += 1;
    }
  }
  const result = { state: normalizedState, source: "pr_head_rollup", total, completed };
  if (total > contexts.length) result.truncated = true;
  return result;
}

export class GitHubClient {
  constructor({ authProvider, fetchImpl = fetch }) {
    this.authProvider = authProvider;
    this.fetchImpl = fetchImpl;
  }

  async graphql(repository, { retryAuth = true } = {}) {
    assertAllowedRepository(repository);
    const [owner, name] = repository.split("/");
    const token = await this.authProvider.getToken();

    // Build the Phase 2A query dynamically
    const query = buildStatusQuery({ prSearchLimit: 10 });

    const response = await this.fetchImpl(GRAPHQL_URL, {
      method: "POST",
      headers: {
        Accept: ACCEPT,
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
      },
      body: JSON.stringify({ query, variables: { owner, name } }),
    });

    if (response.status === 401 && retryAuth) {
      this.authProvider.invalidate();
      await this.authProvider.getToken({ forceRefresh: true });
      return this.graphql(repository, { retryAuth: false });
    }

    if (response.status === 401) {
      throw new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", response.status);
    }

    if (isRateLimitedResponse(response)) {
      throw new GitHubApiError(
        "UPSTREAM_RATE_LIMITED",
        response.status,
        "GitHub rate limit is temporarily preventing synchronization.",
        rateLimitDetails(response)
      );
    }

    if (!response.ok) throw new GitHubApiError("GITHUB_REQUEST_FAILED", response.status);

    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new GitHubApiError("GITHUB_RESPONSE_INVALID", 502);
    }

    if (graphQlRateLimited(payload?.errors)) {
      throw new GitHubApiError(
        "UPSTREAM_RATE_LIMITED",
        403,
        "GitHub rate limit is temporarily preventing synchronization."
      );
    }

    if (!payload?.data) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);

    return { data: payload.data, errors: safeGraphQLErrors(payload.errors) };
  }

  getStatusAggregation(repository = GITHUB_REPOSITORY) {
    return this.graphql(repository);
  }

  /** Return the Phase 2A request budget for documentation/testing */
  getRequestBudget() {
    return getRequestBudget();
  }
}
