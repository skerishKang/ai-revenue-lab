import test from 'node:test';
import assert from 'node:assert/strict';
import { VERIFIED20_RECORDS } from '../src/verified20/ledger.js';
import { validateW9ExpansionRecord, verified50Progress } from '../src/w9-expansion/domain.js';
import { PANELPOWER_CURRENT_W9_RECORDS } from '../src/w9-expansion/panelpower-current.js';
import { VERIFIED50_PROGRESS, W9_EXPANSION_RECORDS, W9_GATE_STATUS } from '../src/w9-expansion/ledger.js';

test('W9 starts from the accepted W8 baseline rather than recreating its first 20 records', () => {
  assert.equal(VERIFIED20_RECORDS.length, 20);
  assert.equal(W9_EXPANSION_RECORDS.length, 3);
  assert.deepEqual(W9_EXPANSION_RECORDS.map((record) => record.ordinal), [21, 22, 23]);
});

test('first W9 batch is bounded paid research and excludes general job postings', () => {
  for (const record of PANELPOWER_CURRENT_W9_RECORDS) {
    const validation = validateW9ExpansionRecord(record);
    assert.equal(validation.countable, true, `${record.ordinal}: ${validation.errors.join('; ')}`);
    assert.equal(record.version.opportunityCategory, 'MARKET_RESEARCH');
    assert.equal(record.version.supplyAvailabilityState, 'PUBLIC_RESEARCH_STUDY_AVAILABLE');
    assert.notEqual(record.version.supplyAvailabilityState, 'PUBLIC_JOB_POSTING_AVAILABLE');
    assert.equal(record.version.expectedPayoutValue, null);
    assert.equal(record.version.acceptanceProbability, null);
    assert.equal(record.version.qualificationProbability, null);
  }
});

test('W9 first batch preserves exact public advertised compensation', () => {
  assert.deepEqual(
    PANELPOWER_CURRENT_W9_RECORDS.map((record) => record.version.advertisedCompensationValue),
    [200000, 200000, 150000],
  );
  assert.equal(PANELPOWER_CURRENT_W9_RECORDS.every((record) => record.version.compensationCurrency === 'KRW'), true);
});

test('W9 progress is fail-closed at 23/50 after the first expansion batch', () => {
  assert.equal(VERIFIED50_PROGRESS.baseline20Passed, true);
  assert.equal(VERIFIED50_PROGRESS.verifiedCount, 23);
  assert.equal(VERIFIED50_PROGRESS.targetCount, 50);
  assert.equal(VERIFIED50_PROGRESS.remainingCount, 27);
  assert.equal(VERIFIED50_PROGRESS.duplicateExpansionOrdinalDetected, false);
  assert.equal(VERIFIED50_PROGRESS.duplicateOpportunityDetected, false);
  assert.equal(VERIFIED50_PROGRESS.gatePassed, false);
  assert.equal(W9_GATE_STATUS.gatePassed, false);
});

test('duplicate expansion ordinals or opportunities cannot inflate Verified50', () => {
  const first = PANELPOWER_CURRENT_W9_RECORDS[0]!;
  const duplicateOrdinal = { ...PANELPOWER_CURRENT_W9_RECORDS[1]!, ordinal: first.ordinal };
  const duplicateOpportunity = { ...PANELPOWER_CURRENT_W9_RECORDS[2]!, opportunity: first.opportunity };
  const progress = verified50Progress(VERIFIED20_RECORDS, [first, duplicateOrdinal, duplicateOpportunity]);
  assert.equal(progress.verifiedCount, 21);
  assert.equal(progress.duplicateExpansionOrdinalDetected, true);
  assert.equal(progress.duplicateOpportunityDetected, true);
  assert.equal(progress.gatePassed, false);
});
