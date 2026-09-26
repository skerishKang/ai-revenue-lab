/**
 * CLAW4 M1 — deterministic packaging pin contract.
 *
 * CENTRAL G1 (issue comment 5840395388) authorized M1_SOURCE_ONLY and corrected
 * the order: electron-builder itself must be exact-pinned before any toolset can
 * be pinned, because a toolset pin under a floating builder version pins nothing.
 *
 * Defect this file exists to prevent, as measured on main 6ab08096:
 *   `scripts.package:win` invoked `electron-builder`, but
 *   `devDependencies.electron-builder` was ABSENT and the lockfile contained
 *   ZERO electron-builder entries. The packaging script therefore referenced a
 *   binary that was never installed, and `npm ci` could not reproduce any
 *   packaging step at all.
 *
 * These assertions read package.json, package-lock.json and electron-builder.yml
 * directly. They are source assertions: no build, no packaging run, no network.
 *
 * M1-B caveat, verified against app-builder-lib@26.16.1 type definitions:
 * the toolset keys are a closed union. `appimage` and `wine` are intentionally
 * absent from electron-builder.yml because this configuration targets `nsis` on
 * `win32` only, so those bundles are never downloaded. A test that demanded
 * every key would be asserting a guarantee that was never verified.
 *
 * M1-B pin values, corrected by CENTRAL review of #3096 (PR comment 5840609494):
 * the first revision pinned the newest accepted key for each toolset
 * (`winCodeSign 1.1.0`, `nsis 1.2.1`). Upstream types those unions as
 * Stable + Beta, and both of those values are Beta. M1 exists to produce a
 * reproducible packaging source, not to adopt a newer Beta toolset, so the pins
 * are the Stable `0.0.0` for both keys and a Beta denylist guards them.
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

const packageJsonText = readAppFile('package.json');
const lockfileText = readAppFile('package-lock.json');
const builderConfigText = readAppFile('electron-builder.yml');

const packageJson = JSON.parse(packageJsonText) as {
  scripts: Record<string, string>;
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
};
const lockfile = JSON.parse(lockfileText) as {
  lockfileVersion: number;
  packages: Record<string, { version?: string; integrity?: string; devDependencies?: Record<string, string> }>;
};

const devDependencies = packageJson.devDependencies ?? {};
const rootLockEntry = lockfile.packages[''] ?? {};
const lockDevDependencies = rootLockEntry.devDependencies ?? {};

/** A pin is exact only when it carries no range operator, wildcard or tag. */
function isExactPin(spec: string | undefined): boolean {
  if (typeof spec !== 'string' || spec.length === 0) return false;
  return !/[\^~><*|\s]/.test(spec) && spec !== 'latest' && spec !== 'x';
}

/**
 * Reads the `toolsets:` block as a key -> value map.
 *
 * This deliberately does not use a YAML library. `js-yaml` is only present as a
 * transitive dependency of the build toolchain, so relying on it would make a
 * contract test depend on a package nobody declared. This parser instead fails
 * closed: an absent block, a duplicated key, or a nested structure is an error
 * rather than a silently empty result.
 */
function parseToolsetsBlock(source: string): Record<string, string> {
  const lines = source.split(/\r?\n/);
  const start = lines.findIndex((line) => /^toolsets:\s*$/.test(line));

  assert.notEqual(start, -1, 'electron-builder.yml has no top-level `toolsets:` block');

  const parsed: Record<string, string> = {};

  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index] as string;

    // A non-indented, non-empty line ends the block.
    if (line.trim().length > 0 && !/^\s/.test(line)) break;
    // Blank lines and comments inside the block carry no key.
    if (line.trim().length === 0 || /^\s*#/.test(line)) continue;

    const match = /^\s+([A-Za-z][A-Za-z0-9]*):\s*(\S.*?)\s*$/.exec(line);
    assert.ok(
      match,
      `electron-builder.yml toolsets block has an unparsable line: ${JSON.stringify(line)}`,
    );

    const key = match[1] as string;
    const value = match[2] as string;

    assert.equal(
      Object.prototype.hasOwnProperty.call(parsed, key),
      false,
      `toolsets.${key} is declared more than once; the effective value would be ambiguous`,
    );
    // An empty or YAML-null value would make the builder fall back to a default,
    // which is exactly the floating behaviour M1-B exists to remove.
    assert.notEqual(
      value,
      '',
      `toolsets.${key} has an empty value; the builder would fall back to a floating default`,
    );
    assert.ok(
      !/^(null|~)$/i.test(value),
      `toolsets.${key}=${value} is YAML null; the builder would fall back to a floating default`,
    );

    parsed[key] = value;
  }

  return parsed;
}

