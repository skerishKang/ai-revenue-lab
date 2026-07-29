/*  business-github-map.js  —  B1–55 durable GitHub mapping (Phase 2A)
 *
 *  One-time mapping cost: Business number → repository + phase Issue pointers.
 *  Contains NO volatile state (no Issue state, PR state, CI, SHA, updated-at).
 *
 *  Each entry identifies:
 *    repository          — GitHub repository
 *    issueNumber         — product-decision Issue (primary durable pointer)
 *    uiPhaseIssue        — Phase 1 UI Issue number (null if absent)
 *    uxPhaseIssue        — Phase 2 UX Issue number (null if absent)
 *    bePhaseIssue        — Phase 3 Backend Issue number (null if absent)
 *    fallbackPrNumber    — explicit PR pointer (only when auto-discovery impossible)
 *
 *  PR #193 original contract preserved:
 *    - fixed repository allowlist
 *    - assertAllowedRepository enforcement
 */

export const GITHUB_REPOSITORY = "skerishKang/ai-revenue-lab";

export const ALLOWED_REPOSITORIES = Object.freeze([GITHUB_REPOSITORY]);

/**
 * @typedef {Object} BusinessGithubMapping
 * @property {number} number       - Business 1–55
 * @property {string} repository   - "skerishKang/ai-revenue-lab"
 * @property {number} issueNumber  - product-decision Issue number
 * @property {number|null} uiPhaseIssue   - Phase 1 UI Issue (null if absent)
 * @property {number|null} uxPhaseIssue   - Phase 2 UX Issue (null if absent)
 * @property {number|null} bePhaseIssue   - Phase 3 Backend Issue (null if absent)
 * @property {number|null} fallbackPrNumber - explicit PR pointer (auto-discovery fallback)
 */

