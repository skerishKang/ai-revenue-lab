/*  business-github-map.js  —  B1–55 durable GitHub mapping (Phase 2A)
 *
 *  One-time mapping cost: Business number → repository + phase Issue pointers.
 *  Contains NO volatile state (no Issue state, PR state, CI, SHA, updated-at).
 *
 *  PR #193 original contract preserved:
 *    - fixed repository allowlist
 *    - assertAllowedRepository enforcement
 */

export const GITHUB_REPOSITORY = "skerishKang/ai-revenue-lab";

export const ALLOWED_REPOSITORIES = Object.freeze([GITHUB_REPOSITORY]);

/** @type {readonly {number:number,repository:string|null,issueNumber:number|null,uiPhaseIssue:number|null,uxPhaseIssue:number|null,bePhaseIssue:number|null,fallbackPrNumbers:{ui:number|null,ux:number|null,backend:number|null}|null}[]} */
export const BUSINESS_GITHUB_MAP = Object.freeze([
  // ── 1–4: CANONICAL  ──
  { number: 1,  repository: GITHUB_REPOSITORY, issueNumber: 108, uiPhaseIssue: 108, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 111, ux: null, backend: null } },
  { number: 2,  repository: GITHUB_REPOSITORY, issueNumber: 43,  uiPhaseIssue: 107, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 88, ux: null, backend: null } },
  { number: 3,  repository: GITHUB_REPOSITORY, issueNumber: 55,  uiPhaseIssue: 75,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 85, ux: null, backend: null } },
  { number: 4,  repository: GITHUB_REPOSITORY, issueNumber: 37,  uiPhaseIssue: 37,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 94, ux: null, backend: null } },
  // ── 5–6  ──
  { number: 5,  repository: GITHUB_REPOSITORY, issueNumber: 99,  uiPhaseIssue: 99,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 109, ux: null, backend: null } },
  { number: 6,  repository: GITHUB_REPOSITORY, issueNumber: 98,  uiPhaseIssue: 155, uxPhaseIssue: 165, bePhaseIssue: null, fallbackPrNumbers: null },
  // ── 7–12  ──
  { number: 7,  repository: GITHUB_REPOSITORY, issueNumber: 166, uiPhaseIssue: 166, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 174, ux: null, backend: null } },
  { number: 8,  repository: GITHUB_REPOSITORY, issueNumber: 168, uiPhaseIssue: 168, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 176, ux: null, backend: null } },
  { number: 9,  repository: GITHUB_REPOSITORY, issueNumber: 170, uiPhaseIssue: 170, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 175, ux: null, backend: null } },
  { number: 10, repository: GITHUB_REPOSITORY, issueNumber: 171, uiPhaseIssue: 171, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 177, ux: null, backend: null } },
  { number: 11, repository: GITHUB_REPOSITORY, issueNumber: 172, uiPhaseIssue: 172, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 179, ux: null, backend: null } },
  { number: 12, repository: GITHUB_REPOSITORY, issueNumber: 173, uiPhaseIssue: 173, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 178, ux: null, backend: null } },
  // ── 13–14: CANONICAL  ──
  { number: 13, repository: GITHUB_REPOSITORY, issueNumber: 76,  uiPhaseIssue: 76,  uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 78, ux: null, backend: null } },
  { number: 14, repository: GITHUB_REPOSITORY, issueNumber: 80,  uiPhaseIssue: 138, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: { ui: 142, ux: null, backend: null } },
  // ── 15–22  ──
  { number: 15, repository: GITHUB_REPOSITORY, issueNumber: 187, uiPhaseIssue: 188, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 16, repository: GITHUB_REPOSITORY, issueNumber: 189, uiPhaseIssue: 190, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 17, repository: GITHUB_REPOSITORY, issueNumber: 191, uiPhaseIssue: 192, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 18, repository: GITHUB_REPOSITORY, issueNumber: 196, uiPhaseIssue: 197, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 19, repository: GITHUB_REPOSITORY, issueNumber: 198, uiPhaseIssue: 199, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 20, repository: GITHUB_REPOSITORY, issueNumber: 200, uiPhaseIssue: 201, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 21, repository: GITHUB_REPOSITORY, issueNumber: 204, uiPhaseIssue: 205, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 22, repository: GITHUB_REPOSITORY, issueNumber: 222, uiPhaseIssue: 223, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  // ── 23–25: existing-project (separate repos)  ──
  { number: 23, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 24, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 25, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  // ── 26–35  ──
  { number: 26, repository: GITHUB_REPOSITORY, issueNumber: 226, uiPhaseIssue: 227, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 27, repository: GITHUB_REPOSITORY, issueNumber: 230, uiPhaseIssue: 231, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 28, repository: GITHUB_REPOSITORY, issueNumber: 234, uiPhaseIssue: 235, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 29, repository: GITHUB_REPOSITORY, issueNumber: 236, uiPhaseIssue: 237, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 30, repository: GITHUB_REPOSITORY, issueNumber: 240, uiPhaseIssue: 242, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 31, repository: GITHUB_REPOSITORY, issueNumber: 241, uiPhaseIssue: 243, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 32, repository: GITHUB_REPOSITORY, issueNumber: 246, uiPhaseIssue: 248, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 33, repository: GITHUB_REPOSITORY, issueNumber: 247, uiPhaseIssue: 249, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 34, repository: GITHUB_REPOSITORY, issueNumber: 252, uiPhaseIssue: 254, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 35, repository: GITHUB_REPOSITORY, issueNumber: 253, uiPhaseIssue: 255, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  // ── 36–43: product-decision + Phase 1 UI issues  ──
  { number: 36, repository: GITHUB_REPOSITORY, issueNumber: 266, uiPhaseIssue: 268, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 37, repository: GITHUB_REPOSITORY, issueNumber: 259, uiPhaseIssue: 260, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 38, repository: GITHUB_REPOSITORY, issueNumber: 267, uiPhaseIssue: 269, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 39, repository: GITHUB_REPOSITORY, issueNumber: 261, uiPhaseIssue: 262, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 40, repository: GITHUB_REPOSITORY, issueNumber: 270, uiPhaseIssue: 272, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 41, repository: GITHUB_REPOSITORY, issueNumber: 271, uiPhaseIssue: 273, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 42, repository: GITHUB_REPOSITORY, issueNumber: 274, uiPhaseIssue: 276, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 43, repository: GITHUB_REPOSITORY, issueNumber: 275, uiPhaseIssue: 277, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  // ── 44: portfolio-console (existing-project)  ──
  { number: 44, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  // ── 45–55: candidate backlog (no mapped issues yet)  ──
  { number: 45, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 46, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 47, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 48, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 49, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 50, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 51, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 52, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 53, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 54, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
  { number: 55, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumbers: null },
]);

/** Get mapping by Business number */
export function getMappingByNumber(number) {
  return BUSINESS_GITHUB_MAP.find((m) => m.number === number) || null;
}

/** Get all mapped Business numbers */
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
