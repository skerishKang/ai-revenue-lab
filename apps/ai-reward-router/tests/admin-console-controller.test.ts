import test from 'node:test';
import assert from 'node:assert/strict';
import { createAdminConsoleFixtureState } from '../src/admin-console/fixture-state.js';
import {
  handleAdminConsoleRequest,
  InMemoryAdminConsoleRepository,
} from '../src/admin-console/controller.js';

const T1 = '2026-08-30T04:00:00.000Z';

test('controller serves dashboard without mutating repository state', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const before = repository.read();
  const result = handleAdminConsoleRequest(repository, { kind: 'GET', route: 'DASHBOARD' });
  const after = repository.read();
  assert.equal(result.revision, 0);
  assert.equal(after.revision, 0);
  assert.equal(before.state, after.state);
  assert.match(result.html, /B64 Admin Console/);
});

test('review action persists through controller and is visible on subsequent GET', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const result = handleAdminConsoleRequest(repository, {
    kind: 'REVIEW',
    command: {
      action: 'APPROVE', role: 'REVIEWER', actorId: 'reviewer-controller', reviewQueueId: 'rq-promo',
      decisionId: 'decision-controller', auditId: 'audit-controller', reason: 'Evidence inspected in admin console', at: T1,
    },
    returnRoute: 'AUDIT_LOG',
  });
  assert.equal(result.revision, 1);
  assert.equal(result.lastAuditId, 'audit-controller');
  assert.match(result.html, /REVIEW_APPROVE/);

  const followup = handleAdminConsoleRequest(repository, { kind: 'GET', route: 'OPPORTUNITIES' });
  assert.equal(followup.revision, 1);
  assert.equal(repository.read().state.versions.find((item) => item.id === 'offer-fixture-promo-v1')?.verificationState, 'VERIFIED');
});

test('forbidden request leaves state and revision unchanged', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const before = repository.read();
  assert.throws(() => handleAdminConsoleRequest(repository, {
    kind: 'REVIEW',
    command: {
      action: 'APPROVE', role: 'VIEWER', actorId: 'viewer-controller', reviewQueueId: 'rq-promo',
      decisionId: 'decision-viewer-controller', auditId: 'audit-viewer-controller', reason: 'Forbidden', at: T1,
    },
  }), /cannot perform opportunity review actions/);
  const after = repository.read();
  assert.equal(after.revision, before.revision);
  assert.equal(after.state, before.state);
});

test('stale/broken operation persists and audit route exposes it', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const result = handleAdminConsoleRequest(repository, {
    kind: 'HEALTH',
    command: {
      action: 'SUPPRESS_OFFER', role: 'OPERATOR', actorId: 'operator-controller', incidentId: 'stale-fixture-usertesting',
      auditId: 'audit-health-controller', reason: 'Source unavailable during operator review', at: T1,
    },
    returnRoute: 'AUDIT_LOG',
  });
  assert.equal(result.revision, 1);
  assert.match(result.html, /STALE_BROKEN_SUPPRESS_OFFER/);
  assert.equal(repository.read().state.opportunities.find((item) => item.id === 'offer-fixture-unknown')?.lifecycleState, 'STALE');
});

test('repository uses optimistic revision guard so concurrent replacement fails closed', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const snapshot = repository.read();
  repository.replace(snapshot.revision, snapshot.state);
  assert.throws(() => repository.replace(snapshot.revision, snapshot.state), /revision conflict/);
});
