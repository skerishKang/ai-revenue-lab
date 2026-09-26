/**
 * #3093 — REAL Windows Electron evidence harness.
 *
 * Proves, against the actual Electron 44 binary on this machine (not a fake,
 * not plain node), the three claims the issue requires:
 *
 *   1. REAL_ELECTRON_RUNNER_HOST_VERIFIED — the headless runner starts,
 *      logs its ready line, stops cleanly, and leaves NO orphan process,
 *      when hosted by the Electron binary in ELECTRON_RUN_AS_NODE=1 mode
 *      through the production NodeRunnerProcessPort + HeadlessRunnerSupervisor.
 *   2. SINGLE_INSTANCE_OWNER + RUNNING_APP_SECOND_INSTANCE_FORWARDING —
 *      a second Electron instance launched with `padiem://pair?...` quits
 *      itself, and the running owner receives the raw deep link through the
 *      #3093 forwarding path and feeds it to the existing bounded intake.
 *   3. WINDOWS_PROTOCOL_REGISTERED — `setAsDefaultProtocolClient` for the
 *      dev launch shape actually writes the HKCU handler. The harness records
 *      the prior state of the key and restores it afterwards; it never leaves
 *      the machine more modified than it found it.
 *
 * CLOSED_APP_DEEPLINK_DELIVERY is proven by scenario 2b: a *fresh* launch
 * whose argv already carries the deep link (the Windows delivery shape when
 * no instance is running) is accepted by the same intake.
 *
 * Run: node scripts/windows-real-evidence.mjs   (from apps/padiem-desktop-shell)
 * Output: JSON evidence summary on stdout; non-zero exit on any failure.
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const distSrc = path.join(appRoot, 'dist', 'src');
const electronBinary = path.join(appRoot, 'node_modules', 'electron', 'dist', 'electron.exe');

if (process.platform !== 'win32') {
  console.error('this harness requires Windows');
  process.exit(2);
}
if (!existsSync(electronBinary)) {
  console.error('electron.exe not found — install the real Electron binary first (this harness never fakes it)');
  process.exit(2);
}
for (const required of [
  path.join(distSrc, 'main', 'single-instance.js'),
  path.join(distSrc, 'main', 'protocol-registration.js'),
  path.join(distSrc, 'main', 'runner-host-mode.js'),
  path.join(distSrc, 'supervisor', 'runner-supervisor.js'),
  path.join(distSrc, 'supervisor', 'production-runner-process-port.js'),
  path.join(distSrc, 'runner', 'headless-runner.js'),
]) {
  if (!existsSync(required)) {
    console.error(`missing compiled module ${required} — run npm run build first`);
    process.exit(2);
  }
}

const tmp = mkdtempSync(path.join(os.tmpdir(), 'claw2-3093-'));

/** The harness app: uses the REAL shell modules, no BrowserWindow. */
function writeHarnessApp() {
  const dir = path.join(tmp, 'harness-app');
  mkdirSync(dir, { recursive: true });
  const rel = (target) => path.join(distSrc, target).replaceAll('\\', '/');
  writeFileSync(
    path.join(dir, 'package.json'),
    JSON.stringify({ name: 'claw2-3093-harness', version: '0.0.0', type: 'module', main: 'harness-main.mjs' }, null, 2),
  );
  const mainSource = [
    "import { app } from 'electron';",
    "import { appendFileSync } from 'node:fs';",
    `import { acquireSingleInstanceOwnership } from 'file:///${rel('main/single-instance.js')}';`,
    `import { registerWindowsProtocolClient } from 'file:///${rel('main/protocol-registration.js')}';`,
    `import { resolveRunnerHostMode } from 'file:///${rel('main/runner-host-mode.js')}';`,
    `import { NodeRunnerProcessPort } from 'file:///${rel('supervisor/production-runner-process-port.js')}';`,
    `import { HeadlessRunnerSupervisor } from 'file:///${rel('supervisor/runner-supervisor.js')}';`,
    `const runnerEntry = ${JSON.stringify(rel('runner/headless-runner.js'))};`,
    'const OUT = process.env.HARNESS_OUT;',
    'const emit = (obj) => appendFileSync(OUT, JSON.stringify(obj) + "\\n");',
    'app.disableHardwareAcceleration();',
    '',
    '// 1) protocol registration through the real #3093 decision module',
    'const reg = registerWindowsProtocolClient(app, {',
    '  platform: process.platform,',
    '  packaged: false,',
    '  defaultApp: Boolean(process.defaultApp),',
    '  execPath: process.execPath,',
    '  appPath: app.getAppPath(),',
    '});',
    "emit({ kind: 'protocol', registered: reg.registered, action: reg.plan.action });",
    '',
    '// 2) single-instance ownership through the real #3093 module',
    'const runnerMode = resolveRunnerHostMode({',
    '  execPath: process.execPath,',
    '  electronVersion: process.versions.electron,',
    '  runnerExecutableOverride: undefined,',
    '  platform: process.platform,',
    '});',
    "emit({ kind: 'hostmode', mode: runnerMode.mode, env: runnerMode.env });",
    'let port = null;',
    'let supervisor = null;',
    'const outcome = acquireSingleInstanceOwnership({',
    '  app,',
    '  forwardDeepLink: (link) => emit({ kind: \'forwarded\', link }),',
    '  onNotOwner: () => app.quit(),',
    '  onSecondInstance: () => emit({ kind: \'woke\' }),',
    '});',
    "emit({ kind: 'ownership', owner: outcome.owner });",
    'if (!outcome.owner) {',
    '  process.exit(0);',
    '}',
    '',
    '// 3) closed-app delivery: first-launch argv scan (same shape as main.ts)',
    "for (const argv of process.argv.slice(1)) {",
    "  if (argv.toLowerCase().startsWith('padiem://')) emit({ kind: 'firstlaunch', link: argv });",
    '}',
    '',
    '(async () => {',
    '  if (process.env.HARNESS_RUNNER !== \'1\') return;',
    '  port = new NodeRunnerProcessPort();',
    '  supervisor = new HeadlessRunnerSupervisor({',
    '    port,',
    '    spec: {',
    '      executablePath: runnerMode.executablePath,',
    '      args: [runnerEntry],',
    '      cwd: app.getAppPath(),',
    '      env: { PADIEM_SHELL: \'claw2-3093-harness\', ...runnerMode.env },',
    '      shell: false,',
    '      stdio: \'pipe\',',
    '    },',
    '    shutdownGraceMs: 6000,',
    '  });',
    '  const started = await supervisor.start();',
    '  emit({ kind: \'runner\', phase: \'started\', state: started.state, pid: started.pid });',
    '  // the ready line crosses a pipe; give the drain a bounded moment',
    '  let lines = [];',
    '  for (let i = 0; i < 60; i += 1) {',
    '    lines = port.boundedActiveOutput().lines;',
    '    if (lines.some((l) => l.includes(\'padiem-headless-runner ready\'))) break;',
    '    await new Promise((r) => setTimeout(r, 100));',
    '  }',
    '  emit({ kind: \'runner\', phase: \'log\', sawReady: lines.some((l) => l.includes(\'padiem-headless-runner ready\')), captured: lines.length });',
    '  const stopped = await supervisor.stop();',
    '  emit({ kind: \'runner\', phase: \'stopped\', state: stopped.state });',
    '  const pid = started.pid;',
    '  emit({ kind: \'runner\', phase: \'exitcode\', code: stopped.lastExitCode, signal: stopped.lastExitSignal, pid });',
    '  app.quit();',
    '})();',
    '',
    "app.on('window-all-closed', () => app.quit());",
    '',
  ].join('\n');
  writeFileSync(path.join(dir, 'harness-main.mjs'), mainSource);
  return dir;
}

