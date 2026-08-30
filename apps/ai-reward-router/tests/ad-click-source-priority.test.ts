import test from 'node:test';
import assert from 'node:assert/strict';
import { effectiveSourcePriority } from '../src/ad-click-first/source-priority.js';
import { sourceById } from '../src/source-policy/registry.js';

test('issue 1112 promotes ayeT to effective P0 without destroying historical registry metadata', () => {
  const ayet = sourceById('SRC-AYET');
  assert.equal(ayet.launchPriority, 'P2');
  const effective = effectiveSourcePriority(ayet);
  assert.equal(effective.registryLaunchPriority, 'P2');
  assert.equal(effective.effectiveLaunchPriority, 'P0');
  assert.equal(effective.overrideReason, 'OWNER_OVERRIDE_1112_AD_CLICK_FIRST');
});

test('all current ad-click integration candidates are effective P0', () => {
  for (const sourceId of ['SRC-AYET', 'SRC-ADPOPCORN', 'SRC-TNK', 'SRC-ADISON']) {
    assert.equal(effectiveSourcePriority(sourceById(sourceId)).effectiveLaunchPriority, 'P0');
  }
});

test('unrelated later-tier source priority is unchanged by the ad-click override', () => {
  const prolific = sourceById('SRC-PROLIFIC');
  const effective = effectiveSourcePriority(prolific);
  assert.equal(effective.effectiveLaunchPriority, prolific.launchPriority);
  assert.equal(effective.overrideReason, null);
});
