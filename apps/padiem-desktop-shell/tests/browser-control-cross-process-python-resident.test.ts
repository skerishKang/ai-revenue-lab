/**
 * #3782 G2/G3 — REAL Windows supervised Node <-> Python Resident pipe, not
 * a mock stdout producer. Exercise the canonical Python 5-kind dispatcher,
 * Node private stdout slot, trusted-main ingress and durable-looking replay
 * refusals. The injected one-use provider is a synthetic TEST fixture:
 * NO authenticated Broker/Engine, HUMAN P01, local lease, live browser,
 * Production wiring or native OS Computer Use is involved.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';

import {
  createResidentApprovedBrowserControlCommandPort,
  RESIDENT_APPROVED_COMMAND_CONTRACT,
  RESIDENT_APPROVED_COMMAND_REQUEST_KIND,
} from '../src/conversation/resident-browser-control-command-take.js';
import {
  createTrustedBrowserControlCommandIngress,
} from '../src/browser/browser-control-canonical-command-ingress.js';
import { NodeRunnerProcessPort } from '../src/supervisor/production-runner-process-port.js';
import type { BoundedActionReceipt } from '../src/browser/browser-action-contract.js';

const COMMAND = 'command.3782.windows.python.e2e';
const SECRET = 'owner-private-type-text-never-in-log-3782';
const ctx = {
  requestFingerprint: 'a'.repeat(64),
  browserSessionRef: 'browser.3782',
  deviceRef: 'device.3782',
  runRef: 'run.3782',
  workspaceRef: 'workspace.3782',
  ownerRef: 'owner.3782',
  originScope: 'https://example.org',
  allowedActionClasses: ['type'],
  ttlSeconds: 60,
  maxActions: 1,
};
const approved = {
  commandRef: COMMAND,
  hostLeaseRef: 'lease.3782',
  capability: 'browser.control',
  context: ctx,
  action: {
    action: 'type', browserSessionRef: ctx.browserSessionRef,
    originRef: ctx.originScope, elementRef: 'el-0001', text: SECRET,
  },
};
const pythonExe = process.env['PADIEM_TEST_PYTHON_EXECUTABLE']
  || (process.platform === 'win32' ? 'python' : 'python3');
const pythonAvailable = process.platform === 'win32' &&
  spawnSync(pythonExe, ['--version'], { encoding: 'utf8' }).status === 0;

/** Uses the actual Python dispatcher in a separate supervised Windows process. */
const pythonProgram = [
  'import json',
  'from kagent.local_agent_desktop_material import ResidentDesktopMaterialResponder',
  `MATERIAL = json.loads(${JSON.stringify(JSON.stringify(approved))})`,
  'used = False',
  'def broker_take(ref):',
  '    global used',
  `    if used or ref != ${JSON.stringify(COMMAND)}:`,
  '        raise ValueError("Broker CAS already consumed or command rejected")',
  '    used = True',
  '    return MATERIAL',
  'def emit_one(line):',
  '    print(line, flush=True)',
  'responder = ResidentDesktopMaterialResponder(',
  '    material_projection=lambda: {"ok": False},',
  '    approved_command_take=broker_take, emit=emit_one)',
  'responder.start()',
  'responder._thread.join()  # one real stdin reader; exit on EOF',
].join('\n');

