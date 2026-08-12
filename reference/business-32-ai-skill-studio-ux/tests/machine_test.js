/* State transition contract test.
 * Verifies: 24 states, all reachable, forbidden transitions rejected,
 * reviewer-handoff role contract, safety invariants.
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

function step(machine, action, payload) {
  return Machine.transition(machine, action, payload);
}

function walk(actions) {
  let machine = Machine.createMachine(Fixture, 'standard');
  actions.forEach(function (entry) {
    const action = Array.isArray(entry) ? entry[0] : entry;
    const payload = Array.isArray(entry) ? entry[1] : undefined;
    machine = step(machine, action, payload);
  });
  return machine;
}

const firstDraft = [
  ['load-ok'],
  ['select-task', { taskId: 'b32-001' }],
  ['check-inputs'],
  ['supplement', { inputId: 'criteria' }],
  ['begin-run'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['request-supplement', { note: '합성 보완 접수' }],
  ['resume-run'],
  ['resume-confirm'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['resolve-conflict', { decision: 'C', reason: '납기·보증 우수' }],
  ['next-step'],
  ['complete-step'],
  ['next-step'],
  ['complete-step']
];

const standardRun = firstDraft.concat([
  ['request-review'],
  ['handoff-to-reviewer'],
  ['reject-review', { note: '보증 근거를 다시 확인할 것' }],
  ['handoff-to-operator'],
  ['apply-correction'],
  ['re-run'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['request-review'],
  ['handoff-to-reviewer'],
  ['approve-review'],
  ['approve'],
  ['handoff-to-operator'],
  ['save-skill'],
  ['complete']
]);

check('machine exposes exactly 24 states', function () {
  const all = Machine.ALL_STATES;
  assert.strictEqual(all.length, 24, 'expected 24 states, got ' + all.length);
  const domain = Machine.DOMAIN_STATES;
  assert.strictEqual(domain.length, 16, 'expected 16 domain states');
  const general = Machine.GENERAL_STATES;
  assert.strictEqual(general.length, 8, 'expected 8 general states');
});

check('exactly two synthetic roles with display names', function () {
  assert.deepStrictEqual(Machine.ROLES, ['operator', 'reviewer']);
  assert.strictEqual(Machine.roleName('operator'), '업무 실행자');
  assert.strictEqual(Machine.roleName('reviewer'), '합성 운영 책임자 · 사람 검토자');
});

check('all 24 states are reachable through deterministic paths', function () {
  const reachable = new Set();
  const record = function (machine) {
    reachable.add(machine.state);
  };

  const walkRecording = function (actions) {
    let machine = Machine.createMachine(Fixture, 'standard');
    record(machine);
    actions.forEach(function (entry) {
      const action = Array.isArray(entry) ? entry[0] : entry;
      const payload = Array.isArray(entry) ? entry[1] : undefined;
      machine = step(machine, action, payload);
      record(machine);
    });
    return machine;
  };

  walkRecording(standardRun);

  let e = Machine.createMachine(Fixture, 'empty-bench');
  record(e);
  e = step(e, 'load-ok');
  record(e);
  e = step(e, 'load-tasks');
  record(e);

  let f = Machine.createMachine(Fixture, 'fault');
  record(f);
  f = step(f, 'load-error');
  record(f);
  f = step(f, 'retry');
  record(f);
  f = step(f, 'retry-confirm');
  record(f);
  f = step(f, 'load-ok');
  record(f);

  let c = Machine.createMachine(Fixture, 'standard');
  record(c);
  c = step(c, 'load-ok');
  c = step(c, 'select-task', { taskId: 'b32-001' });
  c = step(c, 'check-inputs');
  c = step(c, 'supplement', { inputId: 'criteria' });
  c = step(c, 'begin-run');
  c = step(c, 'stop-run');
  record(c);
  c = step(c, 'cancel');
  record(c);
  c = step(c, 'list-tasks');
  record(c);

  let v = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer'], ['approve-review'], ['save-skill']]));
  record(v);
  v = step(v, 'ack');
  record(v);

  const expected = Machine.ALL_STATES.slice();
  expected.forEach(function (state) {
    assert.ok(reachable.has(state), 'state not reachable: ' + state);
  });
});

check('standard journey ends in completed with handoff history', function () {
  const finalMachine = walk(standardRun);
  assert.strictEqual(finalMachine.state, 'completed');
  assert.ok(finalMachine.context.skill, 'skill missing');
  assert.strictEqual(finalMachine.context.versions.length, 1);
  assert.ok(finalMachine.context.roleHistory.length >= 4, 'handoff history preserved');
  assert.strictEqual(finalMachine.context.activeRole, 'operator');
});

check('role contract: operator cannot approve-review', function () {
  const m = walk(firstDraft.concat([['request-review']]));
  assert.strictEqual(m.state, 'review-requested');
  assert.strictEqual(m.context.activeRole, 'operator');
  const blocked = step(m, 'approve-review');
  assert.strictEqual(blocked.state, 'validation-error');
  assert.ok(blocked.feedback.failure.indexOf('업무 실행자') !== -1, 'self-review block message missing');
});

check('role contract: operator cannot reject-review', function () {
  const m = walk(firstDraft.concat([['request-review']]));
  const blocked = step(m, 'reject-review', { note: 'x' });
  assert.strictEqual(blocked.state, 'validation-error');
});

check('role contract: operator cannot final-approve', function () {
  const m = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer'], ['approve-review']]));
  assert.strictEqual(m.state, 'approval-pending');
  assert.strictEqual(m.context.activeRole, 'reviewer');
  const handedBack = step(m, 'handoff-to-operator');
  assert.strictEqual(handedBack.context.activeRole, 'operator');
  const blocked = step(handedBack, 'approve');
  assert.strictEqual(blocked.state, 'validation-error');
});

check('role contract: reviewer can reject-review then hand back', function () {
  const m = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer']]));
  const rejected = step(m, 'reject-review', { note: '재확인 필요' });
  assert.strictEqual(rejected.state, 'correction-required');
  assert.strictEqual(rejected.context.activeRole, 'reviewer');
  const back = step(rejected, 'handoff-to-operator');
  assert.strictEqual(back.context.activeRole, 'operator');
});

check('role contract: reviewer can approve-review and final-approve', function () {
  const m = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer']]));
  const pending = step(m, 'approve-review');
  assert.strictEqual(pending.state, 'approval-pending');
  const approved = step(pending, 'approve');
  assert.strictEqual(approved.state, 'approved');
});

check('forbidden transition throws (initial + save-skill)', function () {
  let machine = Machine.createMachine(Fixture, 'standard');
  machine = step(machine, 'load-ok');
  assert.throws(function () {
    step(machine, 'save-skill');
  }, /invalid transition/);
});

check('forbidden transition throws (draft-result + approve)', function () {
  const m = walk(firstDraft);
  assert.strictEqual(m.state, 'draft-result');
  assert.throws(function () {
    step(m, 'approve');
  }, /invalid transition/);
});

check('missing evidence is never auto-estimated', function () {
  let machine = walk([['load-ok'], ['select-task', { taskId: 'b32-001' }], ['check-inputs'], ['supplement', { inputId: 'criteria' }], ['begin-run'], ['complete-step'], ['next-step'], ['complete-step']]);
  assert.strictEqual(machine.state, 'missing-evidence');
  const actions = Machine.availableActions(machine);
  assert.deepStrictEqual(actions.sort(), ['request-supplement', 'stop-run']);
  assert.throws(function () {
    step(machine, 'complete-step');
  }, /invalid transition/);
  const stopped = step(machine, 'stop-run');
  assert.strictEqual(stopped.state, 'stopped');
});

check('lowest price is never auto-best; conflict needs human decision', function () {
  let machine = walk([['load-ok'], ['select-task', { taskId: 'b32-001' }], ['check-inputs'], ['supplement', { inputId: 'criteria' }], ['begin-run'], ['complete-step'], ['next-step'], ['complete-step'], ['request-supplement'], ['resume-run'], ['resume-confirm'], ['complete-step'], ['next-step'], ['complete-step']]);
  assert.strictEqual(machine.state, 'conflicting-evidence');
  const actions = Machine.availableActions(machine);
  assert.deepStrictEqual(actions.sort(), ['resolve-conflict', 'stop-run']);
  const noDecision = step(machine, 'resolve-conflict', {});
  assert.strictEqual(noDecision.state, 'validation-error', 'conflict must not resolve without human decision');
  const back = step(noDecision, 'ack');
  assert.strictEqual(back.state, 'conflicting-evidence');
});

check('skill save before approval is blocked (validation-error)', function () {
  const m = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer'], ['approve-review']]));
  assert.strictEqual(m.state, 'approval-pending');
  const blocked = step(m, 'save-skill');
  assert.strictEqual(blocked.state, 'validation-error');
  assert.ok(blocked.context.skill === null, 'skill must not exist before approval');
});

check('approved save forms the skill with retained exceptions', function () {
  const finalMachine = walk(standardRun);
  const skill = finalMachine.context.skill;
  assert.ok(skill, 'skill missing');
  assert.ok(skill.exceptions.length >= 3, 'exceptions must be retained');
  const labels = skill.exceptions.map(function (e) {
    return e.label;
  });
  assert.ok(labels.indexOf('MISSING EVIDENCE') !== -1, 'missing evidence retained');
  assert.ok(skill.exceptions.some(function (e) {
    return /충돌|CONFLICT/.test(e.text + e.label);
  }), 'conflict retained');
  assert.strictEqual(skill.authority, 'VERIFIED ORGANIZATIONAL AI SKILL');
});

check('hero authority labels are all defined', function () {
  const expected = [
    'AI-ASSISTED STEP',
    'HUMAN ACTION',
    'SOURCE EVIDENCE',
    'MISSING EVIDENCE',
    'CONFLICTING EVIDENCE',
    'DRAFT RESULT',
    'REVIEW CORRECTION',
    'NOT YET APPROVED',
    'HUMAN-APPROVED',
    'VERIFIED ORGANIZATIONAL AI SKILL'
  ];
  assert.deepStrictEqual(Machine.HERO_LABELS, expected);
});

if (failures > 0) {
  console.error(failures + ' machine contract failure(s)');
  process.exit(1);
}
console.log('machine contract ok');
