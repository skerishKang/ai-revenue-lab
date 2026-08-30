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
import { validateVerified20Record } from '../src/verified20/domain.js';
import { VERIFIED20_PROGRESS, W8_GATE_STATUS } from '../src/verified20/ledger.js';
import { W8_NEGATIVE_DEMONSTRATIONS } from '../src/verified20/negative-demonstrations.js';

test('Prolific first real source is manual/deep-link only after explicit bounded clearance', () => {
  const source = sourceById('SRC-PROLIFIC');
  assert.equal(effectiveAcquisitionDecision({
    source,
    policy: PROLIFIC_W8_POLICY,
    gates: PROLIFIC_PRE_CURATION_GATES,
    attempt: 'DIRECTORY',
    limitsSatisfied: true,
  }), 'MANUAL_ONLY');
  assert.equal(effectiveAcquisitionDecision({
    source,
    policy: PROLIFIC_W8_POLICY,
    gates: PROLIFIC_PRE_CURATION_GATES,
    attempt: 'AUTOMATED',
    limitsSatisfied: true,
  }), 'BLOCK');
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
  const metadata = PROLIFIC_W8_SNAPSHOT.fetchMetadata as {
    transportCallCount?: unknown;
    privateAccountAccess?: unknown;
    loggedInInventoryObserved?: unknown;
  } | null;
  assert.equal(metadata?.transportCallCount, 0);
  assert.equal(metadata?.privateAccountAccess, false);
  assert.equal(metadata?.loggedInInventoryObserved, false);
  assert.equal(PROLIFIC_W8_SNAPSHOT.httpStatus, null);
  assert.equal(PROLIFIC_W8_SNAPSHOT.actorProvenance !== null, true);
});

test('W8 remains fail-closed at 1/20 with all required negative demonstrations still pending', () => {
  assert.equal(VERIFIED20_PROGRESS.verifiedCount, 1);
  assert.equal(VERIFIED20_PROGRESS.targetCount, 20);
  assert.equal(VERIFIED20_PROGRESS.remainingCount, 19);
  assert.equal(VERIFIED20_PROGRESS.gatePassed, false);
  assert.equal(W8_NEGATIVE_DEMONSTRATIONS.every((item) => item.status === 'PENDING'), true);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsComplete, false);
  assert.equal(W8_GATE_STATUS.gatePassed, false);
});
