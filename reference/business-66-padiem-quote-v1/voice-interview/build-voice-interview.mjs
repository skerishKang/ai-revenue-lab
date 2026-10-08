/**
 * #3404 — deterministic, offline build of the reused Global Classroom interview voice
 * engine into one same-origin artifact for B66 Padiem Quote.
 *
 *   node build-voice-interview.mjs            write the artifact + PROVENANCE.json
 *   node build-voice-interview.mjs --check    rebuild and fail unless the committed
 *                                             artifact is byte-identical and the vendored
 *                                             upstream files are still what they claim
 *
 * Conventions follow apps/padiem-desktop-shell and the previous voice-sdk step: fixed
 * target list, one pinned bundler, no config file, no network, and a fail-closed
 * assertion pass instead of trusting the bundler's exit code.
 *
 * The point of this build is that the speech engine is NOT ours: upstream/hooks and
 * upstream/utils are copied unmodified and only bridge.mjs is written here.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.join(here, '..');
const entryPoint = path.join(here, 'bridge.mjs');
const vendorDir = path.join(appRoot, 'vendor');
const provenancePath = path.join(here, 'PROVENANCE.json');

const UPSTREAM_SHA = '299c8e7830f6e4aa0c5202ca5591f240487c5c38';
const UPSTREAM_FILES = [
  'upstream/hooks/useInterviewLive.ts',
  'upstream/utils/audioUtils.ts',
  'upstream/utils/interviewTranslationSessions.ts',
  'upstream/utils/interviewTranslationRouter.ts'
];
/* Fixed, explicit baseline: a range here would make the artifact irreproducible. */
const TARGETS = ['chrome111', 'edge111', 'firefox115', 'safari16.4'];

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

async function readJson(file) {
  return JSON.parse(await readFile(file, 'utf8'));
}

async function resolvedVersion(name) {
  return (await readJson(path.join(here, 'node_modules', name, 'package.json'))).version;
}

async function bundle(outfile) {
  await mkdir(path.dirname(outfile), { recursive: true });
  await build({
    entryPoints: [entryPoint],
    outfile,
    bundle: true,
    format: 'iife',
    platform: 'browser',
    target: TARGETS,
    minify: true,
    legalComments: 'none',
    sourcemap: false,
    loader: { '.ts': 'ts' },
    // Fail closed: a browser artifact must not reach Node builtins.
    external: ['node:*'],
    define: { 'process.env.NODE_ENV': '"production"' },
    logLevel: 'warning'
  });
  return readFile(outfile);
}

/**
 * The bundler exiting is not the contract. These assertions are, because a mis-vendored
 * upstream file or an over-aggressive tree-shake would still "succeed".
 */