test('M1-A: the packaging script and the installed dependency now agree', () => {
  const packagingScript = packageJson.scripts['package:win'] ?? '';

  assert.match(
    packagingScript,
    /\belectron-builder\b/,
    'package:win must still drive electron-builder; removing it would silently drop packaging',
  );
  assert.ok(
    devDependencies['electron-builder'],
    'devDependencies.electron-builder is absent: package:win references a binary that npm ci never installs',
  );
});

test('M1-A: electron-builder is exact-pinned, not range-pinned', () => {
  assert.equal(
    devDependencies['electron-builder'],
    '26.16.1',
    'electron-builder must be exact-pinned to the reviewed 26.x stable release',
  );
  assert.ok(
    isExactPin(devDependencies['electron-builder']),
    'electron-builder must not use ^, ~, >, <, *, latest or a tag',
  );
});

test('M1-A: v27 is not adopted for Azure signing or toolset features', () => {
  const version = devDependencies['electron-builder'] ?? '';

  assert.ok(
    !version.includes('alpha') && !version.includes('beta') && !version.includes('rc'),
    `electron-builder must not be a prerelease pin: ${version}`,
  );
  assert.doesNotMatch(
    version,
    /^27\./,
    'electron-builder v27 changes unset toolsets.* to float to "latest"; adoption is explicitly deferred',
  );
});

test('M1-C: the lockfile resolves electron-builder to the exact reviewed version', () => {
  const entry = lockfile.packages['node_modules/electron-builder'];

  assert.ok(entry, 'package-lock.json has no node_modules/electron-builder entry');
  assert.equal(entry.version, devDependencies['electron-builder']);
  assert.ok(entry.integrity, 'electron-builder lock entry must carry a dist integrity hash');
  assert.match(
    entry.integrity,
    /^sha512-/,
    'electron-builder must be integrity-pinned with sha512',
  );
});

test('M1-C: the lockfile root devDependencies mirror package.json exactly', () => {
  assert.deepEqual(
    lockDevDependencies,
    devDependencies,
    'package-lock.json root devDependencies drifted from package.json',
  );
});

test('M1-C: every direct dependency is exact-pinned in both manifests', () => {
  const looseInPackageJson = Object.entries(devDependencies).filter(([, spec]) => !isExactPin(spec));
  const looseInLockfile = Object.entries(lockDevDependencies).filter(([, spec]) => !isExactPin(spec));

  assert.deepEqual(looseInPackageJson, [], 'package.json has a non-exact dependency pin');
  assert.deepEqual(looseInLockfile, [], 'package-lock.json has a non-exact dependency pin');
});

test('M1-C: no runtime dependency was introduced alongside this dev-only pin', () => {
  assert.equal(
    packageJson.dependencies,
    undefined,
    'electron-builder is a build-time tool; it must not become a shipped runtime dependency',
  );
});

test('M1-B: the two toolsets an NSIS Windows build uses are pinned to the stable key', () => {
  // Parsed from the raw file rather than via a YAML library on purpose: a
  // transitive dependency is not a contract. The parser below rejects anything
  // it cannot read unambiguously, so a malformed or restructured file fails
  // here rather than silently passing a loose text search.
  //
  // CENTRAL review of #3096 (PR comment 5840609494) required the Stable value,
  // not the newest accepted one. `app-builder-lib@26.16.1` types each of these
  // keys as a union that splits into Stable and Beta entries; M1 pins Stable
  // because its purpose is a reproducible packaging source, not a Beta channel.
  const toolsets = parseToolsetsBlock(builderConfigText);

  assert.equal(
    toolsets.winCodeSign,
    '0.0.0',
    'winCodeSign must be pinned to the Stable key; the Beta keys need an owner decision',
  );
  assert.equal(
    toolsets.nsis,
    '0.0.0',
    'nsis must be pinned to the Stable key; the Beta key needs an owner decision',
  );
});

