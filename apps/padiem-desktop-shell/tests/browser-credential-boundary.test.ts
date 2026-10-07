/**
 * #3611 — negative guard: Padiem Desktop must not acquire ZCode-style browser
 * credential/profile authority.
 *
 * This is a tripwire, not a proof of absence. It fails loudly when a future edit
 * introduces a real browser profile/cookie/credential path, a second browser
 * authority, or a browser-control channel, instead of relying on review.
 *
 * Fail-closed rules:
 *   - an empty or missing scan root is a failure, never a silent pass;
 *   - the guard file itself is the only exclusion, and the exclusion is asserted,
 *     so the guard cannot be silenced by widening the exclusion;
 *   - the ownership rule (below) survives renames of individual APIs.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '..', '..', '..', '..');

const SCAN_ROOTS = [
  path.join(repoRoot, 'apps', 'padiem-desktop-shell', 'src'),
  path.join(repoRoot, 'apps', 'padiem-desktop-shell', 'tests'),
  path.join(repoRoot, 'apps', 'korean-ai-code-agent', 'src'),
];

/**
 * Exactly this file may contain the forbidden literals (it defines them).
 *
 * The pointer is the guard's *source* file on purpose: `node --test` runs the
 * compiled copy in `dist/tests`, so `import.meta.url` would resolve to a path the
 * scan never visits and the exclusion would silently exclude nothing.
 */
const SCAN_EXCLUSION_PATH = path.join(
  repoRoot,
  'apps',
  'padiem-desktop-shell',
  'tests',
  'browser-credential-boundary.test.ts',
);
const SCAN_EXCLUSION = [path.normalize(SCAN_EXCLUSION_PATH)];

/**
 * Credential/profile authority that must never appear in Desktop or kagent
 * source. Patterns are literal identifier fragments, matched against
 * comment-stripped executable code only.
 */
const FORBIDDEN_CREDENTIAL_PATTERNS: ReadonlyArray<{ pattern: RegExp; why: string }> = [
  { pattern: /chromeCookieManager/i, why: 'Chrome cookie import helper' },
  { pattern: /chromeLocalStorageManager/i, why: 'Chrome LocalStorage import helper' },
  { pattern: /chromeCredentialManager/i, why: 'Chrome credential/decryption helper' },
  { pattern: /chromeProfileDiscovery/i, why: 'Chrome profile discovery' },
  { pattern: /chromeExecutableDiscovery/i, why: 'Chrome installation discovery' },
  { pattern: /windowsChromeAppBoundKey/i, why: 'app-bound key decryption helper' },
  { pattern: /allowElevatedChromeDecryption/i, why: 'elevated browser decryption switch' },
  { pattern: /ImportChromeBrowserData/i, why: 'browser data import channel' },
  { pattern: /ClearEmbeddedBrowserData/i, why: 'embedded browser data channel' },
  { pattern: /os_crypt/i, why: 'platform credential cryptography' },
  { pattern: /\bLocal State\b/, why: 'Chrome key material file' },
  { pattern: /\bLogin Data\b/, why: 'browser password store file' },
  { pattern: /cookies\.sqlite/i, why: 'browser cookie database' },
  { pattern: /persist:/i, why: 'persistent browser partition/session identifier' },
  { pattern: /claimTab/i, why: 'claiming an existing user tab/session' },
  { pattern: /executeJavaScript/i, why: 'page content/script extraction primitive' },
  { pattern: /capturePage/i, why: 'page capture primitive' },
  { pattern: /printToPDF/i, why: 'page export primitive' },
];

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^[ \t]*\/\/.*$/gm, '');
}

/** Entries of `export const NAME = Object.freeze([ ... ] as const);` in TS source. */
function frozenArrayEntries(source: string, constant: string): string[] {
  const match = new RegExp(
    `export const ${constant} = Object\\.freeze\\(\\[([\\s\\S]*?)\\] as const\\);`,
  ).exec(source);
  assert.notEqual(match, null, `missing frozen field-set literal: ${constant}`);
  return [...match![1]!.matchAll(/'([^']*)'/g)].map((entry) => entry[1]!);
}

