/**
 * #3404 — deterministic, offline build of the Gemini Live SDK bundle that B66
 * Padiem Quote serves from its own origin.
 *
 *   node build-voice-sdk.mjs          write the artifact + PROVENANCE.json
 *   node build-voice-sdk.mjs --check  rebuild and fail unless the committed
 *                                     artifact is byte-identical
 *
 * Conventions follow apps/padiem-desktop-shell/scripts/build.mjs (the repo's
 * existing locked-esbuild precedent): fixed target list, `bundle: true`,
 * `minify: false`, `legalComments: 'none'`, no config file, no network access,
 * and a fail-closed assertion pass instead of trusting the bundler's output.
 *
 * Nothing in this directory runs at page load. The artifact is a static file;
 * the browser only reaches it through a lazy dynamic import when the user
 * presses the microphone.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const entryPoint = path.join(here, 'src', 'genai-live.mjs');
const vendorDir = path.join(appRoot, 'vendor');
const provenancePath = path.join(here, 'PROVENANCE.json');

// Fixed, explicit baseline. A range here would make the artifact irreproducible.
const TARGETS = ['chrome111', 'edge111', 'firefox115', 'safari16.4'];

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

async function readJson(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}

async function resolvedVersion(name) {
  const pkg = await readJson(path.join(here, 'node_modules', name, 'package.json'));
  return pkg.version;
}

async function bundle(outfile) {
  await mkdir(path.dirname(outfile), { recursive: true });
  await build({
    entryPoints: [entryPoint],
    outfile,
    bundle: true,
    format: 'esm',
    platform: 'browser',
    target: TARGETS,
    minify: false,
    legalComments: 'none',
    sourcemap: false,
    // Fail closed: a browser bundle must not reach Node builtins. Upstream
    // licences are carried in voice-sdk/licenses/ and cited in the app-level
    // THIRD_PARTY_NOTICES.md instead of being inlined as comments.
    external: ['node:*'],
    logLevel: 'warning',
  });
  return readFile(outfile);
}

/**
 * The bundler succeeding is not the contract. These assertions are, because a
 * mis-resolved entry or an over-aggressive tree-shake still "builds".
 */
