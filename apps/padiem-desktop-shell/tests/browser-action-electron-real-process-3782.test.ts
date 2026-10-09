/**
 * Opt-in G3 probe with the REAL Windows Electron binary and Chromium CDP.
 * No customer profile, external site, real P01, Broker or production activation.
 * CI without an explicitly installed Electron binary reports SKIPPED, not PASS.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

const binary = process.env['PADIEM_TEST_ELECTRON_EXE'] || '';
const enabled = process.platform === 'win32'
  && path.isAbsolute(binary)
  && path.basename(binary).toLowerCase() === 'electron.exe'
  && existsSync(binary);

test('real isolated Windows Electron AX geometry -> bounded CDP click changes local page', {
  skip: enabled ? undefined : 'Requires explicit PADIEM_TEST_ELECTRON_EXE to installed Windows Electron binary',
  timeout: 20_000,
}, async () => {
  const profile = mkdtempSync(path.join(os.tmpdir(), 'padiem-browser-3782-'));
  const fixture = path.resolve(process.cwd(), 'tests', 'fixtures', 'electron-browser-action-real-3782.cjs');
  const env = { ...process.env };
  delete env['ELECTRON_RUN_AS_NODE'];
  let output = '';
  let errorText = '';
  try {
    await new Promise<void>((resolve, reject) => {
      const child = spawn(binary, [fixture, '--user-data-dir=' + profile], {
        env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: false, shell: false,
      });
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error('real Electron smoke timed out'));
      }, 12_000);
      child.stdout?.on('data', x => {
        output = (output + x.toString('utf8')).slice(-1200);
      });
      child.stderr?.on('data', x => {
        errorText = (errorText + x.toString('utf8')).slice(-1200);
      });
      child.on('error', error => { clearTimeout(timer); reject(error); });
      child.on('exit', code => {
        clearTimeout(timer);
        code === 0 ? resolve() : reject(
          new Error('real Electron browser process failed (exit ' + code + ')'),
        );
      });
    });
    assert.match(output, /PADIEM_REAL_ELECTRON_BROWSER_TEST=PASS/);
    assert.ok(!output.includes('TOP_SECRET'));
    assert.ok(!errorText.includes('TOP_SECRET'));
  } finally {
    rmSync(profile, { recursive: true, force: true, maxRetries: 2 });
  }
});
