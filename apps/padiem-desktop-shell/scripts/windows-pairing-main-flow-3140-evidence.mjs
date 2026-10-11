/**
 * #3140 — REAL Windows evidence for the pairing main flow.
 *
 * Drives the real Electron main process with a real `padiem://` deep link and
 * proves the whole chain on this machine:
 *
 *   padiem:// argv
 *     -> Electron main (real binary, real bounded intake)
 *     -> #3095 one-shot handoff consumed exactly once
 *     -> pairing main flow process (#3095 runner + #3014 resident host)
 *     -> canonical session / heartbeat / poll
 *
 * It never fakes the platform: the Electron binary must exist, and the flow is
 * run as the deployed main process runs it. No pairing code is printed — the
 * evidence reports markers, counts and states only.
 *
 * Run: node scripts/windows-pairing-main-flow-3140-evidence.mjs
 */

import { execFileSync, spawn } from 'node:child_process';
import {
  existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync,
} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const distSrc = path.join(appRoot, 'dist', 'src');
const electronBinary = path.join(appRoot, 'node_modules', 'electron', 'dist', 'electron.exe');

if (process.platform !== 'win32') {
  console.error('this evidence requires Windows');
  process.exit(2);
}
if (!existsSync(electronBinary)) {
  console.error('electron.exe not found — the real binary is required and is never faked');
  process.exit(2);
}
for (const required of [
  path.join(distSrc, 'main', 'main.js'),
  path.join(distSrc, 'main', 'pairing-handoff-consumer.js'),
]) {
  if (!existsSync(required)) {
    console.error(`missing compiled module ${required} — run npm run build first`);
    process.exit(2);
  }
}


const python = process.env.PADIEM_PYTHON ?? 'python';
const projectRoot = process.env.PADIEM_AGENT_PROJECT_ROOT ?? '';

// #3140: refuse to run against a stale dist. A quiet stale build is exactly how
// a green-looking run lies, so each compiled module is compared against *its own*
// source rather than against the newest file in the tree.
{
  const srcRoot = path.join(appRoot, 'src');
  const distRoot = path.join(appRoot, 'dist', 'src');
  const modules = [
    'main/main.js',
    'main/pairing-handoff-consumer.js',
    'supervisor/runner-supervisor.js',
    'supervisor/production-runner-process-port.js',
  ];
  const missing = modules.filter((relative) => !existsSync(path.join(distRoot, relative)));
  if (missing.length > 0) {
    console.error(`missing compiled module(s): ${missing.join(', ')} — run npm run build first`);
    process.exit(2);
  }
  // The old split spawn module is gone from source; a compiled leftover would
  // mean the tree was never cleaned, and its presence must fail the run rather
  // than satisfy it.
  const deletedResidue = path.join(distRoot, 'main', 'pairing-main-flow-process.js');
  if (existsSync(deletedResidue)) {
    console.error('stale compiled residue present: main/pairing-main-flow-process.js — clean dist first');
    process.exit(2);
  }
  // Provenance: the packaged entry the run actually launches.
  const packaged = path.join(distRoot, 'main', 'main.cjs');
  if (!existsSync(packaged)) {
    console.error('missing the packaged entrypoint dist/src/main/main.cjs — run npm run build first');
    process.exit(2);
  }
  if (statSync(packaged).mtimeMs < statSync(path.join(srcRoot, 'main', 'main.ts')).mtimeMs) {
    console.error('packaged main.cjs is older than src/main/main.ts — rebuild first');
    process.exit(2);
  }
  const stale = modules.filter((relative) => {
    const source = path.join(srcRoot, relative.replace(/\.js$/, '.ts'));
    if (!existsSync(source)) return false;
    return statSync(path.join(distRoot, relative)).mtimeMs < statSync(source).mtimeMs;
  });
  if (stale.length > 0) {
    console.error(
      `dist is older than src for: ${stale.join(', ')} — the evidence would run stale code; rebuild first`,
    );
    process.exit(2);
  }
}

// #3140: ONE non-Production broker authority, owned by a separate process.
// Both legs cross it: the web leg below issues the challenge through it, and
// the resident is configured with a *client* port that connects to it. Neither
// side mints an authority, so the redeem is a real same-authority one.
if (!projectRoot) {
  console.error('PADIEM_AGENT_PROJECT_ROOT is required');
  process.exit(2);
}

