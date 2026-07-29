/*  business-identity-data.js  —  ESM wrapper over the single phase authority source
 *
 *  The canonical data lives in business-identity-core.js (UMD), which the
 *  browser loads as a classic script (window.ARL_IDENTITY_CORE) before
 *  business-manifest.js derives uiStatus/uxStatus/backendStatus from it.
 *
 *  Server code imports this wrapper so /api/github-status and the browser
 *  manifest can never drift: both resolve the same frozen table.
 *
 *  No volatile GitHub state (Issue state, PR state, CI, SHA) is stored here.
 */

import identityCore from "./business-identity-core.js";

export const BUSINESS_PHASE_AUTHORITY = identityCore.BUSINESS_PHASE_AUTHORITY;

/**
 * Build identitySource for createGitHubStatusService.
 * Returns a plain object keyed by Business number with {uiStatus, uxStatus, backendStatus}.
 */
export function buildIdentitySource() {
  return identityCore.buildIdentitySource();
}
