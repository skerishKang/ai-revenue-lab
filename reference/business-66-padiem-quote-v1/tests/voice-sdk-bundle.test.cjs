/* B66 voice SDK bundle (#3404) — supply-chain and same-origin discipline.
   This asserts structure and integrity of the committed artifact; the rebuild itself is
   proven by `node voice-sdk/build-voice-sdk.mjs --check`, which CI runs as a separate step
   because it needs the locked toolchain rather than the repo checkout. */
const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const SRC = path.join(__dirname, "..");
const SDK_DIR = path.join(SRC, "voice-sdk");
const VENDOR_DIR = path.join(SRC, "vendor");

/* The head CENTRAL pinned for this lane's reference implementation. */
const REFERENCE_SHA = "299c8e7830f6e4aa0c5202ca5591f240487c5c38";

function read(file) {
  return fs.readFileSync(file, "utf8");
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function main() {
  const manifest = JSON.parse(read(path.join(SDK_DIR, "package.json")));
  const provenance = JSON.parse(read(path.join(SDK_DIR, "PROVENANCE.json")));

  /* --- exact pins, no ranges -------------------------------------------- */
  assert.equal(manifest.private, true, "the build package is never published");
  for (const [name, spec] of Object.entries(Object.assign({}, manifest.dependencies, manifest.devDependencies))) {
    assert.equal(/^[\d.]+(-[\w.]+)?$/.test(spec), true,
      `${name} must be pinned exactly, found ${spec}`);
  }
  assert.equal(manifest.dependencies["@google/genai"], "2.24.0",
    "the version global-classroom resolves to");
  assert.equal(manifest.devDependencies.esbuild, "0.25.12",
    "the esbuild pin the repository already uses (apps/padiem-desktop-shell)");

  /* --- the artifact is the one the manifest names ------------------------ */
  const artifactName = `genai-live-${manifest.dependencies["@google/genai"]}.js`;
  const artifactPath = path.join(VENDOR_DIR, artifactName);
  assert.ok(fs.existsSync(artifactPath), `the artifact ${artifactName} is committed`);
  const files = fs.readdirSync(VENDOR_DIR);
  assert.deepEqual(files, [artifactName], "only the pinned artifact is served from vendor/");

  /* --- provenance agrees with the bytes on disk -------------------------- */
  assert.equal(provenance.sdk.version, manifest.dependencies["@google/genai"]);
  assert.equal(provenance.sdk.entry, "@google/genai/web", "the browser build, not the node one");
  assert.equal(provenance.sdk.license, "Apache-2.0");
  assert.equal(provenance.artifact.sha256, sha256(artifactPath),
    "PROVENANCE.json describes this exact file");
  assert.equal(provenance.artifact.bytes, fs.statSync(artifactPath).size);
  assert.equal(provenance.reference.sha, REFERENCE_SHA,
    "the reference head the version was taken from is recorded");
  assert.equal(provenance.bundler.version, manifest.devDependencies.esbuild);
  assert.equal(provenance.bundler.minify, false, "the shipped bundle is readable, not minified");
  for (const name of ["chrome111", "edge111", "firefox115", "safari16.4"]) {
    assert.ok(provenance.bundler.targets.includes(name), `target ${name} is declared`);
  }

  /* --- licences are present, not just named ------------------------------ */
  for (const entry of [
    { file: provenance.sdk.licenseFile, mustContain: "Apache License" },
    { file: "voice-sdk/licenses/p-retry.MIT.txt", mustContain: "MIT License" },
    { file: "voice-sdk/licenses/retry.LICENSE.txt", mustContain: "Tim" }
  ]) {
    const text = read(path.join(SRC, entry.file));
    assert.ok(text.includes(entry.mustContain), `${entry.file} carries its licence text`);
    assert.ok(text.length > 400, `${entry.file} is the full text, not a stub`);
  }
  for (const [name, version] of Object.entries(provenance.inlinedDependencies)) {
    assert.match(version, /^\d+\.\d+\.\d+$/, `${name} is resolved to an exact version`);
  }

  const notices = read(path.join(SRC, "THIRD_PARTY_NOTICES.md"));
  assert.ok(notices.includes("UPSTREAM_VERSION=2.24.0"), "the notices name the exact version");
  assert.ok(notices.includes(provenance.artifact.sha256), "the notices name the artifact hash");
  assert.ok(notices.includes("Apache-2.0") && notices.includes("MIT"), "both licence families are cited");
  assert.ok(notices.includes(REFERENCE_SHA), "the reference head is cited");
  assert.ok(notices.includes("RUNTIME_DEPENDENCY=NO"),
    "the reference product is a design source, not a runtime dependency");

  /* --- the artifact is self-contained and same-origin only --------------- */
  const artifact = read(artifactPath);
  const bare = [...artifact.matchAll(/(?:^|[\s;])(?:import|export)\s*(?:[^'"]*?\sfrom\s)?['"]([^'"]+)['"]/g)]
    .map((m) => m[1])
    .filter((spec) => !spec.startsWith("./") && !spec.startsWith("../"));
  assert.deepEqual(bare, [], "no bare specifier survives: the page cannot be made to resolve one");
  for (const cdn of ["cdn.", "jsdelivr", "unpkg", "esm.sh", "skypack", "googleapis.com/ajax"]) {
    assert.equal(artifact.includes(cdn), false, `no CDN reference (${cdn})`);
  }
  assert.equal(artifact.includes("node:fs") || artifact.includes("require(\"http\")"), false,
    "no Node builtin reached the browser bundle");
  assert.ok(artifact.includes("BidiGenerateContent"), "the Live session surface is present");
  assert.ok(artifact.includes("sendRealtimeInput"), "the realtime input surface is present");

  /* --- nothing eager is loaded by the page ------------------------------- */
  const html = read(path.join(SRC, "index.html"));
  assert.equal(/<script[^>]+src="[^"]*vendor/i.test(html), false,
    "the bundle is not referenced by the page: it is lazily imported on mic press");
  assert.equal(/<script[^>]+src="https?:/i.test(html), false, "no external script origin at all");
  assert.equal(html.includes('type="module"'), false,
    "B66 stays a classic-script app; only the mic path crosses into ESM");
  assert.ok(html.includes("voice-stt.js") && html.includes("voice-input.js"),
    "the voice lane is still wired into the existing composer");

  /* --- the loader seam is a path, so the import can be tested ------------ */
  const stt = read(path.join(SRC, "voice-stt.js"));
  assert.ok(stt.includes(`/vendor/${artifactName}`),
    "voice-stt.js imports exactly the pinned artifact name");
  assert.ok(stt.includes("import("), "the import is dynamic, so it costs nothing at page load");

  /* --- build tooling is ignored, not committed --------------------------- */
  const ignore = read(path.join(SDK_DIR, ".gitignore"));
  assert.ok(ignore.includes("node_modules/"), "the locked install never lands in git");
  assert.equal(fs.existsSync(path.join(SRC, "node_modules")), false,
    "no node_modules at the app root: the app itself remains dependency-free");

  console.log("B66_VOICE_SDK_BUNDLE=PASS");
  console.log(`SDK_EXACT_VERSION=${manifest.dependencies["@google/genai"]}`);
  console.log(`VOICE_SDK_BYTES=${provenance.artifact.bytes}`);
  console.log(`VOICE_SDK_SHA256=${provenance.artifact.sha256}`);
  console.log("VOICE_SDK_SAME_ORIGIN=YES");
  console.log("VOICE_SDK_RUNTIME_CDN=NO");
}

try {
  main();
} catch (error) {
  console.error("B66_VOICE_SDK_BUNDLE=FAIL");
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
}
