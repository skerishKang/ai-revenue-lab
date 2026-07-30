/*  github-client.js  —  GitHub GraphQL client (deterministic batched refresh)
 *
 *  The status refresh is split into one CORE operation plus a fixed number of
 *  DISCOVERY batches (see business-github-query.js). Evidence: the previous
 *  single operation returned HTTP 504 reproducibly (3/3, ~10.7s). Batching each
 *  discovery slice well under the per-operation deadline restores live sync.
 *
 *  Execution contract:
 *    - deterministic batch order; results merged by batch index
 *    - fixed maximum batch count (getBatchPlan)
 *    - bounded concurrency (exactly `concurrency` workers, never one per batch)
 *    - installation token reused across the whole refresh
 *    - at most ONE 401 token refresh per full refresh
 *    - no per-batch retry loop; a timeout/transport/5xx failure aborts the refresh
 *    - any failed or partial batch ⇒ no fresh payload (throw ⇒ stale/normalized)
 *    - duplicate or missing discovery alias ⇒ fail safe (no fresh payload)
 *    - merged `data` preserves the existing logical GraphQL shape
 *    - HTTP 504 ⇒ GITHUB_GRAPHQL_TIMEOUT; other non-OK ⇒ safe request-failure
 */

import { GITHUB_REPOSITORY, assertAllowedRepository } from "./business-github-map.js";
import {
  buildCoreQuery, buildDiscoveryAliasSelections, buildDiscoveryBatchQuery,
  partitionDiscoverySelections, getRequestBudget,
  GRAPHQL_BATCH_SIZE, GRAPHQL_BATCH_CONCURRENCY,
} from "./business-github-query.js";
import { bindFetchImpl } from "./runtime-fetch.js";
import { OUTBOUND_DEADLINES, OutboundTimeoutError, createDeadlineRunner } from "./outbound-deadline.js";

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
  constructor({
    authProvider, fetchImpl = fetch, timeouts = OUTBOUND_DEADLINES, timers,
    AbortControllerImpl = AbortController, stageLogger = null,
    batchSize = GRAPHQL_BATCH_SIZE, concurrency = GRAPHQL_BATCH_CONCURRENCY,
  }) {
    this.authProvider = authProvider;
    this.fetchImpl = bindFetchImpl(fetchImpl);
    this.timeouts = timeouts;
    this.deadlines = createDeadlineRunner(timers);
    this.AbortControllerImpl = AbortControllerImpl;
    this.stageLogger = stageLogger;
    this.batchSize = batchSize;
    this.concurrency = concurrency;
  }

  /* Send ONE GraphQL operation and classify the response. Returns
   * { data, errors } on success, or { unauthorized: true } for HTTP 401 so the
   * caller can coordinate the single shared token refresh. Throws on timeout,
   * transport failure, rate-limit, 504, other non-OK, or invalid/partial body. */
  async #sendOperation(query, variables, token) {
    const logStage = this.stageLogger;
    const startedAt = Date.now();

    let response;
    try {
      response = await this.deadlines.fetchWithDeadline(
        this.fetchImpl,
        GRAPHQL_URL,
        {
          method: "POST",
          headers: {
            Accept: ACCEPT,
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
          },
          body: JSON.stringify(variables ? { query, variables } : { query }),
        },
        this.timeouts.graphqlRequestMs,
        "graphql-request",
        this.AbortControllerImpl
      );
    } catch (error) {
      if (error instanceof OutboundTimeoutError) {
        if (logStage) logStage("graphql", "timeout", startedAt);
        throw new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
      }
      if (logStage) logStage("graphql", "error", startedAt);
      throw new GitHubApiError("GITHUB_GRAPHQL_TRANSPORT_FAILED", 502);
    }

    if (response.status === 401) return { unauthorized: true };

    if (isRateLimitedResponse(response)) {
      if (logStage) logStage("graphql", "error", startedAt);
      throw new GitHubApiError(
        "UPSTREAM_RATE_LIMITED",
        response.status,
        "GitHub rate limit is temporarily preventing synchronization.",
        rateLimitDetails(response)
      );
    }

    // HTTP 504 is an upstream gateway timeout: classify explicitly as a GraphQL
    // timeout. Any other non-OK status keeps the safe request-failure contract.
    if (response.status === 504) {
      if (logStage) logStage("graphql", "timeout", startedAt);
      throw new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
    }

    if (!response.ok) {
      if (logStage) logStage("graphql", "error", startedAt);
      throw new GitHubApiError("GITHUB_REQUEST_FAILED", response.status);
    }

    let payload;
    try {
      payload = await this.deadlines.readJsonWithDeadline(response, this.timeouts.graphqlBodyMs, "graphql-body");
    } catch (error) {
      if (error instanceof OutboundTimeoutError) {
        if (logStage) logStage("graphql", "timeout", startedAt);
        throw new GitHubApiError("GITHUB_GRAPHQL_TIMEOUT", 504);
      }
      if (logStage) logStage("graphql", "error", startedAt);
      throw new GitHubApiError("GITHUB_RESPONSE_INVALID", 502);
    }

    if (graphQlRateLimited(payload?.errors)) {
      if (logStage) logStage("graphql", "error", startedAt);
      throw new GitHubApiError(
        "UPSTREAM_RATE_LIMITED",
        403,
        "GitHub rate limit is temporarily preventing synchronization."
      );
    }

    if (!payload?.data) {
      if (logStage) logStage("graphql", "error", startedAt);
      throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
    }

    if (logStage) logStage("graphql", "success", startedAt);
    return { data: payload.data, errors: safeGraphQLErrors(payload.errors) };
  }

  /* Run the discovery batches with bounded concurrency: exactly `concurrency`
   * workers pull from a shared index, so the number of in-flight operations is
   * capped and never scales with the batch count. Results are stored by batch
   * index to keep merge order deterministic. */
  async #runDiscoveryBatches(batches, runOperation) {
    const results = new Array(batches.length);
    let next = 0;
    const limit = Math.max(1, Math.min(this.concurrency, batches.length));
    const workers = Array.from({ length: limit }, async () => {
      while (next < batches.length) {
        const index = next;
        next += 1;
        results[index] = await runOperation(buildDiscoveryBatchQuery(batches[index], index), undefined);
      }
    });
    await Promise.all(workers);
    return results;
  }

  /* Merge the core result with every discovery batch into the single logical
   * GraphQL data shape the service consumes, failing safe on any duplicate or
   * missing discovery alias (partial data is never reported as fresh). */
  #mergeResults(core, batchResults, selections) {
    const merged = { ...core.data };
    const errors = [...core.errors];
    const seen = new Set();
    for (const result of batchResults) {
      for (const key of Object.keys(result.data)) {
        if (seen.has(key)) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
        seen.add(key);
        merged[key] = result.data[key];
      }
      errors.push(...result.errors);
    }
    if (!merged.repository) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
    for (const spec of selections) {
      if (!(spec.alias in merged)) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
    }
    return { data: merged, errors };
  }

  async getStatusAggregation(repository = GITHUB_REPOSITORY) {
    assertAllowedRepository(repository);
    const [owner, name] = repository.split("/");

    // Shared 401-refresh coordinator: at most ONE token refresh per full refresh.
    // Concurrent 401s share the single in-flight exchange; any 401 observed after
    // the refresh has completed fails fast instead of refreshing again.
    const refresh = { done: false, promise: null };
    const refreshOnce = async () => {
      if (refresh.done) return false;
      if (!refresh.promise) {
        refresh.promise = (async () => {
          this.authProvider.invalidate();
          await this.authProvider.getToken({ forceRefresh: true });
          refresh.done = true;
        })();
      }
      await refresh.promise;
      return true;
    };

    // One operation with a single 401 retry gated by refreshOnce (no retry loop).
    const runOperation = async (query, variables) => {
      let token = await this.authProvider.getToken();
      let result = await this.#sendOperation(query, variables, token);
      if (result.unauthorized) {
        const didRefresh = await refreshOnce();
        if (!didRefresh) throw new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", 401);
        token = await this.authProvider.getToken();
        result = await this.#sendOperation(query, variables, token);
        if (result.unauthorized) throw new GitHubApiError("GITHUB_GRAPHQL_AUTH_FAILED", 401);
      }
      return result;
    };

    const core = await runOperation(buildCoreQuery(), { owner, name });

    const selections = buildDiscoveryAliasSelections();
    const batches = partitionDiscoverySelections(selections, this.batchSize);
    const batchResults = await this.#runDiscoveryBatches(batches, runOperation);

    return this.#mergeResults(core, batchResults, selections);
  }

  /** Return the batched request budget for documentation/testing */
  getRequestBudget() {
    return getRequestBudget();
  }
}
