import test from 'node:test';
import assert from 'node:assert/strict';
import {
  P2_VISIBILITY_LOCK,
  buildP2PreparedBacklog,
  compareP2PreparedOpportunities,
  type P2PreparedOpportunity,
} from '../src/p2-microtask/domain.js';
import { buildAdClickFirstConsumerHome, buildAdClickFirstTodayRoute } from '../src/ad-click-first/consumer-home.js';
import { VERIFIED20_RECORDS } from '../src/verified20/ledger.js';

function prepared(overrides: Partial<P2PreparedOpportunity> = {}): P2PreparedOpportunity {
  return {
    opportunityId: 'p2-base',
    canonicalKey: 'SRC-TEST:p2-base',
    sourceId: 'SRC-TEST',
    title: '짧은 데이터 태스크',
    kind: 'DATA_TASK',
    preparationState: 'RANKABLE',
    supplyMode: 'CURRENT_TASK_INVENTORY',
    payModel: 'PER_TASK',
    rewardAmount: 1000,
    rewardCurrency: 'KRW',
    estimatedActiveMinutes: 10,
    estimatedTotalEffortMinutes: 12,
    normalizedHourlyValue: 6000,
    certainty: 'GUARANTEED',
    applicationRequired: false,
    qualificationRequired: false,
    identityKycKnown: true,
    requiredEligibilityCount: 0,
    languageRequirementsKnown: true,
    skillRequirementsKnown: true,
    deviceRequirementsKnown: true,
    scheduleRequirementKnown: true,
    repeatabilityKnown: true,
    payoutDelayKnown: true,
    purchaseOrSpendRequired: false,
    unresolvedFrictionFields: [],
    knownFrictionScore: 0,
    canonicalDestinationUrl: 'https://example.com/task',
    lastCheckedAt: '2026-08-30T13:00:00.000Z',
    supplyClaimMode: 'PUBLIC_CURRENT_INVENTORY',
    supplyAvailabilityState: 'CURRENT_TASK_AVAILABLE',
    ...overrides,
  };
}

const P2_CATEGORIES = new Set([
  'MICROTASK',
  'DATA_ANNOTATION',
  'DATA_REVIEW',
  'SEARCH_OR_QUALITY_EVALUATION',
  'AI_EVALUATION',
  'TRANSCRIPTION',
]);

function acceptedP2Record() {
  const record = VERIFIED20_RECORDS.find((item) =>
    P2_CATEGORIES.has(item.version.opportunityCategory)
    && (item.version.incomeLadderLevel === 'TASK_WORK' || item.version.incomeLadderLevel === 'MICRO_REWARD'));
  assert.ok(record, 'accepted ledger should contain at least one P2 candidate');
  return record;
}

test('P2 preparation reuses accepted task records without becoming consumer-visible', () => {
  const backlog = buildP2PreparedBacklog(VERIFIED20_RECORDS);
  assert.equal(backlog.mode, 'P2_MICROTASK_PREPARATION_HIDDEN');
  assert.equal(backlog.issueNumber, 1133);
  assert.equal(backlog.consumerVisible, false);
  assert.equal(backlog.visibilityLock.consumerVisible, false);
  assert.equal(backlog.visibilityLock.automaticUnlockAllowed, false);
  assert.ok(backlog.opportunities.length > 0);
});

test('public project applications remain references instead of being fabricated into current task inventory', () => {
  const backlog = buildP2PreparedBacklog(VERIFIED20_RECORDS);
  const references = backlog.opportunities.filter((item) => item.preparationState === 'PROJECT_APPLICATION_REFERENCE_ONLY');
  assert.ok(references.length > 0);
  assert.ok(references.every((item) => item.supplyMode === 'PUBLIC_PROJECT_APPLICATION'));
});

test('skilled digital gigs do not leak backward into the P2 microtask tier', () => {
  const skilled = VERIFIED20_RECORDS.filter((item) =>
    P2_CATEGORIES.has(item.version.opportunityCategory)
    && item.version.incomeLadderLevel === 'SKILLED_DIGITAL_GIG');
  const backlog = buildP2PreparedBacklog(VERIFIED20_RECORDS);
  for (const item of skilled) {
    assert.equal(backlog.opportunities.some((preparedItem) => preparedItem.opportunityId === item.opportunity.id), false);
  }
});

test('unknown current-task data never outranks a fully rankable microtask', () => {
  const good = prepared();
  const unknown = prepared({
    opportunityId: 'p2-unknown',
    preparationState: 'UNRANKABLE_MISSING_CRITICAL_DATA',
    rewardAmount: null,
    rewardCurrency: null,
    normalizedHourlyValue: null,
    unresolvedFrictionFields: ['payoutDelay'],
  });
  assert.ok(compareP2PreparedOpportunities(good, unknown) < 0);
});

test('within equally known current tasks, lower friction then higher normalized hourly value wins', () => {
  const highFriction = prepared({ opportunityId: 'high-friction', knownFrictionScore: 3, normalizedHourlyValue: 12000 });
  const lowFriction = prepared({ opportunityId: 'low-friction', knownFrictionScore: 0, normalizedHourlyValue: 6000 });
  assert.ok(compareP2PreparedOpportunities(lowFriction, highFriction) < 0);

  const lowerValue = prepared({ opportunityId: 'lower-value', normalizedHourlyValue: 6000 });
  const higherValue = prepared({ opportunityId: 'higher-value', normalizedHourlyValue: 9000 });
  assert.ok(compareP2PreparedOpportunities(higherValue, lowerValue) < 0);
});

test('P2 backlog suppresses duplicate canonical opportunities', () => {
  const record = acceptedP2Record();
  const backlog = buildP2PreparedBacklog([record, record]);
  assert.equal(backlog.opportunities.length, 1);
  assert.equal(backlog.duplicateSuppressedCount, 1);
});

test('P2 visibility lock keeps microtasks out of primary navigation, Home and Today Route', () => {
  assert.equal(P2_VISIBILITY_LOCK.primaryNavigationVisible, false);
  assert.equal(P2_VISIBILITY_LOCK.homeSectionVisible, false);
  assert.equal(P2_VISIBILITY_LOCK.todayRouteVisible, false);

  const home = buildAdClickFirstConsumerHome([]);
  const route = buildAdClickFirstTodayRoute([]);
  assert.deepEqual(home.primaryNavigation, [{ id: 'EARN_NOW', label: '바로 적립' }]);
  assert.equal(home.laterTierNavigationVisible, false);
  assert.equal(home.laterTierSectionsVisible, false);
  assert.equal(route.laterTierSuggestionsVisible, false);
});
