/*  business-pr-discovery.js  —  automatic PR discovery (Phase 2A)
 *
 *  This module is the SINGLE normalization boundary between raw GraphQL PR
 *  nodes and the rest of the server. Every consumer (merger, service, tests)
 *  receives the normalized schema produced by normalizeRawPr:
 *
 *    { number, title, state, draft, merged, headSha, headRef, baseSha,
 *      baseRef, body, updatedAt, url, checks, discoveryMethod? }
 *
 *  Raw GraphQL field names (isDraft, headRefOid, headRefName, baseRefOid,
 *  baseRefName) never appear downstream.
 *
 *  Discovery order per phase:
 *    1. structured Business/phase marker in PR body
 *    2. "Refs #issueNumber" in PR body
 *    3. "Related to #issueNumber" in PR body
 *    4. branch/title convention matching (headRefName)
 *    5. static fallback PR pointer
 *
 *  Ambiguous matches → conflict (never guess).
 *  A static fallback pointer that disagrees with an automatic discovery is a
 *  conflict, not a silent override.
 *  PR merge does not imply phase approval.
 */

function parseStructuredMarker(body) {
  if (!body) return null;
  const bizMatch = body.match(/business:\s*(\d+)/);
  const phaseMatch = body.match(/phase:\s*(ui|ux|backend)/);
  if (bizMatch && phaseMatch) return { businessNumber: parseInt(bizMatch[1], 10), phase: phaseMatch[1] };
  return null;
}

function parseRefs(body) {
  if (!body) return [];
  const refs = [];
  const regex = /Refs\s+#(\d+)/gi;
  let match;
  while ((match = regex.exec(body)) !== null) refs.push(parseInt(match[1], 10));
  return refs;
}

function parseRelatedTo(body) {
  if (!body) return [];
  const refs = [];
  const regex = /Related\s+to\s+#(\d+)/gi;
  let match;
  while ((match = regex.exec(body)) !== null) refs.push(parseInt(match[1], 10));
  return refs;
}

const CHECK_TERMINAL_STATES = new Set(["SUCCESS", "FAILURE", "ERROR"]);

/** Normalize the PR head commit check rollup (single implementation). */
export function normalizeChecks(rawPr) {
  const rollup = rawPr?.commits?.nodes?.[0]?.commit?.statusCheckRollup || null;
  if (!rollup) return { state: "unavailable", source: "pr_head_rollup", total: 0, completed: 0 };
  const contexts = Array.isArray(rollup?.contexts?.nodes) ? rollup.contexts.nodes : [];
  const total = Number(rollup?.contexts?.totalCount) || contexts.length;
  const aggregateState = String(rollup.state || "").toUpperCase();
  const normalizedState = aggregateState === "SUCCESS" ? "pass"
    : aggregateState === "FAILURE" || aggregateState === "ERROR" ? "fail"
    : aggregateState === "PENDING" || aggregateState === "EXPECTED" ? "pending"
    : "unavailable";
  let completed = 0;
  for (const ctx of contexts) {
    const tn = String(ctx?.__typename || "");
    if (tn === "CheckRun" && String(ctx?.status || "").toUpperCase() === "COMPLETED") completed++;
    else if (tn === "StatusContext" && CHECK_TERMINAL_STATES.has(String(ctx?.state || "").toUpperCase())) completed++;
  }
  const result = { state: normalizedState, source: "pr_head_rollup", total, completed };
  if (total > contexts.length) result.truncated = true;
  return result;
}

/**
 * The single raw→normalized PR conversion. Accepts a raw GraphQL PullRequest
 * node (search result or fallbackPr alias) and returns the normalized schema.
 */
export function normalizeRawPr(node) {
  if (!node || !node.number) return null;
  return {
    number: Number(node.number),
    title: String(node.title || ""),
    state: String(node.state || "").toLowerCase(),
    draft: Boolean(node.isDraft),
    merged: Boolean(node.merged),
    headSha: String(node.headRefOid || ""),
    headRef: String(node.headRefName || ""),
    baseSha: String(node.baseRefOid || ""),
    baseRef: String(node.baseRefName || ""),
    updatedAt: String(node.updatedAt || ""),
    url: String(node.url || ""),
    body: String(node.body || ""),
    checks: normalizeChecks(node),
  };
}

/** Whole-word business/phase prefix matching (business-1 must not match business-11). */
function conventionMatches(pr, businessNumber, phase, phaseIssueNumber) {
  const bizRegex = new RegExp(`business-${businessNumber}(?!\\d)`, "i");
  const phaseRegex = new RegExp(`${phase}-${phaseIssueNumber}(?!\\d)`, "i");
  return bizRegex.test(pr.title || "") || bizRegex.test(pr.headRef || "")
    || phaseRegex.test(pr.title || "") || phaseRegex.test(pr.headRef || "");
}

function discovered(pr, method, truncated) {
  const result = { status: "discovered", pullRequest: { ...pr, discoveryMethod: method }, candidates: null, reason: null };
  if (truncated) result.truncated = true;
  return result;
}