/** Entries of `NAME = frozenset({ ... })` in Python source. */
function pythonFrozenSetEntries(source: string, constant: string): string[] {
  const match = new RegExp(`${constant} = frozenset\\(([\\s\\S]*?)\\n\\)`).exec(source);
  assert.notEqual(match, null, `missing frozenset literal: ${constant}`);
  return [...match![1]!.matchAll(/"([^"]*)"/g)].map((entry) => entry[1]!);
}

/** Page-derived field names, lower-cased for comparison against declared field sets. */
const PAGE_DERIVED_NAMES = [
  'title',
  'pagetitle',
  'text',
  'body',
  'html',
  'source',
  'dom',
  'snapshot',
  'screenshot',
  'image',
  'pdf',
  'dialogtext',
  'formvalues',
  'values',
  'attributes',
  'cookies',
  'localstorage',
  'sessionstorage',
  'headers',
];

function collectSourceFiles(root: string): string[] {
  const found: string[] = [];
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const full = path.join(directory, entry);
      if (statSync(full).isDirectory()) {
        if (entry === 'node_modules' || entry === 'dist') continue;
        walk(full);
        continue;
      }
      if (/\.(ts|tsx|cts|mts|js|mjs|cjs|py)$/.test(entry)) found.push(full);
    }
  };
  walk(root);
  return found;
}

test('#3611 every scan root exists (an empty scan is a failure, not a pass)', () => {
  for (const root of SCAN_ROOTS) {
    assert.equal(existsSync(root), true, `scan root missing: ${root}`);
    assert.ok(collectSourceFiles(root).length > 0, `scan root is empty: ${root}`);
  }
});

test('#3611 the only source excluded from the credential scan is this guard file', () => {
  assert.equal(SCAN_EXCLUSION.length, 1);
  assert.equal(SCAN_EXCLUSION[0], path.normalize(SCAN_EXCLUSION_PATH));
  // The exclusion must be this file and it must sit in the scanned tests root, so
  // it cannot be widened to silence the guard.
  assert.equal(
    path.normalize(path.dirname(SCAN_EXCLUSION_PATH)),
    path.normalize(path.join(repoRoot, 'apps', 'padiem-desktop-shell', 'tests')),
  );
  assert.equal(
    path.basename(SCAN_EXCLUSION_PATH),
    path.basename(fileURLToPath(import.meta.url)).replace(/\.js$/, '.ts'),
    'the excluded source must be this guard file',
  );
  for (const root of SCAN_ROOTS) {
    for (const file of collectSourceFiles(root)) {
      if (path.normalize(file) === SCAN_EXCLUSION[0]) continue;
      assert.equal(
        FORBIDDEN_CREDENTIAL_PATTERNS.some((entry) => entry.pattern.test(stripComments(readFileSync(file, 'utf8')))),
        false,
        `credential/profile authority pattern found in ${file}`,
      );
    }
  }
});

test('#3611 only the browser-open electron binding may touch browser/session APIs', () => {
  const allowedBinding = path.join(
    repoRoot,
    'apps',
    'padiem-desktop-shell',
    'src',
    'browser',
    'browser-open-electron-view.ts',
  );
  const ownershipPatterns = [
    /BrowserWindow/,
    /WebContentsView/,
    /BrowserView/,
    /setPermissionRequestHandler/,
    /will-download/,
    /webContents\.session/,
    /partition:/,
  ];
  const desktopSource = path.join(repoRoot, 'apps', 'padiem-desktop-shell', 'src');
  let checked = 0;
  const walk = (directory: string): void => {
    for (const entry of readdirSync(directory)) {
      const full = path.join(directory, entry);
      if (statSync(full).isDirectory()) {
        if (entry === 'node_modules' || entry === 'dist') continue;
        walk(full);
        continue;
      }
      if (!/\.(ts|tsx|cts)$/.test(entry)) continue;
      if (path.normalize(full) === path.normalize(allowedBinding)) continue;
      // The shell window in main.ts predates #3611 and keeps its own guards; the
      // ownership rule here is about the *browser* APIs this slice introduces.
      if (path.normalize(full) === path.join(desktopSource, 'main', 'main.ts')) continue;
      checked += 1;
      const code = stripComments(readFileSync(full, 'utf8'));
      for (const pattern of ownershipPatterns) {
        assert.equal(pattern.test(code), false, `${full} must not reference browser API ${pattern}`);
      }
    }
  };
  walk(desktopSource);
  assert.ok(checked > 10, 'the ownership rule must actually scan the desktop sources');

  const binding = stripComments(readFileSync(allowedBinding, 'utf8'));
  assert.match(binding, /partition: ephemeralPartitionName\(\)/);
  assert.equal(/persist:/i.test(binding), false, 'the binding must never use a persistent partition');
});