test('Windows real Python Resident -> supervised private pipe -> trusted ingress; one-use and secret-free logs', {
  skip: !pythonAvailable && 'requires Windows and local Python for cross-process gate',
  timeout: 20_000,
}, async () => {
  const port = new NodeRunnerProcessPort();
  const repositoryRoot = path.resolve(process.cwd(), '..', '..');
  const pythonPath = [
    path.join(repositoryRoot, 'apps', 'korean-ai-code-agent', 'src'),
    path.join(repositoryRoot, 'packages', 'padiem-control-plane'),
    path.join(repositoryRoot, 'packages', 'padiem-ai-core'),
  ].join(path.delimiter);
  const child = await port.spawnResident({
    executablePath: pythonExe,
    args: ['-u', '-c', pythonProgram],
    cwd: process.cwd(),
    env: { PATH: process.env.PATH || '', SystemRoot: process.env.SystemRoot || '',
           PYTHONPATH: pythonPath, PYTHONIOENCODING: 'utf-8',
           APPDATA: process.env.APPDATA || '', LOCALAPPDATA: process.env.LOCALAPPDATA || '',
           USERPROFILE: process.env.USERPROFILE || '' },
    shell: false, stdio: 'pipe',
  });
  const send = (line: string): boolean => child.sendLine?.(line) === true;
  let binds = 0, executes = 0, closes = 0;
  const boundedReceipt = { status: 'test_only_no_Input' } as unknown as BoundedActionReceipt;
  const p = createResidentApprovedBrowserControlCommandPort({
    boundary: {
      sendResidentLine: line => send(line),
      takeResidentBrowserControlCommandTakeLine: () =>
        port.takeResidentBrowserControlCommandTakeLine(),
      residentRunning: () => child.isAlive(),
    },
    // This flag is TEST-ONLY. Real Desktop main hardcodes false.
    sourceConfigured: true, timeoutMs: 8_000, pollIntervalMs: 10,
  });
  const ingress = createTrustedBrowserControlCommandIngress({
    approvedCommands: p,
    browserControl: {
      bindApprovedView: (leaseRef, context) => {
        binds++;
        assert.equal(leaseRef, approved.hostLeaseRef);
        assert.deepEqual(context, ctx);
        return {
          configured: true,
          execute: async action => {
            executes++;
            assert.deepEqual(action, approved.action);
            // Absolutely no Electron or browser input is executed in test.
            return boundedReceipt;
          },
          close: async () => { closes++; },
        };
      },
    },
  });
  try {
    // A forged Desktop request carrying a P01/command body must not reach
    // the Broker callback. The Python dispatcher rejects unknown fields.
    assert.equal(send(JSON.stringify({
      contract_version: RESIDENT_APPROVED_COMMAND_CONTRACT,
      request: RESIDENT_APPROVED_COMMAND_REQUEST_KIND,
      commandRef: COMMAND,
      decision: 'approved',
      browser_action: approved.action,
    })), true);
    // Only correlation can enter this private boundary.
    let observed: BoundedActionReceipt;
    try {
      observed = await ingress.executeApprovedCommand(COMMAND);
    } catch (err) {
      const view = port.residentObservation();
      const retained = JSON.stringify(port.boundedResidentOutput().lines);
      const safe = retained.replaceAll(SECRET, '[private-redacted]');
      assert.fail('trusted ingress refused: ' +
        JSON.stringify({isAlive: child.isAlive(), observation: view, retained: safe}).slice(0, 1300));
      throw err;
    }
    assert.equal(observed, boundedReceipt);
    assert.deepEqual({binds, executes, closes}, {binds: 1, executes: 1, closes: 1});
    await assert.rejects(() => ingress.executeApprovedCommand(COMMAND));
    assert.deepEqual({binds, executes, closes}, {binds: 1, executes: 1, closes: 1});
    const retained = JSON.stringify(port.boundedResidentOutput().lines);
    assert.ok(!retained.includes(SECRET), 'private action text never enters diagnostics');
    assert.ok(!retained.includes('owner-private-type'));
    assert.ok(!retained.includes('"decision":"approved"'));
    assert.ok(retained.includes('redacted'), 'private take is redacted at capture');
  } finally {
    child.kill();
    await child.waitForExit(3_000);
  }
  assert.equal(port.takeResidentBrowserControlCommandTakeLine(), null,
    'raw private take is dropped on supervised process exit');
  // Real product security posture is not affected by this TEST source.
});


/** Real SQLite Durable Object CAS in a supervised Python child, with synthetic
 * already-admitted P01 fixture only. No network, actual user or browser Input.
 */
