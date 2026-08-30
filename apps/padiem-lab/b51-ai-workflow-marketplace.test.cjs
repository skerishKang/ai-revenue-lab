const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B51 route is bounded to the approved current-main AI Workflow Marketplace runtime', () => {
  const route = routes.find(candidate => candidate.number === 51);
  assert.ok(route, 'missing B51 route');
  assert.equal(route.route, 'b51');
  assert.equal(route.sourcePath, 'reference/business-51-ai-workflow-marketplace-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '검증 워크플로우 장터');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');

  assert.match(index, /검증 워크플로우 장터/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NO LIVE EXECUTION, INSTALLATION, ACCOUNT CONNECTION, OR PAYMENT/);
  assert.match(index, /PERMISSION REQUIRED — NOT GRANTED/);
  assert.match(index, /SAFE TRIAL ONLY/);
  assert.match(index, /PRODUCTION USE NOT APPROVED/);
  assert.match(index, /NOT INSTALLED/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B51 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B51 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B51 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B51 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B51 current-main source unexpectedly includes UX #426');
});
