/*  business-verdict-parser.js  —  phase verdict parser with Business/phase binding (Phase 2A)
 *
 *  Parses structured HTML comment blocks:
 *
 *    <!-- portfolio-verdict
 *    business: 15
 *    phase: ui
 *    verdict: UI_APPROVED
 *    accepted_head: abcdef1234567890abcdef1234567890abcdef12
 *    -->
 *
 *  Key changes:
 *    - Binds verdicts to expectedBusinessNumber + expectedPhase
 *    - Rejects blocks for other Businesses/phases
 *    - Detects conflicts across verdict, accepted_head, and source
 *    - PR merge/deployment never creates approval
 */

import { getMappingByNumber } from "./business-github-map.js";

const VALID_VERDICTS = {
  ui: ["UI_NOT_READY", "UI_CONDITIONALLY_READY", "UI_APPROVED"],
  ux: ["UX_NOT_READY", "UX_CONDITIONALLY_READY", "UX_APPROVED"],
  backend: ["BACKEND_FROZEN", "BACKEND_DEFERRED", "BACKEND_AUTHORIZED", "BACKEND_IN_PROGRESS", "BACKEND_IMPLEMENTED"],
};

const VERDICTS_REQUIRING_HEAD = new Set(["UI_APPROVED", "UX_APPROVED", "BACKEND_AUTHORIZED", "BACKEND_IMPLEMENTED"]);
const SHA_HEX = /^[0-9a-f]{40}$/;

/**
 * @typedef {Object} VerdictResult
 * @property {"verified"|"unverified"|"invalid"|"conflict"} status
 * @property {string|null} verdict
 * @property {string|null} acceptedHead
 * @property {string|null} source  - "issue_body" | "pr_body" | "static_fallback"
 * @property {number|null} businessNumber
 * @property {string|null} phase
 * @property {string|null} reason
 */

/**
 * Parse verdict blocks from text and filter by expected Business/phase.
 * Returns `null` when no matching block exists (not even invalid ones).
 */
function parseVerdictBlocks(text, expectedBusinessNumber, expectedPhase) {
  if (!text) return [];

  const regex = /<!--\s*portfolio-verdict\s*([\s\S]*?)-->/g;
  const results = [];
  let match;
  while ((match = regex.exec(text)) !== null) {
    const block = match[1];
    const businessNum = parseInt(block.match(/business:\s*(\d+)/)?.[1], 10);
    const phase = block.match(/phase:\s*(ui|ux|backend)/)?.[1];
    const verdict = block.match(/verdict:\s*(\S+)/)?.[1]?.trim() || null;
    const acceptedHead = block.match(/accepted_head:\s*(\S+)/)?.[1]?.trim() || null;

    // Skip blocks for other Businesses/phases
    if (businessNum !== expectedBusinessNumber || phase !== expectedPhase) continue;

    // Incomplete block
    if (!businessNum || !phase || !verdict) {
      results.push({ status: "invalid", verdict: null, acceptedHead: null, businessNumber: businessNum, phase, source: null, reason: "INCOMPLETE_BLOCK" });
      continue;
    }

    // Phase/verdict compatibility
    const validForPhase = VALID_VERDICTS[phase];
    if (!validForPhase || !validForPhase.includes(verdict)) {
      results.push({ status: "invalid", verdict, acceptedHead, businessNumber: businessNum, phase, source: null, reason: `INVALID_VERDICT_PHASE: phase=${phase} verdict=${verdict}` });
      continue;
    }

    // accepted_head validation
    if (VERDICTS_REQUIRING_HEAD.has(verdict)) {
      if (!acceptedHead || !SHA_HEX.test(acceptedHead)) {
        results.push({ status: "invalid", verdict, acceptedHead, businessNumber: businessNum, phase, source: null, reason: "MISSING_OR_INVALID_ACCEPTED_HEAD" });
        continue;
      }
    }

    results.push({ status: "verified", verdict, acceptedHead, businessNumber: businessNum, phase, source: null, reason: null });
  }

  return results;
}

/**
 * Resolve phase verdict from a pool of sources (issue body, PR body, static fallback).
 * Filters by expected Business number and phase.
 *
 * Conflict rules:
 *   - Same Business/phase, different verdicts → conflict
 *   - Same verdict, different accepted_heads → conflict
 *   - PR merge does not equal approval
 */
export function resolvePhaseVerdictFromPool({
  expectedBusinessNumber,
  expectedPhase,
  issueBody,
  prBody,
  staticFallback,
}) {
  const allBlocks = [];

  // Parse issue body blocks
  if (issueBody) {
    allBlocks.push(...parseVerdictBlocks(issueBody, expectedBusinessNumber, expectedPhase).map((b) => ({ ...b, source: "issue_body" })));
  }

  // Parse PR body blocks
  if (prBody) {
    allBlocks.push(...parseVerdictBlocks(prBody, expectedBusinessNumber, expectedPhase).map((b) => ({ ...b, source: "pr_body" })));
  }

  // Separate into categories
  const verified = allBlocks.filter((b) => b.status === "verified");
  const invalid = allBlocks.filter((b) => b.status === "invalid");

  // Different verdicts → conflict
  const uniqueVerdicts = new Set(verified.map((b) => b.verdict));
  if (uniqueVerdicts.size > 1) {
    return { status: "conflict", verdict: null, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: null, reason: "MULTIPLE_CONFLICTING_VERDICTS" };
  }

  // Same verdict, different accepted_heads → conflict
  if (verified.length >= 2) {
    const heads = new Set(verified.map((b) => b.acceptedHead));
    if (heads.size > 1) {
      return { status: "conflict", verdict: verified[0].verdict, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: null, reason: "CONFLICTING_ACCEPTED_HEADS" };
    }
  }

  // Single verified verdict
  if (verified.length === 1) {
    return verified[0];
  }

  // Static fallback (explicitly marked unverified)
  if (staticFallback) {
    return { status: "unverified", verdict: staticFallback, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: "static_fallback", reason: "STATIC_FALLBACK_NOT_MACHINE_VERIFIED" };
  }

  // Invalid blocks but no verified ones → diagnostics
  if (invalid.length > 0) {
    return { ...invalid[0], businessNumber: expectedBusinessNumber, phase: expectedPhase, source: invalid[0].source || null };
  }

  return { status: "unverified", verdict: null, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: null, reason: "NO_VERDICT_FOUND" };
}

/** Check if a verdict represents an approved state */
export function isApprovedVerdict(verdict) {
  if (!verdict) return false;
  return verdict === "UI_APPROVED" || verdict === "UX_APPROVED" || verdict === "BACKEND_AUTHORIZED" || verdict === "BACKEND_IMPLEMENTED";
}

/** Get valid verdicts for a phase */
export function getValidVerdicts(phase) {
  return VALID_VERDICTS[phase] || [];
}

// Backward compatibility export
export const parseVerdictBlock = parseVerdictBlocks;
export const resolvePhaseVerdict = resolvePhaseVerdictFromPool;
