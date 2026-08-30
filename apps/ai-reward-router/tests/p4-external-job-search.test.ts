import test from 'node:test';
import assert from 'node:assert/strict';
import {
  P4_PRODUCT_BOUNDARY,
  P4_VISIBILITY_LOCK,
  buildP4HiddenSearchBacklog,
  compareP4ExternalJobReferences,
  prepareP4ExternalJobReference,
  type P4ExternalJobCandidate,
} from '../src/job-search-assist/domain.js';
import { buildAdClickFirstConsumerHome, buildAdClickFirstTodayRoute } from '../src/ad-click-first/consumer-home.js';

const NOW = '2026-08-30T13:30:00.000Z';

function candidate(overrides: Partial<P4ExternalJobCandidate> = {}): P4ExternalJobCandidate {
  return {
    sourceId: 'SRC-LEVER',
    provider: 'Example Employer',
    title: 'Korean AI Quality Reviewer',
    location: 'South Korea',
    workMode: 'REMOTE',
    compensationSummary: 'USD 30/hour observed on the public posting.',
    observedCompensation: { amount: 30, currency: 'USD', unit: 'HOUR', explicitlyObserved: true },
    destinationUrl: 'https://jobs.example.com/roles/korean-reviewer',
    lastCheckedAt: '2026-08-30T12:30:00.000Z',
    sourceAuthority: 'ESTABLISHED_JOB_BOARD',
    postingAvailability: 'PUBLIC_POSTING_OBSERVED',
    applicationManagedExternally: true,
    fullDescriptionStoredByB64: false,
    b64OwnedInventory: false,
    ...overrides,
  };
}

test('P4 remains a hidden external-search lane and never becomes B64 general job inventory', () => {
  const backlog = buildP4HiddenSearchBacklog([candidate()], NOW);
  assert.equal(backlog.mode, 'P4_EXTERNAL_JOB_SEARCH_PREPARATION_HIDDEN');
  assert.equal(backlog.issueNumber, 1138);
  assert.equal(backlog.consumerVisible, false);
  assert.equal(backlog.generalJobInventoryOwnedByB64, false);
  assert.equal(P4_PRODUCT_BOUNDARY.generalJobListingsOwnedByB64, false);
  assert.equal(P4_PRODUCT_BOUNDARY.applicationWorkflowOwnedByB64, false);
  assert.equal(P4_PRODUCT_BOUNDARY.fullJobDescriptionReplicationAllowed, false);
});

test('fresh HTTPS result from an established source is a reference only, not owned inventory', () => {
  const prepared = prepareP4ExternalJobReference(candidate(), NOW);
  assert.equal(prepared.resultState, 'REFERENCE_READY');
  assert.equal(prepared.sourceOfTruth, 'EXTERNAL_PROVIDER');
  assert.equal(prepared.applicationManagedExternally, true);
  assert.equal(prepared.fullDescriptionStoredByB64, false);
  assert.equal(prepared.b64OwnedInventory, false);
  assert.equal(prepared.hiringStatus, 'UNKNOWN');
});

test('unsafe non-HTTPS destination is fail-closed', () => {
  const prepared = prepareP4ExternalJobReference(candidate({ destinationUrl: 'http://jobs.example.com/role' }), NOW);
  assert.equal(prepared.resultState, 'BLOCKED_UNSAFE_DESTINATION');
});

test('stale posting reference requires refresh before it can be surfaced', () => {
  const prepared = prepareP4ExternalJobReference(
    candidate({ lastCheckedAt: '2026-08-20T12:30:00.000Z' }),
    NOW,
  );
  assert.equal(prepared.resultState, 'REFRESH_REQUIRED');
});

test('ended posting is suppressed even when its prior evidence is otherwise valid', () => {
  const prepared = prepareP4ExternalJobReference(candidate({ postingAvailability: 'PUBLIC_POSTING_ENDED' }), NOW);
  assert.equal(prepared.resultState, 'BLOCKED_ENDED');
});

