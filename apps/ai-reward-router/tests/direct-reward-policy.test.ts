import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canActivateDirectRewardProvider,
  directRewardPolicyByProvider,
} from '../src/ad-click-first/direct-reward-policy.js';

test('ayeT is the primary web candidate but remains inactive before onboarding and live authority', () => {
  const policy = directRewardPolicyByProvider('SRC-AYET');
  assert.equal(policy.state, 'CANDIDATE_ONBOARDING_REQUIRED');
  assert.equal(policy.webPath, 'SUPPORTED');
  assert.equal(policy.realWorldUserReward, 'ALLOWED_OR_SUPPORTED');
  assert.equal(canActivateDirectRewardProvider('SRC-AYET'), false);
});

test('Google and Unity/Tapjoy real-world rewarded-ad paths are explicitly blocked', () => {
  for (const providerId of ['GOOGLE_REWARDED_ADS', 'UNITY_TAPJOY_REWARDED']) {
    const policy = directRewardPolicyByProvider(providerId);
    assert.equal(policy.state, 'BLOCK_REAL_WORLD_REWARD');
    assert.equal(policy.realWorldUserReward, 'PROHIBITED');
    assert.equal(policy.activateInAdClickP0, false);
  }
});

test('AdGate stays pending even though a web offerwall exists because external-value user reward authority is unconfirmed', () => {
  const policy = directRewardPolicyByProvider('ADGATE_MEDIA');
  assert.equal(policy.webPath, 'SUPPORTED');
  assert.equal(policy.state, 'PENDING_EXPLICIT_REWARD_VALUE_CLEARANCE');
  assert.equal(policy.realWorldUserReward, 'UNCONFIRMED');
  assert.equal(policy.activateInAdClickP0, false);
});

test('mobile external-point candidates remain disabled until an approved B64 integration path exists', () => {
  for (const providerId of ['SRC-ADPOPCORN', 'SRC-TNK']) {
    const policy = directRewardPolicyByProvider(providerId);
    assert.equal(policy.state, 'CANDIDATE_MOBILE_PATH_ONLY');
    assert.equal(policy.webPath, 'UNCONFIRMED');
    assert.equal(policy.activateInAdClickP0, false);
  }
});
