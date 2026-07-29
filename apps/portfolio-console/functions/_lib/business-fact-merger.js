/*  business-fact-merger.js  —  merge static identity + live GitHub facts + phase verdicts (Phase 2A)
 *
 *  Core merge rules:
 *    - Static identity (number, slug, authority) never overwritten by live data
 *    - Static priority/product-boundary never overwritten by live data
 *    - UI/UX/Backend phase verdicts: live verdict with valid accepted_head > static judgment
 *    - Static fallback used when live verdict is unavailable or invalid
 *    - PR merge does NOT imply phase approval
 *    - Deployment does NOT imply release
 *    - Conflict/unverified states preserved in output
 */

import { resolvePhaseVerdict, parseVerdictBlock, isApprovedVerdict } from "./business-verdict-parser.js";
import { discoverBusinessPrs } from "./business-pr-discovery.js";
import { safeError } from "./response.js";

const SCHEMA_VERSION = 2;  // Phase 2A schema

/**
 * @typedef {Object} MergedBusiness
 * @property {number} number
 * @property {string} connectionState  - "connected" | "partial" | "unmapped"
 * @property {object|null} issue
 * @property {object|null} pullRequest
 * @property {object} checks
 * @property {object|null} phaseDiscovery
 * @property {object|null} phaseVerdicts
 * @property {object|null} error
 */

/**
 * Normalize a single issue from GraphQL data.
 */
function normalizeIssue(issue) {
  if (!issue) return null;
  return {
    number: Number(issue.number),
    title: String(issue.title || ""),
    state: String(issue.state || "").toLowerCase(),
    updatedAt: issue.updatedAt || null,
    url: String(issue.url || ""),
  };
}

/**
 * Normalize a single PR from GraphQL data.
 */
function normalizePullRequest(pr) {
  if (!pr) return null;
  return {
    number: Number(pr.number),
    title: String(pr.title || ""),
    state: String(pr.state || "").toLowerCase(),
    draft: Boolean(pr.isDraft),
    merged: Boolean(pr.merged),
    headSha: String(pr.headRefOid || ""),
    baseRef: String(pr.baseRefName || ""),
    updatedAt: String(pr.updatedAt || ""),
    url: String(pr.url || ""),
  };
}

/**
 * Normalize CI/check status from PR data.
 */
function normalizeChecks(prData) {
  if (!prData) return { state: "unavailable", source: "none", total: 0, completed: 0 };
  const rollup = prData?.commits?.nodes?.[0]?.commit?.statusCheckRollup || null;
  if (!rollup) return { state: "unavailable", source: "pr_head_rollup", total: 0, completed: 0 };
  const contexts = Array.isArray(rollup?.contexts?.nodes) ? rollup.contexts.nodes : [];
  const total = Number(rollup?.contexts?.totalCount) || contexts.length;
  const aggregateState = String(rollup.state || "").toUpperCase();
  const normalizedState = aggregateState === "SUCCESS" ? "pass"
    : aggregateState === "FAILURE" || aggregateState === "ERROR" ? "fail"
    : aggregateState === "PENDING" || aggregateState === "EXPECTED" ? "pending"
    : "unavailable";
  const terminalStates = new Set(["SUCCESS", "FAILURE", "ERROR"]);
  let completed = 0;
  for (const ctx of contexts) {
    const tn = String(ctx?.__typename || "");
    if (tn === "CheckRun" && String(ctx?.status || "").toUpperCase() === "COMPLETED") completed++;
    else if (tn === "StatusContext" && terminalStates.has(String(ctx?.state || "").toUpperCase())) completed++;
  }
  const result = { state: normalizedState, source: "pr_head_rollup", total, completed };
  return result;
}

/**
 * Merge all data sources into a unified response for one Business.
 */
