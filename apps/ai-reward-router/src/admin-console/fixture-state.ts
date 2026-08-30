import {
  AI_DATA_WORK_FIXTURE,
  MATERIAL_CHANGE_FIXTURE,
  MICRO_REWARD_FIXTURE,
  PAID_RESEARCH_FIXTURE,
  UNKNOWN_COMPENSATION_FIXTURE,
  type OpportunityFixtureBundle,
} from '../persistence/fixtures.js';
import {
  CURRENT_SOURCE_COLLECTION_GATES,
  CURRENT_SOURCE_POLICY_REVIEWS,
  CURRENT_SOURCE_REGISTRY,
} from '../source-policy/registry.js';
import type { AdminConsoleState, StaleBrokenRecord } from './domain.js';

const bundles: readonly OpportunityFixtureBundle[] = [
  MICRO_REWARD_FIXTURE,
  PAID_RESEARCH_FIXTURE,
  AI_DATA_WORK_FIXTURE,
  UNKNOWN_COMPENSATION_FIXTURE,
];

const STALE_FIXTURE: StaleBrokenRecord = Object.freeze({
  id: 'stale-fixture-usertesting',
  sourceId: 'SRC-USERTESTING',
  offerId: 'offer-fixture-unknown',
  cause: 'SOURCE_PAGE_UNAVAILABLE',
  detail: 'Synthetic W7 fixture: source evidence is temporarily unavailable.',
  detectedAt: '2026-08-30T00:00:00.000Z',
  state: 'OPEN',
});

export function createAdminConsoleFixtureState(): AdminConsoleState {
  return Object.freeze({
    sources: Object.freeze([...CURRENT_SOURCE_REGISTRY]),
    policies: Object.freeze([...CURRENT_SOURCE_POLICY_REVIEWS]),
    gates: Object.freeze([...CURRENT_SOURCE_COLLECTION_GATES]),
    snapshots: Object.freeze(bundles.map((bundle) => bundle.snapshot)),
    opportunities: Object.freeze([
      ...bundles.map((bundle) => bundle.opportunity),
      MATERIAL_CHANGE_FIXTURE.opportunity,
    ]),
    versions: Object.freeze([
      ...bundles.flatMap((bundle) => bundle.versions),
      ...MATERIAL_CHANGE_FIXTURE.versions,
    ]),
    evidence: Object.freeze(bundles.flatMap((bundle) => bundle.evidence)),
    reviewQueue: Object.freeze([
      ...bundles.flatMap((bundle) => bundle.reviewQueue),
      ...MATERIAL_CHANGE_FIXTURE.reviewQueue,
    ]),
    changes: Object.freeze([MATERIAL_CHANGE_FIXTURE.change]),
    reviewDecisions: Object.freeze([]),
    reviewPatches: Object.freeze([]),
    reextractRequests: Object.freeze([]),
    staleBroken: Object.freeze([STALE_FIXTURE]),
    auditLog: Object.freeze([]),
  });
}
