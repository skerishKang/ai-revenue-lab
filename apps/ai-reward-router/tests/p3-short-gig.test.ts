import test from 'node:test';
import assert from 'node:assert/strict';
import {
  P3_VISIBILITY_LOCK,
  buildP3PreparedBacklog,
  compareP3PreparedOpportunities,
  prepareP3Opportunity,
  type P3PreparedOpportunity,
} from '../src/p3-short-gig/domain.js';
import { buildAdClickFirstConsumerHome, buildAdClickFirstTodayRoute } from '../src/ad-click-first/consumer-home.js';
import { VERIFIED20_RECORDS } from '../src/verified20/ledger.js';

function prepared(overrides: Partial<P3PreparedOpportunity> = {}): P3PreparedOpportunity {
  return {
    opportunityId: 'p3-base',
    canonicalKey: 'SRC-TEST:p3-base',
    sourceId: 'SRC-TEST',
    title: '테스트 단기 프로젝트',
    kind: 'REMOTE_PROJECT',
    preparationState: 'RANKABLE',
    supplyMode: 'CURRENT_GIG_INVENTORY',
    commitmentMode: 'BOUNDED_PROJECT_OR_TASK',
    payModel: 'FIXED_PROJECT',
    rewardAmount: 100000,
    rewardCurrency: 'KRW',
    estimatedActiveMinutes: 300,
    estimatedTotalEffortMinutes: 360,
    normalizedHourlyValue: 20000,
    certainty: 'GUARANTEED',
    applicationRequired: false,
    qualificationRequired: false,
    acceptanceProbabilityKnown: true,
    identityKycKnown: true,
    languageRequirementsKnown: true,
    skillRequirementsKnown: true,
    deviceRequirementsKnown: true,
    scheduleRequirementKnown: true,
    payoutDelayKnown: true,
    repeatabilityKnown: true,
    purchaseOrSpendRequired: false,
    requiredEligibilityCount: 0,
    unresolvedFrictionFields: [],
    knownFrictionScore: 0,
    canonicalDestinationUrl: 'https://example.com/project',
    lastCheckedAt: '2026-08-30T13:00:00.000Z',
    supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
    supplyAvailabilityState: 'CURRENT_PROJECT_AVAILABLE',
    ...overrides,
  };
}

test('P3 preparation reuses accepted skilled-gig records without becoming consumer-visible', () => {
  const backlog = buildP3PreparedBacklog(VERIFIED20_RECORDS);
  assert.equal(backlog.mode, 'P3_SHORT_GIG_PREPARATION_HIDDEN');
  assert.equal(backlog.issueNumber, 1135);
  assert.equal(backlog.consumerVisible, false);
  assert.equal(backlog.visibilityLock.automaticUnlockAllowed, false);
  assert.ok(backlog.opportunities.length > 0);
});

test('existing public role/project pages remain application references instead of current executable gig supply', () => {
  const backlog = buildP3PreparedBacklog(VERIFIED20_RECORDS);
  const references = backlog.opportunities.filter((item) => item.preparationState === 'PROJECT_APPLICATION_REFERENCE_ONLY');
  assert.ok(references.length > 0);
  assert.ok(references.every((item) => item.supplyMode === 'PUBLIC_PROJECT_APPLICATION'));
});

test('recurring side jobs and open-ended digital work are excluded from P3', () => {
  const base = VERIFIED20_RECORDS.find((record) => record.version.incomeLadderLevel === 'SKILLED_DIGITAL_GIG') ?? VERIFIED20_RECORDS[0]!;
  const recurring = {
    ...base,
    version: {
      ...base.version,
      opportunityCategory: 'RECURRING_DIGITAL_WORK' as const,
      incomeLadderLevel: 'RECURRING_SIDE_JOB' as const,
    },
  };
  assert.equal(prepareP3Opportunity(recurring), null);
});

test('unknown commitment cannot outrank a bounded current short gig', () => {
  const bounded = prepared();
  const unknown = prepared({
    opportunityId: 'p3-unknown',
    preparationState: 'UNRANKABLE_UNKNOWN_COMMITMENT',
    commitmentMode: 'UNKNOWN_COMMITMENT',
    estimatedActiveMinutes: null,
    estimatedTotalEffortMinutes: null,
    normalizedHourlyValue: null,
    unresolvedFrictionFields: ['estimatedTotalEffortMinutes'],
  });
  assert.ok(compareP3PreparedOpportunities(bounded, unknown) < 0);
});

test('within equally known current short gigs, higher supportable hourly value ranks first', () => {
  const lower = prepared({ opportunityId: 'lower', normalizedHourlyValue: 15000 });
  const higher = prepared({ opportunityId: 'higher', normalizedHourlyValue: 25000 });
  assert.ok(compareP3PreparedOpportunities(higher, lower) < 0);
});

test('more unresolved application and project friction ranks after otherwise equivalent P3 gigs', () => {
  const known = prepared({ opportunityId: 'known' });
  const unknown = prepared({
    opportunityId: 'unknown-friction',
    unresolvedFrictionFields: ['acceptanceProbability', 'payoutDelay'],
  });
  assert.ok(compareP3PreparedOpportunities(known, unknown) < 0);
});

test('P3 backlog suppresses duplicate source/canonical project identities', () => {
  const candidate = VERIFIED20_RECORDS.find((record) => prepareP3Opportunity(record) !== null);
  assert.ok(candidate);
  const backlog = buildP3PreparedBacklog([candidate!, candidate!]);
  assert.equal(backlog.opportunities.length, 1);
  assert.equal(backlog.duplicateSuppressedCount, 1);
});

test('P3 visibility lock keeps short gigs out of navigation, Home and Today Route', () => {
  assert.equal(P3_VISIBILITY_LOCK.primaryNavigationVisible, false);
  assert.equal(P3_VISIBILITY_LOCK.homeSectionVisible, false);
  assert.equal(P3_VISIBILITY_LOCK.todayRouteVisible, false);

  const home = buildAdClickFirstConsumerHome([]);
  const route = buildAdClickFirstTodayRoute([]);
  assert.deepEqual(home.primaryNavigation, [{ id: 'EARN_NOW', label: '바로 적립' }]);
  assert.equal(home.laterTierNavigationVisible, false);
  assert.equal(home.laterTierSectionsVisible, false);
  assert.equal(route.laterTierSuggestionsVisible, false);
});
