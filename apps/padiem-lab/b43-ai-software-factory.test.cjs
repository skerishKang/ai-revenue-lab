const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B43 route is bounded to the approved current-main AI Software Factory runtime', () => {
  const route = routes.find(candidate => candidate.number === 43);
  assert.ok(route, 'missing B43 route');
  assert.equal(route.route, 'b43');
  assert.equal(route.sourcePath, 'reference/business-43-ai-software-factory-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 소프트웨어 공장');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /AI 소프트웨어 공장/);
  assert.match(index, /HUMAN-VERIFIED SOFTWARE DELIVERY PACKAGE/);
  assert.match(index, /NO LIVE REPOSITORY, CODE GENERATION, CI, MERGE, OR DEPLOYMENT CONNECTION/);
  assert.match(index, /GENERATED PATCH — SYNTHETIC/);
  assert.match(index, /REVIEWED PATCH/);
  assert.match(index, /IMPLEMENTATION SELF-CHECK/);
  assert.match(index, /INDEPENDENT VALIDATION/);
  assert.match(index, /FAILED CHECK/);
  assert.match(index, /UNRESOLVED CONDITION/);
  assert.match(index, /NOT MERGED/);
  assert.match(index, /DEPLOYMENT READINESS — NOT DEPLOYED/);
  assert.match(index, /HUMAN REVIEW REQUIRED/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B43 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B43 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B43 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B43 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B43 current-main source unexpectedly includes UX #420');
});
