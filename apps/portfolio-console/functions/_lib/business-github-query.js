/*  business-github-query.js  —  deterministic batched GraphQL query builder
 *
 *  The original single-operation query grew large enough (164 discovery search
 *  aliases, each returning PR nodes with full check rollups) that GitHub's
 *  GraphQL gateway returned HTTP 504 reproducibly (3/3, ~10.7s). This module
 *  splits the work into:
 *
 *    A. one CORE operation — repository identity, default branch/latest commit,
 *       open Issue/PR counts, draft PR count, direct Issue aliases and explicit
 *       fallback PR aliases; and
 *    B. DISCOVERY operations — the Refs / Related-to / structured-marker /
 *       branch-convention search aliases, partitioned into fixed-size
 *       deterministic batches.
 *
 *  Unified alias contract (unchanged, preserved after merge):
 *    issue{N}                        — product-decision or phase Issue
 *    prSearchRefs{N}                 — bounded PR search for `"Refs #N"`
 *    prSearchRelated{N}              — bounded PR search for `"Related to #N"`
 *    prSearchMarker{B}_{phase}       — bounded PR search for the structured marker
 *    prSearchConvention{B}_{phase}   — bounded PR search for `head:business-B-P`
 *    fallbackPr{N}                   — explicit phase-scoped fallback PR
 *
 *  After the client merges the core result with every discovery batch, the
 *  resulting `data` object is byte-for-byte the same logical shape the service
 *  already consumes (root.repository, root[alias], root.draftPullRequests).
 */

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";

const SEARCH_PR_QUERY_PREFIX = `repo:${GITHUB_REPOSITORY} type:pr`;

const PHASES = Object.freeze(["ui", "ux", "backend"]);
const PHASE_ISSUE_KEYS = Object.freeze({ ui: "uiPhaseIssue", ux: "uxPhaseIssue", backend: "bePhaseIssue" });

/* Evidence-based batching constants (see benchmark in PR #342). Each discovery
 * batch carries at most GRAPHQL_BATCH_SIZE search aliases; batches run with at
 * most GRAPHQL_BATCH_CONCURRENCY in flight. Both are injectable for tests. */
export const GRAPHQL_BATCH_SIZE = 25;
export const GRAPHQL_BATCH_CONCURRENCY = 3;

function esc(val) { return JSON.stringify(val); }

function mappedEntries() {
  return BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
}

/* PR field selection shared by search aliases and fallback PRs (with CI rollup). */
const PR_FIELDS = `number title state isDraft merged headRefOid headRefName baseRefOid baseRefName updatedAt url body
        commits(last: 1) { nodes { commit { statusCheckRollup {
          state contexts(first: 100) { totalCount nodes {
            __typename
            ... on CheckRun { status conclusion name }
            ... on StatusContext { state context }
          } }
        } } } }`;

function searchSelection(alias, expression, limit) {
  return `  ${alias}: search(
    query: ${esc(`${SEARCH_PR_QUERY_PREFIX} ${expression}`)}
    type: ISSUE
    first: ${limit}
  ) {
    issueCount
    nodes {
      ... on PullRequest {
        ${PR_FIELDS}
      }
    }
  }`;
}

function allIssueNumbers() {
  const set = new Set();
  for (const m of mappedEntries()) {
    if (m.issueNumber) set.add(m.issueNumber);
    if (m.uiPhaseIssue) set.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) set.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) set.add(m.bePhaseIssue);
  }
  return [...set].sort((a, b) => a - b);
}

function phaseIssueNumbers() {
  const set = new Set();
  for (const m of mappedEntries()) {
    if (m.uiPhaseIssue) set.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) set.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) set.add(m.bePhaseIssue);
  }
  return [...set].sort((a, b) => a - b);
}

/**
 * Build the CORE operation: repository identity/counts, direct Issue aliases,
 * explicit fallback PR aliases, and the draft PR count. Uses $owner/$name.
 */
export function buildCoreQuery() {
  const issueSelections = allIssueNumbers()
    .map((n) => `  issue${n}: issue(number: ${n}) {
    number title state stateReason updatedAt url body
  }`)
    .join("\n");

  const fallbackPrSelections = getFallbackPrNumbers()
    .map((n) => `  fallbackPr${n}: pullRequest(number: ${n}) {
    ${PR_FIELDS}
  }`)
    .join("\n");

  const draftQuery = `repo:${GITHUB_REPOSITORY} is:pr is:open is:draft`;

  return `query PortfolioAutoSyncCore($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner url
    defaultBranchRef { name target { ... on Commit { oid messageHeadline committedDate } } }
    issues(first: 1, states: OPEN) { totalCount }
    pullRequests(first: 1, states: OPEN) { totalCount }
${issueSelections}
${fallbackPrSelections}
  }
  draftPullRequests: search(query: ${esc(draftQuery)}, type: ISSUE, first: 1) { issueCount }
}`;
}

/**
 * Build the ordered, de-duplicated list of discovery search alias specs.
 * Order is deterministic: Refs/Related-to by ascending phase Issue number, then
 * marker/convention by (Business number, phase). Returns [{ alias, selection }].
 */
