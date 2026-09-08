'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const consoleRoot = path.resolve(__dirname, '..');
const repoRoot = path.resolve(consoleRoot, '..', '..');
const manifestPath = path.join(consoleRoot, 'business-manifest.js');
const docsRoot = path.join(repoRoot, 'docs', 'products', 'padiem-sidecar');
const historicalB53 = path.join(repoRoot, 'reference', 'business-53-embedded-ai-sdk-v1');
const futureRuntime = path.join(repoRoot, 'apps', 'padiem-sidecar');

const context = { window: { ARL_IDENTITY_CORE: null } };
vm.createContext(context);
vm.runInContext(fs.readFileSync(manifestPath, 'utf8'), context, { filename: manifestPath });

const businesses = context.window.ARL_MANIFEST;
assert.ok(Array.isArray(businesses), 'ARL_MANIFEST must be an array');

const b53Entries = businesses.filter((business) => business.number === 53);
assert.equal(b53Entries.length, 1, 'B53 must have exactly one Business identity');

const b53 = b53Entries[0];
assert.equal(b53.slug, 'padiem-sidecar');
assert.equal(b53.title, 'Padiem Sidecar');
assert.equal(b53.koreanTitle, '파디엠 사이드카');
assert.equal(b53.numberAuthority, 'proposed-number');
assert.equal(b53.workspace, 'docs/products/padiem-sidecar/');
assert.equal(b53.state, 'review');

assert.equal(
  businesses.some((business) => business.number !== 53 && business.slug === 'padiem-sidecar'),
  false,
  'Padiem Sidecar must not consume a second Business number'
);

const expectedDocs = [
  'README.md',
  'PRODUCT_CHARTER.md',
  'PRODUCT_REQUIREMENTS.md',
  'ARCHITECTURE.md',
  'OWNERSHIP_BOUNDARIES.md',
  'EMBED_AND_HOST_INTEGRATION.md',
  'TENANCY_SECURITY_AND_PRIVACY.md',
  'OPERATIONS_RUNBOOK.md',
  'RELEASE_AND_ROLLBACK.md',
  'RELIABILITY_AND_INCIDENTS.md',
  'CUSTOMER_ONBOARDING.md',
  'PRICING_AND_COMMERCIALIZATION.md',
  'ADOPTION_AND_REUSE_MATRIX.md',
  'ROADMAP.md'
];

for (const file of expectedDocs) {
  assert.equal(fs.existsSync(path.join(docsRoot, file)), true, `missing canonical Sidecar document: ${file}`);
}

assert.equal(
  fs.existsSync(historicalB53),
  true,
  'historical Embedded AI SDK reference must remain preserved'
);
assert.equal(
  fs.existsSync(futureRuntime),
  false,
  'S0 must not claim/create apps/padiem-sidecar runtime'
);

const readme = fs.readFileSync(path.join(docsRoot, 'README.md'), 'utf8');
const architecture = fs.readFileSync(path.join(docsRoot, 'ARCHITECTURE.md'), 'utf8');
const security = fs.readFileSync(path.join(docsRoot, 'TENANCY_SECURITY_AND_PRIVACY.md'), 'utf8');
const adoption = fs.readFileSync(path.join(docsRoot, 'ADOPTION_AND_REUSE_MATRIX.md'), 'utf8');

for (const token of ['IP-SIDECAR', 'IP-ENGINE', 'IP-CORE', 'B14']) {
  assert.ok(readme.includes(token), `README must expose platform topology token ${token}`);
  assert.ok(architecture.includes(token), `ARCHITECTURE must expose platform topology token ${token}`);
}

for (const proof of ['B30', 'B61', 'B23']) {
  assert.ok(adoption.includes(proof), `adoption matrix must include first-party proof ${proof}`);
}

assert.ok(security.includes('BROWSER_PROVIDER_SECRET = NO'));
assert.ok(security.includes('BROWSER_ENGINE_SECRET = NO'));
assert.ok(architecture.includes('DIRECT_B53_TO_PROVIDER = NO'));
assert.ok(architecture.includes('IFRAME_B62_AS_PLATFORM = NO'));

console.log(`Padiem Sidecar S0 registry/docs contract PASS (${expectedDocs.length} canonical docs)`);
