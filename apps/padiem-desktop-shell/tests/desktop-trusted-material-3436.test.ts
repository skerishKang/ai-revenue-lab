/**
 * #3436 B2d — the bounded trusted-local session material channel.
 *
 * The resident host already owns the canonical broker session, the binding and
 * the protected credential store. B2d lets the Desktop main process ask the
 * supervised resident for a bounded projection of that current state over the
 * existing stdio line boundary — and nothing else:
 *
 *   SECOND_SESSION_AUTHORITY=0        no session is opened, copied or stored;
 *                                     the material is the resident's current
 *                                     session, fail-closed on every absence.
 *   DESKTOP_SESSION_OPEN=0            a stopped/expired/unavailable resident
 *                                     stays unavailable; nothing is recovered.
 *   RENDERER_MATERIAL_API=0           no preload method, no IPC channel.
 *   RAW_CREDENTIAL_SECOND_PERSISTENCE=0
 *                                     the raw line is a one-slot read-once
 *                                     value; the retained output buffer keeps
 *                                     only a redacted marker.
 *   RAW_CREDENTIAL_LOGGED=0           refusals carry reason codes only.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  CanonicalConversationController,
  UnconfiguredCanonicalConversationPort,
} from '../src/conversation/canonical-conversation.js';
import {
  type CanonicalConversationHttpTransport,
  type CanonicalDeviceSessionMaterial,
  DesktopAuthenticatedCanonicalConversationPort,
  validateDeviceSessionMaterial,
} from '../src/conversation/desktop-canonical-conversation-port.js';
import {
  type ResidentMaterialBoundary,
  MATERIAL_REQUEST_LINE,
  createResidentDeviceSessionMaterialProvider,
  parseResidentMaterialLine,
} from '../src/conversation/resident-device-session-material.js';
import { NodeRunnerProcessPort } from '../src/supervisor/production-runner-process-port.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.join(here, '..', '..', 'src');

const CREDENTIAL_BYTES = new TextEncoder().encode('b2d-trusted-local-material-credential');
const CREDENTIAL_B64 = Buffer.from(CREDENTIAL_BYTES).toString('base64');
const SESSION_ID = 'sess_b2d_current_1';
const BINDING_REF = 'binding.b2d.current';
const EXPIRES_AT = new Date(Date.now() + 900_000).toISOString();

function materialLine(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    binding_ref: BINDING_REF,
    contract_version: 'claw-desktop-session-material.v1',
    credential_b64: CREDENTIAL_B64,
    credential_generation: 1,
    event: 'desktop_device_session_material',
    expires_at: EXPIRES_AT,
    ok: true,
    session_id: SESSION_ID,
    ...overrides,
  });
}

test('#3436 B2d a valid resident response becomes exactly the B2c material shape', () => {
  const material = parseResidentMaterialLine(materialLine());
  assert.deepEqual(
    validateDeviceSessionMaterial(material),
    { sessionId: SESSION_ID, bindingRef: BINDING_REF, credentialB64: CREDENTIAL_B64 },
  );
});

test('#3436 B2d malformed, stale and widened responses never become material', () => {
  for (const hostile of [
    '',
    'not json',
    '{"ok":true}',
    materialLine({ event: 'something_else' }),
    materialLine({ contract_version: 'claw-desktop-session-material.v2' }),
    materialLine({ ok: false, reason: 'resident_not_online' }),
    materialLine({ session_id: '' }),
    materialLine({ session_id: '../../etc/passwd' }),
    materialLine({ binding_ref: 42 }),
    materialLine({ credential_b64: '!!!not-base64!!!' }),
    materialLine({ credential_b64: '' }),
    materialLine({ credential_generation: 0 }),
    materialLine({ credential_generation: 'one' }),
    materialLine({ expires_at: 'not-a-date' }),
    'x'.repeat(70_000),
  ]) {
    assert.equal(parseResidentMaterialLine(hostile), null, hostile.slice(0, 60));
  }
  // An already-expired projection is stale on arrival: unavailable.
  const expired = materialLine({
    expires_at: new Date(Date.now() - 1000).toISOString(),
  });
  assert.equal(parseResidentMaterialLine(expired), null);
  // Unknown fields fail closed: the B2d success schema is exact-closed, so a
  // widened response — owner/workspace/user-shaped or arbitrary — is never
  // material, even though only the three material values would be forwarded.
  for (const extra of ['account_ref', 'workspace_ref', 'user_id', 'tenant', 'paths', 'request_id']) {
    assert.equal(
      parseResidentMaterialLine(materialLine({ [extra]: 'caller.chosen' })),
      null,
      extra,
    );
  }
});

function fakeBoundary(input: {
  running?: boolean;
  respondWith?: string | null;
  acceptSend?: boolean;
}): ResidentMaterialBoundary & { sent: string[] } {
  const sent: string[] = [];
  return {
    sent,
    sendResidentLine: (line: string) => {
      if (input.acceptSend === false) return false;
      sent.push(line);
      return true;
    },
    takeResidentMaterialLine: () => input.respondWith ?? null,
    residentRunning: () => input.running ?? true,
  };
}

test('#3436 B2d the provider exchanges one bounded request for the current material', async () => {
  const boundary = fakeBoundary({ respondWith: materialLine() });
  const provider = createResidentDeviceSessionMaterialProvider({
    boundary,
    responseTimeoutMs: 500,
    pollIntervalMs: 10,
  });
  const material = await provider();
  assert.deepEqual(material, {
    sessionId: SESSION_ID,
    bindingRef: BINDING_REF,
    credentialB64: CREDENTIAL_B64,
  });
  assert.deepEqual(boundary.sent, [MATERIAL_REQUEST_LINE]);
});

test('#3436 B2d every unavailable condition fails closed to no material', async () => {
  const cases: Array<[string, ResidentMaterialBoundary]> = [
    ['missing resident', fakeBoundary({ running: false })],
    ['refused send', fakeBoundary({ acceptSend: false })],
    ['no response', fakeBoundary({ respondWith: null })],
    ['refused response', fakeBoundary({ respondWith: materialLine({ ok: false, reason: 'resident_not_online' }) })],
    ['malformed response', fakeBoundary({ respondWith: 'garbage' })],
  ];
  for (const [name, boundary] of cases) {
    const provider = createResidentDeviceSessionMaterialProvider({
      boundary,
      responseTimeoutMs: 60,
      pollIntervalMs: 10,
    });
    assert.equal(await provider(), null, name);
  }
});

test('#3436 B2d the raw material line is consumed exactly once', async () => {
  let slot: string | null = materialLine();
  const boundary: ResidentMaterialBoundary = {
    sendResidentLine: () => true,
    takeResidentMaterialLine: () => {
      const line = slot;
      slot = null;
      return line;
    },
    residentRunning: () => true,
  };
  const provider = createResidentDeviceSessionMaterialProvider({
    boundary,
    responseTimeoutMs: 500,
    pollIntervalMs: 10,
  });
  assert.ok(await provider());
  // The slot is empty now: a second call cannot replay stale material.
  slot = materialLine();
  await provider();
  assert.equal(slot, null);
  assert.equal(await provider(), null);
});

test('#3436 B2d serialized calls cannot interleave the exchange', async () => {
  let slot: string | null = null;
  const boundary: ResidentMaterialBoundary = {
    sendResidentLine: () => {
      slot = materialLine();
      return true;
    },
    takeResidentMaterialLine: () => {
      const line = slot;
      slot = null;
      return line;
    },
    residentRunning: () => true,
  };
  const provider = createResidentDeviceSessionMaterialProvider({
    boundary,
    responseTimeoutMs: 500,
    pollIntervalMs: 5,
  });
  const results = await Promise.all([provider(), provider(), provider()]);
  for (const material of results) {
    assert.deepEqual(material, {
      sessionId: SESSION_ID,
      bindingRef: BINDING_REF,
      credentialB64: CREDENTIAL_B64,
    });
  }
});

test('#3436 B2d the retained resident output keeps only the redacted marker', async () => {
  // A real child process is the only honest way to prove the capture layer:
  // the raw line crosses the pipe, the buffer must not keep it.
  const port = new NodeRunnerProcessPort(50);
  const script = [
    `console.log(${JSON.stringify(materialLine())});`,
    `console.log(${JSON.stringify(materialLine({ ok: false, reason: 'session_missing' }))});`,
    'console.log("status line stays readable");',
  ].join(';');
  const handle = await port.spawnResident({
    executablePath: process.execPath,
    args: ['-e', script],
    cwd: process.cwd(),
    env: {},
    shell: false,
    stdio: 'pipe',
  });
  await handle.waitForExit(5_000);

  const lines = port.boundedResidentOutput().lines;
  assert.equal(lines.length, 3);
  assert.match(lines[0] ?? '', /"redacted":true/);
  assert.match(lines[1] ?? '', /"reason":"session_missing"/);
  assert.doesNotMatch(lines.join('\n'), /credential_b64|b2d-trusted-local-material|sess_b2d_current_1/);

  // The settled resident hands out nothing: stale material dies with it.
  assert.equal(port.takeResidentMaterialLine(), null);
});

test('#3436 B2d a live resident hands the raw line once and only once', async () => {
  const port = new NodeRunnerProcessPort(50);
  const handle = await port.spawnResident({
    executablePath: process.execPath,
    args: ['-e', `console.log(${JSON.stringify(materialLine())}); setTimeout(() => {}, 250);`],
    cwd: process.cwd(),
    env: {},
    shell: false,
    stdio: 'pipe',
  });
  // Wait for the capture to land without finishing the child.
  await new Promise((resolve) => setTimeout(resolve, 150));
  const raw = port.takeResidentMaterialLine();
  assert.ok(raw?.includes(CREDENTIAL_B64));
  assert.equal(port.takeResidentMaterialLine(), null);
  // The retained buffer still shows only the redacted marker.
  assert.doesNotMatch(port.boundedResidentOutput().lines.join('\n'), /credential_b64/);
  handle.kill('SIGKILL');
  await handle.waitForExit(2_000);
});

test('#3436 B2d stderr is never a material authority', async () => {
  // A material-like line on stderr is redacted for secret hygiene but NEVER
  // consumed as material: the response authority is stdout only.
  const port = new NodeRunnerProcessPort(50);
  const handle = await port.spawnResident({
    executablePath: process.execPath,
    args: ['-e', `console.error(${JSON.stringify(materialLine())}); setTimeout(() => {}, 250);`],
    cwd: process.cwd(),
    env: {},
    shell: false,
    stdio: 'pipe',
  });
  await new Promise((resolve) => setTimeout(resolve, 150));
  // While the child is alive: no material came from stderr.
  assert.equal(port.takeResidentMaterialLine(), null);
  // The retained stderr diagnostics keep no raw secret.
  const observation = port.residentObservation();
  const stderrTail = observation
    ? ((observation as { stderr_tail?: readonly string[] }).stderr_tail ?? []).join('\n')
    : '';
  assert.doesNotMatch(stderrTail, /credential_b64|b2d-trusted-local-material|sess_b2d_current_1/);
  handle.kill('SIGKILL');
  await handle.waitForExit(2_000);
  // And after settle the slot is still empty — stderr never fed it.
  assert.equal(port.takeResidentMaterialLine(), null);
});

test('#3436 B2d stdout remains the material authority when stderr also emits', async () => {
  const port = new NodeRunnerProcessPort(50);
  const stderrLine = materialLine({ session_id: 'sess_from_stderr' });
  const stdoutLine = materialLine({ session_id: 'sess_from_stdout' });
  const handle = await port.spawnResident({
    executablePath: process.execPath,
    args: [
      '-e',
      [
        `console.error(${JSON.stringify(stderrLine)});`,
        `console.log(${JSON.stringify(stdoutLine)});`,
        'setTimeout(() => {}, 250);',
      ].join(''),
    ],
    cwd: process.cwd(),
    env: {},
    shell: false,
    stdio: 'pipe',
  });
  await new Promise((resolve) => setTimeout(resolve, 150));
  // The one-shot slot holds the STDOUT response, never the stderr one.
  const raw = port.takeResidentMaterialLine();
  assert.ok(raw?.includes('sess_from_stdout'));
  assert.equal(raw?.includes('sess_from_stderr'), false);
  handle.kill('SIGKILL');
  await handle.waitForExit(2_000);
});

test('#3436 B2d valid trusted material drives the B2c canonical read', async () => {
  const requests: CanonicalDeviceSessionMaterial[] = [];
  const transport: CanonicalConversationHttpTransport = {
    async listConversations(material) {
      requests.push(material);
      return {
        status: 200,
        payload: {
          conversations: [
            {
              id: `chat_${'a'.repeat(32)}`,
              title: 'canonical',
              created_at: '2026-10-03T00:00:00Z',
              updated_at: '2026-10-03T00:00:00Z',
            },
          ],
        },
      };
    },
    async readConversation() {
      throw new Error('not exercised here');
    },
  };
  const boundary = fakeBoundary({ respondWith: materialLine() });
  const provider = createResidentDeviceSessionMaterialProvider({
    boundary,
    responseTimeoutMs: 500,
    pollIntervalMs: 10,
  });
  const port = new DesktopAuthenticatedCanonicalConversationPort({
    materialProvider: provider,
    transport,
  });
  const response = await new CanonicalConversationController(port).listConversations();
  assert.equal(response.ok, true);
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0], {
    sessionId: SESSION_ID,
    bindingRef: BINDING_REF,
    credentialB64: CREDENTIAL_B64,
  });
});

test('#3436 B2d unavailable trusted material stays canonical_conversation_unavailable', async () => {
  const transport: CanonicalConversationHttpTransport = {
    async listConversations() {
      throw new Error('must never be reached without material');
    },
    async readConversation() {
      throw new Error('must never be reached without material');
    },
  };
  const boundary = fakeBoundary({ running: false });
  const provider = createResidentDeviceSessionMaterialProvider({
    boundary,
    responseTimeoutMs: 60,
    pollIntervalMs: 10,
  });
  const controller = new CanonicalConversationController(
    new DesktopAuthenticatedCanonicalConversationPort({ materialProvider: provider, transport }),
  );
  const response = await controller.listConversations();
  assert.equal(response.ok, false);
  assert.equal(response.configured, true);
  assert.equal(response.errorCode, 'canonical_conversation_unavailable');
  assert.equal(response.conversations.length, 0);
});

test('#3436 B2d no renderer, preload or IPC surface exists for material', () => {
  const preloadCode = readFileSync(path.join(srcRoot, 'preload', 'preload.cts'), 'utf8');
  for (const forbidden of ['getMaterial', 'getCredential', 'getSession', 'readDeviceMaterial', 'material']) {
    assert.doesNotMatch(preloadCode, new RegExp(forbidden, 'i'), forbidden);
  }
  const contractCode = readFileSync(path.join(srcRoot, 'contract', 'ipc.ts'), 'utf8');
  assert.doesNotMatch(contractCode, /material/i);
  // The main-process composition is the only material consumer.
  const mainCode = readFileSync(path.join(srcRoot, 'main', 'main.ts'), 'utf8');
  assert.match(mainCode, /createResidentDeviceSessionMaterialProvider/);
  const providerModule = readFileSync(
    path.join(srcRoot, 'conversation', 'resident-device-session-material.ts'),
    'utf8',
  );
  assert.match(providerModule, /RENDERER_MATERIAL_API=0/);
  assert.match(providerModule, /DESKTOP_SESSION_OPEN=0/);
});

test('#3436 B2d no session database, no persistence and no browser cookie copy', () => {
  const providerModule = readFileSync(
    path.join(srcRoot, 'conversation', 'resident-device-session-material.ts'),
    'utf8',
  );
  for (const forbidden of [
    'localStorage',
    'writeFile',
    'appendFile',
    'createWriteStream',
    'cookie',
    'open_session',
    'sqlite',
  ]) {
    assert.doesNotMatch(providerModule, new RegExp(forbidden, 'i'), forbidden);
  }
});
