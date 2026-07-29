/*  business-pr-discovery.js  —  automatic PR discovery engine (Phase 2A)
 *
 *  Discovers which PR maps to each Business phase Issue.
 *  Discovery order:
 *    1. explicit machine-readable PR metadata in PR body
 *    2. PR body "Refs #<issueNumber>" references
 *    3. PR body "Related to #<issueNumber>" references
 *    4. structured Business/phase markers in PR body
 *    5. bounded branch/title convention matching
 *    6. static fallback PR pointer
 *
 *  Ambiguous matches return conflict (not guesswork).
 *  PR merge does not imply phase approval.
 */

import { getMappingByNumber } from "./business-github-map.js";

/**
 * @typedef {Object} DiscoveredPr
 * @property {number} number
 * @property {string} title
 * @property {string} state
 * @property {boolean} draft
 * @property {boolean} merged
 * @property {string} headSha
 * @property {string} baseRef
 * @property {string} updatedAt
 * @property {string} url
 * @property {string} discoveryMethod  - "refs" | "related_to" | "marker" | "branch" | "fallback"
 */

/**
 * @typedef {Object} DiscoveryResult
 * @property {"discovered"|"unavailable"|"conflict"} status
 * @property {DiscoveredPr|null} pullRequest
 * @property {number[]} [candidates]  - candidate PR numbers in case of conflict
 * @property {string} [reason]        - conflict or unavailability reason
 */

/**
 * Parse PR body for structured Business phase marker.
 * Expected format in PR body:
 *   business: <number>
 *   phase: <ui|ux|backend>
 */
function parseStructuredMarker(body) {
  if (!body) return null;
  const bizMatch = body.match(/business:\s*(\d+)/);
  const phaseMatch = body.match(/phase:\s*(ui|ux|backend)/);
  if (bizMatch && phaseMatch) {
    return { businessNumber: parseInt(bizMatch[1], 10), phase: phaseMatch[1] };
  }
  return null;
}

/**
 * Parse PR body for "Refs #<number>" references.
 */
function parseRefs(body) {
  if (!body) return [];
  const refs = [];
  const regex = /Refs\s+#(\d+)/gi;
  let match;
  while ((match = regex.exec(body)) !== null) {
    refs.push(parseInt(match[1], 10));
  }
  return refs;
}

/**
 * Parse PR body for "Related to #<number>" references.
 */
function parseRelatedTo(body) {
  if (!body) return [];
  const refs = [];
  const regex = /Related\s+to\s+#(\d+)/gi;
  let match;
  while ((match = regex.exec(body)) !== null) {
    refs.push(parseInt(match[1], 10));
  }
  return refs;
}

/**
 * Normalize a PR node from GraphQL search results.
 */
function normalizePr(node) {
  if (!node || !node.number) return null;
  return {
    number: Number(node.number),
    title: String(node.title || ""),
    state: String(node.state || "").toLowerCase(),
    draft: Boolean(node.isDraft),
    merged: Boolean(node.merged),
    headSha: String(node.headRefOid || ""),
    baseRef: String(node.baseRefName || ""),
    updatedAt: String(node.updatedAt || ""),
    url: String(node.url || ""),
    body: String(node.body || ""),
  };
}

/**
 * Discover which PR maps to a Business's phase Issue.
 *
 * @param {number} businessNumber - Business number
 * @param {number} phaseIssueNumber - Phase Issue number (UI, UX, or Backend)
 * @param {string} phase - "ui" | "ux" | "backend"
 * @param {object[]} searchResults - Array of raw PR nodes from GraphQL search
 * @param {object|null} fallbackPr - Explicit fallback PR node (from fallbackPrNumber)
 * @returns {DiscoveryResult}
 */
