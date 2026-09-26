/**
 * #3093 — main-process wiring assertions (source level).
 *
 * These pin the *shape* of the integration so a future edit cannot silently
 * drop single-instance ownership, re-register the protocol after a window
 * exists, or introduce a second deep-link parser authority. Behaviour is
 * covered by protocol-registration.test.ts / single-instance.test.ts; this
 * file guards the wiring in main.ts itself, in the same style as the #3083
 * preload-and-main-security tests.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.join(here, '..', '..', 'src');

function read(...segments: string[]): string {
  return readFileSync(path.join(srcRoot, ...segments), 'utf8');
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

const mainCode = stripComments(read('main', 'main.ts'));
const singleInstanceCode = stripComments(read('main', 'single-instance.ts'));
const protocolCode = stripComments(read('main', 'protocol-registration.ts'));
const hostModeCode = stripComments(read('main', 'runner-host-mode.ts'));
const builderConfig = readFileSync(path.join(srcRoot, '..', 'electron-builder.yml'), 'utf8');

test('#3093 main acquires the single-instance lock before app.whenReady / any window', () => {
  const ownershipIndex = mainCode.indexOf('acquireInstanceOwnership()');
  const readyIndex = mainCode.indexOf('app.whenReady()');
  // the *call site* inside the owner branch, not the earlier function definition
  const windowIndex = mainCode.indexOf('      createMainWindow();');
  assert.ok(ownershipIndex > 0, 'main must call acquireInstanceOwnership');
  assert.ok(readyIndex > 0 && windowIndex > 0, 'whenReady and createMainWindow call site must exist');
  assert.ok(ownershipIndex < readyIndex, 'ownership must be claimed before whenReady');
  assert.ok(ownershipIndex < windowIndex, 'ownership must be claimed before any window');
  // The whenReady block must be inside the owner branch.
  assert.match(mainCode, /if \(acquireInstanceOwnership\(\)\) \{[\s\S]*app\.whenReady\(\)/);
});

test('#3093 a non-owner quits via onNotOwner and never reaches window creation', () => {
  assert.match(mainCode, /onNotOwner: \(\) => \{[\s\S]*?app\.quit\(\);/);
});

test('#3093 second-instance forwarding reuses the existing pairingDeepLinkSubmit intake only', () => {
  assert.match(mainCode, /forwardDeepLink: \(deepLink\) => \{[\s\S]*?controller\.pairingDeepLinkSubmit\(\{ deepLink \}\)/);
  // SECOND_DEEPLINK_PARSER_AUTHORITY=0: no parsePairingDeepLink call may appear
  // in main or in the single-instance module — interpretation stays in the
  // controller seam.
  assert.equal(/parsePairingDeepLink\s*\(/.test(mainCode), false);
  assert.equal(/parsePairingDeepLink\s*\(/.test(singleInstanceCode), false);
  // single-instance.ts must not even import the parser.
  assert.equal(/pairing-deeplink\.js/.test(singleInstanceCode.replace(/import \{ PAIRING_SEAM \}[^;]*;/, '')), false,
    'only the PAIRING_SEAM scheme constant may be imported');
});

test('#3093 protocol registration happens on the Windows main path', () => {
  assert.match(mainCode, /registerWindowsProtocol\(\)/);
  assert.match(mainCode, /registerWindowsProtocolClient\(app, \{/);
  assert.match(protocolCode, /setAsDefaultProtocolClient/);
  // dev-mode handling: process.defaultApp must drive the plan
  assert.match(mainCode, /defaultApp/);
  assert.match(protocolCode, /register-dev-host|action === 'register-dev-host'/);
});

test('#3093 electron-builder declares the padiem scheme for install-time registration', () => {
  assert.match(builderConfig, /^protocols:$/m);
  assert.match(builderConfig, /^\s{6}- padiem$/m);
  // scheme must match the seam constant, not a drifted copy
  assert.equal(builderConfig.includes('padiem'), true);
});

test('#3093 runner host mode is explicit — the spawn spec never assumes execPath is Node', () => {
  assert.match(mainCode, /resolveRunnerHostMode\(\{/);
  assert.match(mainCode, /executablePath: runnerHostMode\.executablePath/);
  assert.match(mainCode, /\.\.\.runnerHostMode\.env/);
  // the old implicit fallback must be gone from the spawn spec
  assert.equal(/process\.env\.PADIEM_RUNNER_EXECUTABLE \?\? process\.execPath/.test(mainCode), false);
  assert.match(hostModeCode, /ELECTRON_RUN_AS_NODE/);
});

test('#3093 the new main-side modules never touch child_process, fs writes, or the network', () => {
  for (const [name, code] of [
    ['single-instance', singleInstanceCode],
    ['protocol-registration', protocolCode],
    ['runner-host-mode', hostModeCode],
  ] as const) {
    assert.equal(/child_process/.test(code), false, `${name} must not reach child_process`);
    assert.equal(/node:fs|writeFile|createWriteStream/.test(code), false, `${name} must not write files`);
    assert.equal(/fetch\(|XMLHttpRequest|WebSocket|net\.|http:/.test(code), false, `${name} must not reach the network`);
  }
});

test('#3093 #3083 invariants survive: main still never uses a shell or elevation', () => {
  assert.match(mainCode, /shell: false/);
  assert.equal(/shell:\s*true/.test(mainCode), false);
  assert.equal(/elevation|elevat/i.test(mainCode), false);
  assert.equal(/windowsVerbatimArguments|runas/i.test(mainCode), false);
});