test('unknown or non-authoritative public source is not treated as a trusted job result', () => {
  const prepared = prepareP4ExternalJobReference(candidate({ sourceAuthority: 'OTHER_PUBLIC_SOURCE' }), NOW);
  assert.equal(prepared.resultState, 'BLOCKED_SOURCE_AUTHORITY');
});

test('B64 ownership of application, full description, or job inventory violates the P4 boundary', () => {
  const managed = prepareP4ExternalJobReference(candidate({ applicationManagedExternally: false }), NOW);
  const replicated = prepareP4ExternalJobReference(candidate({ fullDescriptionStoredByB64: true }), NOW);
  const owned = prepareP4ExternalJobReference(candidate({ b64OwnedInventory: true }), NOW);
  assert.equal(managed.resultState, 'BLOCKED_OWNERSHIP_BOUNDARY');
  assert.equal(replicated.resultState, 'BLOCKED_OWNERSHIP_BOUNDARY');
  assert.equal(owned.resultState, 'BLOCKED_OWNERSHIP_BOUNDARY');
});

test('missing compensation remains unknown rather than being inferred from display text', () => {
  const prepared = prepareP4ExternalJobReference(candidate({
    compensationSummary: 'Competitive compensation',
    observedCompensation: null,
  }), NOW);
  assert.equal(prepared.resultState, 'REFERENCE_READY');
  assert.equal(prepared.compensationKnown, false);
  assert.equal(prepared.normalizedCompensation, null);
  assert.ok(prepared.unresolvedFields.includes('compensation'));
});

test('ranking compares pay only when currency and unit are actually comparable', () => {
  const lower = prepareP4ExternalJobReference(candidate({
    title: 'Lower',
    observedCompensation: { amount: 20, currency: 'USD', unit: 'HOUR', explicitlyObserved: true },
  }), NOW);
  const higher = prepareP4ExternalJobReference(candidate({
    title: 'Higher',
    destinationUrl: 'https://jobs.example.com/roles/higher',
    observedCompensation: { amount: 40, currency: 'USD', unit: 'HOUR', explicitlyObserved: true },
  }), NOW);
  assert.ok(compareP4ExternalJobReferences(higher, lower, { preferredCurrency: 'USD' }) < 0);

  const krw = prepareP4ExternalJobReference(candidate({
    title: 'KRW',
    destinationUrl: 'https://jobs.example.com/roles/krw',
    observedCompensation: { amount: 50000, currency: 'KRW', unit: 'HOUR', explicitlyObserved: true },
  }), NOW);
  assert.equal(compareP4ExternalJobReferences(higher, krw, { preferredCurrency: 'USD' }) < 0, true);
});

test('P4 backlog suppresses duplicate canonical external references', () => {
  const first = candidate({ destinationUrl: 'https://jobs.example.com/roles/korean-reviewer?b=2&a=1#apply' });
  const second = candidate({ destinationUrl: 'https://jobs.example.com/roles/korean-reviewer?a=1&b=2' });
  const backlog = buildP4HiddenSearchBacklog([first, second], NOW);
  assert.equal(backlog.preparedReferences.length, 1);
  assert.equal(backlog.duplicateSuppressedCount, 1);
});

test('P4 visibility lock keeps external job search out of navigation, Home and Today Route', () => {
  assert.equal(P4_VISIBILITY_LOCK.primaryNavigationVisible, false);
  assert.equal(P4_VISIBILITY_LOCK.homeSectionVisible, false);
  assert.equal(P4_VISIBILITY_LOCK.todayRouteVisible, false);
  assert.equal(P4_VISIBILITY_LOCK.automaticUnlockAllowed, false);

  const home = buildAdClickFirstConsumerHome([]);
  const route = buildAdClickFirstTodayRoute([]);
  assert.deepEqual(home.primaryNavigation, [{ id: 'EARN_NOW', label: '바로 적립' }]);
  assert.equal(home.laterTierNavigationVisible, false);
  assert.equal(home.laterTierSectionsVisible, false);
  assert.equal(route.laterTierSuggestionsVisible, false);
});
