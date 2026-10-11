/**
 * CLAW2 #3152 — real-Windows evidence for the supported per-user uninstall.
 *
 * The defect (CLAW3, PR #3146) was a packaging defect, so the evidence has to
 * be a packaging run: a real fresh per-user install of the built NSIS setup,
 * then the real installed uninstaller, then the four facts the issue names.
 * Nothing here is stubbed - the installer and uninstaller are the shipped
 * artifacts, and the registry and filesystem are this machine's own.
 *
 * The supported invocation for this configuration (`oneClick: false`,
 * `perMachine: false`) is the uninstaller the install drops next to the app:
 *
 *     %LOCALAPPDATA%\Programs\<install dir>\Uninstall <product>.exe
 *
 * `/S` is additionally honoured by the builder's own uninstaller script, which
 * parses the flag and switches itself to silent mode, so the silent variant
 * below is the same supported path in a non-interactive form.
 *
 * Path is load-bearing for this defect: the change manipulates `$INSTDIR` and
 * self-removal / current-directory behaviour, so the ACCEPTANCE-OWNER run
 * launches the installed uninstaller directly, at the path the install itself
 * registered, and lets the generated uninstaller perform any internal
 * self-copy behaviour itself. A byte-identical TEMP copy is recorded only as
 * SUPPLEMENTAL comparison evidence; it is never the acceptance owner.
 *
 * The install directory is discovered, never assumed: the authoritative
 * answer is the path the installer itself wrote into the per-user `padiem://`
 * handler. Hardcoding a directory name would measure this harness's assumption
 * instead of the product.
 *
 * Ownership evidence is tri-state. Without elevation the HKLM decoy cannot be
 * created, and that case is reported as NOT_MEASURED - never PASS. The static
 * contract that the uninstall macro contains no HKLM operation lives in
 * `tests/packaging-uninstall-cleanup-3152.test.ts`.
 *
 * The script leaves no residue: everything it creates is either the install it
 * measures or a decoy it removes itself.
 */

import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const productName = 'Padiem Desktop Shell';
const schemeKey = 'HKCU\\Software\\Classes\\padiem';
const programsDir = path.join(os.homedir(), 'AppData', 'Local', 'Programs');
const desktopShortcut = path.join(os.homedir(), 'Desktop', `${productName}.lnk`);
const startMenuPrograms = path.join(
  os.homedir(),
  'AppData',
  'Roaming',
  'Microsoft',
  'Windows',
  'Start Menu',
  'Programs',
);
const uninstallKeyRoot = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall';

// Registrations this installer does not own. If either disappears across
// install + uninstall, the cleanup has overreached.
const decoyMachineKey = 'HKLM\\Software\\PadiemUninstallDecoy3152';
const decoyUserClass = 'HKCU\\Software\\Classes\\unrelateddecoy3152';
// A machine-wide registration this install would only ever *read*. Captured
// read-only before/after; never written, never required to exist.
const machinePadiemKey = 'HKLM\\Software\\Classes\\padiem';

const results = [];

/**
 * Record a result. `state` is one of PASS, FAIL, NOT_MEASURED - three distinct
 * values, because "we could not measure this" is not the same claim as "this
 * held". NOT_MEASURED must never be reported as PASS.
 */
function record(name, state, detail = '') {
  results.push({ name, state, detail });
  process.stdout.write(`${state}  ${name}${detail ? `  [${detail}]` : ''}\n`);
}

function check(name, condition, detail = '') {
  record(name, condition ? 'PASS' : 'FAIL', condition ? '' : detail);
}

function checkNotMeasured(name, detail = '') {
  record(name, 'NOT_MEASURED', detail);
}

function reg(args) {
  return spawnSync('reg', args, { encoding: 'utf8', windowsHide: true });
}
const regQuery = (key) => reg(['query', key]).status === 0;
const regAdd = (key, name, value) => reg(['add', key, '/v', name, '/t', 'REG_SZ', '/d', value, '/f']);
const regDelete = (key) => reg(['delete', key, '/f']);

function regValue(key) {
  const result = reg(['query', key, '/ve']);
  if (result.status !== 0) return null;
  const match = /REG_SZ\s+(.+)/.exec(result.stdout || '');
  return match ? match[1].trim() : null;
}

function executableFromCommand(command) {
  return command.replace(/"%1"\s*$/, '').replace(/^"|"$/g, '');
}