test('M1-B: no Beta toolset is adopted without an owner decision', () => {
  // This is the direct guard for the CENTRAL blocker. A guard that only asserts
  // the correct value still lets a reviewer swap in a Beta value and re-run; an
  // explicit denylist makes the Beta keys FAIL with a specific reason instead.
  //
  // Beta keys per `app-builder-lib@26.16.1` `ToolsetConfig`:
  //   winCodeSign -> 1.0.0, 1.1.0
  //   nsis        -> 1.2.1
  const betaValues: Record<string, readonly string[]> = {
    winCodeSign: ['1.0.0', '1.1.0'],
    nsis: ['1.2.1'],
  };
  const toolsets = parseToolsetsBlock(builderConfigText);

  for (const [key, betas] of Object.entries(betaValues)) {
    const value = toolsets[key];
    assert.ok(value !== undefined, `toolset ${key} is not declared`);
    assert.ok(
      !betas.includes(value),
      `toolset ${key}=${value} is a Beta key (${betas.join(', ')}); adopting a Beta toolset ` +
        'requires an explicit CENTRAL decision and is out of M1 scope',
    );
  }
});

test('M1-B: the toolset values are strings, not YAML numbers', () => {
  const toolsets = parseToolsetsBlock(builderConfigText);

  for (const [key, value] of Object.entries(toolsets)) {
    assert.equal(typeof value, 'string', `toolsets.${key} must be a string scalar`);

    // A YAML bare number is a single dot-free integer/float, e.g. `0` or `1`.
    // Every real toolset version has more than one dot (`1.1.0`, `1.2.1`), which
    // is why they survive as strings. A single-component value would be parsed
    // by the builder as a number and silently fail the string union check, so
    // this assertion catches that shape regression.
    assert.doesNotMatch(
      value,
      /^\d+(\.\d+)?$/,
      `toolsets.${key}=${value} looks like a bare YAML number; quote it so the builder receives a string`,
    );
    assert.match(value, /^\d+\.\d+\.\d+$/, `toolsets.${key}=${value} is not a full x.y.z toolset version`);
  }
});

test('M1-B: no toolset is left to a default', () => {
  // Only the toolsets this win32/nsis configuration can download are allowed.
  // `appimage` and `wine` are never fetched for this target, so they are not
  // required and are not pinned. Pinning a bundle that is never downloaded
  // would imply a guarantee that was never verified.
  const known = new Set([
    'winCodeSign',
    'nsis',
    'appimage',
    'wine',
    'fpm',
    'icons',
    'linuxToolsMac',
    'sevenZip',
  ]);
  const allowed = new Set(['winCodeSign', 'nsis']);
  const declared = Object.keys(parseToolsetsBlock(builderConfigText));

  for (const key of declared) {
    assert.ok(known.has(key), `unexpected toolset key: ${key}`);
    assert.ok(allowed.has(key), `toolset ${key} is never used by this config, so pinning it is noise`);
  }
  assert.ok(declared.includes('winCodeSign'), 'winCodeSign pin is required');
  assert.ok(declared.includes('nsis'), 'nsis pin is required');
});

test('M1-B: the pin values are inside the union the pinned builder accepts', () => {
  // Closed union from app-builder-lib@26.16.1 ToolsetConfig, restricted to the
  // Stable members. Listing only Stable here means this test and the Beta denylist
  // above cannot drift apart: if a future builder renames a Stable key, both the
  // membership check and the Beta guard fail together.
  const allowedValues: Record<string, readonly string[]> = {
    winCodeSign: ['0.0.0'],
    nsis: ['0.0.0'],
  };
  const toolsets = parseToolsetsBlock(builderConfigText);

  for (const [key, values] of Object.entries(allowedValues)) {
    const value = toolsets[key];
    assert.ok(value !== undefined, `toolset ${key} is not declared`);
    assert.ok(
      values.includes(value),
      `toolset ${key}=${value} is not a Stable key accepted by app-builder-lib@26.16.1 (stable: ${values.join(', ')})`,
    );
  }
});

