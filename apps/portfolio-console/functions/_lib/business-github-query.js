/*  business-github-query.js  —  unified GraphQL query builder (Phase 2A)
 *
 *  Builds a single bounded GraphQL query for 55 mapped Businesses.
 *  Unified alias contract:
 *    issue{N}                        — product-decision or phase Issue
 *    prSearchRefs{N}                 — bounded PR search for `"Refs #N"` (phase Issue N)
 *    prSearchRelated{N}              — bounded PR search for `"Related to #N"` (phase Issue N)
 *    prSearchMarker{B}_{phase}       — bounded PR search for the structured
 *                                      marker phrases `"business: B" "phase: P"`
 *    prSearchConvention{B}_{phase}   — bounded PR search for the branch
 *                                      convention `head:business-B-P`
 *    fallbackPr{N}                   — explicit phase-scoped fallback PR (with check rollup)
 *
 *  All four candidate sources per (Business, phase) pair are issued as bounded
 *  aliases inside the SAME single GraphQL request. The service merges the four
 *  pools per (Business, phase), deduplicates by PR number in discovery-priority
 *  order (marker → refs → related → convention) and flags truncation per pool.
 *
 *  Recall vs. authority:
 *    - Search aliases are RECALL nets only. Exact Business/phase binding is
 *      enforced later by business-pr-discovery.js (structured-marker parse and
 *      whole-word convention regex), so search-level substring overlap (e.g.
 *      `business-1` vs `business-11`) can never authorize a wrong PR.
 *    - The convention alias recalls the head-branch convention
 *      `business-{B}-{phase}`. The title convention `{phase}-{issueNumber}` is
 *      matched only inside pools already recalled by other aliases.
 *    - label-based and timeline-based discovery are NOT implemented in Phase 2A.
 *
 *  PR #193 contract:
 *    - single-flight aggregation
 *    - bounded GraphQL request count (exactly 1 operation)
 *    - no unbounded Issue/PR history
 *    - explicit pagination (`first:`) on every search alias
 */

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";

const SEARCH_PR_QUERY_PREFIX = `repo:${GITHUB_REPOSITORY} type:pr`;

const PHASES = Object.freeze(["ui", "ux", "backend"]);
const PHASE_ISSUE_KEYS = Object.freeze({ ui: "uiPhaseIssue", ux: "uxPhaseIssue", backend: "bePhaseIssue" });

function esc(val) { return JSON.stringify(val); }

function mappedEntries() {
  return BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
}

/**
 * Build the complete GraphQL query for all mapped Businesses.
 * @param {object} [opts]
 * @param {number} [opts.prSearchLimit=10]    - page size for Refs/Related-to searches
 * @param {number} [opts.prPrecisionLimit=5]  - page size for marker/convention searches
 * @returns {string}
 */
