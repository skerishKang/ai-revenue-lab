import test from 'node:test';
import assert from 'node:assert/strict';
import {
  P1_VISIBILITY_LOCK,
  buildP1PreparedBacklog,
  compareP1PreparedOpportunities,
  type P1PreparedOpportunity,
} from '../src/p1-survey/domain.js';
import { buildAdClickFirstConsumerHome, buildAdClickFirstTodayRoute } from '../src/ad-click-first/consumer-home.js';
import { VERIFIED20_RECORDS } from '../src/verified20/ledger.js';

function prepared(overrides: Partial<P1PreparedOpportunity> = {}): P1PreparedOpportunity {
  return {
    opportunityId: 'p1-base',
    sourceId: 'SRC-TEST',
    title: '테스트 설문',
    kind: 'SURVEY',
    preparationState: 'RANKABLE',
    estimatedActiveMinutes: 10,
    rewardAmount: 1000,
    rewardCurrency: 'KRW',
    certainty: 'GUARANTEED',
    effectiveHourlyValue: 6000,
    qualificationRequired: false,
    applicationRequired: false,
    identityKycKnown: true,
    purchaseRequirement: 'NOT_ESTABLISHED',
    unresolvedFrictionFields: [],
    knownFrictionScore: 0,
    canonicalDestinationUrl: 'https://example.com/survey',
    lastCheckedAt: '2026-08-30T12:00:00.000Z',
    supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
    supplyAvailabilityState: 'AVAILABLE',
    ...overrides,
  };
}

test('P1 preparation reuses accepted ledger records without becoming consumer-visible', () => {
  const backlog = buildP1PreparedBacklog(VERIFIED20_RECORDS);
  assert.equal(backlog.mode, 'P1_PREPARATION_HIDDEN');
  assert.equal(backlog.issueNumber, 1130);
  assert.equal(backlog.consumerVisible, false);
  assert.equal(backlog.visibilityLock.consumerVisible, false);
  assert.equal(backlog.visibilityLock.automaticUnlockAllowed, false);
  assert.ok(backlog.opportunities.length > 0);
});

test('provider-level survey programs stay references and are not fabricated into current survey offers', () => {
  const backlog = buildP1PreparedBacklog(VERIFIED20_RECORDS);
  const references = backlog.opportunities.filter((item) => item.preparationState === 'PROGRAM_REFERENCE_ONLY');
  assert.ok(references.length > 0);
  assert.ok(references.every((item) => item.supplyClaimMode === 'PROVIDER_PROGRAM_ONLY'));
});

test('unknown or incomplete P1 opportunities never outrank a fully rankable survey', () => {
  const good = prepared();
  const unknown = prepared({
    opportunityId: 'p1-unknown',
    preparationState: 'UNRANKABLE_MISSING_CRITICAL_DATA',
    estimatedActiveMinutes: null,
    rewardAmount: null,
    rewardCurrency: null,
    effectiveHourlyValue: null,
    unresolvedFrictionFields: ['accountLoginRequirement'],
  });
  assert.ok(compareP1PreparedOpportunities(good, unknown) < 0);
});

test('within equally known low-friction surveys, higher effective hourly value ranks first', () => {
  const lower = prepared({ opportunityId: 'lower', rewardAmount: 1000, effectiveHourlyValue: 6000 });
  const higher = prepared({ opportunityId: 'higher', rewardAmount: 1500, effectiveHourlyValue: 9000 });
  assert.ok(compareP1PreparedOpportunities(higher, lower) < 0);
});

test('more unresolved friction ranks after otherwise equivalent P1 opportunities', () => {
  const known = prepared({ opportunityId: 'known' });
  const unknown = prepared({ opportunityId: 'unknown', unresolvedFrictionFields: ['payoutDelay'] });
  assert.ok(compareP1PreparedOpportunities(known, unknown) < 0);
});

test('P1 visibility lock keeps survey out of primary navigation, Home and Today Route', () => {
  assert.equal(P1_VISIBILITY_LOCK.primaryNavigationVisible, false);
  assert.equal(P1_VISIBILITY_LOCK.homeSectionVisible, false);
  assert.equal(P1_VISIBILITY_LOCK.todayRouteVisible, false);

  const home = buildAdClickFirstConsumerHome([]);
  const route = buildAdClickFirstTodayRoute([]);
  assert.deepEqual(home.primaryNavigation, [{ id: 'EARN_NOW', label: '바로 적립' }]);
  assert.equal(home.laterTierNavigationVisible, false);
  assert.equal(home.laterTierSectionsVisible, false);
  assert.equal(route.laterTierSuggestionsVisible, false);
});