export function mergeBusinessFacts({
  mapping,
  issueData,
  phaseIssueResults,
  fallbackPrNode,
  repositoryData,
  paths,
}) {
  if (!mapping.repository) {
    return {
      number: mapping.number,
      connectionState: "unmapped",
      repository: null,
      issue: null,
      pullRequest: null,
      checks: { state: "unavailable", source: "none", total: 0, completed: 0 },
      phaseDiscovery: null,
      phaseVerdicts: null,
      activityAt: null,
      error: null,
    };
  }

  // Normalize primary product-decision issue
  const issueAlias = mapping.issueNumber ? `i${mapping.issueNumber}` : null;
  const issue = normalizeIssue(issueAlias ? repositoryData?.[issueAlias] : null);

  // Auto-discover PRs for each phase
  const prDiscovery = discoverBusinessPrs({ mapping, phaseIssueResults, fallbackPrNode });

  // Pick the best PR (ui phase first, then ux, then backend, then fallback)
  const discoveredPr = prDiscovery.ui?.pullRequest || prDiscovery.ux?.pullRequest || prDiscovery.backend?.pullRequest;
  const prData = discoveredPr;

  // Normalize checks from discovered PR (or fallback)
  let checks = normalizeChecks(prData);
  if (!prData && mapping.fallbackPrNumber) {
    const fbAlias = `fp${mapping.fallbackPrNumber}`;
    const fbData = repositoryData?.[fbAlias] || null;
    checks = normalizeChecks(fbData);
  }

  // Resolve phase verdicts
  const phaseVerdicts = {};
  if (mapping.uiPhaseIssue) {
    const uiIssueData = repositoryData?.[`i${mapping.uiPhaseIssue}`] || null;
    phaseVerdicts.ui = resolvePhaseVerdict({
      issueData: uiIssueData,
      prData,
      staticFallback: null, // would come from manifest
    });
  }
  if (mapping.uxPhaseIssue) {
    const uxIssueData = repositoryData?.[`i${mapping.uxPhaseIssue}`] || null;
    phaseVerdicts.ux = resolvePhaseVerdict({
      issueData: uxIssueData,
      prData,
      staticFallback: null,
    });
  }
  if (mapping.bePhaseIssue) {
    const beIssueData = repositoryData?.[`i${mapping.bePhaseIssue}`] || null;
    phaseVerdicts.backend = resolvePhaseVerdict({
      issueData: beIssueData,
      prData,
      staticFallback: null,
    });
  }

  // Determine connection state
  const diagnostics = [];
  if (prDiscovery.ui?.status === "conflict") diagnostics.push("PR_DISCOVERY_CONFLICT");
  if (prDiscovery.ui?.status === "unavailable" && mapping.uiPhaseIssue) diagnostics.push("PR_UNAVAILABLE");
  if (!issue && mapping.issueNumber) diagnostics.push("ISSUE_UNAVAILABLE");

  const connectionState = diagnostics.length === 0 ? "connected" : "partial";

  // Activity timestamp
  const activityAt = (() => {
    const timestamps = [];
    if (issue?.updatedAt) timestamps.push(new Date(issue.updatedAt).getTime());
    if (prData?.updatedAt) timestamps.push(new Date(prData.updatedAt).getTime());
    const valid = timestamps.filter(Number.isFinite);
    return valid.length ? new Date(Math.max(...valid)).toISOString() : null;
  })();

  return {
    number: mapping.number,
    connectionState,
    repository: mapping.repository,
    issue,
    pullRequest: prData ? normalizePullRequest(prData) : null,
    checks,
    phaseDiscovery: {
      ui: prDiscovery.ui ? { status: prDiscovery.ui.status, method: prDiscovery.ui?.pullRequest?.discoveryMethod || null, candidates: prDiscovery.ui.candidates || null } : null,
      ux: prDiscovery.ux ? { status: prDiscovery.ux.status, method: prDiscovery.ux?.pullRequest?.discoveryMethod || null, candidates: prDiscovery.ux.candidates || null } : null,
      backend: prDiscovery.backend ? { status: prDiscovery.backend.status, method: prDiscovery.backend?.pullRequest?.discoveryMethod || null, candidates: prDiscovery.backend.candidates || null } : null,
    },
    phaseVerdicts: Object.keys(phaseVerdicts).length ? phaseVerdicts : null,
    activityAt,
    error: diagnostics.length ? { code: diagnostics[0], message: "Business GitHub facts are partially available." } : null,
  };
}

/**
 * Create the complete merged response payload.
 */
export function createMergedPayload({
  businessFacts,
  repositoryData,
  syncedAt,
  stale,
}) {
  return {
    ok: true,
    schemaVersion: SCHEMA_VERSION,
    syncedAt,
    stale: Boolean(stale),
    repository: repositoryData ? {
      fullName: String(repositoryData.nameWithOwner || ""),
      url: String(repositoryData.url || ""),
      defaultBranch: String(repositoryData.defaultBranchRef?.name || "main"),
      latestSha: String(repositoryData.defaultBranchRef?.target?.oid || ""),
      latestCommitTitle: String(repositoryData.defaultBranchRef?.target?.messageHeadline || ""),
      latestCommitAt: repositoryData.defaultBranchRef?.target?.committedDate || null,
    } : null,
    businesses: businessFacts,
    errors: [],
  };
}

export { SCHEMA_VERSION };
