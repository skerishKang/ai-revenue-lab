/*  business-verdict-parser.js  —  machine-readable phase verdict parser (Phase 2A)
 *
 *  Parses structured HTML comment blocks from Issue/PR bodies:
 *
 *    <!-- portfolio-verdict
 *    business: 15
 *    phase: ui
 *    verdict: UI_APPROVED
 *    accepted_head: abcdef1234567890abcdef1234567890abcdef12
 *    -->
 *
 *  Rules:
 *    - Phase and verdict series must be compatible (ui → UI_*, ux → UX_*, backend → BACKEND_*)
 *    - accepted_head required for approval verdicts
 *    - Multiple conflicting verdicts → conflict status
 *    - Missing verdict → unverified
 *    - PR merge does not imply approval
 *    - Deployment does not imply release
 */

/**
 * @typedef {Object} VerdictResult
 * @property {"verified"|"unverified"|"invalid"|"conflict"} status
 * @property {string|null} verdict  - e.g. "UI_APPROVED", "UX_NOT_READY", etc.
 * @property {string|null} acceptedHead - SHA of accepted head
 * @property {string|null} source - where the verdict was found: "issue_body" | "pr_body" | "static_fallback"
 * @property {string|null} [reason] - error reason for invalid/conflict
 */

const VALID_VERDICTS = {
  ui: ["UI_NOT_READY", "UI_CONDITIONALLY_READY", "UI_APPROVED"],
  ux: ["UX_NOT_READY", "UX_CONDITIONALLY_READY", "UX_APPROVED"],
  backend: ["BACKEND_FROZEN", "BACKEND_DEFERRED", "BACKEND_AUTHORIZED", "BACKEND_IN_PROGRESS", "BACKEND_IMPLEMENTED"],
};

const VERDICTS_REQUIRING_HEAD = new Set(["UI_APPROVED", "UX_APPROVED", "BACKEND_AUTHORIZED", "BACKEND_IMPLEMENTED"]);

const SHA_HEX = /^[0-9a-f]{40}$/;

/**
 * Parse a single verdict block from a string.
 * @param {string} text - Text containing <!-- portfolio-verdict ... --> block
 * @returns {VerdictResult|null}
 */
export function parseVerdictBlock(text) {
  if (!text) return null;

  const regex = /<!--\s*portfolio-verdict\s*([\s\S]*?)-->/g;
  const matches = [];
  let match;
  while ((match = regex.exec(text)) !== null) {
    matches.push(match[1]);
  }

  if (matches.length === 0) return null;

  const results = [];

  for (const block of matches) {
    const businessMatch = block.match(/business:\s*(\d+)/);
    const phaseMatch = block.match(/phase:\s*(ui|ux|backend)/);
    const verdictMatch = block.match(/verdict:\s*(\S+)/);
    const headMatch = block.match(/accepted_head:\s*(\S+)/);

    const phase = phaseMatch ? phaseMatch[1] : null;
    const verdict = verdictMatch ? verdictMatch[1].trim() : null;
    const acceptedHead = headMatch ? headMatch[1].trim() : null;

    if (!phase || !verdict) {
      results.push({ status: "invalid", verdict: null, acceptedHead: null, source: null, reason: "INCOMPLETE_BLOCK" });
      continue;
    }

    // Phase/verdict compatibility check
    const validForPhase = VALID_VERDICTS[phase];
    if (!validForPhase || !validForPhase.includes(verdict)) {
      results.push({ status: "invalid", verdict, acceptedHead, source: null, reason: `INVALID_VERDICT_PHASE: phase=${phase} verdict=${verdict}` });
      continue;
    }

    // accepted_head validation for approval verdicts
    if (VERDICTS_REQUIRING_HEAD.has(verdict)) {
      if (!acceptedHead || !SHA_HEX.test(acceptedHead)) {
        results.push({ status: "invalid", verdict, acceptedHead, source: null, reason: "MISSING_OR_INVALID_ACCEPTED_HEAD" });
        continue;
      }
    }

    results.push({ status: "verified", verdict, acceptedHead, source: null, reason: null });
  }

  if (results.length === 0) return null;

  // Multiple results → conflict if they differ
  const uniqueVerdicts = new Set(results.filter((r) => r.status === "verified").map((r) => r.verdict));
  if (uniqueVerdicts.size > 1) {
    return { status: "conflict", verdict: null, acceptedHead: null, source: null, reason: "MULTIPLE_CONFLICTING_VERDICTS" };
  }

  const verified = results.find((r) => r.status === "verified");
  if (verified) return verified;

  // Return first invalid if no verified
  return results[0];
}

/**
 * Resolve the phase verdict for a Business's phase.
 * Merges: parsed issue body → parsed PR body → static fallback.
 *
 * @param {object} options
 * @param {object|null} options.issueData - Issue data from GitHub API
 * @param {object|null} options.prData - PR data from GitHub API
 * @param {string|null} options.staticFallback - Static fallback verdict (from manifest)
 * @returns {VerdictResult}
 */
export function resolvePhaseVerdict({ issueData, prData, staticFallback }) {
  // 1. Try issue body
  if (issueData?.body) {
    const issueVerdict = parseVerdictBlock(issueData.body);
    if (issueVerdict && (issueVerdict.status === "verified" || issueVerdict.status === "conflict")) {
      return { ...issueVerdict, source: "issue_body" };
    }
  }

  // 2. Try PR body (PR may have the latest verdict)
  if (prData?.body) {
    const prVerdict = parseVerdictBlock(prData.body);
    if (prVerdict && (prVerdict.status === "verified" || prVerdict.status === "conflict")) {
      return { ...prVerdict, source: "pr_body" };
    }
  }

  // 3. Static fallback
  if (staticFallback) {
    return { status: "unverified", verdict: staticFallback, acceptedHead: null, source: "static_fallback", reason: "STATIC_FALLBACK_NOT_MACHINE_VERIFIED" };
  }

  return { status: "unverified", verdict: null, acceptedHead: null, source: null, reason: "NO_VERDICT_FOUND" };
}

/**
 * Check if a verdict represents an approved state.
 */
export function isApprovedVerdict(verdict) {
  if (!verdict) return false;
  return verdict === "UI_APPROVED" || verdict === "UX_APPROVED" || verdict === "BACKEND_AUTHORIZED" || verdict === "BACKEND_IMPLEMENTED";
}

/**
 * Get all valid verdicts for a phase.
 */
export function getValidVerdicts(phase) {
  return VALID_VERDICTS[phase] || [];
}
