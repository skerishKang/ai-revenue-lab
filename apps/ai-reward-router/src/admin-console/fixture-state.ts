import {
  AI_DATA_WORK_FIXTURE,
  MATERIAL_CHANGE_FIXTURE,
  MICRO_REWARD_FIXTURE,
  PAID_RESEARCH_FIXTURE,
  UNKNOWN_COMPENSATION_FIXTURE,
  type OpportunityFixtureBundle,
} from '../persistence/fixtures.js';
import type { OpportunityEvidence, SourceSnapshot } from '../persistence/domain.js';
import { ACQUISITION_MODES } from '../source-policy/domain.js';
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

const CHANGE_SNAPSHOT_FIXTURE: SourceSnapshot = Object.freeze({
  id: 'snap-fixture-change-2',
  sourceId: 'SRC-RESPONDENT',
  endpointId: null,
  acquiredAt: '2026-08-30T00:00:00.000Z',
  acquisitionModeUsed: ACQUISITION_MODES.DEEP_LINK_OR_DIRECTORY,
  canonicalUrl: 'https://example.invalid/fixture/change-v2',
  contentType: 'text/html',
  rawLocation: null,
  rawPayload: { fixture: true, compensation: 150 },
  contentHash: 'sha256:fixture-change-v2',
  fetchMetadata: null,
  actorProvenance: { actor: 'CENTRAL_FIXTURE' },
  httpStatus: null,
});

const CHANGE_EVIDENCE_FIXTURE: OpportunityEvidence = Object.freeze({
  id: 'ev-change-v2-compensation',
  offerVersionId: 'offer-fixture-change-v2',
  sourceSnapshotId: CHANGE_SNAPSHOT_FIXTURE.id,
  fieldPath: 'advertisedCompensationValue',
  evidenceText: 'SYNTHETIC FIXTURE: updated compensation is 150 USD',
  evidenceLocator: null,
  evidenceHash: 'sha256:ev-change-v2-compensation',
  confidence: 1,
  createdAt: '2026-08-30T00:00:00.000Z',
});

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
    snapshots: Object.freeze([...bundles.map((bundle) => bundle.snapshot), CHANGE_SNAPSHOT_FIXTURE]),
    opportunities: Object.freeze([
      ...bundles.map((bundle) => bundle.opportunity),
      MATERIAL_CHANGE_FIXTURE.opportunity,
    ]),
    versions: Object.freeze([
      ...bundles.flatMap((bundle) => bundle.versions),
      ...MATERIAL_CHANGE_FIXTURE.versions,
    ]),
    evidence: Object.freeze([...bundles.flatMap((bundle) => bundle.evidence), CHANGE_EVIDENCE_FIXTURE]),
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