/** @type {readonly BusinessGithubMapping[]} */
export const BUSINESS_GITHUB_MAP = Object.freeze([
  // ── 1–4: CANONICAL  ──
  { number: 1,  repository: GITHUB_REPOSITORY, issueNumber: 108, uiPhaseIssue: 108, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 111 },
  { number: 2,  repository: GITHUB_REPOSITORY, issueNumber: 43,  uiPhaseIssue: 107, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 88 },
  { number: 3,  repository: GITHUB_REPOSITORY, issueNumber: 55,  uiPhaseIssue: 75,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 85 },
  { number: 4,  repository: GITHUB_REPOSITORY, issueNumber: 37,  uiPhaseIssue: 37,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 94 },
  // ── 5–6  ──
  { number: 5,  repository: GITHUB_REPOSITORY, issueNumber: 99,  uiPhaseIssue: 99,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 109 },
  { number: 6,  repository: GITHUB_REPOSITORY, issueNumber: 98,  uiPhaseIssue: 98,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  // ── 7–12  ──
  { number: 7,  repository: GITHUB_REPOSITORY, issueNumber: 166, uiPhaseIssue: 166, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 174 },
  { number: 8,  repository: GITHUB_REPOSITORY, issueNumber: 168, uiPhaseIssue: 168, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 176 },
  { number: 9,  repository: GITHUB_REPOSITORY, issueNumber: 170, uiPhaseIssue: 170, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 175 },
  { number: 10, repository: GITHUB_REPOSITORY, issueNumber: 171, uiPhaseIssue: 171, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 177 },
  { number: 11, repository: GITHUB_REPOSITORY, issueNumber: 172, uiPhaseIssue: 172, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 179 },
  { number: 12, repository: GITHUB_REPOSITORY, issueNumber: 173, uiPhaseIssue: 173, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 178 },
  // ── 13–14: CANONICAL  ──
  { number: 13, repository: GITHUB_REPOSITORY, issueNumber: 76,  uiPhaseIssue: 76,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 78 },
  { number: 14, repository: GITHUB_REPOSITORY, issueNumber: 80,  uiPhaseIssue: 138, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 142 },
  // ── 15–22: product-decision + Phase 1 UI issues  ──
  { number: 15, repository: GITHUB_REPOSITORY, issueNumber: 187, uiPhaseIssue: 188, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 16, repository: GITHUB_REPOSITORY, issueNumber: 189, uiPhaseIssue: 190, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 17, repository: GITHUB_REPOSITORY, issueNumber: 191, uiPhaseIssue: 192, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 18, repository: GITHUB_REPOSITORY, issueNumber: 196, uiPhaseIssue: 197, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 19, repository: GITHUB_REPOSITORY, issueNumber: 198, uiPhaseIssue: 199, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 20, repository: GITHUB_REPOSITORY, issueNumber: 200, uiPhaseIssue: 201, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 21, repository: GITHUB_REPOSITORY, issueNumber: 204, uiPhaseIssue: 205, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 22, repository: GITHUB_REPOSITORY, issueNumber: 222, uiPhaseIssue: 223, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  // ── 23–25: existing-project (separate repos)  ──
  { number: 23, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 24, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 25, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  // ── 26–35: product-decision + Phase 1 UI issues  ──
  { number: 26, repository: GITHUB_REPOSITORY, issueNumber: 226, uiPhaseIssue: 227, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 27, repository: GITHUB_REPOSITORY, issueNumber: 230, uiPhaseIssue: 231, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 28, repository: GITHUB_REPOSITORY, issueNumber: 234, uiPhaseIssue: 235, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 29, repository: GITHUB_REPOSITORY, issueNumber: 236, uiPhaseIssue: 237, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 30, repository: GITHUB_REPOSITORY, issueNumber: 240, uiPhaseIssue: 242, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 31, repository: GITHUB_REPOSITORY, issueNumber: 241, uiPhaseIssue: 243, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 32, repository: GITHUB_REPOSITORY, issueNumber: 246, uiPhaseIssue: 248, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 33, repository: GITHUB_REPOSITORY, issueNumber: 247, uiPhaseIssue: 249, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 34, repository: GITHUB_REPOSITORY, issueNumber: 252, uiPhaseIssue: 254, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 35, repository: GITHUB_REPOSITORY, issueNumber: 253, uiPhaseIssue: 255, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  // ── 36–43: product-decision + Phase 1 UI issues  ──
  { number: 36, repository: GITHUB_REPOSITORY, issueNumber: 266, uiPhaseIssue: 268, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 37, repository: GITHUB_REPOSITORY, issueNumber: 259, uiPhaseIssue: 260, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 38, repository: GITHUB_REPOSITORY, issueNumber: 267, uiPhaseIssue: 269, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 39, repository: GITHUB_REPOSITORY, issueNumber: 261, uiPhaseIssue: 262, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 40, repository: GITHUB_REPOSITORY, issueNumber: 270, uiPhaseIssue: 272, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 41, repository: GITHUB_REPOSITORY, issueNumber: 271, uiPhaseIssue: 273, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 42, repository: GITHUB_REPOSITORY, issueNumber: 274, uiPhaseIssue: 276, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 43, repository: GITHUB_REPOSITORY, issueNumber: 275, uiPhaseIssue: 277, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  // ── 44: portfolio-console (existing-project)  ──
  { number: 44, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  // ── 45–55: candidate backlog (no mapped issues yet)  ──
  { number: 45, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 46, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 47, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 48, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 49, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 50, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 51, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 52, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 53, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 54, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
  { number: 55, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
]);

/** Convenience: get mapping by Business number */
export function getMappingByNumber(number) {
  return BUSINESS_GITHUB_MAP.find((m) => m.number === number) || null;
}

/** Convenience: get all mapped Business numbers */
export function getMappedNumbers() {
  return BUSINESS_GITHUB_MAP.map((m) => m.number);
}

/** Verify a repository string is in the allowlist */
export function assertAllowedRepository(repository) {
  if (!ALLOWED_REPOSITORIES.includes(repository)) {
    const error = new Error("Repository is not allowlisted.");
    error.code = "REPOSITORY_NOT_ALLOWED";
    throw error;
  }
  return repository;
}