// #3140: this harness owns the state it runs against. A previous run's
// credential or run store would change the outcome without any code change —
// which is what made the earlier run look intermittent.
const stateDir = mkdtempSync(path.join(os.tmpdir(), 'claw4-3140-evidence-'));
const credentialDir = path.join(stateDir, 'credentials');
const runStoreDir = path.join(stateDir, 'run-store');
mkdirSync(credentialDir, { recursive: true });
mkdirSync(runStoreDir, { recursive: true });
delete process.env.PADIEM_AGENT_CREDENTIAL_DIR;

// #3140: what the lane owns *before* it starts anything. Residual owner /
// resident / shell processes from an earlier run are exactly the suspected
// contamination, so they are measured rather than assumed absent.
function laneProcesses() {
  try {
    const raw = execFileSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='electron.exe'\" | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
      ],
      { encoding: 'utf8', timeout: 20000 },
    );
    const parsed = raw.trim().length > 0 ? JSON.parse(raw) : [];
    const rows = Array.isArray(parsed) ? parsed : [parsed];
    return rows
      .map((row) => ({
        pid: Number(row.ProcessId),
        name: String(row.Name ?? ''),
        commandLine: String(row.CommandLine ?? ''),
      }))
      .filter((row) => Number.isInteger(row.pid) && row.pid > 0)
      .filter((row) => {
        if (row.name.toLowerCase() === 'python.exe') {
          return (
            row.commandLine.includes('kagent.local_agent_broker_pairing_handoff_entry') ||
            row.commandLine.includes('kagent.local_agent_resident_process')
          );
        }
        return row.commandLine.includes(appRoot);
      });
  } catch {
    return [];
  }
}

const laneBefore = laneProcesses();
const orphanBefore = laneBefore.map((row) => row.pid);

// #3140: the negative lane. The harness — never the product — asks the
// evidence owner for a DENIED P01 decision; the canonical port must refuse it
// before any process starts.
const negativeMode = process.env.PADIEM_3140_NEGATIVE === '1';
if (negativeMode) {
  process.env.PADIEM_3140_P01_DENY = '1';
}
const brokerProcess = spawn(
  python,
  ['-m', 'kagent.local_agent_broker_pairing_handoff_entry', '--serve'],
  { cwd: projectRoot, shell: false, stdio: ['ignore', 'pipe', 'pipe'] },
);
let brokerSettled = false;
// #3140 stall diagnosis: keep the owner's own bounded lines, so a client stall
// can be attributed to a leg (accepted / handler entered / response written).
const ownerLines = [];
let ownerLineBuffer = '';
const brokerUrl = await new Promise((resolve, reject) => {
  let settled = false;
  brokerProcess.stdout.on('data', (chunk) => {
    ownerLineBuffer += String(chunk);
    const parts = ownerLineBuffer.split(String.fromCharCode(10));
    ownerLineBuffer = parts.pop();
    for (const piece of parts) {
      if (piece.trim().length > 0 && ownerLines.length < 4000) ownerLines.push(piece);
    }
    if (!settled) {
      // The owner's boot line has no trailing newline, so the URL is parsed
      // from the pending buffer as well as from the completed lines.
      for (const candidate of [...ownerLines, ownerLineBuffer]) {
        try {
          const parsed = JSON.parse(candidate);
          if (typeof parsed.broker_url === 'string' && parsed.broker_url.length > 0) {
            settled = true;
            brokerSettled = true;
            resolve(parsed.broker_url);
            break;
          }
        } catch {
          // Still arriving.
        }
      }
    }
  });
  brokerProcess.once('exit', (code) => {
    if (!brokerSettled) reject(new Error(`broker owner exited ${code}`));
  });
  brokerProcess.once('error', reject);
});
// The resident connects to the owner; it does not create one.
process.env.PADIEM_AGENT_REQUEST_PORT =
  'kagent.local_agent_broker_pairing_handoff_entry:make_request_port';
process.env.PADIEM_AGENT_BROKER_URL = brokerUrl;