export function buildDiscoveryAliasSelections(opts = {}) {
  const { prSearchLimit = 10, prPrecisionLimit = 5 } = opts;
  const selections = [];
  const seen = new Set();
  const push = (alias, selection) => {
    if (seen.has(alias)) throw new Error(`duplicate discovery alias: ${alias}`);
    seen.add(alias);
    selections.push({ alias, selection });
  };

  for (const n of phaseIssueNumbers()) {
    push(`prSearchRefs${n}`, searchSelection(`prSearchRefs${n}`, `"Refs #${n}"`, prSearchLimit));
    push(`prSearchRelated${n}`, searchSelection(`prSearchRelated${n}`, `"Related to #${n}"`, prSearchLimit));
  }
  for (const m of mappedEntries()) {
    for (const phase of PHASES) {
      if (!m[PHASE_ISSUE_KEYS[phase]]) continue;
      push(`prSearchMarker${m.number}_${phase}`, searchSelection(`prSearchMarker${m.number}_${phase}`, `"business: ${m.number}" "phase: ${phase}"`, prPrecisionLimit));
      push(`prSearchConvention${m.number}_${phase}`, searchSelection(`prSearchConvention${m.number}_${phase}`, `head:business-${m.number}-${phase}`, prPrecisionLimit));
    }
  }
  return selections;
}

/**
 * Build one DISCOVERY operation from a batch of alias specs. Discovery aliases
 * are self-contained search expressions, so the operation declares no variables.
 */
export function buildDiscoveryBatchQuery(batchSelections, batchIndex = 0) {
  const body = batchSelections.map((s) => s.selection).join("\n");
  return `query PortfolioAutoSyncDiscovery${batchIndex} {
${body}
}`;
}

/** Partition alias specs into fixed-size deterministic batches. */
export function partitionDiscoverySelections(selections, batchSize = GRAPHQL_BATCH_SIZE) {
  if (!Number.isInteger(batchSize) || batchSize <= 0) throw new Error("batchSize must be a positive integer");
  const batches = [];
  for (let i = 0; i < selections.length; i += batchSize) batches.push(selections.slice(i, i + batchSize));
  return batches;
}

/**
 * Static, evidence-based request plan. Tests assert these bounds so the refresh
 * can never issue an unbounded number of GraphQL operations.
 */
export function getBatchPlan(opts = {}) {
  const batchSize = opts.batchSize || GRAPHQL_BATCH_SIZE;
  const concurrency = opts.concurrency || GRAPHQL_BATCH_CONCURRENCY;
  const selections = buildDiscoveryAliasSelections(opts);
  const discoveryBatchCount = Math.ceil(selections.length / batchSize);
  const maxGraphqlRequests = 1 + discoveryBatchCount;
  return {
    batchSize,
    concurrency,
    coreRequests: 1,
    discoveryAliasCount: selections.length,
    discoveryBatchCount,
    maxGraphqlRequests,
  };
}

/** Get all unique Issue numbers that will be queried */
export function getAllIssueNumbers() {
  return allIssueNumbers();
}

/** Get all phase Issue numbers that need PR discovery */
export function getPhaseIssueNumbers() {
  return phaseIssueNumbers();
}

/** Get all phase-scoped fallback PR numbers (deduped across phases) */
export function getFallbackPrNumbers() {
  const prs = new Set();
  for (const m of mappedEntries()) {
    const nums = m.fallbackPrNumbers;
    if (!nums) continue;
    for (const phase of PHASES) if (nums[phase]) prs.add(nums[phase]);
  }
  return [...prs].sort((a, b) => a - b);
}

/**
 * GraphQL aliases carrying the bounded dual PR search for one phase Issue.
 * Order matters: Refs results are merged before Related-to results.
 */
export function getPrSearchAliases(issueNum) {
  return [`prSearchRefs${issueNum}`, `prSearchRelated${issueNum}`];
}

/**
 * Ordered candidate-pool specs for one (Business, phase) pair, in discovery
 * priority order: marker → refs → related → convention.
 */
export function getDiscoveryPoolSpecs(mapping, phase) {
  const issueNum = mapping[PHASE_ISSUE_KEYS[phase]];
  if (!issueNum) return [];
  return [
    { pool: "marker", alias: `prSearchMarker${mapping.number}_${phase}` },
    { pool: "refs", alias: `prSearchRefs${issueNum}` },
    { pool: "related", alias: `prSearchRelated${issueNum}` },
    { pool: "convention", alias: `prSearchConvention${mapping.number}_${phase}` },
  ];
}

/**
 * Static request/node budget for the batched refresh.
 */
export function getQueryBudget(opts = {}) {
  const { prSearchLimit = 10, prPrecisionLimit = 5 } = opts;
  const plan = getBatchPlan(opts);
  const phaseIssues = phaseIssueNumbers().length;
  let phasePairs = 0;
  for (const m of mappedEntries()) for (const phase of PHASES) if (m[PHASE_ISSUE_KEYS[phase]]) phasePairs += 1;
  const refRelatedAliases = phaseIssues * 2;
  const precisionAliases = phasePairs * 2;
  return {
    coreRequests: 1,
    discoveryBatchCount: plan.discoveryBatchCount,
    maxGraphqlRequests: plan.maxGraphqlRequests,
    batchSize: plan.batchSize,
    concurrency: plan.concurrency,
    issueAliases: allIssueNumbers().length,
    fallbackAliases: getFallbackPrNumbers().length,
    searchAliases: refRelatedAliases + precisionAliases + 1, // +1 = draft count (core)
    discoverySearchAliases: refRelatedAliases + precisionAliases,
    searchNodeBudget: refRelatedAliases * prSearchLimit + precisionAliases * prPrecisionLimit + 1,
  };
}

/**
 * Request budget for the batched refresh:
 *   cold        = 1 token exchange + core + discovery batches
 *   cachedToken = core + discovery batches
 *   worstCase   = 2 token exchanges + every operation attempted twice (one 401 refresh)
 */
export function getRequestBudget(opts = {}) {
  const plan = getBatchPlan(opts);
  return {
    cold: 1 + plan.maxGraphqlRequests,
    cachedToken: plan.maxGraphqlRequests,
    worstCase: 2 + 2 * plan.maxGraphqlRequests,
    maxTokenExchanges: 2,
    maxGraphqlRequests: plan.maxGraphqlRequests,
  };
}
