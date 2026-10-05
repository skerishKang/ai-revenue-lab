/**
 * CLAW5 #3157 · CLAW1 #3165 — compile the renderer modules and their tests for the test suite.
 *
 * The production build bundles the renderer into one file and removes the
 * per-module output, so a test that exercises the real i18n / preference / view
 * modules needs them compiled somewhere that is neither bundled nor packaged.
 * `dist/tests/renderer` is that place, and `dist/tests` is where the existing
 * `node --test dist/tests/*.test.js` step already looks.
 *
 * Two passes, in this order on purpose: the renderer modules must exist before
 * a test can resolve its relative imports of them.
 *
 *   pass 1  src/renderer/*  -> dist/tests/renderer/*
 *   pass 2  tests/desktop-settings-3157.test.ts and tests/desktop-easy-mode-3165.test.ts -> dist/tests/*
 */

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import ts from 'typescript';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const checkOnly = process.argv.includes('--check');

const configPath = path.join(root, 'tsconfig.json');
const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
if (configFile.error) {
  throw new Error(ts.flattenDiagnosticMessageText(configFile.error.messageText, '\n'));
}

function compile(files, overrides) {
  const parsed = ts.parseJsonConfigFileContent(
    configFile.config,
    ts.sys,
    root,
    { noEmit: false, declaration: false, ...overrides },
    configPath,
  );
  const program = ts.createProgram(files, parsed.options);
  const emitted = checkOnly ? { diagnostics: [] } : program.emit();
  return ts
    .getPreEmitDiagnostics(program)
    .concat(emitted.diagnostics)
    .filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error);
}

function report(diagnostics) {
  for (const diagnostic of diagnostics) {
    process.stderr.write(`${ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')}\n`);
  }
  return diagnostics.length > 0;
}

const rendererFiles = ['i18n.ts', 'preferences.ts', 'api.ts', 'types.ts', 'app.tsx'].map((name) =>
  path.join(root, 'src', 'renderer', name),
);

// Mirrors `src` under `dist/tests`, so the emitted renderer keeps its own
// relative imports (`../contract/ipc.js`) and the test's rewritten
// `./renderer/*.js` imports resolve next to it.
if (
  report(
    compile(rendererFiles, {
      outDir: path.join(root, 'dist', 'tests'),
      rootDir: path.join(root, 'src'),
    }),
  )
) {
  process.exit(1);
}
if (!checkOnly) {
  await mkdir(path.join(root, 'dist', 'tests', 'renderer'), { recursive: true });
}

const testFiles = [
  'desktop-settings-3157.test.ts',
  'desktop-easy-mode-3165.test.ts',
  'desktop-workspace-ui-3436.test.ts',
  'desktop-run-artifact-3436.test.ts',
].map((name) => path.join(root, 'tests', name));
for (const testFile of testFiles) {
  if (report(compile([testFile], { outDir: path.join(root, 'dist', 'tests') }))) {
    process.exit(1);
  }
}

if (!checkOnly) {
  // The emitted tests are the same files, relocated under dist/tests. Their
  // source-relative imports of the renderer therefore have to point at the
  // modules pass 1 emitted next to them.
  for (const testFile of testFiles) {
    const emittedTest = path.join(
      root,
      'dist',
      'tests',
      path.basename(testFile).replace(/\.ts$/, '.js'),
    );
    const source = await readFile(emittedTest, 'utf8');
    await writeFile(emittedTest, source.replaceAll('../src/renderer/', './renderer/'));
  }
}

process.stdout.write(
  checkOnly
    ? 'padiem-desktop-shell: renderer test typecheck passed\n'
    : 'padiem-desktop-shell: renderer test modules emitted to dist/tests\n',
);