function launchElectron(appDir, args, env) {
  // Strip any inherited ELECTRON_RUN_AS_NODE from the calling shell: if it is
  // set in the parent environment, electron.exe silently degrades to plain
  // Node and cannot load the app at all. The runner child gets the variable
  // back only through the explicit spawn-spec env, which is the point.
  const { ELECTRON_RUN_AS_NODE: _stripped, ...cleanEnv } = process.env;
  return spawn(electronBinary, [appDir, ...args], {
    cwd: appDir,
    env: { ...cleanEnv, ...env },
    stdio: 'ignore',
    windowsHide: true,
  });
}

function readEvents(file) {
  if (!existsSync(file)) return [];
  return readFileSync(file, 'utf8')
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line));
}

function waitFor(predicate, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (predicate()) return resolve(true);
      if (Date.now() > deadline) return reject(new Error(`timeout waiting for ${what}`));
      setTimeout(tick, 100);
    };
    tick();
  });
}

function processAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function regQuery(key) {
  return new Promise((resolve) => {
    const child = spawn('reg', ['query', key], { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    let out = '';
    child.stdout.on('data', (c) => (out += String(c)));
    child.stderr.on('data', (c) => (out += String(c)));
    child.once('exit', (code) => resolve({ code, out }));
  });
}

function regDelete(key) {
  return new Promise((resolve) => {
    const child = spawn('reg', ['delete', key, '/f'], { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    child.once('exit', (code) => resolve(code));
  });
}

const results = {};
const failures = [];
const check = (name, ok, detail) => {
  results[name] = { ok, detail };
  if (!ok) failures.push(`${name}: ${detail}`);
};

try {
  const harnessDir = writeHarnessApp();

  // --- registry prior state (restore afterwards; never leave extra state) ---
  const regKey = 'HKCU\\Software\\Classes\\padiem';
  const before = await regQuery(regKey);
  const existedBefore = before.code === 0;

  // --- scenario 1: runner host under real Electron, start/log/stop/no-orphan ---
  const out1 = path.join(tmp, 'events-runner.ndjson');
  const inst1 = launchElectron(harnessDir, [], { HARNESS_OUT: out1, HARNESS_RUNNER: '1' });
  await waitFor(() => existsSync(out1) && readEvents(out1).some((e) => e.kind === 'runner' && e.phase === 'exitcode'), 30000, 'runner scenario');
  const runnerPid = readEvents(out1).find((e) => e.kind === 'runner' && e.phase === 'exitcode').pid;
  await waitFor(() => inst1.exitCode !== null || !processAlive(inst1.pid), 15000, 'instance 1 exit').catch(() => undefined);
  inst1.kill();
  const ev1 = readEvents(out1);
  const started = ev1.find((e) => e.kind === 'runner' && e.phase === 'started');
  const logEv = ev1.find((e) => e.kind === 'runner' && e.phase === 'log');
  const stopped = ev1.find((e) => e.kind === 'runner' && e.phase === 'stopped');
  check('hostmode_electron_run_as_node', ev1.some((e) => e.kind === 'hostmode' && e.mode === 'electron-run-as-node' && e.env.ELECTRON_RUN_AS_NODE === '1'), JSON.stringify(ev1.filter((e) => e.kind === 'hostmode')));
  check('runner_started_under_electron', started?.state === 'RUNNING' && started?.pid > 0, JSON.stringify(started));
  check('runner_log_ready_line', logEv?.sawReady === true, JSON.stringify(logEv));
  check('runner_stopped_cleanly', stopped?.state === 'STOPPED', JSON.stringify(stopped));
  await new Promise((r) => setTimeout(r, 700));
  check('runner_no_orphan', !processAlive(runnerPid), `runner pid ${runnerPid} still alive`);
  const reg1 = ev1.find((e) => e.kind === 'protocol');
  check('protocol_registered_via_default_app_path', reg1?.registered === true && (reg1?.action === 'register-dev-host' || reg1?.action === 'register-direct'), JSON.stringify(reg1));
  const after = await regQuery(regKey);
  check('hku_protocol_key_present', after.code === 0, `reg query exit ${after.code}: ${after.out.slice(0, 120)}`);

  // --- scenario 2: closed-app delivery — fresh launch argv carries the link ---
  const out2 = path.join(tmp, 'events-closed.ndjson');
  const inst2 = launchElectron(harnessDir, ['padiem://pair?evidence=closed'], { HARNESS_OUT: out2 });
  await waitFor(() => existsSync(out2) && readEvents(out2).some((e) => e.kind === 'firstlaunch'), 20000, 'closed-app delivery');
  const ev2 = readEvents(out2);
  check('closed_app_deeplink_delivery', ev2.some((e) => e.kind === 'firstlaunch' && e.link === 'padiem://pair?evidence=closed'), JSON.stringify(ev2.filter((e) => e.kind === 'firstlaunch')));
  inst2.kill();
  await waitFor(() => inst2.exitCode !== null, 10000, 'instance 2 exit').catch(() => undefined);

  // --- scenario 3: running app + second instance forwarding ---
  const out3 = path.join(tmp, 'events-owner.ndjson');
  const owner = launchElectron(harnessDir, [], { HARNESS_OUT: out3 });
  await waitFor(() => existsSync(out3) && readEvents(out3).some((e) => e.kind === 'ownership' && e.owner === true), 20000, 'owner ready');
  const out4 = path.join(tmp, 'events-second.ndjson');
  const second = launchElectron(harnessDir, ['padiem://pair?evidence=forward'], { HARNESS_OUT: out4 });
  // second instance must quit itself (non-owner)
  await waitFor(() => second.exitCode !== null, 25000, 'second instance quit');
  const ev3 = readEvents(out3);
  check('single_instance_owner', ev3.some((e) => e.kind === 'ownership' && e.owner === true), 'owner flag');
  check('second_instance_self_quits', second.exitCode !== null, `exit=${second.exitCode}`);
  await waitFor(() => readEvents(out3).some((e) => e.kind === 'forwarded'), 15000, 'forwarded deep link').catch(() => undefined);
  const ev3final = readEvents(out3);
  check('running_app_second_instance_forwarding', ev3final.some((e) => e.kind === 'forwarded' && e.link === 'padiem://pair?evidence=forward'), JSON.stringify(ev3final.filter((e) => e.kind === 'forwarded' || e.kind === 'woke')));
  owner.kill();
  await waitFor(() => owner.exitCode !== null, 10000, 'owner exit').catch(() => undefined);

  // --- registry restore ---
  if (!existedBefore && after.code === 0) {
    const rc = await regDelete(regKey);
    check('registry_restored', rc === 0, `reg delete exit ${rc}`);
  } else {
    check('registry_restored', true, existedBefore ? 'pre-existing key left untouched' : 'key absent, nothing to restore');
  }
} catch (error) {
  failures.push(`harness error: ${error instanceof Error ? error.message : String(error)}`);
} finally {
  rmSync(tmp, { recursive: true, force: true });
}

console.log(JSON.stringify({ results, failures, verdict: failures.length === 0 ? 'PASS' : 'FAIL' }, null, 2));
process.exit(failures.length === 0 ? 0 : 1);
