import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveAcquisitionDecision } from '../src/source-policy/decision.js';
import { sourceById } from '../src/source-policy/registry.js';
import {
  OUTLIER_PRE_CURATION_GATES,
  OUTLIER_VERIFIED20_RECORD,
  OUTLIER_W8_POLICY,
  OUTLIER_W8_SNAPSHOT,
  OUTLIER_W8_VERSION,
} from '../src/verified20/outlier.js';
import {
  PROLIFIC_PRE_CURATION_GATES,
  PROLIFIC_VERIFIED20_RECORD,
  PROLIFIC_W8_POLICY,
  PROLIFIC_W8_REQUIREMENTS,
  PROLIFIC_W8_SNAPSHOT,
  PROLIFIC_W8_VERSION,
} from '../src/verified20/prolific.js';
import { validateVerified20Record, verified20Progress } from '../src/verified20/domain.js';
import { VERIFIED20_PROGRESS, W8_GATE_STATUS } from '../src/verified20/ledger.js';
import { W8_NEGATIVE_DEMONSTRATIONS } from '../src/verified20/negative-demonstrations.js';

test('Prolific first real source is manual/deep-link only after explicit bounded clearance', () => {
  const source = sourceById('SRC-PROLIFIC');
  assert.equal(effectiveAcquisitionDecision({ source, policy: PROLIFIC_W8_POLICY, gates: PROLIFIC_PRE_CURATION_GATES, attempt: 'DIRECTORY', limitsSatisfied: true }), 'MANUAL_ONLY');
  assert.equal(effectiveAcquisitionDecision({ source, policy: PROLIFIC_W8_POLICY, gates: PROLIFIC_PRE_CURATION_GATES, attempt: 'AUTOMATED', limitsSatisfied: true }), 'BLOCK');
  assert.equal(PROLIFIC_W8_POLICY.automationPermission, 'BLOCKED');
});

