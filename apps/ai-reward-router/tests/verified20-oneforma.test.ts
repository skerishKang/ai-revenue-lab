import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveAcquisitionDecision } from '../src/source-policy/decision.js';
import { sourceById } from '../src/source-policy/registry.js';
import { verified20Progress, validateVerified20Record } from '../src/verified20/domain.js';
import {
  ONEFORMA_AUDIO_QA_RECORD,
  ONEFORMA_INTENT_ANNOTATOR_RECORD,
  ONEFORMA_BILINGUAL_TRANSLATION_RECORD,
  ONEFORMA_PARAGRAPH_TRANSLATION_RECORD,
  ONEFORMA_AI_QA_RECORD,
  ONEFORMA_PODCAST_TRANSCRIPTION_RECORD,
  ONEFORMA_FINAL_GATES,
  ONEFORMA_VERIFIED20_RECORDS,
  ONEFORMA_W8_POLICY,
} from '../src/verified20/oneforma.js';

test('OneForma public-project acquisition is manual/deep-link only', () => {
  const source = sourceById('SRC-ONEFORMA');
  assert.equal(effectiveAcquisitionDecision({ source, policy: ONEFORMA_W8_POLICY, gates: ONEFORMA_FINAL_GATES, attempt: 'DIRECTORY', limitsSatisfied: true }), 'MANUAL_ONLY');
  assert.equal(effectiveAcquisitionDecision({ source, policy: ONEFORMA_W8_POLICY, gates: ONEFORMA_FINAL_GATES, attempt: 'AUTOMATED', limitsSatisfied: true }), 'BLOCK');
  assert.equal(ONEFORMA_W8_POLICY.automationPermission, 'BLOCKED');
});

test('six OneForma Korea records are independently countable real opportunities', () => {
  assert.equal(ONEFORMA_VERIFIED20_RECORDS.length, 6);
  for (const record of ONEFORMA_VERIFIED20_RECORDS) {
    const validation = validateVerified20Record(record);
    assert.equal(validation.countable, true, `${record.slot}: ${validation.errors.join('; ')}`);
    assert.equal(record.realEvidence, true);
    assert.equal(record.syntheticFixture, false);
    assert.equal(record.supplyClaimMode, 'PUBLIC_CURRENT_INVENTORY');
    assert.equal(record.version.supplyAvailabilityState, 'PUBLIC_PROJECT_APPLICATION_OPEN');
    assert.deepEqual(record.version.eligibleCountriesOrRegions, ['KOREA']);
    assert.equal(record.version.advertisedCompensationValue, null);
    assert.equal(record.version.expectedPayoutValue, null);
    assert.equal(record.version.compensationCurrency, null);
    assert.equal(record.version.acceptanceProbability, null);
    assert.equal(record.compensationComponents[0]?.amount, null);
    assert.equal(record.compensationComponents[0]?.currency, null);
  }
  const progress = verified20Progress(ONEFORMA_VERIFIED20_RECORDS);
  assert.equal(progress.verifiedCount, 6);
  assert.equal(progress.duplicateSlotDetected, false);
  assert.equal(progress.duplicateOpportunityDetected, false);
});

test('OneForma slots 5 through 10 remain contiguous and canonical identities are unique', () => {
  assert.deepEqual(ONEFORMA_VERIFIED20_RECORDS.map((record) => record.slot), [5, 6, 7, 8, 9, 10]);
  assert.equal(new Set(ONEFORMA_VERIFIED20_RECORDS.map((record) => record.opportunity.id)).size, 6);
  assert.equal(new Set(ONEFORMA_VERIFIED20_RECORDS.map((record) => record.opportunity.canonicalKey)).size, 6);
  assert.equal(new Set(ONEFORMA_VERIFIED20_RECORDS.map((record) => record.snapshot.canonicalUrl)).size, 6);
});

test('OneForma task categories and compensation bases reflect each public project without invented numeric pay', () => {
  assert.equal(ONEFORMA_AUDIO_QA_RECORD.version.opportunityCategory, 'TRANSCRIPTION');
  assert.equal(ONEFORMA_AUDIO_QA_RECORD.version.compensationType, 'HOURLY');
  assert.equal(ONEFORMA_INTENT_ANNOTATOR_RECORD.version.opportunityCategory, 'DATA_ANNOTATION');
  assert.equal(ONEFORMA_INTENT_ANNOTATOR_RECORD.version.compensationType, 'HOURLY');
  assert.equal(ONEFORMA_BILINGUAL_TRANSLATION_RECORD.version.opportunityCategory, 'TRANSLATION');
  assert.equal(ONEFORMA_BILINGUAL_TRANSLATION_RECORD.version.compensationType, 'PER_UNIT');
  assert.equal(ONEFORMA_PARAGRAPH_TRANSLATION_RECORD.version.compensationType, 'PER_UNIT');
  assert.equal(ONEFORMA_AI_QA_RECORD.version.opportunityCategory, 'AI_EVALUATION');
  assert.equal(ONEFORMA_AI_QA_RECORD.version.compensationType, 'HOURLY');
  assert.equal(ONEFORMA_PODCAST_TRANSCRIPTION_RECORD.version.opportunityCategory, 'TRANSCRIPTION');
  assert.equal(ONEFORMA_PODCAST_TRANSCRIPTION_RECORD.version.compensationType, 'HOURLY');
});

test('OneForma evidence uses official public OneForma URLs and excludes account/private project material', () => {
  for (const record of ONEFORMA_VERIFIED20_RECORDS) {
    for (const evidence of record.evidence) {
      const locator = evidence.evidenceLocator as { url?: unknown } | null;
      assert.equal(typeof locator?.url, 'string');
      assert.equal(new URL(String(locator?.url)).hostname, 'www.oneforma.com');
    }
    const metadata = record.snapshot.fetchMetadata as { productTransportCallCount?: unknown; privateAccountAccess?: unknown; securedProjectDocumentsAccessed?: unknown } | null;
    assert.equal(metadata?.productTransportCallCount, 0);
    assert.equal(metadata?.privateAccountAccess, false);
    assert.equal(metadata?.securedProjectDocumentsAccessed, false);
  }
});
