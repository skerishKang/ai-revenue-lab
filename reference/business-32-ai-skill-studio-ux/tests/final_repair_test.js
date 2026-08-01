/* Final repair tests.
 * Role-history direction invariants, operator-only action boundaries,
 * approval→save handoff, empty-bench recovery, drawer close/Escape/focus.
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
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

const firstDraft = [
  ['load-ok'],
  ['select-task', { taskId: 'b32-001' }],
  ['check-inputs'],
  ['supplement', { inputId: 'criteria' }],
  ['begin-run'],
  ['complete-step'],
  ['next-step'],
  ['complete-step'],
  ['request-supplement', { note: '접수' }],
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
];

const toReviewerPending = firstDraft.concat([
  ['request-review'],
  ['handoff-to-reviewer']
]);

/* ---------- role history direction ---------- */

check('operator → reviewer history direction is correct', function () {
  const m = walk(toReviewerPending);
  assert.strictEqual(m.context.activeRole, 'reviewer');
  const last = m.context.roleHistory[m.context.roleHistory.length - 1];
  assert.strictEqual(last.from, 'operator');
  assert.strictEqual(last.to, 'reviewer');
  assert.strictEqual(last.action, 'handoff-to-reviewer');
});

check('reviewer → operator history direction is correct', function () {
  const m = walk(toReviewerPending.concat([['handoff-to-operator']]));
  assert.strictEqual(m.context.activeRole, 'operator');
  const last = m.context.roleHistory[m.context.roleHistory.length - 1];
  assert.strictEqual(last.from, 'reviewer');
  assert.strictEqual(last.to, 'operator');
  assert.strictEqual(last.action, 'handoff-to-operator');
});

check('consecutive roleHistory chain matches invariants', function () {
  const m = walk(toReviewerPending.concat([
    ['reject-review', { note: '재확인' }],
    ['handoff-to-operator'],
    ['apply-correction'],
    ['request-review'],
    ['handoff-to-reviewer']
  ]));
  const history = m.context.roleHistory;
  assert.ok(history.length >= 3, 'expected multiple handoffs, got ' + history.length);
  history.forEach(function (entry) {
    assert.notStrictEqual(entry.from, entry.to, 'from must differ from to');
  });
  assert.strictEqual(history[history.length - 1].to, m.context.activeRole);
  for (let i = 1; i < history.length; i += 1) {
    assert.strictEqual(history[i - 1].to, history[i].from, 'chain mismatch at ' + i);
  }
});

/* ---------- operator-only boundary ---------- */

function machineAt(state, role) {
  return {
    state: state,
    scenario: 'standard',
    context: { activeRole: role, previous: null },
    fixture: Fixture
  };
}

check('reviewer cannot apply-correction', function () {
  const result = Machine.transition(machineAt('correction-required', 'reviewer'), 'apply-correction');
  assert.strictEqual(result.state, 'validation-error');
  assert.ok(result.feedback.failure.indexOf('검토자는 업무 실행·수정·저장을 대신할 수 없습니다.') !== -1);
});

check('reviewer cannot re-run', function () {
  const result = Machine.transition(machineAt('revised', 'reviewer'), 're-run');
  assert.strictEqual(result.state, 'validation-error');
});

check('reviewer cannot complete-step', function () {
  const result = Machine.transition(machineAt('running', 'reviewer'), 'complete-step');
  assert.strictEqual(result.state, 'validation-error');
});

check('reviewer cannot save-skill', function () {
  const result = Machine.transition(machineAt('approved', 'reviewer'), 'save-skill');
  assert.strictEqual(result.state, 'validation-error');
});

check('operator can still execute an operator-only action', function () {
  const result = Machine.transition(machineAt('revised', 'operator'), 're-run');
  assert.strictEqual(result.state, 'running');
});

/* ---------- reviewer-only boundary (reinforced) ---------- */

check('operator cannot reject-review', function () {
  const m = walk(firstDraft.concat([['request-review']]));
  assert.strictEqual(m.context.activeRole, 'operator');
  const result = Machine.transition(m, 'reject-review', { note: 'x' });
  assert.strictEqual(result.state, 'validation-error');
});

check('operator cannot approve-review', function () {
  const m = walk(firstDraft.concat([['request-review']]));
  const result = Machine.transition(m, 'approve-review');
  assert.strictEqual(result.state, 'validation-error');
});

check('operator cannot final-approve', function () {
  const m = walk(firstDraft.concat([['request-review'], ['handoff-to-reviewer'], ['approve-review']]));
  const pending = Machine.transition(m, 'handoff-to-operator');
  assert.strictEqual(pending.context.activeRole, 'operator');
  const result = Machine.transition(pending, 'approve');
  assert.strictEqual(result.state, 'validation-error');
});

