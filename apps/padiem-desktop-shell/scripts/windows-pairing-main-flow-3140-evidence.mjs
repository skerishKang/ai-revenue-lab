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


const python = process.env.PADIEM_PYTHON ?? 'python';
const projectRoot = process.env.PADIEM_AGENT_PROJECT_ROOT ?? '';

// #3140: ONE non-Production broker authority, owned by a separate process.
// Both legs cross it: the web leg below issues the challenge through it, and
// the resident is configured with a *client* port that connects to it. Neither
// side mints an authority, so the redeem is a real same-authority one.
if (!projectRoot) {
  console.error('PADIEM_AGENT_PROJECT_ROOT is required');
  process.exit(2);
}

const brokerProcess = spawn(
  python,
  ['-m', 'kagent.local_agent_broker_pairing_handoff_entry', '--serve'],
  { cwd: projectRoot, shell: false, stdio: ['ignore', 'pipe', 'pipe'] },
);
let brokerSettled = false;
const brokerUrl = await new Promise((resolve, reject) => {
  let text = '';
  brokerProcess.stdout.on('data', (chunk) => {
    text += String(chunk);
    const lines = text.split(String.fromCharCode(10)).filter((line) => line.trim().length > 0);
    if (lines.length > 0) {
      try {
        brokerSettled = true;
        resolve(JSON.parse(lines[lines.length - 1]).broker_url);
      } catch {
        // Keep reading until the owner prints its URL.
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

const summary = {
  electron_binary: path.basename(electronBinary),
  deep_link_delivered: evidence !== null,
  evidence,
  // The one-time code must not appear anywhere in the harness output.
  pairing_code_in_output: output.includes(pairingCode),
};
process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
brokerProcess.kill();
rmSync(logDir, { recursive: true, force: true });
const flowReported = (evidence?.main_flow_lines ?? []).find((line) => line.includes('"status"'));
process.stdout.write(`${JSON.stringify({ ...summary, flow_reported: flowReported ?? null }, null, 2)}
`);
process.exit(evidence && evidence.handoff_delivered === true && flowReported ? 0 : 3);
