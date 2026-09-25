/**
 * CLAW4 #3083 — deterministic build for the desktop shell.
 *
 * Steps:
 *   1. tsc emits main / preload / contract / supervisor / runner / tests
 *   2. esbuild bundles the React renderer to a single ESM file
 *   3. the renderer HTML + CSS are copied next to the bundle
 *
 * No bundler config, secret, or network access is involved.
 */

import { build } from 'esbuild';
import { cp, mkdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..');
const outDir = path.join(root, 'dist', 'src', 'renderer');

await rm(outDir, { recursive: true, force: true });
await mkdir(outDir, { recursive: true });

await build({
  entryPoints: [path.join(root, 'src', 'renderer', 'index.tsx')],
  outfile: path.join(outDir, 'renderer.js'),
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: ['chrome128'],
  jsx: 'automatic',
  sourcemap: true,
  minify: false,
  // Fail closed: the renderer must not reach Node builtins.
  external: ['electron', 'node:*'],
  logLevel: 'warning',
  define: {
    'process.env.NODE_ENV': '"production"',
  },
});

await cp(path.join(root, 'src', 'renderer', 'index.html'), path.join(outDir, 'index.html'));
await cp(path.join(root, 'src', 'renderer', 'shell.css'), path.join(outDir, 'shell.css'));

process.stdout.write('padiem-desktop-shell: renderer bundle written to dist/src/renderer\n');
