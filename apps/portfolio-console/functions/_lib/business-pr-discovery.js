/*  business-pr-discovery.js  —  automatic PR discovery (Phase 2A)
 *
 *  Discovery order per phase:
 *    1. structured Business/phase marker in PR body
 *    2. "Refs #issueNumber" in PR body
 *    3. "Related to #issueNumber" in PR body
 *    4. branch/title convention matching (headRefName)
 *    5. static fallback PR pointer
 *
 *  Ambiguous matches → conflict (never guess).
 *  PR merge does not imply phase approval.
 */

import { getMappingByNumber } from "./business-github-map.js";

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

function normalizePr(node) {
  if (!node || !node.number) return null;
  return {
    number: Number(node.number),
    title: String(node.title || ""),
    state: String(node.state || "").toLowerCase(),
    draft: Boolean(node.isDraft),
    merged: Boolean(node.merged),
    headSha: String(node.headRefOid || ""),
    headRef: String(node.headRefName || ""),
    baseRef: String(node.baseRefName || ""),
    updatedAt: String(node.updatedAt || ""),
    url: String(node.url || ""),
    body: String(node.body || ""),
    commits: node.commits || null,
  };
}

/**
 * Discover which PR maps to a Business's phase Issue.
 * @param {number} businessNumber
 * @param {number} phaseIssueNumber - The phase Issue number to discover PR for
 * @param {string} phase - "ui" | "ux" | "backend"
 * @param {object[]} searchResults - Array of raw PR nodes from prSearch{N} search
 * @param {object|null} fallbackPrNode - Explicit fallback PR node from fallbackPr{N}
 * @returns {{status:"discovered"|"unavailable"|"conflict", pullRequest:object|null, candidates?:number[], reason?:string}}
 */
export function discoverPr({
  businessNumber,
  phaseIssueNumber,
  phase,
  searchResults,
  fallbackPrNode,
}) {
  if (!phaseIssueNumber) {
    return { status: "unavailable", pullRequest: null, reason: "NO_PHASE_ISSUE" };
  }

  const candidates = (searchResults || []).map(normalizePr).filter(Boolean);

  // ── 1. Structured marker match ──
  const markerMatches = candidates.filter((pr) => {
    const marker = parseStructuredMarker(pr.body);
    return marker && marker.businessNumber === businessNumber && marker.phase === phase;
  });
  if (markerMatches.length === 1) return { status: "discovered", pullRequest: { ...markerMatches[0], discoveryMethod: "marker" } };
  if (markerMatches.length > 1) return { status: "conflict", pullRequest: null, candidates: markerMatches.map((p) => p.number), reason: "MULTIPLE_MARKER_MATCHES" };

  // ── 2. Refs #issueNumber match ──
  const refsMatches = candidates.filter((pr) => parseRefs(pr.body).includes(phaseIssueNumber));
  if (refsMatches.length === 1) return { status: "discovered", pullRequest: { ...refsMatches[0], discoveryMethod: "refs" } };
  if (refsMatches.length > 1) return { status: "conflict", pullRequest: null, candidates: refsMatches.map((p) => p.number), reason: "MULTIPLE_REFS_MATCHES" };

  // ── 3. Related to #issueNumber match ──
  const relatedMatches = candidates.filter((pr) => parseRelatedTo(pr.body).includes(phaseIssueNumber));
  if (relatedMatches.length === 1) return { status: "discovered", pullRequest: { ...relatedMatches[0], discoveryMethod: "related_to" } };
  if (relatedMatches.length > 1) return { status: "conflict", pullRequest: null, candidates: relatedMatches.map((p) => p.number), reason: "MULTIPLE_RELATED_MATCHES" };

  // ── 4. Branch/title convention (headRefName) ──
  const branchMatches = candidates.filter((pr) => {
    const title = (pr.title || "").toLowerCase();
    const ref = (pr.headRef || "").toLowerCase();
    const bizPrefix = `business-${businessNumber}`;
    const phasePrefix = `${phase}-${phaseIssueNumber}`;
    return title.includes(bizPrefix) || title.includes(phasePrefix) || ref.includes(bizPrefix) || ref.includes(phasePrefix);
  });
  if (branchMatches.length === 1) return { status: "discovered", pullRequest: { ...branchMatches[0], discoveryMethod: "branch" } };
  if (branchMatches.length > 1) return { status: "conflict", pullRequest: null, candidates: branchMatches.map((p) => p.number), reason: "MULTIPLE_BRANCH_MATCHES" };

  // ── 5. Static fallback PR pointer ──
  if (fallbackPrNode && fallbackPrNode.number) {
    const pr = normalizePr(fallbackPrNode);
    return { status: "discovered", pullRequest: { ...pr, discoveryMethod: "fallback" } };
  }

  return { status: "unavailable", pullRequest: null, reason: "NO_DISCOVERY_MATCH" };
}

/**
 * Discover PRs for ALL phases of a single Business.
 * Each phase receives the Business's fallbackPrNumber.
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
    if (!issueNum) continue;

    const searchNodes = (phaseIssueResults?.[`prSearch${issueNum}`]?.nodes || []);
    result[key] = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: issueNum,
      phase,
      searchResults: searchNodes,
      fallbackPrNode: mapping.fallbackPrNumber ? fallbackPrNode : null,
    });
  }

  // For phases without their own Issue, try primary issue number
  // This handles B1-B14 where issueNumber === uiPhaseIssue
  if (!result.ui && mapping.issueNumber) {
    const searchNodes = (phaseIssueResults?.[`prSearch${mapping.issueNumber}`]?.nodes || []);
    result.ui = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: mapping.issueNumber,
      phase: "ui",
      searchResults: searchNodes,
      fallbackPrNode: mapping.fallbackPrNumber ? fallbackPrNode : null,
    });
  }

  return result;
}
