/*  business-identity-data.js  —  Shared static Business phase authority source
 *
 *  This is the SINGLE shared source for static Business identity phase status values.
 *  Both the browser manifest (business-manifest.js → window.ARL_MANIFEST)
 *  and the API handler (/api/github-status → createGitHubStatusService)
 *  derive identitySource from this same data.
 *
 *  No volatile GitHub state (Issue state, PR state, CI, SHA) is stored here.
 *  Full display identity (slug, title, koreanTitle, workspace, etc.) is in business-manifest.js only.
 */

/* c8 ignore next 3 */
const NA = {
  CANONICAL: "canonical", PROPOSED: "proposed-number", CANDIDATE: "candidate",
  EXISTING_PROJECT: "existing-project", RESERVED: "reserved", RECONCILIATION: "number-reconciliation-required",
};

const BUSINESS_PHASE_AUTHORITY = Object.freeze([
  // n, uiStatus, uxStatus, backendStatus
  { n:1,  ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:2,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
  { n:3,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
  { n:4,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"NOT_APPLICABLE" },
  { n:5,  ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:6,  ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:7,  ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:8,  ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:9,  ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"FROZEN" },
  { n:10, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:11, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:12, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:13, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"DECISION_PENDING" },
  { n:14, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IN_PROGRESS" },
  { n:15, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:16, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:17, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:18, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:19, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:20, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:21, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:22, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:23, ui:"UI_APPROVED",   ux:"IN_PROGRESS",    be:"IMPLEMENTED" },
  { n:24, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
  { n:25, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:26, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:27, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:28, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:29, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:30, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:31, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:32, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:33, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:34, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:35, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:36, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:37, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:38, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:39, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:40, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:41, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:42, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:43, ui:"IN_PROGRESS",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:44, ui:"UI_APPROVED",   ux:"NOT_STARTED",    be:"IMPLEMENTED" },
  { n:45, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:46, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:47, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:48, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:49, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:50, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:51, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:52, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:53, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:54, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
  { n:55, ui:"NOT_STARTED",   ux:"BLOCKED_BY_UI",  be:"FROZEN" },
]);

/**
 * Build identitySource for createGitHubStatusService.
 * Returns a plain object keyed by Business number with {uiStatus, uxStatus, backendStatus}.
 */
export function buildIdentitySource() {
  const map = {};
  for (const entry of BUSINESS_PHASE_AUTHORITY) {
    map[entry.n] = { uiStatus: entry.ui, uxStatus: entry.ux, backendStatus: entry.be };
  }
  return map;
}
