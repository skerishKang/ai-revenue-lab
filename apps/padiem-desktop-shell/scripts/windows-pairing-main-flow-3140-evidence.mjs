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

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const distSrc = path.join(appRoot, 'dist', 'src');
const electronBinary = path.join(appRoot, 'node_modules', 'electron', 'dist', 'electron.exe');
const projectRoot = process.env.PADIEM_AGENT_PROJECT_ROOT ?? '';

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
  path.join(distSrc, 'main', 'pairing-main-flow-process.js'),
]) {
  if (!existsSync(required)) {
    console.error(`missing compiled module ${required} — run npm run build first`);
    process.exit(2);
  }
}

// #3140 review item 1: the Web leg and the resident must meet at the SAME
// canonical broker authority. The resident never constructs one, so a real
// Windows run needs a non-Production broker that both legs reach, published to
// the resident through its configured entry point
// (PADIEM_AGENT_REQUEST_PORT -> "module:factory").
//
// This harness does not stand one up, and it must not fake one: the previous
// shape derived the code deterministically from the resident's own authority,
// which proved reconstruction rather than redemption. Without a configured
// boundary the honest outcome is a refusal, which is what this reports.
const brokerEntry = process.env.PADIEM_AGENT_REQUEST_PORT;
if (!brokerEntry) {
  process.stdout.write(
    `${JSON.stringify(
      {
        evidence: 'unavailable',
        reason: 'no_configured_broker_boundary',
        detail:
          'the Windows run needs a non-Production broker both the Web leg and the resident reach; ' +
          'the resident refuses without one and this harness will not invent a code',
        pairing_code_in_output: false,
      },
      null,
      2,
    )}
`,
  );
  process.exit(5);
}

const deepLink = `padiem://pair?code=${pairingCode}&ref=pairref-3140-evidence`;
const logDir = mkdtempSync(path.join(os.tmpdir(), 'claw4-3140-electron-'));
const marker = path.join(logDir, 'handoff-delivered.json');
const env = {
  ...process.env,
  PADIEM_AGENT_PROJECT_ROOT: projectRoot,
  PADIEM_PYTHON: python,
  PADIEM_AGENT_REQUEST_PORT: brokerEntry,
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

const summary = {
  electron_binary: path.basename(electronBinary),
  deep_link_delivered: evidence !== null,
  evidence,
  // The one-time code must not appear anywhere in the harness output.
  pairing_code_in_output: output.includes(pairingCode),
};
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
rmSync(logDir, { recursive: true, force: true });
const flowReported = (evidence?.main_flow_lines ?? []).find((line) => line.includes('"status"'));
process.stdout.write(`${JSON.stringify({ ...summary, flow_reported: flowReported ?? null }, null, 2)}
`);
process.exit(evidence && evidence.handoff_delivered === true && flowReported ? 0 : 3);
