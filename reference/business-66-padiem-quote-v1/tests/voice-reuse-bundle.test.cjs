/* B66 reused-voice artifact (#3404, OWNER decision REUSE_GLOBAL_CLASSROOM_INTERVIEW).
   Proves the speech engine is upstream's, unmodified, and that B66 ships it as one
   same-origin artifact. The rebuild itself is proven in CI by
   `node voice-interview/build-voice-interview.mjs --check`. */
const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const SRC = path.join(__dirname, "..");
const IV = path.join(SRC, "voice-interview");
const REF_SHA = "299c8e7830f6e4aa0c5202ca5591f240487c5c38";

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function main() {
  const manifest = readJson(path.join(IV, "package.json"));
  const provenance = readJson(path.join(IV, "PROVENANCE.json"));

  /* --- exact pins only, and the pins the reference product resolves to -------- */
  const pinned = Object.assign({}, manifest.dependencies, manifest.devDependencies);
  for (const [name, spec] of Object.entries(pinned)) {
    assert.equal(/^[\d.]+(-[\w.]+)?$/.test(spec), true, `${name} must be pinned exactly, found ${spec}`);
  }
  assert.equal(pinned["@google/genai"], "2.24.0");
  assert.equal(pinned.react, "19.2.3", "the React the reference app renders with");
  assert.equal(pinned["react-dom"], "19.2.3");
  assert.equal(pinned.esbuild, "0.25.12", "the esbuild pin this repository already uses");
  assert.equal(manifest.private, true, "the build package is never published");

  /* --- the engine is upstream's, byte for byte -------------------------------- */
  assert.equal(provenance.upstream.sha, REF_SHA);
  assert.equal(provenance.upstream.editPolicy.indexOf("UNMODIFIED") >= 0, true);
  assert.deepEqual(provenance.upstream.files, [
    "upstream/hooks/useInterviewLive.ts",
    "upstream/utils/audioUtils.ts",
    "upstream/utils/interviewTranslationSessions.ts",
    "upstream/utils/interviewTranslationRouter.ts"
  ], "the reused interview engine and its real dependencies");
  for (const [rel, info] of Object.entries(provenance.upstreamFiles)) {
    const bytes = fs.readFileSync(path.join(IV, rel));
    assert.equal(crypto.createHash("sha256").update(bytes).digest("hex"), info.sha256,
      `${rel} is no longer what was vendored — reuse means unmodified, patch upstream instead`);
    assert.equal(bytes.length, info.bytes);
    assert.equal(bytes.includes(Buffer.from("\r\n")), false, `${rel} keeps upstream line endings`);
  }
  /* the interview engine is not a rewritten copy of the deleted local one */
  const engine = fs.readFileSync(path.join(IV, "upstream/hooks/useInterviewLive.ts"), "utf8");
  assert.ok(engine.includes("gemini-3.5-transcribe-live"), "upstream model policy intact");
  assert.ok(engine.includes("translationTargets = DEFAULT_TRANSLATION_TARGETS"), "upstream signature intact");
  assert.deepEqual(provenance.writtenHere, ["bridge.mjs"],
    "only the React mount seam is B66-authored");

  /* --- the artifact exists, is the one the manifest names, and is self-contained */
  const artifactName = `b66-voice-interview-${REF_SHA.slice(0, 8)}.js`;
  const artifactPath = path.join(SRC, "vendor", artifactName);
  assert.ok(fs.existsSync(artifactPath), `the committed artifact ${artifactName} exists`);
  assert.deepEqual(fs.readdirSync(path.join(SRC, "vendor")), [artifactName],
    "one artifact, and the superseded custom-engine bundle is gone");
  const bytes = fs.readFileSync(artifactPath);
  assert.equal(provenance.artifact.sha256, crypto.createHash("sha256").update(bytes).digest("hex"));
  assert.equal(provenance.artifact.bytes, bytes.length);
  /* ~600 KB for React + SDK + engine: heavy enough that lazy loading matters */
  assert.ok(bytes.length < 1_500_000, "the reused artifact stays a reasonable one-shot download");

  const text = bytes.toString("utf8");
  for (const needle of ["B66VoiceInterview", "gemini-3.5-transcribe-live", "BidiGenerateContent",
    "/api/live-token", "audio/pcm;rate=16000"]) {
    assert.ok(text.includes(needle), `the artifact still carries ${needle}`);
  }
  for (const forbidden of ["api.groq.com", "jsdelivr", "unpkg", "esm.sh", "skypack", "cdn.jsdelivr"]) {
    assert.equal(text.includes(forbidden), false, `no ${forbidden} in the shipped artifact`);
  }
  const bare = [...text.matchAll(/(?:^|[\s;])(?:import|export)\s*(?:[^'"]*?\sfrom\s)?['"]([^'"]+)['"]/g)]
    .map((m) => m[1]).filter((spec) => !spec.startsWith("./") && !spec.startsWith("../"));
  assert.deepEqual(bare, [], "everything is inlined; the page resolves no bare specifier");

  /* --- licences ------------------------------------------------------------ */
  for (const [file, marker] of [
    ["licenses/google-genai.APACHE-2.0.txt", "Apache License"],
    ["licenses/react.MIT.txt", "MIT"],
    ["licenses/react-dom.MIT.txt", "MIT"],
    ["licenses/p-retry.MIT.txt", "MIT License"],
    ["licenses/retry.LICENSE.txt", "Tim"]
  ]) {
    const licence = fs.readFileSync(path.join(IV, file), "utf8");
    assert.ok(licence.includes(marker), `${file} carries its licence text`);
    assert.ok(licence.length > 400, `${file} is the full text`);
  }
  const notices = fs.readFileSync(path.join(SRC, "THIRD_PARTY_NOTICES.md"), "utf8");
  assert.ok(notices.includes(REF_SHA), "the notices cite the upstream commit");
  assert.ok(notices.includes("useInterviewLive"), "and name the reused engine");
  assert.ok(notices.includes(provenance.artifact.sha256), "and the artifact hash");

  /* --- B66 side: no leftover custom engine, nothing eager -------------------- */
  for (const gone of ["voice-stt.js", "voice-input.js", "voice-sdk"]) {
    assert.equal(fs.existsSync(path.join(SRC, gone)), false, `${gone} must be deleted, not kept as a fallback`);
  }
  const html = fs.readFileSync(path.join(SRC, "index.html"), "utf8");
  assert.equal(/<script[^>]+src="[^"]*b66-voice-interview/i.test(html), false,
    "the artifact is never referenced by the page: it loads on the first mic press");
  assert.equal(html.includes(artifactName), false, "not even by name");

  /* --- the mount seam is the only B66-authored source in the bundle ---------- */
  const bridge = fs.readFileSync(path.join(IV, "bridge.mjs"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  assert.ok(bridge.includes("useInterviewLive"), "the bridge mounts the upstream hook");
  assert.ok(bridge.includes("translationTargets: []"), "translation stays off: no extra session or token");
  assert.equal(/GoogleGenAI|BidiGenerateContent|getUserMedia|createScriptProcessor/.test(bridge), false,
    "the seam implements no capture or protocol of its own");

  /* --- CI wiring keeps the reused path honest -------------------------------- */
  const workflow = fs.readFileSync(path.join(SRC, "..", "..", ".github", "workflows", "b66-neutral-pages-beta.yml"), "utf8");
  for (const line of [
    "npm ci --ignore-scripts",
    "node build-voice-interview.mjs --check",
    "node verify-worker-bundle.mjs",
    "node tests/voice-bridge.test.cjs",
    "node tests/voice-reuse-bundle.test.cjs",
    "node tests/voice-token-route.test.mjs"
  ]) {
    assert.ok(workflow.includes(line), `CI must run: ${line}`);
  }

  console.log("B66_VOICE_REUSE=PASS");
  console.log(`ARCHITECTURE=REUSE_GLOBAL_CLASSROOM_INTERVIEW`);
  console.log(`GLOBAL_CLASSROOM_REFERENCE_SHA=${REF_SHA}`);
  console.log(`REUSED_ENGINE=upstream/hooks/useInterviewLive.ts (unmodified)`);
  console.log(`VOICE_ARTIFACT=vendor/${artifactName}`);
  console.log(`VOICE_BYTES=${provenance.artifact.bytes}`);
  console.log(`VOICE_SHA256=${provenance.artifact.sha256}`);
  console.log("VOICE_UPSTREAM_UNMODIFIED=YES");
}

try {
  main();
} catch (error) {
  console.error("B66_VOICE_REUSE=FAIL");
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}