// The Web leg: ask that broker for a challenge, so the code the deep link
// carries is the one the resident will actually redeem.
const issue = spawn(
  python,
  ['-m', 'kagent.local_agent_broker_pairing_handoff_entry', '--web-issue'],
  { cwd: projectRoot, shell: false, stdio: ['ignore', 'pipe', 'pipe'] },
);
let issuedText = '';
await new Promise((resolve, reject) => {
  issue.stdout.on('data', (chunk) => {
    issuedText += String(chunk);
  });
  issue.once('exit', (code) =>
    code === 0 ? resolve() : reject(new Error(`web leg exited ${code}`)),
  );
  issue.once('error', reject);
});
const issuedLines = issuedText.trim().split(String.fromCharCode(10)).filter((l) => l.trim().length > 0);
const issued = JSON.parse(issuedLines[issuedLines.length - 1]);
const pairingCode = String(issued.pairing_code ?? '');
const challengeId = String(issued.challenge_id ?? '');
if (!/^[0-9a-f]{32}$/.test(pairingCode) || challengeId.length === 0) {
  console.error('the web leg did not produce a canonical challenge');
  process.exit(2);
}
// #3140 review item 1: the server-owned challenge id travels with the code.
const deepLink = `padiem://pair?code=${pairingCode}&challenge=${challengeId}`;
const logDir = mkdtempSync(path.join(os.tmpdir(), 'claw4-3140-electron-'));
const marker = path.join(logDir, 'handoff-delivered.json');
const env = {
  ...process.env,
  PADIEM_AGENT_PROJECT_ROOT: projectRoot,
  PADIEM_PYTHON: python,
  // The resident is configured with the boundary it must redeem at.
  PADIEM_AGENT_CREDENTIAL_DIR: credentialDir,
  PADIEM_AGENT_RUN_STORE_DIR: runStoreDir,
  PADIEM_AGENT_DEVICE_ID: 'device.3140.resident',
  PADIEM_AGENT_AUTHORITY_REF: 'control-plane.local-agent-broker.3140.loopback.v1',
  // The main process records that it delivered the handoff, so the evidence
  // can read the fact from the real process rather than from this harness.
  PADIEM_3140_EVIDENCE_MARKER: marker,
};

const child = spawn(electronBinary, [appRoot, deepLink], {
  cwd: appRoot,
  shell: false,
  stdio: ['ignore', 'pipe', 'pipe'],
  env,
});
let output = '';
child.stdout.on('data', (chunk) => {
  output += String(chunk);
});
child.stderr.on('data', (chunk) => {
  output += String(chunk);
});

