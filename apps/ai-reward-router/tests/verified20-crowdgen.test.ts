import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CROWDGEN_MOOGERAH_RECORD,
  CROWDGEN_MOOGERAH_VERSION,
  CROWDGEN_PLUMERIA_RECORD,
  CROWDGEN_PLUMERIA_VERSION,
} from '../src/verified20/crowdgen.js';
import { validateVerified20Record, verified20Progress } from '../src/verified20/domain.js';

test('CrowdGen Moogerah is a countable distinct real slot with conditional fixed pay', () => {
  const validation = validateVerified20Record(CROWDGEN_MOOGERAH_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(CROWDGEN_MOOGERAH_RECORD.slot, 3);
  assert.equal(CROWDGEN_MOOGERAH_VERSION.compensationType, 'FIXED');
  assert.equal(CROWDGEN_MOOGERAH_VERSION.advertisedCompensationValue, 85);
  assert.equal(CROWDGEN_MOOGERAH_VERSION.expectedPayoutValue, null);
  assert.equal(CROWDGEN_MOOGERAH_RECORD.certaintyType, 'CONDITIONAL');
  assert.deepEqual(CROWDGEN_MOOGERAH_VERSION.eligibleCountriesOrRegions, ['KOREA']);
  assert.deepEqual(CROWDGEN_MOOGERAH_VERSION.ageRequirements, { minimumAge: 18 });
});

test('CrowdGen Plumeria is a countable distinct real slot with conditional hourly pay', () => {
  const validation = validateVerified20Record(CROWDGEN_PLUMERIA_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(CROWDGEN_PLUMERIA_RECORD.slot, 4);
  assert.equal(CROWDGEN_PLUMERIA_VERSION.compensationType, 'HOURLY');
  assert.equal(CROWDGEN_PLUMERIA_VERSION.advertisedCompensationValue, 12);
  assert.equal(CROWDGEN_PLUMERIA_VERSION.compensationCurrency, 'USD');
  assert.equal(CROWDGEN_PLUMERIA_VERSION.expectedPayoutValue, null);
  assert.equal(CROWDGEN_PLUMERIA_VERSION.acceptanceProbability, null);
  assert.equal(CROWDGEN_PLUMERIA_RECORD.certaintyType, 'CONDITIONAL');
  assert.deepEqual(CROWDGEN_PLUMERIA_VERSION.eligibleCountriesOrRegions, ['KOREA']);
});

test('two distinct opportunities from one provider remain two canonical opportunities', () => {
  assert.equal(CROWDGEN_MOOGERAH_RECORD.opportunity.sourceId, 'SRC-CROWDGEN');
  assert.equal(CROWDGEN_PLUMERIA_RECORD.opportunity.sourceId, 'SRC-CROWDGEN');
  assert.notEqual(CROWDGEN_MOOGERAH_RECORD.opportunity.id, CROWDGEN_PLUMERIA_RECORD.opportunity.id);
  assert.notEqual(CROWDGEN_MOOGERAH_RECORD.opportunity.canonicalKey, CROWDGEN_PLUMERIA_RECORD.opportunity.canonicalKey);
  assert.notEqual(CROWDGEN_MOOGERAH_RECORD.snapshot.canonicalUrl, CROWDGEN_PLUMERIA_RECORD.snapshot.canonicalUrl);
  const progress = verified20Progress([CROWDGEN_MOOGERAH_RECORD, CROWDGEN_PLUMERIA_RECORD]);
  assert.equal(progress.verifiedCount, 2);
  assert.equal(progress.duplicateSlotDetected, false);
  assert.equal(progress.duplicateOpportunityDetected, false);
});

test('CrowdGen W8 evidence stays on official public CrowdGen pages', () => {
  for (const record of [CROWDGEN_MOOGERAH_RECORD, CROWDGEN_PLUMERIA_RECORD]) {
    for (const item of record.evidence) {
      const locator = item.evidenceLocator as { url?: unknown } | null;
      assert.equal(typeof locator?.url, 'string');
      assert.equal(new URL(String(locator?.url)).hostname, 'crowdgen.com');
    }
    const metadata = record.snapshot.fetchMetadata as { productTransportCallCount?: unknown; privateAccountAccess?: unknown; loggedInProjectInventoryObserved?: unknown } | null;
    assert.equal(metadata?.productTransportCallCount, 0);
    assert.equal(metadata?.privateAccountAccess, false);
    assert.equal(metadata?.loggedInProjectInventoryObserved, false);
  }
});
