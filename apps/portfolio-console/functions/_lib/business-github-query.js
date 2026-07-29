/*  business-github-query.js  —  unified GraphQL query builder (Phase 2A)
 *
 *  Builds a single bounded GraphQL query for 55 mapped Businesses.
 *  Unified alias contract:
 *    issue{N}       — product-decision Issue
 *    uiIssue{N}     — Phase 1 UI Issue (when different from product issue)
 *    uxIssue{N}     — Phase 2 UX Issue (when different)
 *    beIssue{N}     — Phase 3 Backend Issue (when different)
 *    prSearch{N}    — PR discovery search results for issue N
 *    fallbackPr{N}  — explicit fallback PR (with check rollup)
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

  const issueSelection = `issue(number: __NUMBER__) {
    number title state stateReason updatedAt url body
  }`;

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

  // Build PR search selections with CI/check rollup
  const searchQuery = (issueNum) => {
    // Use Refs/Related to to narrow search: exact issue number reference
    return `${SEARCH_PR_QUERY_PREFIX} "Refs #${issueNum}" "Related to #${issueNum}"`;
  };

  const prSearchSelections = [...phaseIssueNumbers]
    .sort((a, b) => a - b)
    .map((n) => `  prSearch${n}: search(
    query: ${esc(`${SEARCH_PR_QUERY_PREFIX} "Refs #${n}"`)}
    type: ISSUE
    first: ${prSearchLimit}
  ) {
    issueCount
    nodes {
      ... on PullRequest {
        number title state isDraft merged headRefOid headRefName baseRefName updatedAt url body
        commits(last: 1) { nodes { commit { statusCheckRollup {
          state contexts(first: 100) { totalCount nodes {
            __typename
            ... on CheckRun { status conclusion name }
            ... on StatusContext { state context }
          } }
        } } } }
      }
    }
  }`)
    .join("\n");

  // Build fallback PR selections with CI/check rollup
  const fallbackPrSelections = mappedEntries
    .filter((m) => m.fallbackPrNumber)
    .map((m) => `  fallbackPr${m.fallbackPrNumber}: pullRequest(number: ${m.fallbackPrNumber}) {
    number title state isDraft merged headRefOid headRefName baseRefName updatedAt url body
    commits(last: 1) { nodes { commit { statusCheckRollup {
      state contexts(first: 100) { totalCount nodes {
        __typename
        ... on CheckRun { status conclusion name }
        ... on StatusContext { state context }
      } }
    } } } }
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

/** Request budget: cold=2 (token + GraphQL), cached token=1 (GraphQL only), worst case=4 (401 recovery) */
export function getRequestBudget() {
  return { cold: 2, cachedToken: 1, worstCase: 4 };
}
