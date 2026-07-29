/*  business-fact-merger.js  —  Phase 2A fact merger
 *
 *  Merges static identity + live GitHub facts + phase verdicts.
 *  Unified alias contract: issue{N}, prSearch{N}, fallbackPr{N}
 *
 *  Rules:
 *    - Static identity/authority never overwritten by live data
 *    - Static phase status used as fallback when no machine-readable verdict
 *    - PR merge does NOT imply phase approval
 *    - Conflict/unverified states preserved
 */

import { resolvePhaseVerdictFromPool } from "./business-verdict-parser.js";
import { discoverBusinessPrs } from "./business-pr-discovery.js";
import { safeError } from "./response.js";

const SCHEMA_VERSION = 2;

function normalizeIssue(issue) {
  if (!issue) return null;
  return {
    number: Number(issue.number),
    title: String(issue.title || ""),
    state: String(issue.state || "").toLowerCase(),
    stateReason: issue.stateReason || null,
    updatedAt: issue.updatedAt || null,
    url: String(issue.url || ""),
  };
}

function normalizePullRequest(pr) {
  if (!pr) return null;
  return {
    number: Number(pr.number),
    title: String(pr.title || ""),
    state: String(pr.state || "").toLowerCase(),
    draft: Boolean(pr.isDraft),
    merged: Boolean(pr.merged),
    headSha: String(pr.headRefOid || ""),
    headRef: String(pr.headRefName || ""),
    baseRef: String(pr.baseRefName || ""),
    updatedAt: String(pr.updatedAt || ""),
    url: String(pr.url || ""),
  };
}

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
  if (total > contexts.length) result.truncated = true;
  return result;
}

/**
 * Get the static fallback phase verdict from the identity source.
 * The identity source is the manifest object passed via API.
 */
function getStaticFallback(mapping, identitySource) {
  if (!identitySource) return null;
  const biz = identitySource[mapping.number];
  return biz || null;
}

/**
 * Merge all data sources into a unified response for one Business.
 */
export function mergeBusinessFacts({
  mapping,
  repositoryData,
  phaseIssueResults,
  fallbackPrNode,
  identitySource, // Map<number, {uiStatus, uxStatus, backendStatus}>
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

  // ── Normalize all Issues ──
  const issueAlias = mapping.issueNumber ? `issue${mapping.issueNumber}` : null;
  const issue = normalizeIssue(issueAlias ? repositoryData?.[issueAlias] : null);

  const phaseIssues = {};
  const phaseFallbacks = {};
  const staticBiz = (identitySource || {})[mapping.number] || {};

  if (mapping.uiPhaseIssue) {
    phaseIssues.ui = repositoryData?.[`issue${mapping.uiPhaseIssue}`] || null;
    phaseFallbacks.ui = staticBiz.uiStatus || null;
  }
  if (mapping.uxPhaseIssue) {
    phaseIssues.ux = repositoryData?.[`issue${mapping.uxPhaseIssue}`] || null;
    phaseFallbacks.ux = staticBiz.uxStatus || null;
  }
  if (mapping.bePhaseIssue) {
    phaseIssues.backend = repositoryData?.[`issue${mapping.bePhaseIssue}`] || null;
    phaseFallbacks.backend = staticBiz.backendStatus || null;
  }

  // ── Auto-discover PRs for each phase ──
  const prDiscovery = discoverBusinessPrs({ mapping, phaseIssueResults, fallbackPrNode });

  // Pick best PR
  const discoveredPr = prDiscovery.ui?.pullRequest || prDiscovery.ux?.pullRequest || prDiscovery.backend?.pullRequest || null;

  // Normalize checks
  let checks = { state: "unavailable", source: "none", total: 0, completed: 0 };
  let pullRequest = null;

  if (discoveredPr) {
    pullRequest = normalizePullRequest(discoveredPr);
    checks = normalizeChecks(discoveredPr);
  } else if (mapping.fallbackPrNumber) {
    const fbAlias = `fallbackPr${mapping.fallbackPrNumber}`;
    const fbData = repositoryData?.[fbAlias] || null;
    if (fbData) {
      pullRequest = normalizePullRequest(fbData);
      checks = normalizeChecks(fbData);
    }
  }

  // ── Resolve phase verdicts with Business/phase binding ──
  const phaseVerdicts = {};
  const phases = ["ui", "ux", "backend"];
  for (const phase of phases) {
    const phaseIssue = phaseIssues[phase];
    const phaseIssueNumber = mapping[`${phase}PhaseIssue`];
    if (!phaseIssueNumber) continue;

    phaseVerdicts[phase] = resolvePhaseVerdictFromPool({
      expectedBusinessNumber: mapping.number,
      expectedPhase: phase,
      issueBody: phaseIssue?.body || null,
      prBody: pullRequest?.body || null,
      staticFallback: phaseFallbacks[phase],
    });
  }

  // ── Determine connection state ──
  const diagnostics = [];
  if (prDiscovery.ui?.status === "conflict") diagnostics.push("PR_DISCOVERY_CONFLICT");
  if (prDiscovery.ui?.status === "unavailable" && mapping.uiPhaseIssue) diagnostics.push("PR_UNAVAILABLE");
  if (!issue && mapping.issueNumber) diagnostics.push("ISSUE_UNAVAILABLE");
  const connectionState = diagnostics.length === 0 ? "connected" : "partial";

  // Activity timestamp
  const activityAt = (() => {
    const timestamps = [];
    if (issue?.updatedAt) timestamps.push(new Date(issue.updatedAt).getTime());
    if (pullRequest?.updatedAt) timestamps.push(new Date(pullRequest.updatedAt).getTime());
    const valid = timestamps.filter(Number.isFinite);
    return valid.length ? new Date(Math.max(...valid)).toISOString() : null;
  })();

  return {
    number: mapping.number,
    connectionState,
    repository: mapping.repository,
    productDecisionIssue: issue,
    phaseIssues: Object.keys(phaseIssues).length ? {
      ui: normalizeIssue(phaseIssues.ui),
      ux: normalizeIssue(phaseIssues.ux),
      backend: normalizeIssue(phaseIssues.backend),
    } : null,
    pullRequest,
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
export function createMergedPayload({ businessFacts, repositoryData, syncedAt, stale }) {
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