export function discoverPr({
  businessNumber,
  phaseIssueNumber,
  phase,
  searchResults,
  fallbackPr,
}) {
  if (!phaseIssueNumber) {
    return { status: "unavailable", pullRequest: null, reason: "NO_PHASE_ISSUE" };
  }

  const candidates = (searchResults || [])
    .map(normalizePr)
    .filter(Boolean);

  if (candidates.length === 0 && fallbackPr) {
    const pr = normalizePr(fallbackPr);
    return {
      status: "discovered",
      pullRequest: { ...pr, discoveryMethod: "fallback" },
    };
  }

  if (candidates.length === 0) {
    return { status: "unavailable", pullRequest: null, reason: "NO_PRS_FOUND" };
  }

  // 1. Try structured marker match
  const markerMatches = candidates.filter((pr) => {
    const marker = parseStructuredMarker(pr.body);
    return marker && marker.businessNumber === businessNumber && marker.phase === phase;
  });
  if (markerMatches.length === 1) {
    return {
      status: "discovered",
      pullRequest: { ...markerMatches[0], discoveryMethod: "marker" },
    };
  }
  if (markerMatches.length > 1) {
    return {
      status: "conflict",
      pullRequest: null,
      candidates: markerMatches.map((p) => p.number),
      reason: "MULTIPLE_MARKER_MATCHES",
    };
  }

  // 2. Try "Refs #issueNumber" match
  const refsMatches = candidates.filter((pr) => {
    const refs = parseRefs(pr.body);
    return refs.includes(phaseIssueNumber);
  });
  if (refsMatches.length === 1) {
    return {
      status: "discovered",
      pullRequest: { ...refsMatches[0], discoveryMethod: "refs" },
    };
  }
  if (refsMatches.length > 1) {
    return {
      status: "conflict",
      pullRequest: null,
      candidates: refsMatches.map((p) => p.number),
      reason: "MULTIPLE_REFS_MATCHES",
    };
  }

  // 3. Try "Related to #issueNumber" match
  const relatedMatches = candidates.filter((pr) => {
    const related = parseRelatedTo(pr.body);
    return related.includes(phaseIssueNumber);
  });
  if (relatedMatches.length === 1) {
    return {
      status: "discovered",
      pullRequest: { ...relatedMatches[0], discoveryMethod: "related_to" },
    };
  }
  if (relatedMatches.length > 1) {
    return {
      status: "conflict",
      pullRequest: null,
      candidates: relatedMatches.map((p) => p.number),
      reason: "MULTIPLE_RELATED_MATCHES",
    };
  }

  // 4. Try branch/title convention (conservative)
  const branchMatches = candidates.filter((pr) => {
    const title = (pr.title || "").toLowerCase();
    const refName = (pr.headRef || "").toLowerCase();
    const bizPrefix = `business-${businessNumber}`;
    const phasePrefix = `${phase}-${phaseIssueNumber}`;
    return title.includes(bizPrefix) || title.includes(phasePrefix) ||
           refName.includes(bizPrefix) || refName.includes(phasePrefix);
  });
  if (branchMatches.length === 1) {
    return {
      status: "discovered",
      pullRequest: { ...branchMatches[0], discoveryMethod: "branch" },
    };
  }
  if (branchMatches.length > 1) {
    return {
      status: "conflict",
      pullRequest: null,
      candidates: branchMatches.map((p) => p.number),
      reason: "MULTIPLE_BRANCH_MATCHES",
    };
  }

  // 5. Fall back to explicit pointer
  if (fallbackPr) {
    const pr = normalizePr(fallbackPr);
    return {
      status: "discovered",
      pullRequest: { ...pr, discoveryMethod: "fallback" },
    };
  }

  return { status: "unavailable", pullRequest: null, reason: "NO_DISCOVERY_MATCH" };
}

/**
 * Discover PRs for all phases of a single Business.
 */
export function discoverBusinessPrs({
  mapping,
  phaseIssueResults,
  fallbackPrNode,
}) {
  const result = {
    ui: null,
    ux: null,
    backend: null,
  };

  if (mapping.uiPhaseIssue) {
    const searchNodes = (phaseIssueResults[`prSearch${mapping.uiPhaseIssue}`]?.nodes || []);
    result.ui = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: mapping.uiPhaseIssue,
      phase: "ui",
      searchResults: searchNodes,
      fallbackPr: null, // ui phase doesn't use fallback
    });
  }

  if (mapping.uxPhaseIssue) {
    const searchNodes = (phaseIssueResults[`prSearch${mapping.uxPhaseIssue}`]?.nodes || []);
    result.ux = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: mapping.uxPhaseIssue,
      phase: "ux",
      searchResults: searchNodes,
      fallbackPr: null,
    });
  }

  if (mapping.bePhaseIssue) {
    const searchNodes = (phaseIssueResults[`prSearch${mapping.bePhaseIssue}`]?.nodes || []);
    result.backend = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: mapping.bePhaseIssue,
      phase: "backend",
      searchResults: searchNodes,
      fallbackPr: null,
    });
  }

  // Also try primary issue PR discovery
  if (mapping.issueNumber && mapping.issueNumber !== mapping.uiPhaseIssue) {
    const searchNodes = (phaseIssueResults[`prSearch${mapping.issueNumber}`]?.nodes || []);
    const mainPrResult = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: mapping.issueNumber,
      phase: "ui", // treat primary issue as UI phase for discovery
      searchResults: searchNodes,
      fallbackPr: fallbackPrNode,
    });
    // Only use if no specific phase PR was found
    if (!result.ui || result.ui.status === "unavailable") {
      result.ui = mainPrResult;
    }
  }

  return result;
}
