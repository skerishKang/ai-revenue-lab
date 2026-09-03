const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const repoRoot = path.resolve(root, '..', '..');
const manifestPath = path.join(root, 'internal-platform-manifest.js');
const businessesPath = path.join(root, 'businesses.js');
const consolePath = path.join(root, 'internal-platform-console.js');
const registryPath = path.join(repoRoot, 'docs', 'internal-platform', 'INTERNAL_PLATFORM_REGISTRY.md');
const playbookPath = path.join(repoRoot, 'docs', 'internal-platform', 'AI_ADOPTION_PLAYBOOK.md');

const manifestSource = fs.readFileSync(manifestPath, 'utf8');
const context = { window: {} };
vm.runInNewContext(manifestSource, context, { filename: manifestPath });

const platforms = context.window.ARL_INTERNAL_PLATFORMS;
assert.ok(Array.isArray(platforms), 'Internal Platform manifest must expose an array');
assert.deepEqual(Array.from(platforms, (item) => item.id), ['IP-CORE', 'IP-ENGINE', 'IP-CONTROL']);
assert.equal(new Set(Array.from(platforms, (item) => item.id)).size, 3, 'Internal Platform IDs must be unique');
assert.ok(platforms.every((item) => item.businessNumber === null), 'Internal Platform components must not claim Business numbers');

const byId = Object.fromEntries(Array.from(platforms, (item) => [item.id, item]));
assert.equal(byId['IP-CORE'].sourcePath, 'packages/padiem-ai-core/');
assert.equal(byId['IP-ENGINE'].sourcePath, 'apps/padiem-ai-engine/');
assert.equal(byId['IP-CONTROL'].sourcePath, 'packages/padiem-control-plane/');
assert.equal(byId['IP-ENGINE'].currentIssue.label, '#1698');
assert.match(byId['IP-ENGINE'].currentWorkEn, /multi-caller service identity registry/i);
assert.ok(byId['IP-ENGINE'].dependencies.includes('IP-CORE'));
assert.ok(byId['IP-CORE'].dependencies.includes('B14 Korean AI Platform'));

for (const item of platforms) {
  assert.match(item.id, /^IP-[A-Z]+$/);
  assert.equal(item.repository, 'skerishKang/ai-revenue-lab');
  assert.ok(item.sourcePath.endsWith('/'));
  assert.ok(Array.isArray(item.owns) && item.owns.length > 0);
  assert.ok(Array.isArray(item.doesNotOwn) && item.doesNotOwn.length > 0);
}

const businessesSource = fs.readFileSync(businessesPath, 'utf8');
assert.match(businessesSource, /internal-platform-manifest\.js/);
assert.match(businessesSource, /internal-platform-console\.js/);
assert.doesNotMatch(businessesSource, /ARL_BUSINESSES\s*=\s*.*ARL_INTERNAL_PLATFORMS/);

const consoleSource = fs.readFileSync(consolePath, 'utf8');
assert.match(consoleSource, /dataset\.view\s*=\s*"platform"/);
assert.match(consoleSource, /Internal Platform/);
assert.match(consoleSource, /Business number/);

assert.ok(fs.existsSync(registryPath), 'Internal Platform registry document must exist');
assert.ok(fs.existsSync(playbookPath), 'AI adoption playbook must exist');
const registry = fs.readFileSync(registryPath, 'utf8');
const playbook = fs.readFileSync(playbookPath, 'utf8');
assert.match(registry, /IP-CORE/);
assert.match(registry, /IP-ENGINE/);
assert.match(registry, /IP-CONTROL/);
assert.match(registry, /Business number/i);
assert.match(playbook, /PRODUCT_ADAPTER/);
assert.match(playbook, /REUSE_CORE/);
assert.match(playbook, /ENGINE_TRANSPORT/);
assert.match(playbook, /B14_EXECUTION/);
assert.match(playbook, /PRODUCT_DIRECT_PROVIDER = NO/);

console.log('Internal Platform registry contract: PASS');