/**
 * Discover which PR maps to a Business's phase Issue.
 * @param {object} args
 * @param {number} args.businessNumber
 * @param {number|null} args.phaseIssueNumber - phase Issue number to discover PR for
 * @param {"ui"|"ux"|"backend"} args.phase
 * @param {object[]|{nodes:object[],truncated?:boolean}} [args.searchResults] - merged raw PR nodes (Refs + Related to)
 * @param {object|null} [args.fallbackPrNode] - raw fallback PR node from fallbackPr{N}
 * @returns {{status:"discovered"|"unavailable"|"conflict", pullRequest:object|null, candidates?:number[]|null, reason?:string|null, truncated?:boolean}}
 */
export function discoverPr({
  businessNumber,
  phaseIssueNumber,
  phase,
  searchResults,
  fallbackPrNode,
}) {
  if (!phaseIssueNumber) {
    return { status: "unavailable", pullRequest: null, candidates: null, reason: "NO_PHASE_ISSUE" };
  }

  const pool = Array.isArray(searchResults) ? { nodes: searchResults, truncated: false } : (searchResults || { nodes: [], truncated: false });
  const truncated = Boolean(pool.truncated);
  const candidates = (pool.nodes || []).map(normalizeRawPr).filter(Boolean);

  const conflict = (reason, matches) => ({ status: "conflict", pullRequest: null, candidates: matches.map((p) => p.number), reason });

  // ── 1. Structured marker match ──
  const markerMatches = candidates.filter((pr) => {
    const marker = parseStructuredMarker(pr.body);
    return marker && marker.businessNumber === businessNumber && marker.phase === phase;
  });
  if (markerMatches.length === 1) return discovered(markerMatches[0], "marker", truncated);
  if (markerMatches.length > 1) return conflict("MULTIPLE_MARKER_MATCHES", markerMatches);

  // ── 2. Refs #issueNumber match ──
  const refsMatches = candidates.filter((pr) => parseRefs(pr.body).includes(phaseIssueNumber));
  if (refsMatches.length === 1) return discovered(refsMatches[0], "refs", truncated);
  if (refsMatches.length > 1) return conflict("MULTIPLE_REFS_MATCHES", refsMatches);

  // ── 3. Related to #issueNumber match ──
  const relatedMatches = candidates.filter((pr) => parseRelatedTo(pr.body).includes(phaseIssueNumber));
  if (relatedMatches.length === 1) return discovered(relatedMatches[0], "related_to", truncated);
  if (relatedMatches.length > 1) return conflict("MULTIPLE_RELATED_MATCHES", relatedMatches);

  // ── 4. Branch/title convention (headRefName) ──
  const branchMatches = candidates.filter((pr) => conventionMatches(pr, businessNumber, phase, phaseIssueNumber));
  if (branchMatches.length === 1) return discovered(branchMatches[0], "branch", truncated);
  if (branchMatches.length > 1) return conflict("MULTIPLE_BRANCH_MATCHES", branchMatches);

  // ── 5. Static fallback PR pointer ──
  const fallbackPr = normalizeRawPr(fallbackPrNode);
  if (fallbackPr) return discovered(fallbackPr, "fallback", false);

  const unavailable = { status: "unavailable", pullRequest: null, candidates: null, reason: "NO_DISCOVERY_MATCH" };
  if (truncated) unavailable.truncated = true;
  return unavailable;
}

/**
 * Guard: an automatic discovery that disagrees with the static fallback
 * pointer is a mapping conflict (never silently ignored).
 */
export function reconcileWithFallback(discoveryResult, fallbackPrNode) {
  if (!fallbackPrNode?.number) return discoveryResult;
  if (discoveryResult.status !== "discovered") return discoveryResult;
  if (discoveryResult.pullRequest.discoveryMethod === "fallback") return discoveryResult;
  const fallbackNumber = Number(fallbackPrNode.number);
  if (fallbackNumber === discoveryResult.pullRequest.number) return discoveryResult;
  return {
    status: "conflict",
    pullRequest: null,
    candidates: [discoveryResult.pullRequest.number, fallbackNumber],
    reason: "FALLBACK_DISCOVERY_MISMATCH",
  };
}

/**
 * Discover PRs for ALL phases of a single Business.
 * Each phase receives the Business's fallbackPrNode.
 */
export function discoverBusinessPrs({ mapping, phaseIssueResults, fallbackPrNode }) {
  const result = { ui: null, ux: null, backend: null };

  const phases = [
    { key: "ui", issueKey: "uiPhaseIssue", phase: "ui" },
    { key: "ux", issueKey: "uxPhaseIssue", phase: "ux" },
    { key: "backend", issueKey: "bePhaseIssue", phase: "backend" },
  ];

  for (const { key, issueKey, phase } of phases) {
    const issueNum = mapping[issueKey];
    const searchPool = issueNum ? (phaseIssueResults?.[`prSearch${issueNum}`] || { nodes: [], truncated: false }) : { nodes: [], truncated: false };
    const discovery = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: issueNum || null,
      phase,
      searchResults: searchPool,
      fallbackPrNode: mapping.fallbackPrNumber ? fallbackPrNode : null,
    });
    result[key] = reconcileWithFallback(discovery, mapping.fallbackPrNumber ? fallbackPrNode : null);
  }

  return result;
}