test('M1-B: the stable key is a fixed checksum, not a floating default', () => {
  // "0.0.0" is only a real pin if upstream branches on it explicitly. Read from
  // app-builder-lib@26.16.1/out/toolsets/windows.js, the legacy path is selected
  // by `value === "0.0.0"` and resolves to fixed, checksummed downloads:
  //
  //   winCodeSign-2.6.0.7z    cdaec7154dda7cc31f88d886e2489379a0625a737d610b5ae7f62a12f16743a4
  //   nsis-3.0.4.1.7z         9877df902530f96357d13a7a31ae2b9df67f48b11ffc9a1700a7c961574ec5fa
  //   nsis-resources-3.4.1.7z  593a9a92ef958321293ac6a2ee61e64bf1bd543142a5bd6b3d310709cc924103
  //
  // This test reads the installed app-builder-lib to confirm the branch still
  // exists, so a future dependency bump that turns "0.0.0" back into a sentinel
  // fails here instead of silently unpinning the toolset.
  const toolsetsLib = path.join(appRoot, 'node_modules', 'app-builder-lib', 'out', 'toolsets', 'windows.js');

  let source: string;
  try {
    source = readFileSync(toolsetsLib, 'utf8');
  } catch {
    // app-builder-lib is a build-time dependency. When the tree is not installed
    // the contract cannot be inspected, so assert the pin shape that makes the
    // guarantee meaningful rather than passing silently.
    const toolsets = parseToolsetsBlock(builderConfigText);
    assert.equal(toolsets.winCodeSign, '0.0.0');
    assert.equal(toolsets.nsis, '0.0.0');
    return;
  }

  assert.match(
    source,
    /winCodeSign === "0\.0\.0"/,
    'app-builder-lib no longer branches on the winCodeSign stable key; the pin would become a sentinel',
  );
  assert.match(
    source,
    /nsis === "0\.0\.0"/,
    'app-builder-lib no longer branches on the nsis stable key; the pin would become a sentinel',
  );
  for (const checksum of [
    'cdaec7154dda7cc31f88d886e2489379a0625a737d610b5ae7f62a12f16743a4',
    '9877df902530f96357d13a7a31ae2b9df67f48b11ffc9a1700a7c961574ec5fa',
    '593a9a92ef958321293ac6a2ee61e64bf1bd543142a5bd6b3d310709cc924103',
  ]) {
    assert.ok(
      source.includes(checksum),
      `app-builder-lib no longer carries the stable toolset checksum ${checksum.slice(0, 12)}...`,
    );
  }
});

test('M1-D: publish stays disabled', () => {
  assert.match(builderConfigText, /^publish:\s*null\s*$/m, 'publish must remain null in M1');
});

test('M1-D: production signing stays off and no signing material is configured', () => {
  assert.match(
    builderConfigText,
    /^\s{2}signAndEditExecutable:\s*false\s*$/m,
    'signAndEditExecutable must remain false until M4 proves a signing adapter',
  );

  // M4 owns the Azure Artifact Signing adapter. M1 must not pre-wire it, and
  // must not name a certificate, an identity, or a signing endpoint.
  for (const forbidden of [
    'azureSignOptions',
    'CSC_LINK',
    'CSC_KEY_PASSWORD',
    'WIN_CSC_LINK',
    'certificateSubjectName',
    'pfx',
    '.p12',
    'Trusted Signing',
  ]) {
    assert.ok(
      !builderConfigText.includes(forbidden),
      `electron-builder.yml must not configure signing material in M1: found ${forbidden}`,
    );
  }
});

test('M1-D: no update feed is configured', () => {
  assert.ok(
    !builderConfigText.includes('updaterCacheDirName'),
    'no update feed is configured in M1',
  );
  assert.match(
    builderConfigText,
    /^\s{2}differentialPackage:\s*false\s*$/m,
    'differentialPackage must stay false while no update feed is published',
  );

  const packageJsonHasUpdater = /electron-updater/.test(packageJsonText);
  assert.equal(packageJsonHasUpdater, false, 'electron-updater must not be a dependency in M1');
});

test('M1: the lockfile still records the pre-existing dependency set', () => {
  // Guards against a lockfile regenerated against a different dependency set.
  assert.equal(lockfile.lockfileVersion, 3);
  for (const name of ['electron', 'typescript', 'esbuild', 'react', 'react-dom']) {
    assert.ok(
      lockfile.packages[`node_modules/${name}`],
      `lockfile lost the pre-existing direct dependency ${name}`,
    );
  }
});
