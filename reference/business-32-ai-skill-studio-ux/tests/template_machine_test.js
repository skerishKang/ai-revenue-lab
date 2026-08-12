/* Template ↔ machine consistency test.
 * For every reachable state and role, render the template and verify every
 * rendered data-action is a legal, role-allowed transition; verify unique
 * rendered IDs and that no template hardcodes a reviewer actor.
 */
'use strict';

const assert = require('assert');
const Machine = require('../scripts/machine.js');
const Fixture = require('../scripts/fixture.js');
const Templates = require('../scripts/templates.js');

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

function actionsInHtml(html) {
  const actions = [];
  const re = /data-action="([a-z-]+)"/g;
  let m;
  while ((m = re.exec(html)) !== null) actions.push(m[1]);
  return actions;
}

function idsInHtml(html) {
  const ids = [];
  const re = /\bid="([^"]+)"/g;
  let m;
  while ((m = re.exec(html)) !== null) ids.push(m[1]);
  return ids;
}

function rolesFor(state) {
  const reviewStates = ['review-requested', 'correction-required', 'approval-pending', 'approved', 'draft-result', 'revised'];
  if (reviewStates.indexOf(state) !== -1) {
    return ['operator', 'reviewer'];
  }
  return ['operator'];
}

function collectReachable() {
  const machines = [];
  const add = function (machine) {
    if (!machines.some(function (m) {
      return m.state === machine.state && m.context.activeRole === machine.context.activeRole;
    })) {
      machines.push(machine);
    }
  };
  let m = Machine.createMachine(Fixture, 'standard');
  add(m);
  const seq = [
    ['load-ok'], ['select-task', { taskId: 'b32-001' }], ['check-inputs'],
    ['supplement', { inputId: 'criteria' }], ['begin-run'],
    ['complete-step'], ['next-step'], ['complete-step'],
    ['request-supplement', { note: '접수' }], ['resume-run'], ['resume-confirm'],
    ['complete-step'], ['next-step'], ['complete-step'],
    ['resolve-conflict', { decision: 'C' }], ['next-step'], ['complete-step'],
    ['next-step'], ['complete-step'], ['request-review'],
    ['handoff-to-reviewer'], ['reject-review', { note: '재확인' }],
    ['handoff-to-operator'], ['apply-correction'], ['re-run'],
    ['complete-step'], ['next-step'], ['complete-step'], ['next-step'],
    ['complete-step'], ['next-step'], ['complete-step'], ['next-step'],
    ['complete-step'], ['request-review'], ['handoff-to-reviewer'],
    ['approve-review'], ['approve'], ['handoff-to-operator'],
    ['save-skill'], ['complete']
  ];
  seq.forEach(function (entry) {
    m = Machine.transition(m, entry[0], entry[1]);
    add(m);
  });

  let e = Machine.createMachine(Fixture, 'empty-bench');
  add(e);
  e = Machine.transition(e, 'load-ok');
  add(e);
  e = Machine.transition(e, 'load-tasks');
  add(e);

  let f = Machine.createMachine(Fixture, 'fault');
  add(f);
  f = Machine.transition(f, 'load-error');
  add(f);
  f = Machine.transition(f, 'retry');
  add(f);
  f = Machine.transition(f, 'retry-confirm');
  add(f);

  let c = Machine.createMachine(Fixture, 'standard');
  c = Machine.transition(c, 'load-ok');
  c = Machine.transition(c, 'select-task', { taskId: 'b32-001' });
  c = Machine.transition(c, 'check-inputs');
  c = Machine.transition(c, 'supplement', { inputId: 'criteria' });
  c = Machine.transition(c, 'begin-run');
  c = Machine.transition(c, 'stop-run');
  add(c);
  c = Machine.transition(c, 'cancel');
  add(c);

  let v = Machine.createMachine(Fixture, 'standard');
  v = Machine.transition(v, 'load-ok');
  v = Machine.transition(v, 'select-task', { taskId: 'b32-001' });
  v = Machine.transition(v, 'check-inputs');
  v = Machine.transition(v, 'supplement', { inputId: 'criteria' });
  v = Machine.transition(v, 'begin-run');
  v = Machine.transition(v, 'stop-run');
  v = Machine.transition(v, 'cancel');
  v = Machine.transition(v, 'select-task', { taskId: 'b32-001' });
  v = Machine.transition(v, 'check-inputs');
  v = Machine.transition(v, 'begin-run');
  v = Machine.transition(v, 'complete-step');
  v = Machine.transition(v, 'next-step');
  v = Machine.transition(v, 'complete-step');
  v = Machine.transition(v, 'request-supplement');
  v = Machine.transition(v, 'resume-run');
  v = Machine.transition(v, 'resume-confirm');
  v = Machine.transition(v, 'complete-step');
  v = Machine.transition(v, 'next-step');
  v = Machine.transition(v, 'complete-step');
  v = Machine.transition(v, 'resolve-conflict', { decision: 'C' });
  v = Machine.transition(v, 'next-step');
  v = Machine.transition(v, 'complete-step');
  v = Machine.transition(v, 'next-step');
  v = Machine.transition(v, 'complete-step');
  v = Machine.transition(v, 'request-review');
  v = Machine.transition(v, 'handoff-to-reviewer');
  v = Machine.transition(v, 'approve-review');
  v = Machine.transition(v, 'save-skill');
  add(v);
  v = Machine.transition(v, 'ack');
  add(v);

  return machines;
}