test('Windows canonical Broker SQLite CAS -> Python Resident -> trusted main; replay fails closed', {
  skip: !pythonAvailable && 'Windows Python required',
  timeout: 20_000,
}, async () => {
  const root = path.resolve(process.cwd(), '..', '..');
  const sourcePaths = [
    path.join(root, 'apps', 'korean-ai-code-agent', 'src'),
    path.join(root, 'packages', 'padiem-control-plane'),
    path.join(root, 'packages', 'padiem-control-plane', 'tests'),
    path.join(root, 'packages', 'padiem-ai-core'),
  ].join(path.delimiter);
  const supervisor = new NodeRunnerProcessPort();
  const child = await supervisor.spawnResident({
    executablePath: pythonExe,
    args: ['-u', path.join(process.cwd(), 'tests', 'broker_resident_3782.py')],
    cwd: process.cwd(),
    env: {
      PATH: process.env.PATH || '',
      SystemRoot: process.env.SystemRoot || '',
      USERPROFILE: process.env.USERPROFILE || '',
      LOCALAPPDATA: process.env.LOCALAPPDATA || '',
      APPDATA: process.env.APPDATA || '',
      PYTHONPATH: sourcePaths,
      PYTHONIOENCODING: 'utf-8',
    },
    shell: false, stdio: 'pipe',
  });
  const ref = 'command.3782.1';
  const summary: string[] = [];
  const boundary = {
    sendResidentLine: (line: string) => child.sendLine?.(line) === true,
    takeResidentBrowserControlCommandTakeLine: () => {
      const raw = supervisor.takeResidentBrowserControlCommandTakeLine();
      if (raw !== null) {
        try {
          const r = JSON.parse(raw) as { ok?: unknown; reason?: unknown };
          summary.push(r.ok === true ? 'ok' : String(r.reason ?? 'unknown_refusal'));
        } catch {
          summary.push('not_json');
        }
      }
      return raw;
    },
    residentRunning: () => child.isAlive(),
  };
  const source = () => createResidentApprovedBrowserControlCommandPort({
    boundary, sourceConfigured: true, timeoutMs: 8_000, pollIntervalMs: 10,
  });
  const count = { bind: 0, execute: 0, close: 0 };
  const ingress = createTrustedBrowserControlCommandIngress({
    approvedCommands: source(),
    browserControl: {
      bindApprovedView: (lease, ctx) => {
        count.bind++;
        assert.equal(lease, 'hostlease.3782.1');
        assert.equal(ctx.originScope, 'https://example.com');
        assert.equal(ctx.browserSessionRef, 'browser.3782.1');
        return {
          configured: true,
          execute: async act => {
            count.execute++;
            assert.deepEqual(act, {
              action: 'click', elementRef: 'el-0001',
              browserSessionRef: 'browser.3782.1',
              originRef: 'https://example.com',
            });
            return { type: 'safe_fixture_only' } as unknown as BoundedActionReceipt;
          },
          close: async () => { count.close++; },
        };
      },
    },
  });
  try {
    // Wrong broker owner correlation must fail without spending the good slot.
    await assert.rejects(() => source().takeApprovedCommand('command.3782.other'));
    assert.deepEqual(summary, ['command_take_refused']);
    assert.deepEqual(count, { bind: 0, execute: 0, close: 0 });
    let receipt: BoundedActionReceipt;
    try {
      receipt = await ingress.executeApprovedCommand(ref);
    } catch {
      assert.fail('G2 first take refused: ' + JSON.stringify({
        summary,
        alive: child.isAlive(),
        stderrLines: supervisor.residentObservation()?.stderr_lines ?? null,
        category: supervisor.residentObservation()?.stderr_tail?.filter(s => s.includes('BROKER_TEST_CATEGORY')).slice(-1),
      }));
      return;
    }
    assert.equal((receipt as unknown as {type:string}).type, 'safe_fixture_only');
    assert.deepEqual(count, { bind: 1, execute: 1, close: 1 });
    await assert.rejects(() => source().takeApprovedCommand(ref));
    assert.deepEqual(summary, ['command_take_refused', 'ok', 'command_take_refused']);
    assert.deepEqual(count, { bind: 1, execute: 1, close: 1 });
    const retained = JSON.stringify(supervisor.boundedResidentOutput().lines);
    assert.ok(retained.includes('redacted'));
    assert.ok(!retained.includes('device-browser-command-credential-3782'));
    assert.ok(!retained.includes('hostlease.3782.1'));
  } finally {
    child.kill();
    await child.waitForExit(3_000);
  }
  assert.equal(supervisor.takeResidentBrowserControlCommandTakeLine(), null);
});
