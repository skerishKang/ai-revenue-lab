/*  business-github-query.js  —  unified GraphQL query builder (Phase 2A)
 *
 *  Builds a single bounded GraphQL query for 55 mapped Businesses.
 *  Unified alias contract:
 *    issue{N}           — product-decision Issue
 *    uiIssue{N}         — Phase 1 UI Issue (when different from product issue)
 *    uxIssue{N}         — Phase 2 UX Issue (when different)
 *    beIssue{N}         — Phase 3 Backend Issue (when different)
 *    prSearchRefs{N}    — bounded PR search for `"Refs #N"` (issue N)
 *    prSearchRelated{N} — bounded PR search for `"Related to #N"` (issue N)
 *    fallbackPr{N}      — explicit fallback PR (with check rollup)
 *
 *  Both PR search expressions are issued as bounded aliases inside the SAME
 *  single GraphQL request (first: prSearchLimit each). The service merges and
 *  de-duplicates the two pools by PR number; truncation is flagged when
 *  issueCount exceeds the returned nodes.
 *
 *  PR #193 contract:
 *    - single-flight aggregation
 *    - bounded GraphQL request count
 *    - no unbounded Issue/PR history
 *    - explicit pagination on all connections
 */

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";

const SEARCH_PR_QUERY_PREFIX = `repo:${GITHUB_REPOSITORY} type:pr`;

function esc(val) { return JSON.stringify(val); }

/**
 * Build the complete GraphQL query for all mapped Businesses.
 * @param {object} [opts]
 * @param {number} [opts.prSearchLimit=10]
 * @returns {string}
 */
export function buildStatusQuery(opts = {}) {
  const { prSearchLimit = 10 } = opts;

  const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);

  // ── Collect ALL unique Issue numbers for querying ──
  const allIssueNumbers = new Set();
  for (const m of mappedEntries) {
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

  // ── Collect ALL unique phase Issue numbers for PR discovery ──
  const phaseIssueNumbers = new Set();
  for (const m of mappedEntries) {
    if (m.uiPhaseIssue) phaseIssueNumbers.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) phaseIssueNumbers.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) phaseIssueNumbers.add(m.bePhaseIssue);
  }

  // PR field selection shared by search aliases and fallback PRs (with CI/check rollup)
  const PR_FIELDS = `number title state isDraft merged headRefOid headRefName baseRefOid baseRefName updatedAt url body
        commits(last: 1) { nodes { commit { statusCheckRollup {
          state contexts(first: 100) { totalCount nodes {
            __typename
            ... on CheckRun { status conclusion name }
            ... on StatusContext { state context }
          } }
        } } } }`;

  // Bounded dual search per phase Issue: "Refs #N" and "Related to #N".
  // Both aliases live in the same single GraphQL request (request budget = 1).
  const searchSelection = (alias, expression, indent) => `  ${alias}: search(
    query: ${esc(`${SEARCH_PR_QUERY_PREFIX} ${expression}`)}
    type: ISSUE
    first: ${prSearchLimit}
  ) {
    issueCount
    nodes {
      ... on PullRequest {
        ${PR_FIELDS}
      }
    }
  }`;

  const prSearchSelections = [...phaseIssueNumbers]
    .sort((a, b) => a - b)
    .map((n) => [
      searchSelection(`prSearchRefs${n}`, `"Refs #${n}"`),
      searchSelection(`prSearchRelated${n}`, `"Related to #${n}"`),
    ].join("\n"))
    .join("\n");

  // Build fallback PR selections with CI/check rollup
  const fallbackPrSelections = mappedEntries
    .filter((m) => m.fallbackPrNumber)
    .map((m) => `  fallbackPr${m.fallbackPrNumber}: pullRequest(number: ${m.fallbackPrNumber}) {
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
${prSearchSelections}
}`;
}

/** Get all unique Issue numbers that will be queried */
export function getAllIssueNumbers() {
  const issues = new Set();
  const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
  for (const m of mappedEntries) {
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
  const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
  for (const m of mappedEntries) {
    if (m.uiPhaseIssue) issues.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) issues.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) issues.add(m.bePhaseIssue);
  }
  return [...issues].sort((a, b) => a - b);
}

/** Get all fallback PR numbers */
export function getFallbackPrNumbers() {
  const prs = new Set();
  const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
  for (const m of mappedEntries) {
    if (m.fallbackPrNumber) prs.add(m.fallbackPrNumber);
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

/** Request budget: cold=2 (token + GraphQL), cached token=1 (GraphQL only), worst case=4 (401 recovery) */
export function getRequestBudget() {
  return { cold: 2, cachedToken: 1, worstCase: 4 };
}