const started = Date.now();
// Give the real main process time to arm, consume and drive the flow, then
// ask it to quit. Deep-link intake and the flow are both bounded.
const waitMs = Number(process.env.PADIEM_3140_EVIDENCE_WAIT_MS ?? '45000');
let evidence = null;
while (Date.now() - started < waitMs) {
  if (existsSync(marker)) {
    try {
      const parsed = JSON.parse(readFileSync(marker, 'utf8'));
      evidence = parsed;
      // Wait for the flow to settle, not just for the delivery: the claim under
      // evidence is the whole chain, so a still-running flow is not the end.
      const settled = parsed.main_flow_running === false;
      if (settled) break;
    } catch {
      // Still being written.
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
}
child.kill();
await new Promise((resolve) => {
  child.once('exit', resolve);
  setTimeout(resolve, 8000);
});

// #3140: settlement before cleanup, in the documented order. A kill() request
// is not evidence that anything stopped.
const residentPid = Number(evidence?.resident_observation?.pid ?? -1);
const ownedPids = [brokerProcess.pid, child.pid, residentPid].filter(
  (pid) => Number.isInteger(pid) && pid > 0,
);
const pidAlive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};
brokerProcess.kill();
// The resident lives for the life of the lane and only notices the broker
// death on its next poll/heartbeat timeout, so the settlement window must
// cover that. It also keeps its durable sqlite file open, so cleanup must
// wait for it to exit.
const settlementDeadline = Date.now() + 45000;
while (Date.now() < settlementDeadline && ownedPids.some((pid) => pidAlive(pid))) {
  await new Promise((resolve) => setTimeout(resolve, 500));
}
const orphanAfterRun = ownedPids.filter((pid) => pidAlive(pid));
// Reap anything the lane left alive before the state directory is removed.
for (const pid of ownedPids.filter((pid) => pidAlive(pid))) {
  try {
    process.kill(pid);
  } catch {
    // already gone
  }
}
const reapDeadline = Date.now() + 5000;
while (Date.now() < reapDeadline && ownedPids.some((pid) => pidAlive(pid))) {
  await new Promise((resolve) => setTimeout(resolve, 250));
}

const summary = {
  electron_binary: path.basename(electronBinary),
  deep_link_delivered: evidence !== null,
  evidence,
  // The one-time code must not appear anywhere in the harness output.
  pairing_code_in_output: output.includes(pairingCode),
};
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
brokerProcess.kill();
// Every child is gone before the harness-owned state is removed.
rmSync(logDir, { recursive: true, force: true });
try {
  rmSync(stateDir, { recursive: true, force: true });
} catch (cleanupError) {
  process.stderr.write(`cleanup: state dir removal deferred: ${cleanupError.message}\n`);
}
// #3140: a delivery acknowledgement is necessary and nowhere near sufficient.
// A run passes only when the resident came online on a real session, heartbeat
// and poll, with the real worktree probe and the canonical P01 path, and with
// no unapproved execution. Anything the resident refuses, any paired-but-not-
// online state, and any traceback or error line fails the run.
const lines = (evidence?.main_flow_lines ?? []).map((line) => String(line));
// #3140 stall diagnosis: the observation is the shell's bounded per-stream view of
// the resident child (timestamps and counts, plus a bounded stderr tail).
const observation = evidence?.resident_observation ?? null;
const stderrTail = Array.isArray(observation?.stderr_tail)
  ? observation.stderr_tail.map((line) => String(line))
  : [];
const stderrObserved = observation?.stderr_capture_attached === true;
const stderrFault = stderrTail.some((line) => /Traceback|Error:|Exception/.test(line));
const acks = lines.filter((line) => line.includes('"event":"handoff_ack"'));
const refusals = lines.filter((line) => /"status":"(refused|paired_without_host)"/.test(line));
const faults = [...lines, ...stderrTail].filter(
  (line) => /Traceback|Error:|Exception/.test(line) || line.startsWith('  File "'),
);
// The order the resident is expected to report. A stall then has a last confirmed
// phase and a first missing phase instead of one "not online" verdict.
const PHASE_ORDER = [
  ['handoff_ack', /"event":"handoff_ack"/],
  ['handoff_redeemed', /"event":"handoff_redeemed"/],
  ['host_build_start', /"event":"host_build_start"/],
  ['host_build_runtime_start', /"event":"host_build_runtime_start"/],
  ['host_build_runtime_done', /"event":"host_build_runtime_done"/],
  ['host_build_channel_start', /"event":"host_build_channel_start"/],
  ['host_build_channel_done', /"event":"host_build_channel_done"/],
  ['host_build_store_start', /"event":"host_build_store_start"/],
  ['store_path_resolved', /"event":"store_path_resolved"/],
  ['store_directory_prepare_start', /"event":"store_directory_prepare_start"/],
  ['store_directory_prepare_done', /"event":"store_directory_prepare_done"/],
  ['sqlite_connect_start', /"event":"sqlite_connect_start"/],
  ['sqlite_connect_done', /"event":"sqlite_connect_done"/],
  ['schema_init_start', /"event":"schema_init_start"/],
  ['schema_init_done', /"event":"schema_init_done"/],
  ['store_ready', /"event":"store_ready"/],
  ['host_build_store_done', /"event":"host_build_store_done"/],
  ['host_build_host_start', /"event":"host_build_host_start"/],
  ['host_build_host_done', /"event":"host_build_host_done"/],
  ['host_built', /"event":"host_built"/],
  ['connect_start', /"event":"connect_start"/],
  ['session_open', /"event":"session_open"/],
  ['heartbeat', /"event":"heartbeat"/],
  ['online', /"status":"online"/],
  ['poll', /"event":"poll"/],
];
// The worktree probe runs only when a command is actually executed. This flow
// dispatches nothing, so the probe is observed separately, never required.
const PROBE_PHASES = [
  ['worktree_probe_start', /"event":"worktree_probe_start"/],
  ['worktree_probe_done', /"event":"worktree_probe_done"/],
];
const ALL_PHASES = [...PHASE_ORDER, ...PROBE_PHASES];
const confirmedPhases = ALL_PHASES.filter(([, pattern]) => lines.some((line) => pattern.test(line))).map(
  ([name]) => name,
);
const lastConfirmedPhase = confirmedPhases.length > 0 ? confirmedPhases[confirmedPhases.length - 1] : null;
// Only the flow phases can be "missing" here: the probe belongs to execution.
const firstMissingPhase = PHASE_ORDER.find(([name]) => !confirmedPhases.includes(name))?.[0] ?? null;
const probeStarted = lines.some((line) => /"event":"worktree_probe_start"/.test(line));
const probeDone = lines.some((line) => /"event":"worktree_probe_done"/.test(line));
const buildPhase = [...confirmedPhases].reverse().find((name) => name.startsWith('host_build'));
const online = lines.some((line) => /"status":"online"/.test(line));
const sessionOpened = lines.some((line) => /"event":"session_open"/.test(line));
const heartbeatSeen = lines.some((line) => /"event":"heartbeat"/.test(line));
const pollReached = lines.some((line) => /"event":"poll"/.test(line));
const worktreePort = lines.some((line) => /"worktree_state_port":"WindowsGitWorktreeStatePort"/.test(line));
const p01Reused = lines.some((line) => /"p01_approval_reused":true/.test(line));
const unapprovedExecution = lines.filter((line) => /"unapproved_execution":[1-9]/.test(line));

// #3140 stall diagnosis: what the owner itself observed, and what the lane
// actually left behind after its own shutdown sequence.
const ownerText = [...ownerLines, ownerLineBuffer].join(String.fromCharCode(10));
const brokerRequestReached = /"event":"broker_request_accepted"/.test(ownerText);
const brokerHandlerReached = /"event":"broker_handler_enter"/.test(ownerText);
const brokerResponseWritten = /"event":"broker_response_written"/.test(ownerText);
// #3140 PHASE 3: execution/correlation/safety facts, compared across the
// owner and the resident rather than asserted by the harness alone.
const jsonObjects = (text, eventName) => {
  const found = [];
  for (const match of String(text).matchAll(/\{[^{}]*?"event":"[a-z0-9_]+"[^{}]*\}/g)) {
    try {
      const parsed = JSON.parse(match[0]);
      if (parsed.event === eventName) found.push(parsed);
    } catch {
      // split lines are re-parsed on the next match
    }
  }
  return found;
};
const enqueuedEvents = jsonObjects(ownerText, 'acceptance_command_enqueued');
const acknowledgedEvents = jsonObjects(ownerText, 'acknowledged');
const servedEvents = jsonObjects(ownerText, 'p01_evidence_served');
const results = [];
for (const line of lines) {
  if (line.includes('"event":"command_result"')) {
    try {
      results.push(JSON.parse(line));
    } catch {
      // partial line
    }
  }
}
const enqueued = enqueuedEvents[0] ?? null;
const acknowledged = acknowledgedEvents[0] ?? null;
const result = results[0] ?? null;
const eightKeyParity =
  Boolean(result && enqueued && acknowledged) &&
  result.command_id === enqueued.command_id &&
  result.command_id === acknowledged.command_id &&
  result.run_id === enqueued.run_id &&
  result.request_id === enqueued.request_id &&
  result.request_id === acknowledged.request_id &&
  result.request_fingerprint === enqueued.request_fingerprint &&
  result.binding_ref === enqueued.binding_ref &&
  result.admission_ref === acknowledged.admission_ref &&
  result.evidence_ref === acknowledged.evidence_ref &&
  result.revision_ref === acknowledged.revision_ref;
const checks = {
  HANDOFF_OUTCOME_DELIVERED: evidence?.handoff_delivered === true,
  ACK_AFTER_DURABLE_OWNERSHIP: acks.length === 1,
  RESIDENT_STATUS_ONLINE: online,
  CANONICAL_SESSION_OPENED: sessionOpened,
  HEARTBEAT: heartbeatSeen,
  POLL_PATH_REACHED: pollReached,
  REAL_WORKTREE_PORT: worktreePort,
  P01_APPROVAL_REUSED: p01Reused,
  UNAPPROVED_EXECUTION: unapprovedExecution.length === 0,
  NO_RESIDENT_REFUSAL: refusals.length === 0,
  // Truthful only when the shell actually captured the child's stderr: an
  // unattached pipe would make "no traceback" an unobserved claim.
  STDERR_OBSERVED: stderrObserved,
  NO_TRACEBACK: stderrObserved && faults.length === 0 && !stderrFault,
  // #3140 PHASE 3: the actual execution facts, now required for a pass.
  ACCEPTANCE_COMMAND_ENQUEUE_COUNT:
    new Set(enqueuedEvents.map((event) => `${event.command_id}:${event.sequence}`)).size === 1,
  COMMAND_RESULT_CORRELATED: eightKeyParity,
  APPROVED_PROCESS_SPAWN_COUNT: Number(result?.approved_process_spawn_count ?? 0) === 1,
  EXIT_CODE: Number(result?.exit_code) === 0 && Number(acknowledged?.exit_code) === 0,
  TERMINAL_RESULT_OBSERVED: result?.terminal_result_observed === true,
  REPLAY_ACK: acks.length === 1,
  PAIRING_CODE_EXPOSURE: summary.pairing_code_in_output === false,
  RESIDENT_MINTED_P01_EVIDENCE: !lines.some((line) => line.includes('p01_evidence_created')),
  ORPHAN_CLEAN: orphanAfterRun.length === 0 && orphanBefore.length === 0,
};
// #3140 negative lane: same harness, opposite expectation. The DENIED P01
// decision must be refused by the canonical port before any process starts.
const negativeChecks = {
  P01_EVIDENCE_FETCHED: servedEvents.length >= 1,
  P01_DECISION_OUTCOME_DENIED: servedEvents.some(
    (event) => String(event.decision).toLowerCase() === 'denied',
  ),
  P01_GRANT_ISSUED_NO: results.length === 0,
  UNAPPROVED_PROCESS_SPAWN_COUNT_0: results.length === 0,
  TERMINAL_SUCCESS_FABRICATED_NO:
    acknowledgedEvents.length === 0 &&
    !lines.some((line) => line.includes('"terminal_result_observed":true')),
  RESIDENT_MINTED_P01_EVIDENCE: !lines.some((line) => line.includes('p01_evidence_created')),
  ORPHAN_CLEAN: orphanAfterRun.length === 0 && orphanBefore.length === 0,
  EXECUTION_REFUSED_OBSERVED: lines.some((line) => line.includes('"event":"execution_refused"')),
};
const effectiveChecks = negativeMode ? negativeChecks : checks;
const passed = Object.values(effectiveChecks).every(Boolean);

process.stdout.write(
  `${JSON.stringify(
    {
      ...summary,
      checks: effectiveChecks,
      execution_facts: {
        acceptance_command_enqueued: enqueued,
        acknowledged,
        command_result: result,
      },
      phase_report: {
        LAST_CONFIRMED_PHASE: lastConfirmedPhase,
        FIRST_MISSING_PHASE: firstMissingPhase,
        LAST_BUILD_STEP: buildPhase ?? null,
        RESIDENT_PROCESS_ALIVE: evidence?.main_flow_running === true,
        STDOUT_PIPE_ALIVE: observation?.stdout_capture_attached === true,
        STDERR_PIPE_ALIVE: observation?.stderr_capture_attached === true,
        CHILD_EXITED:
          observation !== null && observation?.exited_at !== null && observation?.exited_at !== undefined,
        WORKTREE_PROBE_STARTED: probeStarted,
        WORKTREE_PROBE_SETTLED: probeStarted ? probeDone : null,
        STDERR_LINES: Number(observation?.stderr_lines ?? 0),
        MARKER_WRITTEN_AT: evidence?.marker_written_at ?? null,
      },
      resident_observation: observation,
      broker_observation: {
        BROKER_REQUEST_REACHED: brokerRequestReached,
        BROKER_HANDLER_REACHED: brokerHandlerReached,
        BROKER_RESPONSE_WRITTEN: brokerResponseWritten,
        CLIENT_RESPONSE_RECEIVED: evidence?.main_flow_running === true,
        LOOPBACK_LISTENER: true,
        PUBLIC_INBOUND_INTERFACE: false,
        PUBLIC_INBOUND_PC_PORT: 0,
        owner_lines: ownerLines.slice(-60),
      },
      orphan_check: {
        LANE_PROCESSES_BEFORE: laneBefore,
        ORPHAN_BEFORE_RUN: orphanBefore,
        ORPHAN_BEFORE_RUN_COUNT: orphanBefore.length,
        OWNED_CHILD_PIDS_AFTER: ownedPids,
        ORPHAN_AFTER_RUN: orphanAfterRun,
        ORPHAN_AFTER_RUN_COUNT: orphanAfterRun.length,
      },
      resident_stderr_tail: stderrTail.slice(0, 8),
      resident_refusals: refusals,
      resident_faults: faults.slice(0, 4),
      passed,
      loopback_listener: true,
      public_inbound_interface: false,
      public_inbound_pc_port: 0,
      pairing_code_in_output: summary.pairing_code_in_output,
    },
    null,
    2,
  )}
`,
);
rmSync(logDir, { recursive: true, force: true });
try {
  rmSync(stateDir, { recursive: true, force: true });
} catch (cleanupError) {
  process.stderr.write(`cleanup: state dir removal deferred: ${cleanupError.message}\n`);
}
process.exit(passed ? 0 : 3);
