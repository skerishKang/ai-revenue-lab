import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PRODUCT_OPPORTUNITY_LANES,
  PRODUCT_SCOPE_POLICY,
  WELO_EXTERNAL_JOB_REFERENCES,
  jobSearchAssistPrompt,
} from '../src/job-search-assist/index.js';

test('product scope keeps pocket money and short gigs in core while general jobs stay external', () => {
  assert.deepEqual(PRODUCT_SCOPE_POLICY.coreCatalogLanes, [
    PRODUCT_OPPORTUNITY_LANES.POCKET_MONEY,
    PRODUCT_OPPORTUNITY_LANES.SHORT_GIG,
  ]);
  assert.equal(PRODUCT_SCOPE_POLICY.externalOnlyLane, PRODUCT_OPPORTUNITY_LANES.EXTERNAL_JOB_SEARCH);
  assert.equal(PRODUCT_SCOPE_POLICY.generalJobListingsOwnedByB64, false);
  assert.equal(PRODUCT_SCOPE_POLICY.applicationWorkflowOwnedByB64, false);
  assert.equal(PRODUCT_SCOPE_POLICY.hiringStatusSourceOfTruthOwnedByB64, false);
});

test('Welo discoveries are external search references, not B64-owned inventory', () => {
  assert.equal(WELO_EXTERNAL_JOB_REFERENCES.length, 6);
  for (const item of WELO_EXTERNAL_JOB_REFERENCES) {
    assert.equal(item.lane, 'EXTERNAL_JOB_SEARCH');
    assert.equal(item.applicationManagedExternally, true);
    assert.equal(item.fullDescriptionStoredByB64, false);
    assert.equal(item.destinationUrl.startsWith('https://jobs.lever.co/weloglobal/'), true);
  }
});

test('job search assistant instruction explicitly searches external sites and deep-links', () => {
  const prompt = jobSearchAssistPrompt({ query: '한국어 AI 알바', location: 'South Korea', remotePreference: 'REMOTE' });
  assert.match(prompt, /established job boards and official employer pages/);
  assert.match(prompt, /deep-link/);
  assert.match(prompt, /Do not ingest or operate the job listing as B64-owned inventory/);
});
