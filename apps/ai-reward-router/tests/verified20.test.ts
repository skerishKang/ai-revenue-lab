import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveAcquisitionDecision } from '../src/source-policy/decision.js';
import { sourceById } from '../src/source-policy/registry.js';
import {
  PROLIFIC_PRE_CURATION_GATES,
  PROLIFIC_VERIFIED20_RECORD,
  PROLIFIC_W8_POLICY,
  PROLIFIC_W8_REQUIREMENTS,
  PROLIFIC_W8_SNAPSHOT,
  PROLIFIC_W8_VERSION,
} from '../src/verified20/prolific.js';
import { OUTLIER_CURRENT_VERIFIED20_RECORD } from '../src/verified20/outlier-current.js';
import { validateVerified20Record, verified20Progress } from '../src/verified20/domain.js';
import { VERIFIED20_PROGRESS, W8_GATE_STATUS } from '../src/verified20/ledger.js';
import { W8_NEGATIVE_DEMONSTRATIONS } from '../src/verified20/negative-demonstrations.js';

test('Prolific real source is manual/deep-link only after explicit bounded clearance', () => {
  const source = sourceById('SRC-PROLIFIC');
  assert.equal(effectiveAcquisitionDecision({ source, policy: PROLIFIC_W8_POLICY, gates: PROLIFIC_PRE_CURATION_GATES, attempt: 'DIRECTORY', limitsSatisfied: true }), 'MANUAL_ONLY');
  assert.equal(effectiveAcquisitionDecision({ source, policy: PROLIFIC_W8_POLICY, gates: PROLIFIC_PRE_CURATION_GATES, attempt: 'AUTOMATED', limitsSatisfied: true }), 'BLOCK');
  assert.equal(PROLIFIC_W8_POLICY.automationPermission, 'BLOCKED');
});

test('slot 1 Prolific remains a countable provider-level real record without private inventory claims', () => {
  const validation = validateVerified20Record(PROLIFIC_VERIFIED20_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(PROLIFIC_VERIFIED20_RECORD.slot, 1);
  assert.equal(PROLIFIC_VERIFIED20_RECORD.supplyClaimMode, 'PROVIDER_PROGRAM_ONLY');
  assert.equal(PROLIFIC_W8_VERSION.supplyAvailabilityState, 'ACCOUNT_SPECIFIC_UNKNOWN');
  assert.equal(PROLIFIC_W8_VERSION.advertisedCompensationValue, null);
  assert.equal(PROLIFIC_W8_VERSION.expectedPayoutValue, null);
  assert.equal(PROLIFIC_W8_VERSION.qualificationProbability, null);
  assert.equal(PROLIFIC_W8_VERSION.acceptanceProbability, null);
});

test('Prolific evidence preserves the exact over-18 interpretation and manual provenance', () => {
  assert.deepEqual(PROLIFIC_W8_VERSION.eligibleCountriesOrRegions, ['KOREA']);
  assert.equal(PROLIFIC_W8_REQUIREMENTS.find((item) => item.id === 'req-w8-prolific-age')?.operator, 'GT');
  assert.deepEqual(PROLIFIC_W8_VERSION.ageRequirements, { minimumExclusiveAge: 18 });
  assert.deepEqual(PROLIFIC_W8_VERSION.payoutMethod, { method: 'PayPal', cashoutThreshold: '$6/£6' });
  const metadata = PROLIFIC_W8_SNAPSHOT.fetchMetadata as { transportCallCount?: unknown; privateAccountAccess?: unknown; loggedInInventoryObserved?: unknown } | null;
  assert.equal(metadata?.transportCallCount, 0);
  assert.equal(metadata?.privateAccountAccess, false);
  assert.equal(metadata?.loggedInInventoryObserved, false);
});

test('current Outlier slot is the reviewed v2 record, not the historical v1 baseline', () => {
  const validation = validateVerified20Record(OUTLIER_CURRENT_VERIFIED20_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(OUTLIER_CURRENT_VERIFIED20_RECORD.slot, 2);
  assert.equal(OUTLIER_CURRENT_VERIFIED20_RECORD.version.versionNumber, 2);
  assert.equal(OUTLIER_CURRENT_VERIFIED20_RECORD.version.title.includes('Voice AI Evaluator'), true);
});

test('general public job postings are rejected from VERIFIED 20 even if otherwise fully reviewed', () => {
  const jobPostingRecord = {
    ...OUTLIER_CURRENT_VERIFIED20_RECORD,
    version: {
      ...OUTLIER_CURRENT_VERIFIED20_RECORD.version,
      supplyAvailabilityState: 'PUBLIC_JOB_POSTING_AVAILABLE',
    },
  };
  const validation = validateVerified20Record(jobPostingRecord);
  assert.equal(validation.countable, false);
  assert.equal(validation.errors.includes('general job postings belong to external job-search assist, not VERIFIED 20 core supply'), true);
});

test('duplicate copies of one real opportunity can never fake a 20/20 gate', () => {
  const duplicates = Array.from({ length: 20 }, () => OUTLIER_CURRENT_VERIFIED20_RECORD);
  const progress = verified20Progress(duplicates);
  assert.equal(progress.verifiedCount, 1);
  assert.equal(progress.duplicateSlotDetected, true);
  assert.equal(progress.duplicateOpportunityDetected, true);
  assert.equal(progress.gatePassed, false);
});

test('W8 remains fail-closed at 14/20 with four real negative demonstrations passed', () => {
  assert.equal(VERIFIED20_PROGRESS.verifiedCount, 14);
  assert.equal(VERIFIED20_PROGRESS.targetCount, 20);
  assert.equal(VERIFIED20_PROGRESS.remainingCount, 6);
  assert.equal(VERIFIED20_PROGRESS.gatePassed, false);
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.filter((item) => item.status === 'PASS').length, 4);
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'STALE_SOURCE_SUPPRESSION')?.status, 'PASS');
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'REJECTED_DUPLICATE')?.status, 'PASS');
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'LOW_CONFIDENCE_REVIEW')?.status, 'PASS');
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'MATERIAL_VERSION_CHANGE')?.status, 'PASS');
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'BROKEN_LINK_SUPPRESSION')?.status, 'PENDING');
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsPassed, 4);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsComplete, false);
  assert.equal(W8_GATE_STATUS.gatePassed, false);
});
