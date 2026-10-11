/**
 * #3093 — Windows protocol registration decision tests.
 *
 * Pure decision + injected-fake execution. No Electron runtime, no registry.
 * The real-Windows registration evidence is a separate gated harness
 * (`scripts/windows-real-evidence.mjs`) because it touches HKCU.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PROTOCOL_SCHEME,
  registerWindowsProtocolClient,
  windowsProtocolRegistrationPlan,
  type ProtocolClientApp,
} from '../src/main/protocol-registration.js';
import { PAIRING_SEAM } from '../src/contract/pairing-deeplink.js';

interface RecordedCall {
  scheme: string;
  path?: string;
  args?: readonly string[];
}

function fakeApp(result = true): { app: ProtocolClientApp; calls: RecordedCall[] } {
  const calls: RecordedCall[] = [];
  return {
    calls,
    app: {
      setAsDefaultProtocolClient(scheme, path?, args?) {
        calls.push({ scheme, path, args });
        return result;
      },
    },
  };
}

test('#3093 scheme is byte-identical to the existing pairing seam — no second scheme authority', () => {
  assert.equal(PROTOCOL_SCHEME, 'padiem');
  assert.equal(PROTOCOL_SCHEME, PAIRING_SEAM.SCHEME);
});

test('#3093 packaged Windows build registers the scheme directly', () => {
  const { app, calls } = fakeApp();
  const outcome = registerWindowsProtocolClient(app, {
    platform: 'win32',
    packaged: true,
    defaultApp: false,
    execPath: 'C:\\Program Files\\Padiem\\Padiem Desktop Shell.exe',
    appPath: 'C:\\Program Files\\Padiem\\resources\\app.asar',
  });
  assert.equal(outcome.registered, true);
  assert.equal(outcome.plan.action, 'register-direct');
  assert.deepEqual(calls, [{ scheme: 'padiem', path: undefined, args: undefined }]);
});

test('#3093 dev launch registers the Electron binary WITH the app directory', () => {
  // This is the `process.defaultApp` requirement: registering bare Electron in
  // dev would hand Windows a scheme that launches Electron with no app.
  const { app, calls } = fakeApp();
  const outcome = registerWindowsProtocolClient(app, {
    platform: 'win32',
    packaged: false,
    defaultApp: true,
    execPath: 'C:\\dev\\electron\\electron.exe',
    appPath: 'C:\\dev\\padiem-desktop-shell',
  });
  assert.equal(outcome.registered, true);
  assert.equal(outcome.plan.action, 'register-dev-host');
  assert.equal(calls.length, 1);
  assert.equal(calls[0]!.scheme, 'padiem');
  assert.equal(calls[0]!.path, 'C:\\dev\\electron\\electron.exe');
  assert.deepEqual(calls[0]!.args, ['C:\\dev\\padiem-desktop-shell']);
});

test('#3093 dev launch without an app path registers nothing (fail closed)', () => {
  const { app, calls } = fakeApp();
  const outcome = registerWindowsProtocolClient(app, {
    platform: 'win32',
    packaged: false,
    defaultApp: true,
    execPath: 'C:\\dev\\electron\\electron.exe',
    appPath: '',
  });
  assert.equal(outcome.registered, false);
  assert.equal(outcome.plan.action, 'skip-dev-without-app-path');
  assert.equal(calls.length, 0);
});

test('#3093 non-Windows platforms register nothing', () => {
  for (const platform of ['darwin', 'linux', 'freebsd'] as const) {
    const { app, calls } = fakeApp();
    const outcome = registerWindowsProtocolClient(app, {
      platform,
      packaged: true,
      defaultApp: false,
      execPath: '/usr/bin/padiem',
      appPath: '/usr/lib/padiem',
    });
    assert.equal(outcome.registered, false, platform);
    assert.equal(outcome.plan.action, 'skip-not-windows', platform);
    assert.equal(calls.length, 0, platform);
  }
});

test('#3093 a rejected registration is reported truthfully, never upgraded to success', () => {
  const { app } = fakeApp(false);
  const outcome = registerWindowsProtocolClient(app, {
    platform: 'win32',
    packaged: true,
    defaultApp: false,
    execPath: 'C:\\padiem\\shell.exe',
    appPath: 'C:\\padiem\\app',
  });
  assert.equal(outcome.registered, false);
  assert.equal(outcome.plan.action, 'register-direct');
});

test('#3093 plan is pure: same input yields the same decision with no side effects', () => {
  const input = {
    platform: 'win32' as const,
    packaged: false,
    defaultApp: true,
    execPath: 'C:\\e\\electron.exe',
    appPath: 'C:\\app',
  };
  const a = windowsProtocolRegistrationPlan(input);
  const b = windowsProtocolRegistrationPlan(input);
  assert.deepEqual(a, b);
});
