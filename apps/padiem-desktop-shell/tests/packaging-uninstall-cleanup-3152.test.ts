/**
 * CLAW2 #3152 — per-user uninstall cleanup ownership contract.
 *
 * The defect this file exists to prevent was measured twice by CLAW3 on the
 * packaged Windows build (PR #3146): after the supported per-user uninstall,
 * the installed payload directory and `HKCU\Software\Classes\padiem` survived,
 * so a `padiem://` handoff resolved to an executable that no longer existed.
 *
 * Two things are asserted here, and the second one exists because this branch
 * first got it wrong:
 *
 * 1. Ownership. The uninstall must remove the payload, the per-user protocol
 *    handler, its shortcuts and its own uninstall registration, and must not
 *    touch a registration this installer did not create.
 * 2. The hook. `customUnInstallSection` looks like the obvious place for a
 *    "final cleanup" section, and it is a supported electron-builder hook -
 *    but defining it makes the builder add a components page to the uninstaller
 *    (`MUI_UNPAGE_COMPONENTS` + `MUI_COMPONENTSPAGE_NODESC`). Real-Windows
 *    evidence on this branch measured the consequence: the silent uninstaller
 *    ran and removed nothing at all. The sweep therefore lives in
 *    `customUnInstall`, and the absence of the section hook is asserted so a
 *    well-meaning refactor cannot reintroduce that regression.
 *
 * These are source assertions: no packaging run, no registry write, no
 * network. The real-Windows install/uninstall evidence is produced separately
 * by `scripts/windows-uninstall-evidence.mjs`.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
// Tests run from `dist/tests`, so the app root lives two levels up.
const appRoot = path.join(here, '..', '..');

function readAppFile(name: string): string {
  return readFileSync(path.join(appRoot, name), 'utf8');
}

const installer = readAppFile('build/installer.nsh');
const builderConfig = readAppFile('electron-builder.yml');

/** The body of the owned uninstall sweep, without its macro wrapper. */
function cleanupMacro(): string {
  const start = installer.indexOf('!macro customUnInstall\n');
  assert.notEqual(start, -1, 'the owned uninstall sweep macro must exist');
  const end = installer.indexOf('!macroend', start);
  return installer.slice(start, end);
}

test('the per-user install still registers the #3093 protocol handler', () => {
  // Regression guard for #3093: the install half of the deeplink contract is
  // untouched by #3152.
  assert.match(installer, /WriteRegStr HKCU "Software\\Classes\\padiem" "" "URL:Padiem Pairing Handoff"/);
  assert.match(installer, /WriteRegStr HKCU "Software\\Classes\\padiem\\shell\\open\\command"/);
  assert.match(builderConfig, /include: build\/installer\.nsh/);
  assert.match(builderConfig, /- padiem\b/);
  // Per-user install stays per-user: a machine-wide install is a different
  // ownership contract and must not be implied here.
  assert.match(builderConfig, /perMachine: false/);
});

test('the uninstall removes the installed payload', () => {
  const sweep = cleanupMacro();
  assert.match(sweep, /RMDir \/r "\$INSTDIR"/);
  // Removing the current directory is what leaves a half-removed install, so
  // the sweep moves out first.
  assert.match(sweep, /SetOutPath "\$TEMP"[\s\S]*RMDir \/r "\$INSTDIR"/);
});

test('the uninstall removes the HKCU protocol handler the installer wrote', () => {
  assert.match(cleanupMacro(), /DeleteRegKey HKCU "Software\\Classes\\padiem"/);
});

test('the uninstall removes the shortcuts at the paths it created', () => {
  const sweep = cleanupMacro();
  // Resolved by the builder's own `setLinkVars` (a registry read, with the
  // product file name as fallback) rather than from a constant that is only
  // conditionally defined: an unresolved identifier is a build error, not a
  // silently wrong path.
  assert.match(sweep, /!insertmacro setLinkVars/);
  assert.match(sweep, /Delete "\$oldDesktopLink"/);
  assert.match(sweep, /Delete "\$oldStartMenuLink"/);
  assert.match(sweep, /RMDir "\$SMPROGRAMS\\\$oldMenuDirectory"/);
  assert.doesNotMatch(sweep, /APP_PRODUCT_FILENAME/);
});

test('the uninstall removes the per-user uninstall registration', () => {
  const sweep = cleanupMacro();
  assert.match(sweep, /DeleteRegKey HKCU "\$\{UNINSTALL_REGISTRY_KEY\}"/);
});

test('the sweep never touches a registration this installer does not own', () => {
  const sweep = cleanupMacro();
  // No machine-wide hive, ever: an HKLM `padiem` handler (or any HKLM key) is
  // not this installer's to remove.
  assert.doesNotMatch(sweep, /HKLM/);
  assert.doesNotMatch(sweep, /SHELL_CONTEXT all/);
  // No other URL scheme / class key is named.
  const classKeys = [...sweep.matchAll(/Software\\Classes\\([A-Za-z0-9._-]+)/g)].map((match) => match[1]);
  assert.deepEqual([...new Set(classKeys)], ['padiem']);
  // And no sibling installer's uninstall entry is named either.
  const uninstallKeys = [...sweep.matchAll(/\$\{UNINSTALL_REGISTRY_KEY_?2?\}/g)].map((match) => match[0]);
  assert.ok(
    uninstallKeys.every((key) => key === '${UNINSTALL_REGISTRY_KEY}' || key === '${UNINSTALL_REGISTRY_KEY_2}'),
  );
});

test('the uninstaller gains no components page from a custom section hook', () => {
  // The regression this branch measured: defining `customUnInstallSection`
  // makes electron-builder add MUI_UNPAGE_COMPONENTS to the uninstaller, and
  // the supported silent uninstall then removes nothing. The sweep must stay
  // in `customUnInstall`.
  assert.doesNotMatch(installer, /^!macro customUnInstallSection$/m);
  // `customRemoveFiles` would REPLACE the builder's default removal sequence
  // rather than run alongside it; the sweep must not do that either.
  assert.doesNotMatch(installer, /^!macro customRemoveFiles$/m);
  assert.match(installer, /^!macro customUnInstall$/m);
});
