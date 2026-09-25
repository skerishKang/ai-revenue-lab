import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEVICE_LIFECYCLE,
  DEVICE_LIFECYCLE_STATES,
  DeviceLifecycleError,
  canTransition,
  initialDeviceLifecycleProjection,
  projectDeviceLifecycle,
} from '../src/contract/device-lifecycle.js';

test('#3083 shell exposes exactly the five required presentation states', () => {
  assert.deepEqual([...DEVICE_LIFECYCLE_STATES].sort(), [
    'ACTION_REQUIRED',
    'NOT_PAIRED',
    'OFFLINE',
    'ONLINE',
    'PAIRING',
  ]);
  assert.equal(DEVICE_LIFECYCLE.PRESENTATION_STATE_ONLY, true);
  assert.equal(DEVICE_LIFECYCLE.CANONICAL_TRUTH_OWNED_BY, '#3080');
  assert.equal(DEVICE_LIFECYCLE.RENDERER_MAY_FORGE_ONLINE, false);
});

test('#3083 ONLINE cannot be reached from NOT_PAIRED — a renderer claim cannot skip pairing', () => {
  assert.equal(canTransition('NOT_PAIRED', 'ONLINE'), false);
  const initial = initialDeviceLifecycleProjection();
  assert.equal(initial.state, 'NOT_PAIRED');
  assert.equal(initial.evidenceBacked, false);
  assert.throws(
    () => projectDeviceLifecycle(initial, 'user_pairing_request', 'ONLINE', 'renderer asked nicely'),
    (error: unknown) =>
      error instanceof DeviceLifecycleError && /illegal device lifecycle transition/.test(error.message),
  );
});

test('#3083 a user-initiated ONLINE claim is refused even on a legal edge', () => {
  const paired = projectDeviceLifecycle(
    initialDeviceLifecycleProjection(),
    'user_pairing_request',
    'PAIRING',
    'user started pairing',
  );
  assert.equal(paired.state, 'PAIRING');
  // PAIRING -> ONLINE is a legal edge, but only a supervision/server fact may take it.
  assert.throws(
    () => projectDeviceLifecycle(paired, 'user_pairing_request', 'ONLINE', 'renderer claim'),
    (error: unknown) =>
      error instanceof DeviceLifecycleError && /renderer claims are not evidence/.test(error.message),
  );
  const evidenceBacked = projectDeviceLifecycle(paired, 'supervision', 'ONLINE', 'runner healthy');
  assert.equal(evidenceBacked.state, 'ONLINE');
  assert.equal(evidenceBacked.evidenceBacked, true);
});

test('#3083 unknown device states are refused rather than coerced', () => {
  const initial = initialDeviceLifecycleProjection();
  assert.throws(
    () =>
      projectDeviceLifecycle(
        initial,
        'supervision',
        'ONLINE_AND_TRUSTED' as never,
        'bogus',
      ),
    (error: unknown) =>
      error instanceof DeviceLifecycleError && /unknown device lifecycle state/.test(error.message),
  );
});

test('#3083 every projection advances its revision so the renderer can detect change', () => {
  let projection = initialDeviceLifecycleProjection();
  const revisions: number[] = [projection.sinceRevision];
  projection = projectDeviceLifecycle(projection, 'user_pairing_request', 'PAIRING', 'a');
  revisions.push(projection.sinceRevision);
  projection = projectDeviceLifecycle(projection, 'supervision', 'ONLINE', 'b');
  revisions.push(projection.sinceRevision);
  projection = projectDeviceLifecycle(projection, 'runner_unhealthy', 'OFFLINE', 'c');
  revisions.push(projection.sinceRevision);
  assert.deepEqual(revisions, [0, 1, 2, 3]);
  assert.equal(projection.state, 'OFFLINE');
  // An unhealthy-runner edge is a local observation, not canonical server truth.
  assert.equal(projection.evidenceBacked, false);
});
