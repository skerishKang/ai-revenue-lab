/**
 * #3404 — prove the Pages Worker bundles, without a deploy.
 *
 * PR CI cannot run `wrangler pages deploy` (no Cloudflare credentials), so the one
 * deploy-time risk this lane carries — whether `_worker.js` resolves its relative import of
 * `voice-gemini.js` under Pages' own bundler — is otherwise unverified until a real deploy.
 * Pages bundles `_worker.js` with esbuild, the same tool already pinned for the voice
 * artifact, so the resolution question is answered offline instead.
 *
 *   node voice-interview/verify-worker-bundle.mjs
 *
 * Nothing is deployed, uploaded or written outside a temp directory, and no credential is
 * read.
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const workerEntry = path.join(appRoot, '_worker.js');

async function main() {
  const outDir = await mkdtemp(path.join(tmpdir(), 'b66-worker-bundle-'));
  const outfile = path.join(outDir, 'worker.mjs');
  try {
    const result = await build({
      entryPoints: [workerEntry],
      outfile,
      bundle: true,
      format: 'esm',
      // Cloudflare Workers is its own platform; `neutral` keeps the resolver honest
      // without pulling Node builtins in, which is what Pages does for _worker.js.
      platform: 'neutral',
      target: 'es2022',
      minify: false,
      legalComments: 'none',
      sourcemap: false,
      metafile: true,
      logLevel: 'warning',
    });
    const bundled = await readFile(outfile, 'utf8');
    const inputs = Object.keys(result.metafile.inputs);
    const problems = [];

    if (!inputs.some((name) => name.endsWith('voice-gemini.js'))) {
      problems.push('VOICE_GEMINI_MODULE_NOT_RESOLVED');
    }
    if (!bundled.includes('handleVoiceToken')) {
      problems.push('VOICE_TOKEN_HANDLER_MISSING_FROM_BUNDLE');
    }
    // A surviving bare specifier resolves only at Pages runtime, so catch it here.
    const leftovers = [...bundled.matchAll(/(?:^|[\s;])(?:import|export)\s*(?:[^'"]*?\sfrom\s)?['"]([^'"]+)['"]/g)]
      .map((match) => match[1])
      .filter((spec) => !spec.startsWith('./') && !spec.startsWith('../'));
    if (leftovers.length) problems.push('UNRESOLVED_IMPORT=' + leftovers.join(','));
    if (/from\s+['"]node:/.test(bundled)) problems.push('NODE_BUILTIN_IN_WORKER_BUNDLE');
    if (problems.length) {
      problems.forEach((problem) => console.error('B66_WORKER_BUNDLE=' + problem));
      console.error('ENTRY=' + workerEntry);
      return 1;
    }

    console.log('B66_WORKER_ENTRY=_worker.js');
    console.log(`B66_WORKER_BUNDLE_INPUTS=${inputs.length}`);
    console.log('B66_WORKER_VOICE_MODULE=RESOLVED');
    console.log('B66_WORKER_UNRESOLVED_IMPORTS=0');
    console.log('B66_WORKER_BUNDLE_BYTES=' + Buffer.byteLength(bundled, 'utf8'));
    console.log('B66_WORKER_BUNDLE=PASS');
    console.log('PAGES_DEPLOY_PERFORMED=NO');
    console.log('CLOUDFLARE_CREDENTIALS_USED=NO');
    return 0;
  } finally {
    await rm(outDir, { recursive: true, force: true });
  }
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error('B66_WORKER_BUNDLE=FAIL');
    console.error('REASON=' + (error && error.message ? error.message : String(error)));
    process.exit(1);
  });
