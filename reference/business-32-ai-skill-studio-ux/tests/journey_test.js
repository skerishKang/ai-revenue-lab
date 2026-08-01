/* Journey test: 15-step task-to-verified-skill journey with reviewer handoff,
 * every required sub-journey, and per-action feedback fields.
 */
'use strict';

const assert = require('assert');
const Machine = require('../scripts/machine.js');
const Fixture = require('../scripts/fixture.js');

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (error) {
    failures += 1;
    console.error('FAIL ' + name + ': ' + error.message);
  }
}

function walk(actions) {
  let machine = Machine.createMachine(Fixture, 'standard');
  actions.forEach(function (entry) {
    machine = Machine.transition(machine, entry[0], entry[1]);
  });
  return machine;
}

const toFirstMissing = [
  ['load-ok'],
  ['select-task', { taskId: 'b32-001' }],
  ['check-inputs'],
  ['supplement', { inputId: 'criteria' }],
  ['begin-run'],
  ['complete-step'],
  ['next-step'],
  ['complete-step']
];

const firstDraft = toFirstMissing.concat([
  ['request-supplement', { note: '재견적 요청' }],
  ['resume-run'],
  ['resume-confirm'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['resolve-conflict', { decision: 'C' }],
  ['next-step'],
  ['complete-step'],
  ['next-step'],
  ['complete-step']
]);

const fullJourney = firstDraft.concat([
  ['request-review'],
  ['handoff-to-reviewer'],
  ['reject-review', { note: '보증 재확인' }],
  ['handoff-to-operator'],
  ['apply-correction'],
  ['re-run'],
  ['complete-step'], ['next-step'],
  ['complete-step'], ['next-step'],
  ['complete-step'], ['next-step'],
  ['complete-step'], ['next-step'],
  ['complete-step'],
  ['request-review'],
  ['handoff-to-reviewer'],
  ['approve-review'],
  ['approve'],
  ['handoff-to-operator'],
  ['save-skill'],
  ['complete']
]);

check('15-step journey with handoff completes to skill-saved then completed', function () {
  const m = walk(fullJourney);
  assert.strictEqual(m.state, 'completed');
  assert.ok(m.context.skill);
  assert.strictEqual(m.context.versions[0].version, '1.0');
  assert.strictEqual(m.context.skill.nextReview, '2026-11-01');
  assert.ok(m.context.roleHistory.length >= 4);
});

check('journey feedback includes interaction-contract fields', function () {
  const m = walk(toFirstMissing);
  const fb = m.feedback || {};
  assert.ok(fb.failure, 'missing-evidence must explain failure');
  assert.ok(fb.reviewReason, 'missing-evidence must explain why review needed');
  assert.ok(fb.next, 'must state next action');
});

check('missing-evidence journey ends in a resolvable stopped state', function () {
  const m = walk(toFirstMissing);
  assert.strictEqual(m.state, 'missing-evidence');
  assert.ok(m.context.evidence.missing.length >= 1);
  const stopped = walk(toFirstMissing.concat([['request-supplement', { note: '접수' }]]));
  assert.strictEqual(stopped.state, 'stopped');
  const resumed = walk(toFirstMissing.concat([['request-supplement', { note: '접수' }], ['resume-run'], ['resume-confirm']]));
  assert.strictEqual(resumed.state, 'running');
});

check('conflicting-evidence journey requires human decision', function () {
  const toConflict = toFirstMissing.concat([['request-supplement', { note: '접수' }], ['resume-run'], ['resume-confirm'], ['complete-step'], ['next-step'], ['complete-step']]);
  const m = walk(toConflict);
  assert.strictEqual(m.state, 'conflicting-evidence');
  assert.ok(m.context.evidence.conflicts.length >= 1);
  const resolved = walk(toConflict.concat([['resolve-conflict', { decision: 'C', reason: '납기 7일·보증 24개월' }]]));
  assert.strictEqual(resolved.state, 'step-complete');
  assert.strictEqual(resolved.context.conflictDecision.candidate, 'C');
});

check('stop/resume preserves progress; cancel preserves nothing lost', function () {
  const stopped = walk([['load-ok'], ['select-task', { taskId: 'b32-001' }], ['check-inputs'], ['supplement', { inputId: 'criteria' }], ['begin-run'], ['complete-step'], ['stop-run']]);
  assert.strictEqual(stopped.state, 'stopped');
  const cancelled = walk([['load-ok'], ['select-task', { taskId: 'b32-001' }], ['check-inputs'], ['supplement', { inputId: 'criteria' }], ['begin-run'], ['stop-run'], ['cancel']]);
  assert.strictEqual(cancelled.state, 'cancelled');
  assert.ok(cancelled.feedback.cancel, 'cancel result must be explained');
  const back = walk([['load-ok'], ['select-task', { taskId: 'b32-001' }], ['check-inputs'], ['supplement', { inputId: 'criteria' }], ['begin-run'], ['stop-run'], ['cancel'], ['list-tasks']]);
  assert.strictEqual(back.state, 'initial');
});

check('review correction with handoff then re-run reaches draft again', function () {
  const base = firstDraft.concat([
    ['request-review'],
    ['handoff-to-reviewer'],
    ['reject-review', { note: '재확인' }],
    ['handoff-to-operator'],
    ['apply-correction']
  ]);
  const revised = walk(base);
  assert.strictEqual(revised.state, 'revised');
  assert.ok(revised.context.corrections.length >= 1);
  assert.strictEqual(revised.context.draft.text, '견적 C 조건부 추천');
  const rerun = walk(base.concat([['re-run']]));
  assert.strictEqual(rerun.state, 'running');
  assert.ok(rerun.context.revisionRun, 're-run must be a revision pass');
});

check('pre-approval skill save is blocked with validation-error', function () {
  const pre = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer'], ['approve-review']]));
  assert.strictEqual(pre.state, 'approval-pending');
  const blocked = Machine.transition(pre, 'save-skill');
  assert.strictEqual(blocked.state, 'validation-error');
  assert.ok(blocked.feedback.failure, 'block must explain why');
  const back = Machine.transition(blocked, 'ack');
  assert.strictEqual(back.state, 'approval-pending');
});

check('approved skill save carries exceptions to the final card', function () {
  const m = walk(firstDraft.concat([
    ['request-review'], ['handoff-to-reviewer'], ['reject-review', { note: '재확인' }],
    ['handoff-to-operator'], ['apply-correction'], ['re-run'],
    ['complete-step'], ['next-step'], ['complete-step'], ['next-step'],
    ['complete-step'], ['next-step'], ['complete-step'], ['next-step'], ['complete-step'],
    ['request-review'], ['handoff-to-reviewer'], ['approve-review'], ['approve'],
    ['handoff-to-operator'], ['save-skill']
  ]));
  assert.strictEqual(m.state, 'skill-saved');
  const skill = m.context.skill;
  assert.ok(skill.exceptions.length >= 3, 'exceptions must survive approval');
  assert.ok(skill.evidenceMissing.length >= 1, 'missing evidence recorded');
  assert.ok(skill.evidenceConflicts.length >= 1, 'conflicts recorded');
  assert.ok(skill.corrections.length >= 1, 'corrections recorded');
});

check('system-error → retry → recovery is deterministic', function () {
  let m = Machine.createMachine(Fixture, 'fault');
  m = Machine.transition(m, 'load-error');
  assert.strictEqual(m.state, 'system-error');
  m = Machine.transition(m, 'retry');
  assert.strictEqual(m.state, 'retry');
  m = Machine.transition(m, 'retry-confirm');
  assert.strictEqual(m.state, 'loading');
  m = Machine.transition(m, 'load-ok');
  assert.strictEqual(m.state, 'initial');
});

check('empty bench scenario reaches empty then refills', function () {
  let m = Machine.createMachine(Fixture, 'empty-bench');
  m = Machine.transition(m, 'load-ok');
  assert.strictEqual(m.state, 'empty');
  m = Machine.transition(m, 'load-tasks');
  assert.strictEqual(m.state, 'initial');
});

check('supplement with invalid payload returns validation-error', function () {
  let m = Machine.createMachine(Fixture, 'standard');
  m = Machine.transition(m, 'load-ok');
  m = Machine.transition(m, 'select-task', { taskId: 'b32-001' });
  m = Machine.transition(m, 'check-inputs');
  assert.strictEqual(m.state, 'input-incomplete');
  const bad = Machine.transition(m, 'supplement', { inputId: 'does-not-exist' });
  assert.strictEqual(bad.state, 'validation-error');
  const back = Machine.transition(bad, 'ack');
  assert.strictEqual(back.state, 'input-incomplete');
});

if (failures > 0) {
  console.error(failures + ' journey failure(s)');
  process.exit(1);
}
console.log('journeys ok');
