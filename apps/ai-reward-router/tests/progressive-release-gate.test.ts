import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CURRENT_PROGRESSIVE_RELEASE_STATE,
  RELEASE_GATE_INVARIANTS,
  evaluateProgressiveRelease,
  type ProgressiveReleaseInput,
} from '../src/release-gate/index.js';

function input(overrides: Partial<ProgressiveReleaseInput> = {}): ProgressiveReleaseInput {
  return {
    p0TechnicalComplete: true,
    p0LiveActivationComplete: false,
    technicalPrepared: { P1: true, P2: true, P3: true, P4: true },
    releaseDecisions: { P1: 'NOT_APPROVED', P2: 'NOT_APPROVED', P3: 'NOT_APPROVED', P4: 'NOT_APPROVED' },
    ...overrides,
  };
}

test('current production release snapshot remains P0-only with all later tiers hidden', () => {
  assert.deepEqual(CURRENT_PROGRESSIVE_RELEASE_STATE.visibleTiers, ['P0']);
  assert.equal(CURRENT_PROGRESSIVE_RELEASE_STATE.highestVisibleTier, 'P0');
  assert.equal(CURRENT_PROGRESSIVE_RELEASE_STATE.allLaterTiersHidden, true);
  assert.equal(CURRENT_PROGRESSIVE_RELEASE_STATE.p0.liveActivationComplete, false);
  assert.equal(CURRENT_PROGRESSIVE_RELEASE_STATE.laterTierStates[0]?.state, 'HIDDEN_AWAITING_P0_LIVE');
});

test('P0 technical completion alone cannot unlock P1', () => {
  const state = evaluateProgressiveRelease(input({
    releaseDecisions: { P1: 'APPROVED', P2: 'NOT_APPROVED', P3: 'NOT_APPROVED', P4: 'NOT_APPROVED' },
  }));
  assert.deepEqual(state.visibleTiers, ['P0']);
  assert.equal(state.laterTierStates[0]?.state, 'HIDDEN_AWAITING_P0_LIVE');
});

test('P0 live activation still requires explicit P1 approval', () => {
  const state = evaluateProgressiveRelease(input({ p0LiveActivationComplete: true }));
  assert.deepEqual(state.visibleTiers, ['P0']);
  assert.equal(state.laterTierStates[0]?.state, 'HIDDEN_AWAITING_APPROVAL');
});

test('tiers unlock only in strict approved sequence', () => {
  const state = evaluateProgressiveRelease(input({
    p0LiveActivationComplete: true,
    releaseDecisions: { P1: 'APPROVED', P2: 'APPROVED', P3: 'NOT_APPROVED', P4: 'NOT_APPROVED' },
  }));
  assert.deepEqual(state.visibleTiers, ['P0', 'P1', 'P2']);
  assert.equal(state.highestVisibleTier, 'P2');
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P3')?.state, 'HIDDEN_AWAITING_APPROVAL');
});

test('attempting to skip an earlier tier fails closed', () => {
  const state = evaluateProgressiveRelease(input({
    p0LiveActivationComplete: true,
    releaseDecisions: { P1: 'NOT_APPROVED', P2: 'APPROVED', P3: 'APPROVED', P4: 'APPROVED' },
  }));
  assert.deepEqual(state.visibleTiers, ['P0']);
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P2')?.state, 'HIDDEN_UPSTREAM_LOCK');
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P4')?.consumerVisible, false);
});

test('full explicit sequence can make P1 through P4 visible after P0 live activation', () => {
  const state = evaluateProgressiveRelease(input({
    p0LiveActivationComplete: true,
    releaseDecisions: { P1: 'APPROVED', P2: 'APPROVED', P3: 'APPROVED', P4: 'APPROVED' },
  }));
  assert.deepEqual(state.visibleTiers, ['P0', 'P1', 'P2', 'P3', 'P4']);
  assert.equal(state.highestVisibleTier, 'P4');
  assert.equal(state.allLaterTiersHidden, false);
});

test('revoking an earlier tier hides it and every downstream tier even when downstream approvals remain', () => {
  const state = evaluateProgressiveRelease(input({
    p0LiveActivationComplete: true,
    releaseDecisions: { P1: 'APPROVED', P2: 'REVOKED', P3: 'APPROVED', P4: 'APPROVED' },
  }));
  assert.deepEqual(state.visibleTiers, ['P0', 'P1']);
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P2')?.state, 'HIDDEN_REVOKED');
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P3')?.state, 'HIDDEN_UPSTREAM_LOCK');
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P4')?.state, 'HIDDEN_UPSTREAM_LOCK');
});

test('technical preparation is required independently from release approval', () => {
  const state = evaluateProgressiveRelease(input({
    p0LiveActivationComplete: true,
    technicalPrepared: { P1: true, P2: false, P3: true, P4: true },
    releaseDecisions: { P1: 'APPROVED', P2: 'APPROVED', P3: 'APPROVED', P4: 'APPROVED' },
  }));
  assert.deepEqual(state.visibleTiers, ['P0', 'P1']);
  assert.equal(state.laterTierStates.find((tier) => tier.tier === 'P2')?.state, 'HIDDEN_TECHNICAL_NOT_READY');
});

test('all tier locks prohibit automatic unlock and release never bypasses opportunity policy gates', () => {
  assert.equal(RELEASE_GATE_INVARIANTS.automaticUnlockAllowed, false);
  assert.equal(RELEASE_GATE_INVARIANTS.p1AutomaticUnlockAllowed, false);
  assert.equal(RELEASE_GATE_INVARIANTS.p2AutomaticUnlockAllowed, false);
  assert.equal(RELEASE_GATE_INVARIANTS.p3AutomaticUnlockAllowed, false);
  assert.equal(RELEASE_GATE_INVARIANTS.p4AutomaticUnlockAllowed, false);
  assert.equal(RELEASE_GATE_INVARIANTS.releaseDecisionDoesNotFabricateSupply, true);
  assert.equal(RELEASE_GATE_INVARIANTS.perOpportunityTrustPolicyGatesRemainRequired, true);
});
