/*  business-fact-merger.js  —  Phase 2A fact merger
 *
 *  Merges static identity + live GitHub facts + phase verdicts.
 *  Unified alias contract: issue{N}, prSearchRefs{N}, prSearchRelated{N},
 *  fallbackPr{N} (search pools are pre-merged by the service).
 *
 *  Canonical per-Business schema (schemaVersion 2):
 *    productDecisionIssue            — normalized product-decision Issue|null
 *    phaseIssues.{ui,ux,backend}     — normalized phase Issue|null (always 3 keys)
 *    currentPullRequests.{ui,ux,backend} — normalized PR|null (always 3 keys,
 *                                      checks embedded, discoveryMethod attached)
 *    phaseDiscovery.{ui,ux,backend}  — {status, method, candidates, reason, truncated?}
 *    phaseVerdicts.{ui,ux,backend}   — verdict result (always 3 keys when mapped)
 *
 *  PR normalization happens exactly once, at the GraphQL boundary, in
 *  business-pr-discovery.js (normalizeRawPr). This module never reads raw
 *  GraphQL PR field names.
 *
 *  Rules:
 *    - Static identity/authority never overwritten by live data
 *    - Static phase status used as fallback when no machine-readable verdict
 *    - PR merge does NOT imply phase approval
 *    - Conflict/unverified states preserved
 */

import { resolvePhaseVerdictFromPool } from "./business-verdict-parser.js";
import { discoverBusinessPrs } from "./business-pr-discovery.js";

const SCHEMA_VERSION = 2;

const PHASE_ISSUE_KEYS = Object.freeze({ ui: "uiPhaseIssue", ux: "uxPhaseIssue", backend: "bePhaseIssue" });
const STATIC_FALLBACK_KEYS = Object.freeze({ ui: "uiStatus", ux: "uxStatus", backend: "backendStatus" });
const PHASES = Object.freeze(["ui", "ux", "backend"]);

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

function discoverySummary(discovery) {
  if (!discovery) return null;
  const summary = {
    status: discovery.status,
    method: discovery.pullRequest?.discoveryMethod || null,
    candidates: discovery.candidates || null,
    reason: discovery.reason || null,
  };
  if (discovery.truncated) summary.truncated = true;
  return summary;
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
}) {
  if (!mapping.repository) {
    return {
      number: mapping.number,
      connectionState: "unmapped",
      repository: null,
      productDecisionIssue: null,
      phaseIssues: null,
      currentPullRequests: null,
      phaseDiscovery: null,
      phaseVerdicts: null,
      activityAt: null,
      error: null,
    };
  }

  // ── Normalize product-decision Issue ──
  const issueAlias = mapping.issueNumber ? `issue${mapping.issueNumber}` : null;
  const productDecisionIssue = normalizeIssue(issueAlias ? repositoryData?.[issueAlias] : null);

  // ── Raw + normalized phase Issues (raw bodies feed verdict parsing) ──
  const rawPhaseIssues = { ui: null, ux: null, backend: null };
  const phaseIssues = { ui: null, ux: null, backend: null };
  for (const phase of PHASES) {
    const issueNum = mapping[PHASE_ISSUE_KEYS[phase]];
    if (!issueNum) continue;
    rawPhaseIssues[phase] = repositoryData?.[`issue${issueNum}`] || null;
    phaseIssues[phase] = normalizeIssue(rawPhaseIssues[phase]);
  }

  // ── Auto-discover normalized PRs for each phase ──
  const prDiscovery = discoverBusinessPrs({ mapping, phaseIssueResults, fallbackPrNode });
  const currentPullRequests = {
    ui: prDiscovery.ui?.pullRequest || null,
    ux: prDiscovery.ux?.pullRequest || null,
    backend: prDiscovery.backend?.pullRequest || null,
  };

  // ── Resolve phase verdicts with Business/phase binding ──
  const staticBiz = (identitySource || {})[mapping.number] || {};
  const phaseVerdicts = {};
  for (const phase of PHASES) {
    phaseVerdicts[phase] = resolvePhaseVerdictFromPool({
      expectedBusinessNumber: mapping.number,
      expectedPhase: phase,
      issueBody: rawPhaseIssues[phase]?.body || null,
      prBody: currentPullRequests[phase]?.body || null,
      staticFallback: staticBiz[STATIC_FALLBACK_KEYS[phase]] || null,
    });
  }

  // ── Determine connection state ──
  const diagnostics = [];
  for (const phase of PHASES) {
    if (prDiscovery[phase]?.status === "conflict") diagnostics.push("PR_DISCOVERY_CONFLICT");
  }
  if (!productDecisionIssue && mapping.issueNumber) diagnostics.push("ISSUE_UNAVAILABLE");
  const connectionState = diagnostics.length === 0 ? "connected" : "partial";

  // Activity timestamp
  const activityAt = (() => {
    const timestamps = [];
    if (productDecisionIssue?.updatedAt) timestamps.push(new Date(productDecisionIssue.updatedAt).getTime());
    for (const phase of PHASES) {
      const updatedAt = currentPullRequests[phase]?.updatedAt;
      if (updatedAt) timestamps.push(new Date(updatedAt).getTime());
    }
    const valid = timestamps.filter(Number.isFinite);
    return valid.length ? new Date(Math.max(...valid)).toISOString() : null;
  })();

  return {
    number: mapping.number,
    connectionState,
    repository: mapping.repository,
    productDecisionIssue,
    phaseIssues,
    currentPullRequests,
    phaseDiscovery: {
      ui: discoverySummary(prDiscovery.ui),
      ux: discoverySummary(prDiscovery.ux),
      backend: discoverySummary(prDiscovery.backend),
    },
    phaseVerdicts,
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
