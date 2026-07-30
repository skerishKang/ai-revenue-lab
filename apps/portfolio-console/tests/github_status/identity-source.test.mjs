import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import identityCore from "../../business-identity-core.js";
import { BUSINESS_PHASE_AUTHORITY, buildIdentitySource } from "../../business-identity-data.js";
import { ROOT } from "./fixtures.mjs";

test("identity core defines exactly B1-55 in order, frozen", () => {
  const table = identityCore.BUSINESS_PHASE_AUTHORITY;
  assert.equal(Object.isFrozen(table), true);
  assert.equal(table.length, 55);
  assert.deepEqual(table.map((e) => e.n), Array.from({ length: 55 }, (_, i) => i + 1));
});

test("buildIdentitySource maps all 55 Businesses to phase status triples", () => {
  const source = identityCore.buildIdentitySource();
  assert.equal(Object.keys(source).length, 55);
  for (const entry of identityCore.BUSINESS_PHASE_AUTHORITY) {
    const mapped = source[entry.n];
    assert.equal(mapped.uiStatus, entry.ui);
    assert.equal(mapped.uxStatus, entry.ux);
    assert.equal(mapped.backendStatus, entry.be);
  }
});

test("ESM wrapper shares the identical frozen table with the UMD core", () => {
  assert.equal(BUSINESS_PHASE_AUTHORITY, identityCore.BUSINESS_PHASE_AUTHORITY);
  assert.deepEqual(buildIdentitySource(), identityCore.buildIdentitySource());
});

function loadManifest(coreApi) {
  const source = readFileSync(path.join(ROOT, "business-manifest.js"), "utf-8");
  const window = {};
  if (coreApi) window.ARL_IDENTITY_CORE = coreApi;
  new Function("window", source)(window);
  return window.ARL_MANIFEST;
}

test("manifest joins phase status from the single core source for all 55 entries", () => {
  const manifest = loadManifest(identityCore);
  assert.equal(manifest.length, 55);
  for (const entry of manifest) {
    const phase = identityCore.phaseStatusFor(entry.number);
    assert.equal(entry.uiStatus, phase.ui, `B${entry.number} uiStatus joined from core`);
    assert.equal(entry.uxStatus, phase.ux, `B${entry.number} uxStatus joined from core`);
    assert.equal(entry.backendStatus, phase.be, `B${entry.number} backendStatus joined from core`);
  }
});

test("manifest degrades to safe defaults only when the core script is absent", () => {
  const manifest = loadManifest(null);
  for (const entry of manifest) {
    assert.equal(entry.uiStatus, "NOT_STARTED");
    assert.equal(entry.uxStatus, "BLOCKED_BY_UI");
    assert.equal(entry.backendStatus, "FROZEN");
  }
});

test("server handler resolves identitySource from the shared ESM wrapper", () => {
  const handler = readFileSync(path.join(ROOT, "functions/api/github-status.js"), "utf-8");
  assert.match(handler, /import \{ buildIdentitySource \} from "\.\.\/\.\.\/business-identity-data\.js"/);
  assert.match(handler, /const identitySource = buildIdentitySource\(\)/);
  assert.match(handler, /createGitHubStatusService\(\{[^}]*identitySource[^}]*\}\)/);
});

test("index.html loads the identity core before the manifest", () => {
  const html = readFileSync(path.join(ROOT, "index.html"), "utf-8");
  const coreAt = html.indexOf("business-identity-core.js");
  const manifestAt = html.indexOf("business-manifest.js");
  assert.ok(coreAt !== -1 && manifestAt !== -1, "both scripts present");
  assert.ok(coreAt < manifestAt, "core script must precede manifest");
});
