/** #3782: trusted main -> supervised Resident one-shot browser command. */
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createResidentApprovedBrowserControlCommandPort,
  RESIDENT_APPROVED_COMMAND_CONTRACT,
  RESIDENT_APPROVED_COMMAND_REQUEST_KIND,
  type ResidentApprovedBrowserCommandBoundary,
} from '../src/conversation/resident-browser-control-command-take.js';
import {
  createTrustedBrowserControlCommandIngress,
} from '../src/browser/browser-control-canonical-command-ingress.js';
import type { BrowserControlLeaseContext } from '../src/conversation/resident-browser-control-lease.js';
import type { BoundTrustedBrowserControl } from '../src/browser/browser-action-trusted-main.js';
import type { BoundedActionReceipt } from '../src/browser/browser-action-contract.js';

const REF = 'command.3782.trusted';
const context: BrowserControlLeaseContext = {
  requestFingerprint: 'a'.repeat(64),
  browserSessionRef: 'browser.3782', deviceRef: 'device.3782',
  runRef: 'run.3782', workspaceRef: 'workspace.3782', ownerRef: 'owner.3782',
  originScope: 'https://example.org', allowedActionClasses: ['click'],
  ttlSeconds: 60, maxActions: 1,
};
const approved = {
  commandRef: REF,
  hostLeaseRef: 'lease.3782',
  capability: 'browser.control',
  context,
  action: {
    action: 'click', browserSessionRef: 'browser.3782',
    originRef: 'https://example.org', elementRef: 'el-0001',
  },
};

function response(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    event: RESIDENT_APPROVED_COMMAND_REQUEST_KIND,
    contract_version: RESIDENT_APPROVED_COMMAND_CONTRACT,
    command_ref: REF, ok: true, reason: null, command: approved,
    ...overrides,
  });
}

class Boundary implements ResidentApprovedBrowserCommandBoundary {
  sent: string[] = [];
  answers: string[] = [];
  running = true;
  sendOk = true;
  sendResidentLine(line: string): boolean {
    this.sent.push(line);
    return this.sendOk;
  }
  takeResidentBrowserControlCommandTakeLine(): string | null {
    return this.answers.shift() ?? null;
  }
  residentRunning(): boolean { return this.running; }
}
function port(boundary: Boundary, enabled = true) {
  return createResidentApprovedBrowserControlCommandPort({
    boundary, sourceConfigured: enabled, timeoutMs: 5,
    pollIntervalMs: 0, sleep: async () => undefined,
  });
}

test('real main composition is fail-closed until Broker HUMAN-P01 provider exists', async () => {
  const b = new Boundary();
  const p = port(b, false);
  assert.equal(p.configured, false);
  await assert.rejects(() => p.takeApprovedCommand(REF));
  assert.deepEqual(b.sent, []);
});

test('private stdin request includes commandRef only, never browser action/P01', async () => {
  const b = new Boundary();
  b.sendResidentLine = (line) => {
    b.sent.push(line);
    b.answers.push(response());
    return true;
  };
  const p = port(b);
  const result = await p.takeApprovedCommand(REF);
  assert.deepEqual(result, approved);
  const wire = JSON.parse(b.sent[0]!) as Record<string, unknown>;
  assert.deepEqual(wire, {
    contract_version: RESIDENT_APPROVED_COMMAND_CONTRACT,
    request: RESIDENT_APPROVED_COMMAND_REQUEST_KIND,
    commandRef: REF,
  });
  await assert.rejects(() => p.takeApprovedCommand(REF));
  assert.equal(b.sent.length, 1);
});

test('actual trusted ingress accepts resident command only after canonical shape recheck', async () => {
  const b = new Boundary();
  b.sendResidentLine = (line) => {
    b.sent.push(line);
    b.answers.push(response());
    return true;
  };
  const counts = { bind: 0, execute: 0, close: 0 };
  const receipt = { marker: 'bounded browser test only' } as unknown as BoundedActionReceipt;
  const ingress = createTrustedBrowserControlCommandIngress({
    approvedCommands: port(b),
    browserControl: {
      bindApprovedView: (leaseRef, trusted) => {
        assert.equal(leaseRef, 'lease.3782');
        assert.deepEqual(trusted, context);
        counts.bind++;
        return {
          configured: true,
          execute: async () => { counts.execute++; return receipt; },
          close: async () => { counts.close++; },
        } as BoundTrustedBrowserControl;
      },
    },
  });
  assert.equal(await ingress.executeApprovedCommand(REF), receipt);
  assert.deepEqual(counts, { bind: 1, execute: 1, close: 1 });
  await assert.rejects(() => ingress.executeApprovedCommand(REF));
  assert.equal(b.sent.length, 1);
});