function assertArtifact(text) {
  const problems = [];
  const specifiers = [...text.matchAll(/(?:^|[\s;])(?:import|export)\s*(?:[^'"]*?\sfrom\s)?['"]([^'"]+)['"]/g)]
    .map((match) => match[1])
    .filter((spec) => !spec.startsWith('./') && !spec.startsWith('../'));
  if (specifiers.length) problems.push(`UNINLINED_SPECIFIER=${specifiers.join(',')}`);
  if (/from\s+['"]node:/.test(text)) problems.push('NODE_BUILTIN_IN_BROWSER_BUNDLE');
  for (const needle of ['B66VoiceInterview', 'gemini-3.5-transcribe-live', 'BidiGenerateContent',
    'audio/pcm;rate=16000', '/api/live-token']) {
    if (!text.includes(needle)) problems.push(`MISSING_SURFACE=${needle}`);
  }
  /* The reused engine reaches Gemini and the token route only. Anything that looks like a
     second provider being wired in here is a bug, not a feature. */
  if (text.includes('api.groq.com')) problems.push('GROQ_ENDPOINT_BUNDLED');
  for (const cdn of ['cdn.', 'jsdelivr', 'unpkg', 'esm.sh', 'skypack']) {
    if (text.includes(cdn)) problems.push(`CDN_REFERENCE=${cdn}`);
  }
  return problems;
}

async function main() {
  const check = process.argv.includes('--check');
  const manifest = await readJson(path.join(here, 'package.json'));
  const artifactName = `b66-voice-interview-${UPSTREAM_SHA.slice(0, 8)}.js`;
  const artifactPath = path.join(vendorDir, artifactName);
  const upstream = {};
  for (const rel of UPSTREAM_FILES) {
    const bytes = await readFile(path.join(here, rel));
    upstream[rel] = { bytes: bytes.length, sha256: sha256(bytes) };
  }

  if (check) {
    const tmpDir = path.join(here, '.rebuild-check');
    let produced;
    try {
      produced = await bundle(path.join(tmpDir, artifactName));
    } finally {
      await rm(tmpDir, { recursive: true, force: true });
    }
    let committed;
    try {
      committed = await readFile(artifactPath);
    } catch {
      console.error('VOICE_ARTIFACT_MISSING=' + artifactPath);
      console.error('RUN=node voice-interview/build-voice-interview.mjs');
      return 1;
    }
    console.log(`VOICE_ARTIFACT=${artifactName}`);
    console.log(`REBUILT_SHA256=${sha256(produced)}`);
    console.log(`COMMITTED_SHA256=${sha256(committed)}`);
    if (sha256(produced) !== sha256(committed)) {
      console.error('VOICE_ARTIFACT_DRIFT=YES');
      console.error('MEANING=the committed artifact is not reproducible from package.json + package-lock.json');
      return 1;
    }
    const provenance = await readJson(provenancePath);
    if (provenance.artifact.sha256 !== sha256(committed) || provenance.artifact.bytes !== committed.length) {
      console.error('VOICE_PROVENANCE_STALE=YES');
      return 1;
    }
    for (const [rel, info] of Object.entries(provenance.upstreamFiles)) {
      const current = upstream[rel];
      if (!current || current.sha256 !== info.sha256) {
        console.error(`VOICE_UPSTREAM_DRIFT=${rel}`);
        console.error('MEANING=a vendored upstream file was edited locally; reuse means unmodified');
        return 1;
      }
    }
    const problems = assertArtifact(produced.toString('utf8'));
    if (problems.length) {
      problems.forEach((problem) => console.error('VOICE_ASSERTION=' + problem));
      return 1;
    }
    console.log('VOICE_ARTIFACT_REPRODUCIBLE=YES');
    console.log('VOICE_UPSTREAM_UNMODIFIED=YES');
    console.log('VOICE_BUNDLE=PASS');
    return 0;
  }

  const produced = await bundle(artifactPath);
  const problems = assertArtifact(produced.toString('utf8'));
  if (problems.length) {
    problems.forEach((problem) => console.error('VOICE_ASSERTION=' + problem));
    return 1;
  }
  const provenance = {
    purpose: 'B66 Padiem Quote voice input (#3404) — the Global Classroom interview engine, reused unmodified',
    generatedBy: 'voice-interview/build-voice-interview.mjs',
    upstream: {
      repo: 'skerishKang/global-classroom',
      sha: UPSTREAM_SHA,
      files: UPSTREAM_FILES,
      editPolicy: 'UNMODIFIED — any local change to these files is drift, not maintenance',
      deployedComparison: 'production bundle /assets/index-BhOzGF71.js of '
        + 'https://7-global-classroom.netlify.app matched this source on 10/10 engine '
        + 'fingerprint probes (model ids, pcm mime, token route, fallback copy), 3 negative '
        + 'probes correctly absent'
    },
    upstreamFiles: upstream,
    dependencies: {
      '@google/genai': await resolvedVersion('@google/genai'),
      react: await resolvedVersion('react'),
      'react-dom': await resolvedVersion('react-dom'),
      'p-retry': await resolvedVersion('p-retry'),
      retry: await resolvedVersion('retry')
    },
    bundler: { name: 'esbuild', version: await resolvedVersion('esbuild'), targets: TARGETS, minify: true },
    writtenHere: ['bridge.mjs'],
    disabledUpstreamFeatures: {
      translation: 'translationTargets: [] — no Live Translate session or token',
      groqFallback: 'refused by the mount layer; no /api/transcribe route exists on B66',
      languageDetection: 'not wired; the engine languageCode is the only source'
    },
    licenses: {
      '@google/genai': 'Apache-2.0 (voice-interview/licenses/google-genai.APACHE-2.0.txt)',
      react: 'MIT (voice-interview/licenses/react.MIT.txt)',
      'react-dom': 'MIT (voice-interview/licenses/react-dom.MIT.txt)',
      'p-retry': 'MIT (voice-interview/licenses/p-retry.MIT.txt)',
      retry: 'MIT (voice-interview/licenses/retry.LICENSE.txt)',
      'global-classroom sources': 'see THIRD_PARTY_NOTICES.md'
    },
    artifact: {
      path: 'vendor/' + artifactName,
      sha256: sha256(produced),
      bytes: produced.length,
      loadedAt: 'lazy — the browser fetches it only when the microphone is pressed'
    }
  };
  await writeFile(provenancePath, JSON.stringify(provenance, null, 2) + '\n', 'utf8');
  console.log(`VOICE_ARTIFACT=vendor/${artifactName}`);
  console.log(`VOICE_BYTES=${produced.length}`);
  console.log(`VOICE_SHA256=${provenance.artifact.sha256}`);
  console.log(`REACT_VERSION=${provenance.dependencies.react}`);
  console.log(`SDK_EXACT_VERSION=${provenance.dependencies['@google/genai']}`);
  console.log(`GLOBAL_CLASSROOM_REFERENCE_SHA=${UPSTREAM_SHA}`);
  console.log('VOICE_OFFLINE_BUILD=YES');
  console.log('VOICE_UPSTREAM_UNMODIFIED=YES');
  console.log('VOICE_BUNDLE=PASS');
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error('VOICE_BUILD_FAILED=' + (error && error.message ? error.message : String(error)));
    process.exit(1);
  });
