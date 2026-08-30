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
import {
  GOOGLE_OPINION_REWARDS_KR_RECORD,
  IPSOS_ISAY_KR_RECORD,
  PANELPOWER_AIRDRESSER_RECORD,
  PANELPOWER_PROGRAM_RECORD,
  RAKUTEN_INSIGHT_KR_RECORD,
} from '../src/verified20/korean-pocket-money.js';
import { PANELPOWER_REALTOR_FOCUS_GROUP_RECORD } from '../src/verified20/panelpower-realtor.js';
import { validateVerified20Record, verified20Progress } from '../src/verified20/domain.js';
import { VERIFIED20_PROGRESS, VERIFIED20_RECORDS, W8_GATE_STATUS } from '../src/verified20/ledger.js';
import { W8_NEGATIVE_DEMONSTRATIONS } from '../src/verified20/negative-demonstrations.js';

const CORE_TAIL = Object.freeze([
  RAKUTEN_INSIGHT_KR_RECORD,
  PANELPOWER_PROGRAM_RECORD,
  IPSOS_ISAY_KR_RECORD,
  PANELPOWER_REALTOR_FOCUS_GROUP_RECORD,
  GOOGLE_OPINION_REWARDS_KR_RECORD,
  PANELPOWER_AIRDRESSER_RECORD,
]);

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

test('slots 15-20 are policy-cleared pocket-money or short paid research, never general jobs', () => {
  assert.deepEqual(CORE_TAIL.map((item) => item.slot), [15, 16, 17, 18, 19, 20]);
  for (const record of CORE_TAIL) {
    const validation = validateVerified20Record(record);
    assert.equal(validation.countable, true, `${record.slot}: ${validation.errors.join('; ')}`);
    assert.notEqual(record.version.supplyAvailabilityState, 'PUBLIC_JOB_POSTING_AVAILABLE');
    assert.equal(record.version.opportunityCategory === 'SURVEY' || record.version.opportunityCategory === 'MARKET_RESEARCH', true);
  }
  assert.equal(VERIFIED20_RECORDS.some((record) => record.snapshot.sourceId === 'SRC-LIFEPOINTS-KR'), false);
});

test('provider-level Korean survey programs never fabricate individual survey supply or expected payout', () => {
  for (const record of CORE_TAIL.filter((item) => item.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY')) {
    assert.equal(record.version.supplyAvailabilityState, 'PUBLIC_PROVIDER_PROGRAM_AVAILABLE');
    assert.equal(record.version.expectedPayoutValue, null);
    assert.equal(record.version.acceptanceProbability, null);
    assert.equal(record.version.qualificationProbability, null);
    const metadata = record.snapshot.fetchMetadata as { privateAccountAccess?: unknown; individualSurveyInventoryObserved?: unknown } | null;
    assert.equal(metadata?.privateAccountAccess, false);
    assert.equal(metadata?.individualSurveyInventoryObserved, false);
  }
});

test('Google Opinion Rewards Korea is Android-specific and does not claim guaranteed surveys or cash payout', () => {
  assert.deepEqual(GOOGLE_OPINION_REWARDS_KR_RECORD.version.deviceOsRequirements, ['ANDROID']);
  assert.deepEqual(GOOGLE_OPINION_REWARDS_KR_RECORD.version.eligibleCountriesOrRegions, ['KOREA']);
  assert.equal(GOOGLE_OPINION_REWARDS_KR_RECORD.version.advertisedCompensationValue, null);
  assert.equal(GOOGLE_OPINION_REWARDS_KR_RECORD.version.expectedPayoutValue, null);
  assert.deepEqual(GOOGLE_OPINION_REWARDS_KR_RECORD.version.payoutMethod, { method: 'GOOGLE_PLAY_CREDIT' });
});

test('PanelPower current paid research records are bounded studies, not job listings', () => {
  assert.equal(PANELPOWER_REALTOR_FOCUS_GROUP_RECORD.slot, 18);
  assert.equal(PANELPOWER_REALTOR_FOCUS_GROUP_RECORD.version.advertisedCompensationValue, 100000);
  assert.equal(PANELPOWER_REALTOR_FOCUS_GROUP_RECORD.version.compensationCurrency, 'KRW');
  assert.equal(PANELPOWER_REALTOR_FOCUS_GROUP_RECORD.version.opportunityCategory, 'MARKET_RESEARCH');
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.slot, 20);
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.supplyClaimMode, 'PUBLIC_CURRENT_INVENTORY');
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.version.opportunityCategory, 'MARKET_RESEARCH');
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.version.advertisedCompensationValue, 300000);
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.version.compensationCurrency, 'KRW');
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.version.supplyAvailabilityState, 'PUBLIC_RESEARCH_STUDY_AVAILABLE');
  assert.equal(PANELPOWER_AIRDRESSER_RECORD.version.acceptanceProbability, null);
});

test('W8 data contract reaches exactly 20 unique core records and all five real negative demonstrations', () => {
  assert.equal(VERIFIED20_RECORDS.length, 20);
  assert.equal(VERIFIED20_PROGRESS.verifiedCount, 20);
  assert.equal(VERIFIED20_PROGRESS.targetCount, 20);
  assert.equal(VERIFIED20_PROGRESS.remainingCount, 0);
  assert.equal(VERIFIED20_PROGRESS.duplicateSlotDetected, false);
  assert.equal(VERIFIED20_PROGRESS.duplicateOpportunityDetected, false);
  assert.equal(VERIFIED20_PROGRESS.gatePassed, true);
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.filter((item) => item.status === 'PASS').length, 5);
  for (const item of W8_NEGATIVE_DEMONSTRATIONS) assert.equal(item.status, 'PASS', item.id);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsPassed, 5);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsComplete, true);
  assert.equal(W8_GATE_STATUS.gatePassed, true);
});