test('wrong ref, stale reply, raw rejection and malformed response never bind a view', async () => {
  const variants = [
    response({command_ref: 'other.command'}),
    response({ok: false, reason: 'secret details', command: null}),
    response({contract_version: 'wrong'}),
    response({command: {...approved, capability: 'browser.open'}}),
    'not-json',
  ];
  for (const answer of variants) {
    const b = new Boundary();
    b.sendResidentLine = (line) => {
      b.sent.push(line);
      b.answers.push(answer);
      return true;
    };
    const ingress = createTrustedBrowserControlCommandIngress({
      approvedCommands: port(b),
      browserControl: { bindApprovedView: () => { throw Error('must not bind'); } },
    });
    const error = await assert.rejects(() => ingress.executeApprovedCommand(REF));
    assert.ok(error === undefined || !(String(error)).includes('secret details'));
    assert.equal(b.sent.length, 1);
  }
});

test('offline resident and stale responses are refused without any replay or grant', async () => {
  const b = new Boundary();
  b.running = false;
  await assert.rejects(() => port(b).takeApprovedCommand(REF));
  assert.deepEqual(b.sent, []);
  b.running = true;
  b.answers.push(response({ command_ref: 'old.command' }));
  b.sendResidentLine = () => false;
  await assert.rejects(() => port(b).takeApprovedCommand(REF));
  assert.equal(b.answers.length, 0);
});

test('malformed or unbounded command ref never sends a line', async () => {
  const b = new Boundary();
  for (const ref of ['', 'cmd with whitespace', 'a'.repeat(257), '../secret?x=1']) {
    await assert.rejects(() => port(b).takeApprovedCommand(ref));
  }
  assert.deepEqual(b.sent, []);
});


test('real supervised child transports split private command but REDACTS retained logs', async () => {
  const { NodeRunnerProcessPort } = await import('../src/supervisor/production-runner-process-port.js');
  const PRIVATE = 'PRIVATE-NO-LOG-3782';
  const raw = response({
    command: {
      ...approved,
      action: { ...approved.action, action: 'type', text: PRIVATE },
    },
  });
  const script = [
    `const line = ${JSON.stringify(raw)};`,
    'process.stdout.write(line.slice(0, 31));',
    "setTimeout(() => process.stdout.write(line.slice(31)+'\\n'), 40);",
    'setTimeout(() => process.exit(0), 1500);',
  ].join('');
  const p = new NodeRunnerProcessPort();
  const child = await p.spawnResident({
    executablePath: process.execPath,
    args: ['-e', script],
    cwd: process.cwd(),
    env: {},
    shell: false,
    stdio: 'pipe',
  });
  try {
    let line: string | null = null;
    const deadline = Date.now() + 1200;
    while (line === null && Date.now() < deadline) {
      line = p.takeResidentBrowserControlCommandTakeLine();
      if (line === null) await new Promise(resolve => setTimeout(resolve, 20));
    }
    assert.notEqual(line, null, 'supervised child must deliver one private response');
    assert.ok(line!.includes(PRIVATE));
    assert.equal(p.takeResidentBrowserControlCommandTakeLine(), null);
    const logged = JSON.stringify(p.boundedResidentOutput().lines);
    assert.ok(!logged.includes(PRIVATE), 'private browser command text must never enter logs');
    assert.ok(logged.includes('redacted'));
  } finally {
    child.kill();
    await child.waitForExit(2000);
  }
  assert.equal(p.takeResidentBrowserControlCommandTakeLine(), null);
});


test('oversized split private stdout line never leaks its later fragment into logs', async () => {
  const { NodeRunnerProcessPort } = await import('../src/supervisor/production-runner-process-port.js');
  const script = [
    "process.stdout.write('browser_control_command_take' + 'S'.repeat(70000));",
    "setTimeout(() => process.stdout.write('NEVER-LOG-TAIL-3782\\n'), 40);",
    "setTimeout(() => process.exit(0), 140);",
  ].join('');
  const port = new NodeRunnerProcessPort();
  const child = await port.spawnResident({
    executablePath: process.execPath,
    args: ['-e', script], cwd: process.cwd(), env: {}, shell: false, stdio: 'pipe',
  });
  await child.waitForExit(2000);
  assert.equal(port.takeResidentBrowserControlCommandTakeLine(), null);
  const retained = JSON.stringify(port.boundedResidentOutput().lines);
  assert.ok(!retained.includes('NEVER-LOG-TAIL-3782'));
  assert.ok(!retained.includes('SSSSSSSSSSSSSSSSSSSSSSSSSSSS'));
});
