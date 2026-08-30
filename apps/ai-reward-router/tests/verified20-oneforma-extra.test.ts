import test from 'node:test';
import assert from 'node:assert/strict';
import { validateVerified20Record, verified20Progress } from '../src/verified20/domain.js';
import {
  ONEFORMA_APP_MUSIC_SEARCH_RECORD,
  ONEFORMA_EXTRA_VERIFIED20_RECORDS,
  ONEFORMA_LOCAL_SEARCH_RECORD,
} from '../src/verified20/oneforma-extra.js';

test('OneForma extra public Korea projects are independently countable', () => {
  assert.deepEqual(ONEFORMA_EXTRA_VERIFIED20_RECORDS.map((record) => record.slot), [11, 12]);
  for (const record of ONEFORMA_EXTRA_VERIFIED20_RECORDS) {
    const validation = validateVerified20Record(record);
    assert.equal(validation.countable, true, validation.errors.join('; '));
    assert.equal(record.version.advertisedCompensationValue, null);
    assert.equal(record.version.expectedPayoutValue, null);
    assert.equal(record.version.compensationCurrency, null);
    assert.deepEqual(record.version.eligibleCountriesOrRegions, ['KOREA']);
  }
  const progress = verified20Progress(ONEFORMA_EXTRA_VERIFIED20_RECORDS);
  assert.equal(progress.verifiedCount, 2);
  assert.equal(progress.duplicateSlotDetected, false);
  assert.equal(progress.duplicateOpportunityDetected, false);
});

test('Local Search Quality Evaluator preserves public long-term qualification requirements', () => {
  assert.equal(ONEFORMA_LOCAL_SEARCH_RECORD.version.opportunityCategory, 'SEARCH_OR_QUALITY_EVALUATION');
  assert.equal(ONEFORMA_LOCAL_SEARCH_RECORD.version.compensationType, 'HOURLY');
  assert.equal(ONEFORMA_LOCAL_SEARCH_RECORD.version.qualificationRequired, true);
  assert.equal(ONEFORMA_LOCAL_SEARCH_RECORD.requirements.some((item) => item.displayText.includes('five years')), true);
  assert.equal(ONEFORMA_LOCAL_SEARCH_RECORD.requirements.some((item) => item.displayText.includes('certifications')), true);
});

test('App Store and Music Search Evaluator preserves Korea/iOS/certification requirements', () => {
  assert.equal(ONEFORMA_APP_MUSIC_SEARCH_RECORD.version.opportunityCategory, 'SEARCH_OR_QUALITY_EVALUATION');
  assert.equal(ONEFORMA_APP_MUSIC_SEARCH_RECORD.version.compensationType, 'PER_UNIT');
  assert.deepEqual(ONEFORMA_APP_MUSIC_SEARCH_RECORD.version.languageRequirements, ['KOREAN', 'ENGLISH']);
  assert.deepEqual(ONEFORMA_APP_MUSIC_SEARCH_RECORD.version.deviceOsRequirements, ['IOS_DEVICE']);
  assert.equal(ONEFORMA_APP_MUSIC_SEARCH_RECORD.requirements.some((item) => item.displayText.includes('Apple ID')), true);
  assert.equal(ONEFORMA_APP_MUSIC_SEARCH_RECORD.requirements.some((item) => item.displayText.includes('certification')), true);
});