/* ---------- approval-to-save ---------- */

check('reviewer approval then direct save-skill is BLOCKED', function () {
  const m = walk(firstDraft.concat([
    ['request-review'], ['handoff-to-reviewer'], ['approve-review'], ['approve']
  ]));
  assert.strictEqual(m.state, 'approved');
  assert.strictEqual(m.context.activeRole, 'reviewer');
  const blocked = Machine.transition(m, 'save-skill');
  assert.strictEqual(blocked.state, 'validation-error');
  assert.ok(blocked.context.skill === null, 'skill must not be saved by reviewer');
});

check('reviewer approval → handoff-to-operator → operator save-skill PASSES', function () {
  const m = walk(firstDraft.concat([
    ['request-review'], ['handoff-to-reviewer'], ['approve-review'], ['approve'],
    ['handoff-to-operator']
  ]));
  assert.strictEqual(m.state, 'approved');
  assert.strictEqual(m.context.activeRole, 'operator');
  const saved = Machine.transition(m, 'save-skill');
  assert.strictEqual(saved.state, 'skill-saved');
  assert.ok(saved.context.skill, 'skill must exist after operator save');
});

/* ---------- empty-bench recovery ---------- */

check('empty-bench → load-tasks → initial → select-task is possible', function () {
  let m = Machine.createMachine(Fixture, 'empty-bench');
  m = Machine.transition(m, 'load-ok');
  assert.strictEqual(m.state, 'empty');
  m = Machine.transition(m, 'load-tasks');
  assert.strictEqual(m.state, 'initial');
  m = Machine.transition(m, 'select-task', { taskId: 'b32-001' });
  assert.strictEqual(m.state, 'task-selected');
});

/* ---------- app wiring (static, no browser) ---------- */

const root = path.join(__dirname, '..');
const appSrc = fs.readFileSync(path.join(root, 'scripts', 'app.js'), 'utf8');
const templatesSrc = fs.readFileSync(path.join(root, 'scripts', 'templates.js'), 'utf8');
const indexHtml = fs.readFileSync(path.join(root, 'index.html'), 'utf8');

check('app load-tasks wiring uses the existing empty machine, not a fresh one', function () {
  const branch = appSrc.slice(appSrc.indexOf("action === 'load-tasks'"), appSrc.indexOf('return;', appSrc.indexOf("action === 'load-tasks'")));
  assert.ok(branch.indexOf("transition('load-tasks')") !== -1, 'load-tasks must run on the existing machine');
  assert.ok(branch.indexOf('Machine.createMachine') === -1, 'load-tasks must not recreate a machine');
});

check('drawer inner close button exists with focus key', function () {
  assert.ok(templatesSrc.indexOf('data-focus-key="drawer-close"') !== -1, 'close button focus key missing');
  assert.ok(templatesSrc.indexOf('증거 패널 닫기') !== -1, 'close button label missing');
});

check('drawer aria-expanded toggling is wired', function () {
  assert.ok(appSrc.indexOf("setAttribute('aria-expanded', String(store.evidenceOpen))") !== -1, 'aria-expanded sync missing');
});

check('opener aria-controls matches drawer id', function () {
  assert.ok(templatesSrc.indexOf('aria-controls="evidence-drawer"') !== -1, 'opener aria-controls missing');
  assert.ok(indexHtml.indexOf('id="evidence-drawer"') !== -1, 'drawer container id missing');
  assert.ok(indexHtml.indexOf('aria-labelledby="evidence-drawer-title"') !== -1, 'drawer aria-labelledby missing');
  assert.ok(templatesSrc.indexOf('id="evidence-drawer-title"') !== -1, 'drawer title id missing');
});

check('Escape closes the drawer', function () {
  assert.ok(appSrc.indexOf("event.key === 'Escape'") !== -1, 'Escape handler missing');
  assert.ok(appSrc.indexOf('closeDrawer()') !== -1, 'Escape must call closeDrawer');
});

check('drawer close returns focus to the opener', function () {
  assert.ok(appSrc.indexOf('meta.drawerClosed') !== -1, 'drawerClosed branch missing');
  assert.ok(appSrc.indexOf('[data-action="toggle-evidence"]') !== -1, 'opener focus target missing');
});

check('drawer buttons are included in the focusable collection', function () {
  assert.ok(appSrc.indexOf('drawerEl.querySelectorAll') !== -1, 'collectFocusables must include drawer buttons');
});

check('drawer heading is the open focus target', function () {
  assert.ok(appSrc.indexOf('drawer-heading') !== -1, 'drawer open focus target missing');
});

if (failures > 0) {
  console.error(failures + ' final repair failure(s)');
  process.exit(1);
}
console.log('final repair tests ok');
