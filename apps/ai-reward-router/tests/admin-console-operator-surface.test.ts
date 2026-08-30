import test from 'node:test';
import assert from 'node:assert/strict';
import { createAdminConsoleFixtureState } from '../src/admin-console/fixture-state.js';
import {
  handleAdminConsoleRequest,
  handleAdminReviewFormSubmission,
  InMemoryAdminConsoleRepository,
} from '../src/admin-console/controller.js';

const T1 = '2026-08-30T08:30:00.000Z';

test('operator review page exposes executable review form for all W7 decisions without editable role identity', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const result = handleAdminConsoleRequest(repository, {
    kind: 'GET',
    route: 'OPPORTUNITY_REVIEW',
    selectedId: 'offer-fixture-promo-v1',
  });
  assert.match(result.html, /data-b64-review-form="true"/);
  assert.match(result.html, /name="action" value="APPROVE"/);
  assert.match(result.html, /name="action" value="MODIFY_APPROVE"/);
  assert.match(result.html, /name="action" value="REJECT"/);
  assert.match(result.html, /name="action" value="RE_EXTRACT"/);
  assert.doesNotMatch(result.html, /name="role"/);
  assert.doesNotMatch(result.html, /name="actorId"/);
});

test('APPROVE submitted from operator form completes first-offer review and persists audit without direct state editing', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  const result = handleAdminReviewFormSubmission(
    repository,
    { actorId: 'reviewer-form', role: 'REVIEWER' },
    {
      action: 'APPROVE',
      reviewQueueId: 'rq-promo',
      selectedId: 'offer-fixture-promo-v1',
      reason: 'Reviewed bound source evidence in W7 operator surface',
    },
    { at: T1, idempotencyKey: 'form-approve-promo' },
  );

  const state = repository.read().state;
  assert.equal(result.revision, 1);
  assert.equal(state.reviewQueue.find((item) => item.id === 'rq-promo')?.state, 'RESOLVED');
  assert.equal(state.versions.find((item) => item.id === 'offer-fixture-promo-v1')?.verificationState, 'VERIFIED');
  assert.equal(state.opportunities.find((item) => item.id === 'offer-fixture-promo')?.currentVersionId, 'offer-fixture-promo-v1');
  assert.equal(state.auditLog.at(-1)?.actorId, 'reviewer-form');
  assert.equal(state.auditLog.at(-1)?.action, 'REVIEW_APPROVE');
  assert.match(result.html, /No open review action is available for this version/);
});

test('MODIFY + APPROVE form requires a JSON object patch and creates immutable reviewed version', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  assert.throws(() => handleAdminReviewFormSubmission(
    repository,
    { actorId: 'reviewer-form', role: 'REVIEWER' },
    {
      action: 'MODIFY_APPROVE',
      reviewQueueId: 'rq-research',
      selectedId: 'offer-fixture-research-v1',
      reason: 'Correct evidence-backed title',
      resultingVersionId: 'offer-fixture-research-v2-form',
      patchJson: '[]',
    },
    { at: T1, idempotencyKey: 'form-modify-invalid' },
  ), /patchJson must be a JSON object/);
  assert.equal(repository.read().revision, 0);

  handleAdminReviewFormSubmission(
    repository,
    { actorId: 'reviewer-form', role: 'REVIEWER' },
    {
      action: 'MODIFY_APPROVE',
      reviewQueueId: 'rq-research',
      selectedId: 'offer-fixture-research-v1',
      reason: 'Correct evidence-backed title',
      resultingVersionId: 'offer-fixture-research-v2-form',
      patchJson: '{"title":"Corrected paid research opportunity"}',
    },
    { at: T1, idempotencyKey: 'form-modify-valid' },
  );

  const state = repository.read().state;
  assert.equal(repository.read().revision, 1);
  assert.equal(state.versions.find((item) => item.id === 'offer-fixture-research-v1')?.title, 'Synthetic paid research fixture');
  assert.equal(state.versions.find((item) => item.id === 'offer-fixture-research-v2-form')?.title, 'Corrected paid research opportunity');
  assert.equal(state.opportunities.find((item) => item.id === 'offer-fixture-research')?.currentVersionId, 'offer-fixture-research-v2-form');
  assert.equal(state.reviewPatches.at(-1)?.id, 'patch-form-modify-valid');
});

test('REJECT and RE-EXTRACT form submissions remain fail-closed and auditable', () => {
  const rejectRepository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  handleAdminReviewFormSubmission(
    rejectRepository,
    { actorId: 'reviewer-form', role: 'REVIEWER' },
    { action: 'REJECT', reviewQueueId: 'rq-unknown', reason: 'Evidence insufficient' },
    { at: T1, idempotencyKey: 'form-reject' },
  );
  assert.equal(rejectRepository.read().state.versions.find((item) => item.id === 'offer-fixture-unknown-v1')?.verificationState, 'REJECTED');
  assert.equal(rejectRepository.read().state.auditLog.at(-1)?.action, 'REVIEW_REJECT');

  const reextractRepository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  handleAdminReviewFormSubmission(
    reextractRepository,
    { actorId: 'reviewer-form', role: 'REVIEWER' },
    { action: 'RE_EXTRACT', reviewQueueId: 'rq-ai', reason: 'Conflicting terms need extraction retry' },
    { at: T1, idempotencyKey: 'form-reextract' },
  );
  assert.equal(reextractRepository.read().state.versions.find((item) => item.id === 'offer-fixture-ai-v1')?.verificationState, 'REVIEW_REQUIRED');
  assert.equal(reextractRepository.read().state.reextractRequests.at(-1)?.id, 'reextract-form-reextract');
  assert.equal(reextractRepository.read().state.auditLog.at(-1)?.action, 'REVIEW_RE_EXTRACT');
});

test('viewer form submission cannot self-elevate and leaves repository unchanged', () => {
  const repository = new InMemoryAdminConsoleRepository(createAdminConsoleFixtureState());
  assert.throws(() => handleAdminReviewFormSubmission(
    repository,
    { actorId: 'viewer-form', role: 'VIEWER' },
    { action: 'APPROVE', reviewQueueId: 'rq-promo', reason: 'Attempt unauthorized approval' },
    { at: T1, idempotencyKey: 'form-viewer' },
  ), /cannot perform opportunity review actions/);
  assert.equal(repository.read().revision, 0);
  assert.equal(repository.read().state.auditLog.length, 0);
});
