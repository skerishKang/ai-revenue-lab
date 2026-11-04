import { VERIFIED_PUBLIC_OPPORTUNITIES } from '../../src/public-supply/verified-public-opportunities.js';

/**
 * Deterministic wall clock for the curated-catalog surface tests (#6805).
 *
 * The 7-day display window is a real product rule and keeps its dedicated
 * explicit-date coverage (displayable, stale, freshness) in
 * public-supply.test.ts. The surface contracts, however, assert the curated
 * catalog's rendered content, so they used to fail on a calendar date as soon
 * as the manual re-verification constant aged past the window. Pinning the
 * evaluation instant one day after the newest `verifiedAt` in the catalog
 * keeps those assertions exact and self-updating: when the refresh owner
 * advances `verifiedAt` with a documented check, the pinned instant moves with
 * the data and no test edit is needed.
 */
export const PUBLIC_SUPPLY_TEST_NOW: Date = new Date(
  Math.max(...VERIFIED_PUBLIC_OPPORTUNITIES.map((opportunity) => Date.parse(opportunity.verifiedAt))) +
    24 * 60 * 60 * 1000,
);