test('slot 1 is a countable real evidence record with resolved human approval', () => {
  const validation = validateVerified20Record(PROLIFIC_VERIFIED20_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(PROLIFIC_VERIFIED20_RECORD.realEvidence, true);
  assert.equal(PROLIFIC_VERIFIED20_RECORD.syntheticFixture, false);
  assert.equal(PROLIFIC_VERIFIED20_RECORD.certaintyType, 'CONDITIONAL');
  assert.equal(PROLIFIC_VERIFIED20_RECORD.reviewQueue.state, 'RESOLVED');
  assert.equal(PROLIFIC_VERIFIED20_RECORD.reviewDecision.decision, 'APPROVE');
  assert.equal(PROLIFIC_W8_VERSION.verificationState, 'VERIFIED');
});

test('provider-level Prolific record does not fabricate private current study inventory or study pay', () => {
  assert.equal(PROLIFIC_VERIFIED20_RECORD.supplyClaimMode, 'PROVIDER_PROGRAM_ONLY');
  assert.equal(PROLIFIC_W8_VERSION.supplyAvailabilityState, 'ACCOUNT_SPECIFIC_UNKNOWN');
  assert.equal(PROLIFIC_W8_VERSION.supplyObservedAt, null);
  assert.equal(PROLIFIC_W8_VERSION.advertisedCompensationValue, null);
  assert.equal(PROLIFIC_W8_VERSION.expectedPayoutValue, null);
  assert.equal(PROLIFIC_W8_VERSION.compensationCurrency, null);
  assert.equal(PROLIFIC_W8_VERSION.qualificationProbability, null);
  assert.equal(PROLIFIC_W8_VERSION.acceptanceProbability, null);
  assert.equal(PROLIFIC_VERIFIED20_RECORD.compensationComponents[0]?.amount, null);
});

test('Prolific evidence proves program, Korea eligibility, age threshold, verification, and PayPal without third-party evidence', () => {
  const ids = new Set(PROLIFIC_VERIFIED20_RECORD.evidence.map((item) => item.id));
  for (const critical of PROLIFIC_VERIFIED20_RECORD.criticalEvidenceIds) assert.equal(ids.has(critical), true);
  for (const item of PROLIFIC_VERIFIED20_RECORD.evidence) {
    const locator = item.evidenceLocator as { url?: unknown } | null;
    assert.equal(typeof locator?.url, 'string');
    const hostname = new URL(String(locator?.url)).hostname;
    assert.equal(hostname === 'www.prolific.com' || hostname === 'participant-help.prolific.com', true);
  }
  assert.deepEqual(PROLIFIC_W8_VERSION.eligibleCountriesOrRegions, ['KOREA']);
  assert.equal(PROLIFIC_W8_REQUIREMENTS.find((item) => item.id === 'req-w8-prolific-age')?.operator, 'GT');
  assert.deepEqual(PROLIFIC_W8_VERSION.ageRequirements, { minimumExclusiveAge: 18 });
  assert.deepEqual(PROLIFIC_W8_VERSION.payoutMethod, { method: 'PayPal', cashoutThreshold: '$6/£6' });
});

test('manual Prolific snapshot records zero transport calls and no private account access', () => {
  const metadata = PROLIFIC_W8_SNAPSHOT.fetchMetadata as { transportCallCount?: unknown; privateAccountAccess?: unknown; loggedInInventoryObserved?: unknown } | null;
  assert.equal(metadata?.transportCallCount, 0);
  assert.equal(metadata?.privateAccountAccess, false);
  assert.equal(metadata?.loggedInInventoryObserved, false);
  assert.equal(PROLIFIC_W8_SNAPSHOT.httpStatus, null);
  assert.equal(PROLIFIC_W8_SNAPSHOT.actorProvenance !== null, true);
});

test('Outlier Korean role is manual/deep-link only and automation remains blocked', () => {
  const source = sourceById('SRC-OUTLIER');
  assert.equal(effectiveAcquisitionDecision({ source, policy: OUTLIER_W8_POLICY, gates: OUTLIER_PRE_CURATION_GATES, attempt: 'DIRECTORY', limitsSatisfied: true }), 'MANUAL_ONLY');
  assert.equal(effectiveAcquisitionDecision({ source, policy: OUTLIER_W8_POLICY, gates: OUTLIER_PRE_CURATION_GATES, attempt: 'AUTOMATED', limitsSatisfied: true }), 'BLOCK');
  assert.equal(OUTLIER_W8_POLICY.automationPermission, 'BLOCKED');
});

test('slot 2 is the exact public Outlier Korean role with up-to compensation semantics', () => {
  const validation = validateVerified20Record(OUTLIER_VERIFIED20_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(OUTLIER_VERIFIED20_RECORD.slot, 2);
  assert.equal(OUTLIER_VERIFIED20_RECORD.supplyClaimMode, 'PUBLIC_CURRENT_INVENTORY');
  assert.equal(OUTLIER_W8_VERSION.opportunityCategory, 'AI_EVALUATION');
  assert.equal(OUTLIER_W8_VERSION.compensationType, 'HOURLY');
  assert.equal(OUTLIER_W8_VERSION.advertisedCompensationValue, 31);
  assert.equal(OUTLIER_W8_VERSION.compensationCurrency, 'USD');
  assert.equal(OUTLIER_W8_VERSION.expectedPayoutValue, null);
  assert.equal(OUTLIER_W8_VERSION.acceptanceProbability, null);
  assert.equal(OUTLIER_W8_VERSION.qualificationProbability, null);
  assert.equal(OUTLIER_W8_VERSION.supplyAvailabilityState, 'PUBLIC_ROLE_PAGE_AVAILABLE');
  assert.deepEqual(OUTLIER_W8_VERSION.eligibleCountriesOrRegions, ['KOREA']);
  assert.deepEqual(OUTLIER_W8_VERSION.languageRequirements, ['KOREAN']);
});

test('Outlier evidence is official-only and private task inventory is not observed', () => {
  for (const item of OUTLIER_VERIFIED20_RECORD.evidence) {
    const locator = item.evidenceLocator as { url?: unknown } | null;
    assert.equal(typeof locator?.url, 'string');
    assert.equal(new URL(String(locator?.url)).hostname, 'outlier.ai');
  }
  const metadata = OUTLIER_W8_SNAPSHOT.fetchMetadata as { productTransportCallCount?: unknown; centralResearchNetworkUsed?: unknown; privateAccountAccess?: unknown; loggedInTaskInventoryObserved?: unknown } | null;
  assert.equal(metadata?.productTransportCallCount, 0);
  assert.equal(metadata?.centralResearchNetworkUsed, true);
  assert.equal(metadata?.privateAccountAccess, false);
  assert.equal(metadata?.loggedInTaskInventoryObserved, false);
});

test('duplicate copies of one real opportunity can never fake a 20/20 gate', () => {
  const duplicates = Array.from({ length: 20 }, () => OUTLIER_VERIFIED20_RECORD);
  const progress = verified20Progress(duplicates);
  assert.equal(progress.verifiedCount, 1);
  assert.equal(progress.duplicateSlotDetected, true);
  assert.equal(progress.duplicateOpportunityDetected, true);
  assert.equal(progress.gatePassed, false);
});

test('W8 remains fail-closed at 13/20 with only the real stale-source negative passed', () => {
  assert.equal(VERIFIED20_PROGRESS.verifiedCount, 13);
  assert.equal(VERIFIED20_PROGRESS.targetCount, 20);
  assert.equal(VERIFIED20_PROGRESS.remainingCount, 7);
  assert.equal(VERIFIED20_PROGRESS.gatePassed, false);
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.filter((item) => item.status === 'PASS').length, 1);
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'STALE_SOURCE_SUPPRESSION')?.status, 'PASS');
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsPassed, 1);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsComplete, false);
  assert.equal(W8_GATE_STATUS.gatePassed, false);
});