test('#3611 no page-derived field can reach a browser-open request or receipt', () => {
  const contractsSource = readFileSync(
    path.join(repoRoot, 'apps', 'padiem-desktop-shell', 'src', 'browser', 'browser-open-contracts.ts'),
    'utf8',
  );
  const pythonSource = readFileSync(
    path.join(repoRoot, 'apps', 'korean-ai-code-agent', 'src', 'kagent', 'browser_open.py'),
    'utf8',
  );

  // The declared field sets are the enforcement point: a page-derived field can
  // only reach a caller by being declared here, so an entry that names page
  // content is the failure this test exists to catch.
  const declaredSets: ReadonlyArray<readonly [string, string[]]> = [
    ['APPROVED_BROWSER_OPEN_REQUEST_KEYS', frozenArrayEntries(contractsSource, 'APPROVED_BROWSER_OPEN_REQUEST_KEYS')],
    ['BROWSER_OPEN_RECEIPT_FIELDS', frozenArrayEntries(contractsSource, 'BROWSER_OPEN_RECEIPT_FIELDS')],
    ['BROWSER_OPEN_RECEIPT_DECLARED_FIELDS', pythonFrozenSetEntries(pythonSource, 'BROWSER_OPEN_RECEIPT_DECLARED_FIELDS')],
  ];
  assert.ok(declaredSets[0]![1].length >= 15, 'the request key set must be fully parsed');
  assert.ok(declaredSets[1]![1].length >= 20, 'the receipt field set must be fully parsed');
  assert.ok(declaredSets[2]![1].length >= 17, 'the Python receipt field set must be fully parsed');
  for (const [name, fields] of declaredSets) {
    for (const field of fields) {
      assert.equal(
        PAGE_DERIVED_NAMES.includes(field.toLowerCase()),
        false,
        `${name} must not carry page-derived field ${field}`,
      );
    }
  }

  // Both denial manifests must stay explicit, and must keep agreeing on the
  // names that matter, so a future edit cannot quietly shrink either one.
  const tsManifest = frozenArrayEntries(contractsSource, 'BROWSER_OPEN_FORBIDDEN_PAGE_DERIVED_KEYS');
  const pythonManifest = pythonFrozenSetEntries(pythonSource, '_FORBIDDEN_PAGE_DERIVED_FIELDS');
  assert.ok(tsManifest.length >= 10, 'the TypeScript denial manifest must stay explicit');
  assert.ok(pythonManifest.length >= 10, 'the Python denial manifest must stay explicit');
  for (const shared of ['title', 'html', 'dom', 'screenshot', 'pdf', 'cookies']) {
    assert.ok(tsManifest.includes(shared), `the TypeScript denial manifest must keep listing ${shared}`);
    assert.ok(pythonManifest.includes(shared), `the Python denial manifest must keep listing ${shared}`);
  }

  // Extraction primitives are never legitimate, in any position, in either
  // implementation.
  for (const forbidden of [
    ['execute', 'JavaScript'].join(''),
    ['capture', 'Page'].join(''),
    ['print', 'ToPDF'].join(''),
  ]) {
    assert.equal(contractsSource.includes(forbidden), false, `contracts must not offer ${forbidden}`);
    assert.equal(pythonSource.includes(forbidden), false, `kagent contract must not offer ${forbidden}`);
  }
  assert.match(pythonSource, /BROWSER_OPEN_PAGE_DERIVED_BYTES = 0/);
  assert.match(pythonSource, /BROWSER_CONTROL_IMPLEMENTED = False/);
});
