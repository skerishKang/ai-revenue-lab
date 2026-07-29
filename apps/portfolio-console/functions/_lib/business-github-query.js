/*  business-github-query.js  —  dynamic GraphQL query builder (Phase 2A)
 *
 *  Builds a single bounded GraphQL query for 55 mapped Businesses.
 *  - Issue selections by number
 *  - PR discovery via search queries referencing phase Issues
 *  - Repository facts (default branch, latest commit)
 *  - Explicit pagination on all connections
 *
 *  PR #193 contract:
 *    - single-flight aggregation
 *    - bounded GraphQL request count
 *    - no unbounded Issue/PR history
 */

import { BUSINESS_GITHUB_MAP, GITHUB_REPOSITORY } from "./business-github-map.js";

const SEARCH_PR_QUERY_PREFIX = `repo:${GITHUB_REPOSITORY} type:pr`;

/**
 * Build a PR discovery search query for a given issue number.
 * Searches for PRs that reference the issue via Refs/Related to/closes.
 */
function prSearchQuery(issueNumber, phase) {
  // Escape for GraphQL string: search for PRs referencing the issue
  return `${SEARCH_PR_QUERY_PREFIX} "${issueNumber}"`;
}

/**
 * Build the complete GraphQL query for all mapped Businesses.
 * @param {object} [opts]
 * @param {number} [opts.prSearchLimit=10] - Max PRs to return per phase Issue search
 * @returns {string} The complete GraphQL query string
 */
export function buildStatusQuery(opts = {}) {
  const { prSearchLimit = 10 } = opts;

  // Collect unique phase issue numbers that need PR discovery
  const phaseIssues = new Set();
  const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);

  for (const m of mappedEntries) {
    if (m.uiPhaseIssue) phaseIssues.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) phaseIssues.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) phaseIssues.add(m.bePhaseIssue);
  }

  // Build issue selections (individual issue queries - use old 'issue{N}' format for backward compat)
  const issueSelections = mappedEntries
    .filter((m) => m.issueNumber)
    .map((m) => `  issue${m.issueNumber}: issue(number: ${m.issueNumber}) {
    number title state stateReason updatedAt url
    body
  }`)
    .join("\n");

  // Build PR search selections for each phase issue (for automatic PR discovery)
  const prSearchSelections = [...phaseIssues]
    .map((issueNum) => `  prSearch${issueNum}: search(
    query: ${JSON.stringify(prSearchQuery(issueNum, "ui"))}
    type: ISSUE
    first: ${prSearchLimit}
  ) {
    issueCount
    nodes {
      ... on PullRequest {
        number title state isDraft merged headRefOid baseRefName updatedAt url body
      }
    }
  }`)
    .join("\n");

  // Build fallback PR queries (for explicitly mapped PR numbers - use old 'pr{N}' format)
  const fallbackPrSelections = mappedEntries
    .filter((m) => m.fallbackPrNumber)
    .map((m) => `  pr${m.fallbackPrNumber}: pullRequest(number: ${m.fallbackPrNumber}) {
    number title state isDraft merged headRefOid baseRefName updatedAt url body
    commits(last: 1) { nodes { commit { statusCheckRollup {
      state contexts(first: 100) { totalCount nodes {
        __typename
        ... on CheckRun { status conclusion name }
        ... on StatusContext { state context }
      } }
    } } } }
  }`)
    .join("\n");

  // Build draft PR count query
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
  draftPullRequests: search(query: ${JSON.stringify(draftQuery)}, type: ISSUE, first: 1) { issueCount }
  ${prSearchSelections}
}`;
}

/**
 * Get the set of all phase issue numbers that need PR discovery.
 * Used for fixture/test generation.
 */
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

/**
 * Get the total count of external fetches a cold request will make.
 * Normal: 2 (token exchange + GraphQL)
 * Cached token: 1 (GraphQL only)
 */
export function getRequestBudget() {
  return { cold: 2, cachedToken: 1, worstCase: 4 };
}
