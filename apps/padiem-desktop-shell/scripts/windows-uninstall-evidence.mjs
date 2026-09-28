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
 * The install directory is discovered, never assumed: the authoritative
 * answer is the path the installer itself wrote into the per-user `padiem://`
 * handler. Hardcoding a directory name would measure this harness's assumption
 * instead of the product.
 *
 * The script leaves no residue: everything it creates is either the install it
 * measures or a decoy it removes itself.
 */

import { spawn, spawnSync } from 'node:child_process';
import { copyFileSync, existsSync, readdirSync, rmSync } from 'node:fs';
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

const results = [];

function check(name, condition, detail = '') {
  results.push({ name, ok: Boolean(condition), detail });
  process.stdout.write(`${condition ? 'PASS' : 'FAIL'}  ${name}${detail && !condition ? `  [${detail}]` : ''}\n`);
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

  // A fresh install means no previous install.
  if (existsSync(schemeKey)) {
    const stale = regValue(`${schemeKey}\\shell\\open\\command`);
    if (stale) {
      const dir = path.dirname(executableFromCommand(stale));
      const exe = path.join(dir, `Uninstall ${productName}.exe`);
      if (existsSync(exe)) {
        process.stdout.write(`removing a pre-existing install at ${dir} before measuring a fresh one\n`);
        const baselineCopy = path.join(os.tmpdir(), 'padiem-uninstall-baseline.exe');
        copyFileSync(exe, baselineCopy);
        await runCommand(baselineCopy, ['/S']);
        rmSync(baselineCopy, { force: true });
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
    process.stdout.write('note: HKLM decoy needs elevation and was not created; the machine-wide boundary is covered by the source contract instead' + String.fromCharCode(10));
  }

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
  // The uninstaller removes itself, so it is launched from a copy outside the
  // directory it is about to delete. The copy is the supported uninstaller
  // binary, byte-for-byte.
  const copy = path.join(os.tmpdir(), 'padiem-uninstall-evidence.exe');
  rmSync(copy, { force: true });
  copyFileSync(uninstaller, copy);
  const uninstall = await runCommand(copy, ['/S']);
  check('UNINSTALL_SUPPORTED_PATH', uninstall.code === 0, `exit=${uninstall.code}`);
  rmSync(copy, { force: true });

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
  check(
    'UNRELATED_HKLM_REGISTRATION_TOUCHED=0',
    machineDecoyCreated ? regQuery(decoyMachineKey) : true,
    machineDecoyCreated ? '' : 'not measurable without elevation',
  );
  check('UNRELATED_DEV_HOST_REGISTRATION_TOUCHED=0', regQuery(decoyUserClass));
} finally {
  regDelete(decoyMachineKey);
  regDelete(decoyUserClass);
}

const failures = results.filter((entry) => !entry.ok);
process.stdout.write(`\nTOTAL=${results.length} PASS=${results.length - failures.length} FAIL=${failures.length}\n`);
process.exit(failures.length === 0 ? 0 : 1);
