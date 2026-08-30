import test from 'node:test';
import assert from 'node:assert/strict';
import { VERIFIED20_RECORDS, W8_GATE_STATUS } from '../src/verified20/ledger.js';
import { W8_NEGATIVE_DEMONSTRATIONS } from '../src/verified20/negative-demonstrations.js';
import { CROWDGEN_FIREWEED_STALE_SUPPRESSION } from '../src/verified20/real-negative-evidence.js';

test('real stale CrowdGen Fireweed evidence is suppressed rather than counted', () => {
  assert.equal(CROWDGEN_FIREWEED_STALE_SUPPRESSION.realEvidence, true);
  assert.equal(CROWDGEN_FIREWEED_STALE_SUPPRESSION.disposition, 'SUPPRESSED');
  assert.equal(CROWDGEN_FIREWEED_STALE_SUPPRESSION.countableVerified20, false);
  assert.equal(CROWDGEN_FIREWEED_STALE_SUPPRESSION.reasonCodes.includes('EXPIRED_PROMOTION_STILL_RENDERED'), true);
  assert.equal(VERIFIED20_RECORDS.some((record) => record.snapshot.canonicalUrl === CROWDGEN_FIREWEED_STALE_SUPPRESSION.canonicalUrl), false);
});

test('STALE_SOURCE_SUPPRESSION is PASS only through the real evidence case', () => {
  const stale = W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'STALE_SOURCE_SUPPRESSION');
  assert.equal(stale?.status, 'PASS');
  assert.equal(stale?.evidenceRef, CROWDGEN_FIREWEED_STALE_SUPPRESSION.evidenceId);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsPassed, 1);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsTarget, 5);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsComplete, false);
  assert.equal(W8_GATE_STATUS.gatePassed, false);
});