export function buildStatusQuery(opts = {}) {
  const { prSearchLimit = 10, prPrecisionLimit = 5 } = opts;

  const mapped = mappedEntries();

  // ── Collect ALL unique Issue numbers for querying ──
  const allIssueNumbers = new Set();
  for (const m of mapped) {
    if (m.issueNumber) allIssueNumbers.add(m.issueNumber);
    if (m.uiPhaseIssue) allIssueNumbers.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) allIssueNumbers.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) allIssueNumbers.add(m.bePhaseIssue);
  }

  const issueSelections = [...allIssueNumbers]
    .sort((a, b) => a - b)
    .map((n) => `  issue${n}: issue(number: ${n}) {
    number title state stateReason updatedAt url body
  }`)
    .join("\n");

  // PR field selection shared by search aliases and fallback PRs (with CI/check rollup)
  const PR_FIELDS = `number title state isDraft merged headRefOid headRefName baseRefOid baseRefName updatedAt url body
        commits(last: 1) { nodes { commit { statusCheckRollup {
          state contexts(first: 100) { totalCount nodes {
            __typename
            ... on CheckRun { status conclusion name }
            ... on StatusContext { state context }
          } }
        } } } }`;

  const searchSelection = (alias, expression, limit) => `  ${alias}: search(
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

  // ── Bounded Refs/Related-to searches per unique phase Issue ──
  const phaseIssueNumbers = new Set();
  for (const m of mapped) {
    if (m.uiPhaseIssue) phaseIssueNumbers.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) phaseIssueNumbers.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) phaseIssueNumbers.add(m.bePhaseIssue);
  }
  const refRelatedSelections = [...phaseIssueNumbers]
    .sort((a, b) => a - b)
    .map((n) => [
      searchSelection(`prSearchRefs${n}`, `"Refs #${n}"`, prSearchLimit),
      searchSelection(`prSearchRelated${n}`, `"Related to #${n}"`, prSearchLimit),
    ].join("\n"))
    .join("\n");

  // ── Bounded marker/convention searches per (Business, phase) pair ──
  // Marker: both structured-marker phrases must occur (AND), which restricts
  // the pool to the exact Business and phase.
  // Convention: head-branch qualifier `business-{B}-{phase}`; the phase suffix
  // keeps business-1 apart from business-11 at search level, and the whole-word
  // regex in discovery enforces the final exact binding.
  const precisionSelections = [];
  for (const m of mapped) {
    for (const phase of PHASES) {
      if (!m[PHASE_ISSUE_KEYS[phase]]) continue;
      precisionSelections.push(searchSelection(`prSearchMarker${m.number}_${phase}`, `"business: ${m.number}" "phase: ${phase}"`, prPrecisionLimit));
      precisionSelections.push(searchSelection(`prSearchConvention${m.number}_${phase}`, `head:business-${m.number}-${phase}`, prPrecisionLimit));
    }
  }

  // Build phase-scoped fallback PR selections with CI/check rollup
  const fallbackPrSelections = getFallbackPrNumbers()
    .map((n) => `  fallbackPr${n}: pullRequest(number: ${n}) {
    ${PR_FIELDS}
  }`)
    .join("\n");

  // Draft PR count query
  const draftQuery = `repo:${GITHUB_REPOSITORY} is:pr is:open is:draft`;

  return `query PortfolioAutoSync($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner url
    defaultBranchRef { name target { ... on Commit { oid messageHeadline committedDate } } }
    issues(first: 1, states: OPEN) { totalCount }
    pullRequests(first: 1, states: OPEN) { totalCount }
${issueSelections}
${fallbackPrSelections}
  }
  draftPullRequests: search(query: ${esc(draftQuery)}, type: ISSUE, first: 1) { issueCount }
${refRelatedSelections}
${precisionSelections.join("\n")}
}`;
}

/** Get all unique Issue numbers that will be queried */
export function getAllIssueNumbers() {
  const issues = new Set();
  for (const m of mappedEntries()) {
    if (m.issueNumber) issues.add(m.issueNumber);
    if (m.uiPhaseIssue) issues.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) issues.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) issues.add(m.bePhaseIssue);
  }
  return [...issues].sort((a, b) => a - b);
}

/** Get all phase Issue numbers that need PR discovery */
export function getPhaseIssueNumbers() {
  const issues = new Set();
  for (const m of mappedEntries()) {
    if (m.uiPhaseIssue) issues.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) issues.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) issues.add(m.bePhaseIssue);
  }
  return [...issues].sort((a, b) => a - b);
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
 * priority order: marker → refs → related → convention. The service merges
 * these pools and dedupes by PR number keeping this order.
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
 * Static request/node budget for the single GraphQL operation.
 * Tests assert these upper bounds so the query cannot grow unbounded.
 */
export function getQueryBudget(opts = {}) {
  const { prSearchLimit = 10, prPrecisionLimit = 5 } = opts;
  let phasePairs = 0;
  const phaseIssues = new Set();
  for (const m of mappedEntries()) {
    for (const phase of PHASES) {
      const n = m[PHASE_ISSUE_KEYS[phase]];
      if (!n) continue;
      phasePairs += 1;
      phaseIssues.add(n);
    }
  }
  const refRelatedAliases = phaseIssues.size * 2;
  const precisionAliases = phasePairs * 2;
  return {
    graphqlRequests: 1,
    issueAliases: getAllIssueNumbers().length,
    fallbackAliases: getFallbackPrNumbers().length,
    searchAliases: refRelatedAliases + precisionAliases + 1, // +1 = draft count
    searchNodeBudget: refRelatedAliases * prSearchLimit + precisionAliases * prPrecisionLimit + 1,
  };
}

/** Request budget: cold=2 (token + GraphQL), cached token=1 (GraphQL only), worst case=4 (401 recovery) */
export function getRequestBudget() {
  return { cold: 2, cachedToken: 1, worstCase: 4 };
}