function fileHash(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

/** The directory this install registered for the current user. */
function discoverInstallDir() {
  const command = regValue(`${schemeKey}\\shell\\open\\command`);
  if (command) {
    const found = path.dirname(executableFromCommand(command));
    if (found && existsSync(found)) return found;
  }
  for (const entry of readdirSync(programsDir, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const candidate = path.join(programsDir, entry.name, `Uninstall ${productName}.exe`);
    if (existsSync(candidate)) return path.dirname(candidate);
  }
  return '';
}

/**
 * The per-user uninstall registration, found by the display name it wrote.
 *
 * The key name is not predictable: this builder writes the primary key
 * (`...\Uninstall\<appId>`) and, when that differs from a generated GUID key,
 * a second one as well. `reg query /f` cannot map a matched value back to its
 * key reliably, so the key name is enumerated instead.
 */
function findUninstallEntry() {
  // Forward slashes keep this script free of escape handling; the registry
  // provider accepts them, and the returned key name is joined onto the
  // already-correct `uninstallKeyRoot` for the `reg` checks below.
  const providerPath = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall';
  const script =
    'Get-ChildItem ' + providerPath +
    ' | ForEach-Object { $p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue; ' +
    "if ($p.DisplayName -like '*" + productName + "*') { $_.PSChildName } }";
  const result = spawnSync(
    'powershell',
    ['-NoProfile', '-Command', script],
    { encoding: 'utf8', windowsHide: true },
  );
  const key = (result.stdout || '')
    .split(String.fromCharCode(10))
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return key ? [uninstallKeyRoot, key].join(String.fromCharCode(92)) : '';
}

/** The start-menu entry this install created, whether or not it is a folder. */
function startMenuShortcutExists() {
  if (existsSync(path.join(startMenuPrograms, `${productName}.lnk`))) return true;
  if (!existsSync(path.join(startMenuPrograms, productName))) return false;
  return readdirSync(path.join(startMenuPrograms, productName)).length > 0;
}

/** True when anything this install created remains under the Start menu. */
function startMenuResidue() {
  if (existsSync(path.join(startMenuPrograms, `${productName}.lnk`))) return true;
  if (existsSync(path.join(startMenuPrograms, productName))) return true;
  return false;
}

function runCommand(command, args, { timeoutMs = 600_000 } = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    const timer = setTimeout(() => child.kill(), timeoutMs);
    child.on('close', (code) => { clearTimeout(timer); resolve({ code }); });
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitFor(predicate, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (predicate()) return true;
    if (Date.now() > deadline) {
      process.stdout.write(`  (timed out waiting for ${what})\n`);
      return false;
    }
    await sleep(500);
  }
}

const setup = path.join(appRoot, 'dist-package', `${productName}-0.1.0-x64-setup.exe`);
let installDir = '';
let uninstaller = '';
let uninstallEntry = '';

try {
  check('BUILT_INSTALLER_PRESENT', existsSync(setup), setup);

  // A fresh install means no previous install. This is a registry key, so it
  // must be probed with `regQuery` - `existsSync` on a registry path is always
  // false and would silently skip the baseline cleanup.
  if (regQuery(schemeKey)) {
    const stale = regValue(`${schemeKey}\\shell\\open\\command`);
    if (stale) {
      const dir = path.dirname(executableFromCommand(stale));
      const exe = path.join(dir, `Uninstall ${productName}.exe`);
      if (existsSync(exe)) {
        process.stdout.write(`removing a pre-existing install at ${dir} before measuring a fresh one\n`);
        // Same supported path as the measured uninstall: the installed
        // uninstaller, launched directly at its installed location.
        await runCommand(exe, ['/S']);
        await waitFor(() => !existsSync(dir), 120_000, 'pre-existing uninstall');
      }
    }
    regDelete(schemeKey);
  }
  check('FRESH_BASELINE_NO_PROTOCOL_HANDLER', !regQuery(schemeKey));

  // Decoys first, so an overreaching uninstall is caught rather than assumed.
  const machineDecoyCreated = regAdd(decoyMachineKey, 'Owner', 'machine-wide, not this installer').status === 0;
  regAdd(decoyUserClass, '', 'unrelated scheme, not this installer');
  if (!machineDecoyCreated) {
    process.stdout.write('note: HKLM decoy needs elevation and was not created; that machine-wide decoy is reported NOT_MEASURED, and the machine-wide boundary is additionally covered by the source contract' + String.fromCharCode(10));
  }

  // Additional machine-wide evidence that needs no elevation: the presence of
  // any pre-existing HKLM `padiem` registration, captured read-only. If the
  // uninstall touched the machine hive, before and after would disagree.
  const machinePadiemBefore = regQuery(machinePadiemKey);

  // ---- supported per-user install -------------------------------------
  const customDir = process.env.PADIEM_EVIDENCE_INSTALL_DIR || '';
  const installArgs = customDir ? ['/S', `/D=${customDir}`] : ['/S'];
  const install = await runCommand(setup, installArgs);
  check('FRESH_PER_USER_INSTALL', install.code === 0, `exit=${install.code} args=${installArgs.join(' ')}`);
  check(
    'PAYLOAD_PRESENT_AFTER_INSTALL',
    await waitFor(() => {
      installDir = discoverInstallDir();
      uninstaller = installDir ? path.join(installDir, `Uninstall ${productName}.exe`) : '';
      return Boolean(uninstaller) && existsSync(uninstaller);
    }, 180_000, 'installed payload'),
    installDir,
  );
  if (process.env.PADIEM_EVIDENCE_INSTALL_TWICE === '1') {
    // CLAW3's repro ran against an install directory that already existed
    // (their first repro left one behind), so the second install is an update
    // over a live payload. That is the condition under which the default
    // removal can take a different path.
    process.stdout.write('re-installing over the existing payload (update condition)' + String.fromCharCode(10));
    const second = await runCommand(setup, installArgs);
    check('REINSTALL_OVER_EXISTING_PAYLOAD', second.code === 0, `exit=${second.code}`);
    await sleep(10_000);
  }
  uninstallEntry = findUninstallEntry();
  process.stdout.write(`install dir: ${installDir}\nuninstall entry: ${uninstallEntry || '(none)'}\n`);

  const ready = await waitFor(
    () => regQuery(uninstallEntry) && existsSync(desktopShortcut) && startMenuShortcutExists(),
    120_000,
    'shortcuts and uninstall entry',
  );
  check('INSTALL_COMPLETES_ALL_FOUR_FACTS', ready);
  check('INSTALL_WRITES_PROTOCOL_HANDLER', regQuery(schemeKey));
  check('INSTALL_WRITES_DESKTOP_SHORTCUT', existsSync(desktopShortcut));
  check('INSTALL_WRITES_START_MENU_SHORTCUT', startMenuShortcutExists());
  check('INSTALL_WRITES_UNINSTALL_ENTRY', regQuery(uninstallEntry));

  // ---- supported per-user uninstall -----------------------------------
  // Supplemental comparison only: prove the binary the supported path runs is
  // byte-identical to the installed file. Recorded before the run, because the
  // uninstaller removes itself. This is NOT the acceptance owner.
  const supplementalCopy = path.join(os.tmpdir(), 'padiem-uninstall-evidence.exe');
  rmSync(supplementalCopy, { force: true });
  let copyByteIdentical = false;
  try {
    copyFileSync(uninstaller, supplementalCopy);
    copyByteIdentical = fileHash(uninstaller) === fileHash(supplementalCopy);
  } catch {
    copyByteIdentical = false;
  }
  check('TEMP_COPY_BYTE_IDENTICAL_SUPPLEMENTAL', copyByteIdentical, supplementalCopy);
  rmSync(supplementalCopy, { force: true });

  // ACCEPTANCE OWNER: launch the INSTALLED uninstaller directly, at the path
  // the install itself registered, and let it perform its own internal
  // self-copy. Location is load-bearing for this defect, so this - not a
  // relocated copy - is what the four cleanup facts are measured against.
  process.stdout.write(`launching installed uninstaller directly: ${uninstaller}\n`);
  const uninstall = await runCommand(uninstaller, ['/S']);
  check('UNINSTALL_SUPPORTED_PATH', uninstall.code === 0, `exit=${uninstall.code}`);

  check(
    'INSTALLED_PAYLOAD_AFTER_UNINSTALL=0',
    await waitFor(() => installDir !== '' && !existsSync(installDir), 180_000, 'payload removal'),
    installDir,
  );
  check('HKCU_PADIEM_HANDLER_AFTER_UNINSTALL=0', !regQuery(schemeKey));
  check('DESKTOP_SHORTCUT_AFTER_UNINSTALL=0', !existsSync(desktopShortcut));
  await waitFor(() => !startMenuResidue(), 30_000, 'start menu residue');
  check('START_MENU_SHORTCUT_AFTER_UNINSTALL=0', !startMenuResidue());
  check('HKCU_UNINSTALL_ENTRY_AFTER_UNINSTALL=0', !regQuery(uninstallEntry));

  // ---- ownership boundary --------------------------------------------
  // Tri-state: a created HKLM decoy is measured; without elevation the decoy
  // could not be created, so that specific comparison is NOT_MEASURED - never
  // reported as PASS.
  if (machineDecoyCreated) {
    check('UNRELATED_HKLM_REGISTRATION_TOUCHED=0', regQuery(decoyMachineKey));
  } else {
    checkNotMeasured(
      'UNRELATED_HKLM_REGISTRATION_TOUCHED',
      'HKLM decoy not created without elevation; static no-HKLM contract asserted in tests/packaging-uninstall-cleanup-3152.test.ts',
    );
  }
  // Read-only machine-wide sentinel comparison (no elevation, no mutation).
  const machinePadiemAfter = regQuery(machinePadiemKey);
  check(
    'MACHINE_WIDE_PADIEM_SENTINEL_UNCHANGED=1',
    machinePadiemBefore === machinePadiemAfter,
    `before=${machinePadiemBefore} after=${machinePadiemAfter}`,
  );
  check('UNRELATED_DEV_HOST_REGISTRATION_TOUCHED=0', regQuery(decoyUserClass));
} finally {
  regDelete(decoyMachineKey);
  regDelete(decoyUserClass);
}

const passes = results.filter((entry) => entry.state === 'PASS').length;
const failures = results.filter((entry) => entry.state === 'FAIL').length;
const notMeasured = results.filter((entry) => entry.state === 'NOT_MEASURED').length;
process.stdout.write(
  '\nSUMMARY total=' + String(results.length) +
  ' ok=' + String(passes) +
  ' fail=' + String(failures) +
  ' not_measured=' + String(notMeasured) + '\n',
);
process.exit(failures === 0 ? 0 : 1);