function assertArtifact(text, sdkVersion) {
  const problems = [];

  // Every dependency must be inlined: no bare specifier may survive, or the
  // page would try to resolve it against the origin and fail at runtime.
  const specifiers = [...text.matchAll(/(?:^|[\s;])(?:import|export)\s*(?:[^'"]*?\sfrom\s)?['"]([^'"]+)['"]/g)]
    .map((m) => m[1])
    .filter((spec) => !spec.startsWith('./') && !spec.startsWith('../'));
  if (specifiers.length) problems.push(`UNINLINED_SPECIFIER=${specifiers.join(',')}`);

  if (/from\s+['"]node:/.test(text) || /require\(['"](fs|http|net|tls|crypto)['"]\)/.test(text)) {
    problems.push('NODE_BUILTIN_IN_BROWSER_BUNDLE');
  }
  if (/import\s*\(\s*['"]https?:/.test(text)) {
    problems.push('REMOTE_DYNAMIC_IMPORT');
  }
  // A bundle without the Live path would ship a silent, broken microphone.
  for (const needle of ['BidiGenerateContent', 'sendRealtimeInput', 'GoogleGenAI']) {
    if (!text.includes(needle)) problems.push(`MISSING_LIVE_SURFACE=${needle}`);
  }
  // The artifact name carries the version; drift here is a real supply-chain bug.
  if (!text.includes('/v1alpha/') && !text.includes('v1alpha')) {
    problems.push('NO_V1ALPHA_API_SURFACE');
  }
  return { problems, sdkVersion };
}

async function main() {
  const check = process.argv.includes('--check');
  const manifest = await readJson(path.join(here, 'package.json'));
  const sdkVersion = manifest.dependencies['@google/genai'];
  const esbuildVersion = (await readJson(path.join(here, 'node_modules', 'esbuild', 'package.json'))).version;
  const artifactName = `genai-live-${sdkVersion}.js`;
  const artifactPath = path.join(vendorDir, artifactName);

  if (check) {
    const tmp = path.join(here, '.rebuild-check', artifactName);
    let produced;
    try {
      produced = await bundle(tmp);
    } finally {
      await rm(path.join(here, '.rebuild-check'), { recursive: true, force: true });
    }
    let committed;
    try {
      committed = await readFile(artifactPath);
    } catch {
      console.error('VOICE_SDK_ARTIFACT_MISSING=' + artifactPath);
      console.error('RUN=node voice-sdk/build-voice-sdk.mjs');
      return 1;
    }
    const producedHash = sha256(produced);
    const committedHash = sha256(committed);
    console.log(`VOICE_SDK_ARTIFACT=${artifactName}`);
    console.log(`REBUILT_SHA256=${producedHash}`);
    console.log(`COMMITTED_SHA256=${committedHash}`);
    console.log(`REBUILT_BYTES=${produced.byteLength}`);
    if (producedHash !== committedHash) {
      console.error('VOICE_SDK_BUNDLE_DRIFT=YES');
      console.error('MEANING=the committed artifact is not reproducible from voice-sdk/package.json + package-lock.json');
      return 1;
    }
    const provenance = await readJson(provenancePath);
    if (provenance.artifact.sha256 !== committedHash || provenance.artifact.bytes !== committed.byteLength) {
      console.error('VOICE_SDK_PROVENANCE_STALE=YES');
      return 1;
    }
    const { problems } = assertArtifact(produced.toString('utf8'), sdkVersion);
    if (problems.length) {
      problems.forEach((p) => console.error('VOICE_SDK_ASSERTION=' + p));
      return 1;
    }
    console.log('VOICE_SDK_BUNDLE_REPRODUCIBLE=YES');
    console.log('VOICE_SDK_OFFLINE_BUILD=YES');
    console.log('VOICE_SDK_BUNDLE=PASS');
    return 0;
  }

  const produced = await bundle(artifactPath);
  const text = produced.toString('utf8');
  const { problems } = assertArtifact(text, sdkVersion);
  if (problems.length) {
    problems.forEach((p) => console.error('VOICE_SDK_ASSERTION=' + p));
    return 1;
  }

  const provenance = {
    purpose: 'B66 Padiem Quote voice input (#3404) — pinned Gemini Live SDK, same-origin static artifact',
    generatedBy: 'voice-sdk/build-voice-sdk.mjs',
    sdk: {
      name: '@google/genai',
      version: sdkVersion,
      entry: '@google/genai/web',
      license: 'Apache-2.0',
      licenseFile: 'voice-sdk/licenses/google-genai.APACHE-2.0.txt',
    },
    bundler: { name: 'esbuild', version: esbuildVersion, targets: TARGETS, minify: false, legalComments: 'none' },
    inlinedDependencies: {
      'p-retry': await resolvedVersion('p-retry'),
      retry: await resolvedVersion('retry'),
    },
    reference: {
      product: 'skerishKang/global-classroom',
      sha: '299c8e7830f6e4aa0c5202ca5591f240487c5c38',
      note: 'version taken from the reference app package-lock resolution; B66 does not depend on that repository at runtime',
    },
    artifact: {
      path: 'vendor/' + artifactName,
      sha256: sha256(produced),
      bytes: produced.byteLength,
    },
  };
  await writeFile(provenancePath, JSON.stringify(provenance, null, 2) + '\n', 'utf8');

  console.log(`VOICE_SDK_ARTIFACT=vendor/${artifactName}`);
  console.log(`VOICE_SDK_BYTES=${produced.byteLength}`);
  console.log(`VOICE_SDK_SHA256=${provenance.artifact.sha256}`);
  console.log(`VOICE_SDK_ESBUILD=${esbuildVersion}`);
  console.log(`SDK_EXACT_VERSION=${sdkVersion}`);
  console.log('VOICE_SDK_OFFLINE_BUILD=YES');
  console.log('VOICE_SDK_BUNDLE=PASS');
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error('VOICE_SDK_BUILD_FAILED=' + (error && error.message ? error.message : String(error)));
    process.exit(1);
  });