function renderForRoles(machine) {
  const rendered = [];
  rolesFor(machine.state).forEach(function (role) {
    const copy = {
      state: machine.state,
      scenario: machine.scenario,
      context: Object.assign({}, machine.context, { activeRole: role }),
      feedback: machine.feedback,
      fixture: machine.fixture
    };
    rendered.push({ role: role, copy: copy, html: Templates.render(copy) });
  });
  return rendered;
}

check('every rendered action is a legal, role-allowed transition', function () {
  const machines = collectReachable();
  assert.ok(machines.length >= 25, 'expected many reachable machines');
  machines.forEach(function (machine) {
    renderForRoles(machine).forEach(function (entry) {
      const actions = actionsInHtml(entry.html);
      actions.forEach(function (action) {
        if (action === 'toggle-evidence') return;
        assert.ok(
          Machine.actionAllowed(entry.copy, action),
          'template renders disallowed action "' + action + '" in state ' + machine.state + ' role ' + entry.role
        );
      });
    });
  });
});

check('reviewer-only actions are never rendered for operator role', function () {
  const machines = collectReachable();
  machines.forEach(function (machine) {
    renderForRoles(machine).forEach(function (entry) {
      if (entry.role !== 'operator') return;
      const actions = actionsInHtml(entry.html);
      Machine.REVIEWER_ONLY_ACTIONS.forEach(function (action) {
        assert.ok(actions.indexOf(action) === -1, 'operator view renders ' + action + ' in ' + machine.state);
      });
    });
  });
});

check('no view leaves the user in a dead end without a next action', function () {
  const machines = collectReachable();
  const TERMINAL = ['completed'];
  const AUTO_TRANSITION = ['loading'];
  machines.forEach(function (machine) {
    if (TERMINAL.indexOf(machine.state) !== -1) return;
    if (AUTO_TRANSITION.indexOf(machine.state) !== -1) return;
    renderForRoles(machine).forEach(function (entry) {
      const actions = actionsInHtml(entry.html);
      assert.ok(actions.length > 0, 'no actionable control in state ' + machine.state + ' role ' + entry.role);
    });
  });
});

check('all rendered IDs are unique across every view', function () {
  const machines = collectReachable();
  const seen = {};
  machines.forEach(function (machine) {
    renderForRoles(machine).forEach(function (entry) {
      idsInHtml(entry.html).forEach(function (id) {
        if (seen[id]) seen[id] += 1;
        else seen[id] = 1;
      });
    });
  });
  Object.keys(seen).forEach(function (id) {
    assert.strictEqual(seen[id], 1, 'duplicated rendered ID: ' + id + ' (count ' + seen[id] + ')');
  });
});

check('evidence drawer has one ID only, in the external container', function () {
  const machines = collectReachable();
  machines.forEach(function (machine) {
    renderForRoles(machine).forEach(function (entry) {
      const ids = idsInHtml(entry.html);
      assert.ok(ids.indexOf('evidence-drawer') === -1, 'template must not render id="evidence-drawer"');
    });
  });
});

check('no template hardcodes a reviewer actor on buttons', function () {
  const fs = require('fs');
  const path = require('path');
  const src = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'templates.js'), 'utf8');
  const app = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'app.js'), 'utf8');
  assert.ok(src.indexOf('data-actor') === -1, 'templates.js must not contain data-actor');
  assert.ok(app.indexOf('dataset.actor') === -1, 'app.js must not read dataset.actor');
  assert.ok(src.indexOf('actor:') === -1, 'templates.js must not emit an actor payload');
});

if (failures > 0) {
  console.error(failures + ' template/machine failure(s)');
  process.exit(1);
}
console.log('template/machine consistency ok');
